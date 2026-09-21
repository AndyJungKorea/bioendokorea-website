import hashlib
import hmac
import mimetypes
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, jsonify, request, send_file


DATA_DIR = Path(os.environ.get("COA_DATA_DIR", "/opt/bioendo-coa/data"))
DB_PATH = DATA_DIR / "coa.sqlite3"
FILES_DIR = DATA_DIR / "files"
MAX_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
LOT_PATTERN = re.compile(r"^[A-Z0-9]{4,64}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_BYTES


def normalize_lot(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())


def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def database():
    connection = get_db()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    with database() as connection:
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


def allowed_origin():
    configured = os.environ.get(
        "COA_ALLOWED_ORIGINS",
        "https://bioendokorea.com,https://www.bioendokorea.com",
    )
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    origin = request.headers.get("Origin")
    return origin if origin in allowed else None


@app.after_request
def add_security_headers(response):
    origin = allowed_origin()
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def download_signature(document_id, expires):
    secret = os.environ.get("COA_DOWNLOAD_SECRET", "")
    if not secret:
        raise RuntimeError("COA_DOWNLOAD_SECRET is not configured")
    payload = f"{document_id}:{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def valid_admin_token():
    received = request.headers.get("X-CoA-Admin-Token", "")
    expected = os.environ.get("COA_ADMIN_TOKEN", "")
    return bool(received and expected and secrets.compare_digest(received, expected))


def file_signature_is_valid(data, extension):
    if extension == ".pdf":
        return data.startswith(b"%PDF-")
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    return False


@app.get("/health")
def health():
    with database() as connection:
        document_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        lot_count = connection.execute("SELECT COUNT(DISTINCT lot_norm) FROM lot_aliases").fetchone()[0]
    return jsonify(ok=True, documents=document_count, lots=lot_count)


@app.get("/lookup")
def lookup():
    lot = normalize_lot(request.args.get("lot"))
    if not LOT_PATTERN.fullmatch(lot):
        return jsonify(ok=False, code="invalid_lot", message="Lot 번호를 확인해 주세요."), 400

    with database() as connection:
        rows = connection.execute(
            """
            SELECT d.id, d.original_name, d.content_type, d.size_bytes, d.uploaded_at
              FROM lot_aliases AS a
              JOIN documents AS d ON d.id = a.document_id
             WHERE a.lot_norm = ?
             ORDER BY d.uploaded_at DESC, d.id DESC
            """,
            (lot,),
        ).fetchall()

    if not rows:
        return jsonify(ok=False, code="not_found", message="일치하는 성적서를 찾지 못했습니다."), 404

    expires = int(time.time()) + 600
    documents = []
    for row in rows:
        signature = download_signature(row["id"], expires)
        documents.append(
            {
                "name": row["original_name"],
                "contentType": row["content_type"],
                "size": row["size_bytes"],
                "downloadUrl": f"/api/coa/download/{row['id']}?expires={expires}&sig={signature}",
            }
        )
    return jsonify(ok=True, lot=lot, count=len(documents), documents=documents)


@app.get("/download/<int:document_id>")
def download(document_id):
    try:
        expires = int(request.args.get("expires", "0"))
    except ValueError:
        return "잘못된 요청입니다.", 400
    received_signature = request.args.get("sig", "")
    if expires < int(time.time()) or expires > int(time.time()) + 900:
        return "다운로드 링크가 만료되었습니다. 다시 조회해 주세요.", 403
    expected_signature = download_signature(document_id, expires)
    if not received_signature or not secrets.compare_digest(received_signature, expected_signature):
        return "다운로드 인증에 실패했습니다.", 403

    with database() as connection:
        row = connection.execute(
            "SELECT stored_name, original_name, content_type FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if not row:
        return "성적서를 찾지 못했습니다.", 404
    path = FILES_DIR / row["stored_name"]
    if not path.is_file():
        app.logger.error("COA_FILE_MISSING document_id=%s", document_id)
        return "성적서 파일을 찾지 못했습니다.", 404
    return send_file(
        path,
        mimetype=row["content_type"],
        as_attachment=True,
        download_name=row["original_name"],
        conditional=True,
        max_age=0,
    )


@app.post("/admin/upload")
def admin_upload():
    if not valid_admin_token():
        return jsonify(ok=False, code="unauthorized", message="관리자 인증에 실패했습니다."), 401
    origin = request.headers.get("Origin")
    if origin and not allowed_origin():
        return jsonify(ok=False, code="origin_denied", message="허용되지 않은 요청입니다."), 403

    upload = request.files.get("file")
    lot_values = request.form.get("lots", "")
    source_batch = request.form.get("sourceBatch", "manual").strip()[:120] or "manual"
    lots = []
    for raw in re.split(r"[,\s]+", lot_values):
        normalized = normalize_lot(raw)
        if normalized and normalized not in lots:
            lots.append(normalized)
    if not lots or any(not LOT_PATTERN.fullmatch(item) for item in lots):
        return jsonify(ok=False, code="invalid_lots", message="Lot 번호를 하나 이상 입력해 주세요."), 400
    if not upload or not upload.filename:
        return jsonify(ok=False, code="missing_file", message="성적서 파일을 선택해 주세요."), 400

    original_name = Path(upload.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return jsonify(ok=False, code="invalid_type", message="PDF, PNG, JPG 파일만 등록할 수 있습니다."), 415
    data = upload.read(MAX_FILE_BYTES + 1)
    if not data or len(data) > MAX_FILE_BYTES:
        return jsonify(ok=False, code="invalid_size", message="파일은 20MB 이하만 등록할 수 있습니다."), 413
    if not file_signature_is_valid(data, extension):
        return jsonify(ok=False, code="invalid_signature", message="파일 형식을 확인해 주세요."), 415

    digest = hashlib.sha256(data).hexdigest()
    stored_name = f"{digest}{extension}"
    content_type = mimetypes.types_map.get(extension, "application/octet-stream")
    target = FILES_DIR / stored_name
    if not target.exists():
        temporary = FILES_DIR / f".{stored_name}.tmp"
        temporary.write_bytes(data)
        temporary.replace(target)

    with database() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO documents
              (stored_name, original_name, content_type, sha256, size_bytes, source_batch)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (stored_name, original_name, content_type, digest, len(data), source_batch),
        )
        document_id = connection.execute(
            "SELECT id FROM documents WHERE sha256 = ?", (digest,)
        ).fetchone()[0]
        canonical_document = connection.execute(
            "SELECT original_name, size_bytes FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        for lot in lots:
            connection.execute(
                "INSERT OR IGNORE INTO lot_aliases (lot_norm, lot_display, document_id) VALUES (?, ?, ?)",
                (lot, lot, document_id),
            )
        verified_lots = [
            lot
            for lot in lots
            if connection.execute(
                "SELECT 1 FROM lot_aliases WHERE lot_norm = ? AND document_id = ?",
                (lot, document_id),
            ).fetchone()
        ]

    if verified_lots != lots:
        app.logger.error(
            "COA_LOT_VERIFY_FAILED document_id=%s expected=%s verified=%s",
            document_id,
            lots,
            verified_lots,
        )
        return jsonify(
            ok=False,
            code="lot_verify_failed",
            message="파일은 저장됐지만 Lot 조회 연결 검증에 실패했습니다.",
        ), 500

    return jsonify(
        ok=True,
        document={
            "name": canonical_document["original_name"],
            "lots": lots,
            "verifiedLots": verified_lots,
            "sha256": digest,
            "size": canonical_document["size_bytes"],
        },
    ), 201


initialize_database()
