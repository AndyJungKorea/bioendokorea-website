# BIOENDO CoA server

The public website searches by one normalized Lot number. The isolated server returns every CoA document connected to that Lot.

## Production layout

- Service: `bioendo-coa.service`
- Application: `/opt/bioendo-coa/app`
- Data: `/opt/bioendo-coa/data`
- SQLite: `/opt/bioendo-coa/data/coa.sqlite3`
- Original source archives: `/opt/bioendo-coa/data/source`
- Stored documents: `/opt/bioendo-coa/data/files`
- Internal port: `127.0.0.1:5194`
- Public server prefix: `/coa-api/`
- Website proxy prefix: `/api/coa/`

## Endpoints

- `GET /health`
- `GET /lookup?lot=...`
- `GET /download/<document_id>?expires=...&sig=...`
- `POST /admin/upload` with `X-CoA-Admin-Token`

The service has no document-list endpoint. Download URLs are HMAC-signed and expire after ten minutes. Admin uploads accept PDF, PNG, and JPG up to 20 MB. Files are deduplicated by SHA-256.

## Import policy

`import_coa_zip.py` indexes every eight-digit Lot in a filename. If no eight-digit Lot exists, it accepts a separated four-digit Lot such as `2512`. Product numbers adjacent to letters are not treated as Lot numbers. Paths containing `MSDS` are excluded from the CoA index.

Before importing a new archive, run `test_import.py` and `test_api.py`, keep the original archive, review `import-report.csv`, and verify an exact lookup plus a multi-document lookup.

The administrator screen requires one or more Lot numbers. After upload, the API verifies the database aliases and the screen re-runs each Lot through the public lookup endpoint. It reports completion only when the uploaded file appears in every lookup result.
