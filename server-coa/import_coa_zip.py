import argparse
import csv
import hashlib
import mimetypes
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
EIGHT_DIGIT_LOT = re.compile(r"(?<![A-Z0-9])(\d{8})(?![A-Z0-9])")
FOUR_DIGIT_LOT = re.compile(r"(?<![A-Z0-9])(\d{4})(?![A-Z0-9])")
LOT_OVERRIDES = {
    # Visual verification: the CoA lists these as Matched Endotoxin Lot No.
    "G020030 24061151.pdf": ["23045133", "24045124"],
}


def extract_lots(filename):
    stem = Path(filename).stem.upper()
    lots = list(dict.fromkeys(EIGHT_DIGIT_LOT.findall(stem)))
    if not lots:
        lots = list(dict.fromkeys(FOUR_DIGIT_LOT.findall(stem)))
    for related_lot in LOT_OVERRIDES.get(Path(filename).name, []):
        if related_lot not in lots:
            lots.append(related_lot)
    return lots


def valid_member(name):
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def initialize_database(db_path):
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stored_name TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            content_type TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            source_batch TEXT NOT NULL,
            uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lot_aliases (
            lot_norm TEXT NOT NULL,
            lot_display TEXT NOT NULL,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (lot_norm, document_id)
        );
        CREATE INDEX IF NOT EXISTS idx_lot_aliases_lot ON lot_aliases(lot_norm);
        """
    )
    return connection


def main():
    parser = argparse.ArgumentParser(description="BIOENDO CoA ZIP importer")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--batch", default="Bioendo New CoA collection")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    data_dir = args.data_dir
    files_dir = data_dir / "files"
    source_dir = data_dir / "source"
    files_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    archive_hash = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    archive_copy = source_dir / f"{archive_hash[:16]}_{args.archive.name}"
    if not archive_copy.exists():
        shutil.copy2(args.archive, archive_copy)

    connection = initialize_database(data_dir / "coa.sqlite3")
    report_rows = []
    imported = deduplicated = skipped_msds = unresolved = 0
    with zipfile.ZipFile(args.archive) as archive:
        for member in archive.infolist():
            if member.is_dir() or not valid_member(member.filename):
                continue
            member_path = PurePosixPath(member.filename.replace("\\", "/"))
            if any("MSDS" in part.upper() for part in member_path.parts):
                skipped_msds += 1
                continue
            extension = Path(member_path.name).suffix.lower()
            if extension not in ALLOWED_EXTENSIONS:
                continue
            lots = extract_lots(member_path.name)
            if not lots:
                unresolved += 1
                report_rows.append([member.filename, "", "unresolved", ""])
                continue
            data = archive.read(member)
            digest = hashlib.sha256(data).hexdigest()
            stored_name = f"{digest}{extension}"
            target = files_dir / stored_name
            if target.exists():
                deduplicated += 1
            else:
                target.write_bytes(data)
                imported += 1
            content_type = mimetypes.types_map.get(extension, "application/octet-stream")
            connection.execute(
                """
                INSERT OR IGNORE INTO documents
                  (stored_name, original_name, content_type, sha256, size_bytes, source_batch)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (stored_name, member_path.name, content_type, digest, len(data), args.batch),
            )
            document_id = connection.execute(
                "SELECT id FROM documents WHERE sha256 = ?", (digest,)
            ).fetchone()[0]
            for lot in lots:
                connection.execute(
                    "INSERT OR IGNORE INTO lot_aliases (lot_norm, lot_display, document_id) VALUES (?, ?, ?)",
                    (lot, lot, document_id),
                )
            report_rows.append([member.filename, ",".join(lots), "indexed", digest])
    connection.commit()

    document_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    lot_count = connection.execute("SELECT COUNT(DISTINCT lot_norm) FROM lot_aliases").fetchone()[0]
    connection.close()
    report_path = args.report or (data_dir / "import-report.csv")
    with report_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["archive_path", "lots", "status", "sha256"])
        writer.writerows(report_rows)
    print(
        f"documents={document_count} lots={lot_count} imported={imported} "
        f"deduplicated={deduplicated} skipped_msds={skipped_msds} unresolved={unresolved}"
    )
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
