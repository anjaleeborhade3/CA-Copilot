import json
import os
import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .db import (
    DEFAULT_SETTINGS,
    REPORT_DIR,
    UPLOAD_DIR,
    get_connection,
    initialize_database,
)
from .schemas import (
    ChatRequest,
    AnomalyStatusUpdate,
    ClientCreate,
    ClientUpdate,
    ReportCreate,
    SettingsUpdate,
    TransactionStatusUpdate,
)


MAX_UPLOAD_BYTES = int(os.environ.get("CA_COPILOT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
ALLOWED_EXTENSIONS = {".pdf", ".csv", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png"}
CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".csv": {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"},
    ".doc": {"application/msword"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xls": {"application/vnd.ms-excel", "application/x-ole-storage"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
}
DATE_FORMAT = "%d %b %Y"

app = FastAPI(
    title="CA-Copilot Local API",
    version="1.0.0",
    description="Local-only API and SQLite persistence for the CA-Copilot frontend prototype.",
)

origins = [
    item.strip()
    for item in os.environ.get(
        "CA_COPILOT_CORS_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def startup() -> None:
    initialize_database()
    create_seed_report_files()


def now_display() -> str:
    return date.today().strftime(DATE_FORMAT)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_client(connection: sqlite3.Connection, client_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Client {client_id} was not found.")
    return row


def client_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "industry": row["industry"],
        "documents": row["document_count"],
        "risk": row["risk"],
        "last_review": row["last_review"],
    }


def document_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "client": row["client_name"],
        "name": row["name"],
        "file_size": row["file_size"],
        "document_type": row["document_type"],
        "status": row["status"],
        "financial_year": row["financial_year"],
        "upload_date": row["upload_date"],
        "available_for_download": bool(row["stored_name"] and (UPLOAD_DIR / row["stored_name"]).is_file()),
    }


def transaction_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "client": row["client_name"],
        "bank_amount": row["bank_amount"],
        "book_amount": row["book_amount"],
        "difference": row["difference"],
        "status": row["status"],
        "date": row["transaction_date"],
    }


def anomaly_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "client": row["client_name"],
        "category": row["category"],
        "amount": row["amount"],
        "risk": row["risk"],
        "status": row["status"],
        "detected": row["detected"],
        "reason": row["reason"],
    }


def report_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "client": row["client_name"],
        "report_type": row["report_type"],
        "financial_year": row["financial_year"],
        "status": row["status"],
        "generated": row["generated"],
        "available_for_download": bool(row["stored_name"] and safe_report_file(row["id"]).is_file()),
    }


def ensure_client_exists(client_id: str) -> None:
    with get_connection() as connection:
        fetch_client(connection, client_id)


def validate_upload(upload: UploadFile, extension: str) -> None:
    if extension not in CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type.")
    content_type = (upload.content_type or "").lower()
    if content_type not in CONTENT_TYPES[extension]:
        raise HTTPException(
            status_code=415,
            detail=f"File content type {content_type or 'unknown'} does not match {extension}.",
        )


def validate_file_prefix(extension: str, chunk: bytes) -> None:
    signatures = {
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        ".docx": (b"PK\x03\x04",),
        ".xlsx": (b"PK\x03\x04",),
    }
    allowed = signatures.get(extension)
    if allowed and not any(chunk.startswith(signature) for signature in allowed):
        raise HTTPException(status_code=415, detail=f"File contents do not match the {extension} extension.")
    if extension == ".csv" and b"\x00" in chunk:
        raise HTTPException(status_code=415, detail="CSV content contains binary data.")


def make_report_content(
    report_id: str,
    client_name: str,
    report_type: str,
    financial_year: str,
    status_value: str,
    generated: str,
) -> str:
    with get_connection() as connection:
        transactions = connection.execute(
            """SELECT id, bank_amount, book_amount, difference, status
               FROM transactions WHERE client_id = ? ORDER BY id""",
            (
                connection.execute("SELECT id FROM clients WHERE name = ?", (client_name,)).fetchone()["id"],
            ),
        ).fetchall()
        anomalies = connection.execute(
            """SELECT id, category, amount, risk, status
               FROM anomalies WHERE client_id = ? ORDER BY id""",
            (
                connection.execute("SELECT id FROM clients WHERE name = ?", (client_name,)).fetchone()["id"],
            ),
        ).fetchall()

    transaction_lines = [
        f"- {row['id']}: bank ₹{row['bank_amount']:,.2f}, books ₹{row['book_amount']:,.2f}, "
        f"difference ₹{row['difference']:,.2f}, status {row['status']}"
        for row in transactions
    ] or ["- No transaction records are currently stored."]
    anomaly_lines = [
        f"- {row['id']}: {row['category']}, ₹{row['amount']:,.2f}, {row['risk']} risk, {row['status']}"
        for row in anomalies
    ] or ["- No anomaly records are currently stored."]
    return "\n".join(
        [
            "CA-Copilot Local Report",
            "Frontend prototype report generated from records in the local SQLite database.",
            "This report is not audited, certified, or generated by an AI system.",
            "",
            f"Report ID: {report_id}",
            f"Client: {client_name}",
            f"Report type: {report_type}",
            f"Financial year: {financial_year}",
            f"Status: {status_value}",
            f"Generated: {generated}",
            "",
            "Transactions",
            *transaction_lines,
            "",
            "Anomalies",
            *anomaly_lines,
            "",
        ]
    )


def safe_report_file(report_id: str) -> Path:
    if not re.fullmatch(r"REP-\d{4,}", report_id):
        raise HTTPException(status_code=400, detail="Invalid report ID.")
    return REPORT_DIR / f"{report_id}.txt"


def create_seed_report_files() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT r.id, c.name AS client_name, r.report_type, r.financial_year, r.status, r.generated
               FROM reports r JOIN clients c ON c.id = r.client_id"""
        ).fetchall()
    for row in rows:
        path = safe_report_file(row["id"])
        if not path.exists():
            path.write_text(
                make_report_content(
                    row["id"],
                    row["client_name"],
                    row["report_type"],
                    row["financial_year"],
                    row["status"],
                    row["generated"],
                ),
                encoding="utf-8",
            )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": "sqlite", "mode": "local"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with get_connection() as connection:
        counts = {
            "clients": connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
            "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "matched": connection.execute("SELECT COUNT(*) FROM transactions WHERE status = 'Matched'").fetchone()[0],
            "unmatched": connection.execute("SELECT COUNT(*) FROM transactions WHERE status = 'Unmatched'").fetchone()[0],
            "exceptions": connection.execute("SELECT COUNT(*) FROM transactions WHERE status = 'Exception'").fetchone()[0],
            "open_anomalies": connection.execute("SELECT COUNT(*) FROM anomalies WHERE status = 'Open'").fetchone()[0],
            "high_risk": connection.execute("SELECT COUNT(*) FROM anomalies WHERE risk = 'High' AND status != 'Resolved'").fetchone()[0],
            "anomalies_total": connection.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0],
            "reports": connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
        }
        risk_rows = connection.execute(
            "SELECT risk, COUNT(*) AS count FROM anomalies GROUP BY risk"
        ).fetchall()
        transactions = connection.execute(
            """SELECT t.*, c.name AS client_name FROM transactions t
               JOIN clients c ON c.id = t.client_id
               WHERE t.id IN ('TXN-1005', 'TXN-1003')"""
        ).fetchall()
        anomaly = connection.execute(
            """SELECT a.*, c.name AS client_name FROM anomalies a
               JOIN clients c ON c.id = a.client_id WHERE a.id = 'AN-1002'"""
        ).fetchone()
    by_id = {row["id"]: transaction_payload(row) for row in transactions}
    activity = []
    if "TXN-1005" in by_id:
        activity.append({"kind": "transaction", **by_id["TXN-1005"]})
    if anomaly:
        activity.append({"kind": "anomaly", **anomaly_payload(anomaly)})
    if "TXN-1003" in by_id:
        activity.append({"kind": "transaction", **by_id["TXN-1003"]})
    return {
        **counts,
        "risk_breakdown": {row["risk"].lower(): row["count"] for row in risk_rows},
        "activity": activity,
        "notice": "Live local SQLite counts; sample records are seeded for this frontend prototype.",
    }


@app.get("/api/clients")
def list_clients(
    search: str = Query(default="", max_length=120),
    risk: str = Query(default="all", pattern="^(all|Low|Medium|High|low|medium|high)$"),
) -> dict[str, Any]:
    sql = "SELECT * FROM clients WHERE 1=1"
    params: list[Any] = []
    if search.strip():
        term = f"%{search.strip()}%"
        sql += " AND (name LIKE ? OR industry LIKE ? OR id LIKE ?)"
        params.extend([term, term, term])
    if risk.lower() != "all":
        sql += " AND risk = ?"
        params.append(risk.title())
    sql += " ORDER BY id"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return {"items": [client_payload(row) for row in rows], "count": len(rows)}


@app.post("/api/clients", status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate) -> dict[str, Any]:
    today = now_display()
    with get_connection() as connection:
        max_id = connection.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 4) AS INTEGER)), 0) FROM clients WHERE id GLOB 'CL-[0-9]*'"
        ).fetchone()[0]
        client_id = f"CL-{max_id + 1:03d}"
        try:
            connection.execute(
                """INSERT INTO clients
                   (id, name, industry, document_count, risk, last_review, created_at, updated_at)
                   VALUES (?, ?, ?, 0, ?, ?, ?, ?)""",
                (client_id, payload.name, payload.industry, payload.risk, today, now_iso(), now_iso()),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="A client with this name already exists.") from error
        row = connection.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return client_payload(row)


@app.get("/api/clients/{client_id}")
def get_client(client_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        return client_payload(fetch_client(connection, client_id))


@app.patch("/api/clients/{client_id}")
def update_client(client_id: str, payload: ClientUpdate) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Provide at least one client field to update.")
    columns = {"name", "industry", "risk"}
    if set(updates) - columns:
        raise HTTPException(status_code=422, detail="Unsupported client update field.")
    with get_connection() as connection:
        fetch_client(connection, client_id)
        fields = [f"{column} = ?" for column in updates]
        values = list(updates.values())
        fields.append("updated_at = ?")
        values.extend([now_iso(), client_id])
        try:
            connection.execute(f"UPDATE clients SET {', '.join(fields)} WHERE id = ?", values)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="A client with this name already exists.") from error
        row = fetch_client(connection, client_id)
    return client_payload(row)


@app.delete("/api/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: str) -> None:
    with get_connection() as connection:
        fetch_client(connection, client_id)
        try:
            connection.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="This client has stored records and cannot be deleted.",
            ) from error


@app.get("/api/documents")
def list_documents(
    status_filter: str = Query(default="all", alias="status", pattern="^(all|Reviewed|Pending|Flagged|reviewed|pending|flagged)$"),
    search: str = Query(default="", max_length=200),
    client_id: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    sql = """SELECT d.*, c.name AS client_name FROM documents d
             JOIN clients c ON c.id = d.client_id WHERE 1=1"""
    params: list[Any] = []
    if status_filter.lower() != "all":
        sql += " AND d.status = ?"
        params.append(status_filter.title())
    if search.strip():
        term = f"%{search.strip()}%"
        sql += " AND (d.name LIKE ? OR c.name LIKE ? OR d.document_type LIKE ? OR d.id LIKE ?)"
        params.extend([term, term, term, term])
    if client_id:
        sql += " AND d.client_id = ?"
        params.append(client_id)
    sql += " ORDER BY d.id DESC"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return {"items": [document_payload(row) for row in rows], "count": len(rows)}


@app.post("/api/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    client_id: Annotated[str, Form(min_length=1, max_length=20)],
    name: Annotated[str, Form(min_length=1, max_length=180)],
    document_type: Annotated[str, Form(min_length=1, max_length=60)],
    financial_year: Annotated[str, Form(min_length=4, max_length=20)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    ensure_client_exists(client_id)
    original_name = Path(file.filename or "").name.strip()
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file type.")
    validate_upload(file, extension)
    if len(original_name) > 180 or not name.strip():
        raise HTTPException(status_code=422, detail="Document name is required and must be under 180 characters.")

    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / stored_name
    file_size = 0
    try:
        first_chunk = True
        with destination.open("wb") as output:
            while chunk := await file.read(64 * 1024):
                if first_chunk:
                    validate_file_prefix(extension, chunk)
                    first_chunk = False
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                output.write(chunk)
        if file_size == 0:
            raise HTTPException(status_code=422, detail="Empty files cannot be uploaded.")
        today = now_display()
        with get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO documents
                   (client_id, name, stored_name, file_size, document_type, status,
                    financial_year, upload_date, created_at)
                   VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?)""",
                (
                    client_id,
                    Path(name.strip()).name,
                    stored_name,
                    file_size,
                    document_type.strip(),
                    financial_year.strip(),
                    today,
                    now_iso(),
                ),
            )
            connection.execute(
                "UPDATE clients SET document_count = document_count + 1, updated_at = ? WHERE id = ?",
                (now_iso(), client_id),
            )
            row = connection.execute(
                """SELECT d.*, c.name AS client_name FROM documents d
                   JOIN clients c ON c.id = d.client_id WHERE d.id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return document_payload(row)


@app.post("/api/reconciliation/statements", status_code=status.HTTP_201_CREATED)
async def upload_bank_statement(
    client_id: Annotated[str, Form(min_length=1, max_length=20)],
    bank: Annotated[str, Form(min_length=2, max_length=80)],
    financial_year: Annotated[str, Form(min_length=4, max_length=20)],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    ensure_client_exists(client_id)
    original_name = Path(file.filename or "").name.strip()
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in {".pdf", ".csv", ".xls", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Statement must be a PDF, CSV, XLS, or XLSX file.")
    validate_upload(file, extension)

    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / stored_name
    file_size = 0
    try:
        first_chunk = True
        with destination.open("wb") as output:
            while chunk := await file.read(64 * 1024):
                if first_chunk:
                    validate_file_prefix(extension, chunk)
                    first_chunk = False
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                output.write(chunk)
        if file_size == 0:
            raise HTTPException(status_code=422, detail="Empty files cannot be uploaded.")
        today = now_display()
        with get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO documents
                   (client_id, name, stored_name, file_size, document_type, status,
                    financial_year, upload_date, created_at)
                   VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?)""",
                (
                    client_id,
                    original_name,
                    stored_name,
                    file_size,
                    f"Bank Statement - {bank.strip()}",
                    financial_year.strip(),
                    today,
                    now_iso(),
                ),
            )
            connection.execute(
                "UPDATE clients SET document_count = document_count + 1, updated_at = ? WHERE id = ?",
                (now_iso(), client_id),
            )
            row = connection.execute(
                """SELECT d.*, c.name AS client_name FROM documents d
                   JOIN clients c ON c.id = d.client_id WHERE d.id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {
        **document_payload(row),
        "notice": "Statement file stored locally. It was not parsed into transactions.",
    }


@app.get("/api/documents/{document_id}")
def get_document(document_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT d.*, c.name AS client_name FROM documents d
               JOIN clients c ON c.id = d.client_id WHERE d.id = ?""",
            (document_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document was not found.")
    return document_payload(row)


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: int) -> FileResponse:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT name, stored_name FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document was not found.")
    if not row["stored_name"]:
        raise HTTPException(status_code=404, detail="This sample document has no stored file to download.")
    file_path = (UPLOAD_DIR / row["stored_name"]).resolve()
    if file_path.parent != UPLOAD_DIR.resolve() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="The stored document file is unavailable.")
    return FileResponse(file_path, filename=Path(row["name"]).name, content_disposition_type="attachment")


@app.get("/api/transactions")
def list_transactions(
    status_filter: str = Query(default="all", alias="status", pattern="^(all|Matched|Unmatched|Exception|matched|unmatched|exception)$"),
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    sql = """SELECT t.*, c.name AS client_name FROM transactions t
             JOIN clients c ON c.id = t.client_id WHERE 1=1"""
    params: list[Any] = []
    if status_filter.lower() != "all":
        sql += " AND t.status = ?"
        params.append(status_filter.title())
    if search.strip():
        term = f"%{search.strip()}%"
        sql += " AND (t.id LIKE ? OR c.name LIKE ?)"
        params.extend([term, term])
    sql += " ORDER BY t.id"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return {"items": [transaction_payload(row) for row in rows], "count": len(rows)}


@app.get("/api/transactions/{transaction_id}")
def get_transaction(transaction_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT t.*, c.name AS client_name FROM transactions t
               JOIN clients c ON c.id = t.client_id WHERE t.id = ?""",
            (transaction_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction was not found.")
    return transaction_payload(row)


@app.patch("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: str, payload: TransactionStatusUpdate) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute("SELECT id FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Transaction was not found.")
        connection.execute(
            "UPDATE transactions SET status = 'Matched', difference = 0 WHERE id = ?",
            (transaction_id,),
        )
        updated = connection.execute(
            """SELECT t.*, c.name AS client_name FROM transactions t
               JOIN clients c ON c.id = t.client_id WHERE t.id = ?""",
            (transaction_id,),
        ).fetchone()
    return transaction_payload(updated)


@app.get("/api/anomalies")
def list_anomalies(
    risk: str = Query(default="all", pattern="^(all|High|Medium|Low|high|medium|low)$"),
    status_filter: str = Query(default="all", alias="status", pattern="^(all|Open|Reviewed|Resolved|open|reviewed|resolved)$"),
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    sql = """SELECT a.*, c.name AS client_name FROM anomalies a
             JOIN clients c ON c.id = a.client_id WHERE 1=1"""
    params: list[Any] = []
    if risk.lower() != "all":
        sql += " AND a.risk = ?"
        params.append(risk.title())
    if status_filter.lower() != "all":
        sql += " AND a.status = ?"
        params.append(status_filter.title())
    if search.strip():
        term = f"%{search.strip()}%"
        sql += " AND (a.id LIKE ? OR a.category LIKE ? OR c.name LIKE ? OR a.reason LIKE ?)"
        params.extend([term, term, term, term])
    sql += " ORDER BY a.id"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return {"items": [anomaly_payload(row) for row in rows], "count": len(rows)}


@app.get("/api/anomalies/{anomaly_id}")
def get_anomaly(anomaly_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT a.*, c.name AS client_name FROM anomalies a
               JOIN clients c ON c.id = a.client_id WHERE a.id = ?""",
            (anomaly_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Anomaly was not found.")
    return anomaly_payload(row)


@app.patch("/api/anomalies/{anomaly_id}")
def update_anomaly(anomaly_id: str, payload: AnomalyStatusUpdate) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute("SELECT id FROM anomalies WHERE id = ?", (anomaly_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Anomaly was not found.")
        connection.execute("UPDATE anomalies SET status = ? WHERE id = ?", (payload.status, anomaly_id))
        updated = connection.execute(
            """SELECT a.*, c.name AS client_name FROM anomalies a
               JOIN clients c ON c.id = a.client_id WHERE a.id = ?""",
            (anomaly_id,),
        ).fetchone()
    return anomaly_payload(updated)


@app.post("/api/anomalies/scan")
def scan_anomalies() -> dict[str, Any]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT t.*, c.name AS client_name FROM transactions t
               JOIN clients c ON c.id = t.client_id WHERE t.status != 'Matched' ORDER BY t.id"""
        ).fetchall()
    findings = [
        {
            "transaction_id": row["id"],
            "client": row["client_name"],
            "difference": row["difference"],
            "status": row["status"],
            "rule": "unmatched_or_exception_transaction",
        }
        for row in rows
    ]
    return {
        "mode": "rule_based_local",
        "notice": "Rule-based review of stored local transactions; no AI model or external API was used.",
        "count": len(findings),
        "findings": findings,
    }


def answer_from_database(connection: sqlite3.Connection, client: sqlite3.Row, question: str) -> str:
    lowered = question.lower()
    client_id = client["id"]
    if any(word in lowered for word in ("gst", "tax")):
        rows = connection.execute(
            """SELECT id, category, amount, status FROM anomalies
               WHERE client_id = ? AND category LIKE '%GST%' ORDER BY id""",
            (client_id,),
        ).fetchall()
        if rows:
            return "Stored sample GST-related records: " + "; ".join(
                f"{row['id']} {row['category']} ₹{row['amount']:,.2f} ({row['status']})" for row in rows
            )
        return f"No GST-category anomaly is recorded for {client['name']} in the local database."
    if any(word in lowered for word in ("pending", "document", "file")):
        rows = connection.execute(
            """SELECT name, document_type, status FROM documents
               WHERE client_id = ? AND status = 'Pending' ORDER BY id""",
            (client_id,),
        ).fetchall()
        if rows:
            return f"{client['name']} has {len(rows)} stored pending document(s): " + "; ".join(
                f"{row['name']} ({row['document_type']})" for row in rows
            )
        return f"No pending documents are recorded for {client['name']} in the local database."
    if any(word in lowered for word in ("transaction", "bank", "reconcil", "amount", "high-value")):
        rows = connection.execute(
            """SELECT id, bank_amount, book_amount, difference, status FROM transactions
               WHERE client_id = ? ORDER BY id""",
            (client_id,),
        ).fetchall()
        if rows:
            return f"Stored transactions for {client['name']}: " + "; ".join(
                f"{row['id']} bank ₹{row['bank_amount']:,.2f}, books ₹{row['book_amount']:,.2f}, "
                f"difference ₹{row['difference']:,.2f} ({row['status']})"
                for row in rows
            )
        return f"No transactions are recorded for {client['name']} in the local database."
    if any(word in lowered for word in ("summary", "summar")):
        doc_count = connection.execute(
            "SELECT COUNT(*) FROM documents WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
        transaction_count = connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
        anomaly_count = connection.execute(
            "SELECT COUNT(*) FROM anomalies WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
        return (
            f"{client['name']} has {doc_count} stored document record(s), {transaction_count} "
            f"transaction record(s), and {anomaly_count} anomaly record(s)."
        )
    return (
        f"I can answer questions about the stored documents, GST anomalies, transactions, or "
        f"a summary for {client['name']}. Ask about one of those topics."
    )


@app.post("/api/chat/ask")
def ask_client_file(payload: ChatRequest) -> dict[str, str]:
    with get_connection() as connection:
        client = fetch_client(connection, payload.client_id)
        answer = answer_from_database(connection, client, payload.question)
        connection.execute(
            "INSERT INTO chat_messages (client_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
            (payload.client_id, payload.question, answer, now_iso()),
        )
    return {
        "client_id": payload.client_id,
        "client": client["name"],
        "question": payload.question,
        "answer": answer,
        "mode": "rule_based_local",
        "notice": "Rule-based response from locally stored records; no AI model or external API was used.",
    }


@app.get("/api/chat/{client_id}")
def list_chat_messages(client_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with get_connection() as connection:
        fetch_client(connection, client_id)
        rows = connection.execute(
            """SELECT id, question, answer, created_at FROM chat_messages
               WHERE client_id = ? ORDER BY id DESC LIMIT ?""",
            (client_id, limit),
        ).fetchall()
    return {"items": [dict(row) for row in reversed(rows)], "count": len(rows)}


@app.delete("/api/chat/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def clear_chat(client_id: str) -> None:
    with get_connection() as connection:
        fetch_client(connection, client_id)
        connection.execute("DELETE FROM chat_messages WHERE client_id = ?", (client_id,))


@app.get("/api/reports")
def list_reports(
    status_filter: str = Query(default="all", alias="status", pattern="^(all|Completed|Draft|Pending|completed|draft|pending)$"),
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    sql = """SELECT r.*, c.name AS client_name FROM reports r
             JOIN clients c ON c.id = r.client_id WHERE 1=1"""
    params: list[Any] = []
    if status_filter.lower() != "all":
        sql += " AND r.status = ?"
        params.append(status_filter.title())
    if search.strip():
        term = f"%{search.strip()}%"
        sql += " AND (r.id LIKE ? OR c.name LIKE ? OR r.report_type LIKE ? OR r.financial_year LIKE ?)"
        params.extend([term, term, term, term])
    sql += " ORDER BY r.id"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return {"items": [report_payload(row) for row in rows], "count": len(rows)}


@app.post("/api/reports", status_code=status.HTTP_201_CREATED)
def create_report(payload: ReportCreate) -> dict[str, Any]:
    today = now_display()
    with get_connection() as connection:
        client = fetch_client(connection, payload.client_id)
        max_id = connection.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 1000) FROM reports WHERE id GLOB 'REP-[0-9]*'"
        ).fetchone()[0]
        report_id = f"REP-{max_id + 1:04d}"
        stored_name = f"{report_id}.txt"
        try:
            connection.execute(
                """INSERT INTO reports
                   (id, client_id, report_type, financial_year, status, generated, stored_name)
                   VALUES (?, ?, ?, ?, 'Draft', ?, ?)""",
                (report_id, client["id"], payload.report_type.strip(), payload.financial_year.strip(), today, stored_name),
            )
            row = connection.execute(
                """SELECT r.*, c.name AS client_name FROM reports r
                   JOIN clients c ON c.id = r.client_id WHERE r.id = ?""",
                (report_id,),
            ).fetchone()
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Report could not be created.") from error
    report_path = safe_report_file(report_id)
    report_path.write_text(
        make_report_content(
            report_id,
            row["client_name"],
            row["report_type"],
            row["financial_year"],
            row["status"],
            row["generated"],
        ),
        encoding="utf-8",
    )
    return report_payload(row)


@app.get("/api/reports/{report_id}")
def get_report(report_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT r.*, c.name AS client_name FROM reports r
               JOIN clients c ON c.id = r.client_id WHERE r.id = ?""",
            (report_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Report was not found.")
    return report_payload(row)


@app.get("/api/reports/{report_id}/download")
def download_report(report_id: str) -> FileResponse:
    with get_connection() as connection:
        row = connection.execute("SELECT stored_name FROM reports WHERE id = ?", (report_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Report was not found.")
    file_path = safe_report_file(report_id)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The report file is unavailable.")
    return FileResponse(
        file_path,
        filename=row["stored_name"],
        media_type="text/plain",
        content_disposition_type="attachment",
    )


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute("SELECT values_json FROM settings WHERE id = 1").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO settings (id, values_json, updated_at) VALUES (1, ?, ?)",
                (json.dumps(DEFAULT_SETTINGS), now_iso()),
            )
            return dict(DEFAULT_SETTINGS)
    try:
        return {**DEFAULT_SETTINGS, **json.loads(row["values_json"])}
    except (TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail="Stored settings are corrupted.") from error


@app.put("/api/settings")
def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
    values = payload.model_dump()
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO settings (id, values_json, updated_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET values_json = excluded.values_json,
               updated_at = excluded.updated_at""",
            (json.dumps(values), now_iso()),
        )
    return values


@app.post("/api/settings/reset")
def reset_settings() -> dict[str, Any]:
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO settings (id, values_json, updated_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET values_json = excluded.values_json,
               updated_at = excluded.updated_at""",
            (json.dumps(DEFAULT_SETTINGS), now_iso()),
        )
    return dict(DEFAULT_SETTINGS)


@app.exception_handler(sqlite3.Error)
async def sqlite_error_handler(_request: Any, _error: sqlite3.Error) -> Any:
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500,
        content={"detail": "A local database error occurred. Check the backend log for details."},
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(_request: Any, error: ValidationError) -> Any:
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=422, content={"detail": error.errors(include_url=False)})
