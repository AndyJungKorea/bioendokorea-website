import argparse
import csv
import io
import re
import zipfile
from pathlib import Path, PurePosixPath

import fitz

from import_coa_zip import extract_lots, valid_member


NUMBER_8 = re.compile(r"(?<![A-Z0-9])(\d{8})(?![A-Z0-9])", re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser(description="Compare CoA filenames with embedded PDF text")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    with zipfile.ZipFile(args.archive) as archive:
        for member in archive.infolist():
            if member.is_dir() or not valid_member(member.filename):
                continue
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if any("MSDS" in part.upper() for part in path.parts):
                continue
            filename_lots = extract_lots(path.name)
            extension = Path(path.name).suffix.lower()
            if extension != ".pdf":
                rows.append([member.filename, ",".join(filename_lots), "", "image_filename_index"])
                continue
            try:
                document = fitz.open(stream=io.BytesIO(archive.read(member)), filetype="pdf")
                text = "\n".join(page.get_text("text") for page in document).upper()
            except Exception as error:
                rows.append([member.filename, ",".join(filename_lots), "", f"pdf_read_error:{type(error).__name__}"])
                continue
            if not text.strip():
                rows.append([member.filename, ",".join(filename_lots), "", "pdf_no_embedded_text"])
                continue
            text_numbers = list(dict.fromkeys(NUMBER_8.findall(text)))
            missing = [lot for lot in filename_lots if len(lot) == 8 and lot not in text_numbers]
            status = "confirmed" if not missing else "filename_lot_not_in_text"
            rows.append([member.filename, ",".join(filename_lots), ",".join(text_numbers), status])

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["archive_path", "filename_lots", "pdf_text_8digit_numbers", "status"])
        writer.writerows(rows)
    counts = {}
    for row in rows:
        counts[row[3]] = counts.get(row[3], 0) + 1
    print(counts)
    print(args.report)


if __name__ == "__main__":
    main()
