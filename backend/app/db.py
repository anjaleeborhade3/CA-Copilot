import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("CA_COPILOT_DATA_DIR", PROJECT_ROOT / "backend" / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
DATABASE_PATH = DATA_DIR / "ca_copilot.sqlite3"


DEFAULT_SETTINGS = {
    "fullName": "CA Admin",
    "email": "admin@cacopilot.com",
    "role": "Chartered Accountant",
    "firmName": "CA Copilot Advisory",
    "officeEmail": "contact@cacopilot.com",
    "officeLocation": "Pune, Maharashtra",
    "emailNotifications": True,
    "riskAlerts": True,
    "reportNotifications": True,
    "twoFactor": False,
    "theme": "light",
    "layout": "Comfortable",
}


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                industry TEXT NOT NULL,
                document_count INTEGER NOT NULL DEFAULT 0 CHECK (document_count >= 0),
                risk TEXT NOT NULL CHECK (risk IN ('Low', 'Medium', 'High')),
                last_review TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE ON DELETE RESTRICT,
                name TEXT NOT NULL,
                stored_name TEXT,
                file_size INTEGER NOT NULL DEFAULT 0 CHECK (file_size >= 0),
                document_type TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('Reviewed', 'Pending', 'Flagged')),
                financial_year TEXT NOT NULL,
                upload_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE ON DELETE RESTRICT,
                bank_amount REAL NOT NULL CHECK (bank_amount >= 0),
                book_amount REAL NOT NULL CHECK (book_amount >= 0),
                difference REAL NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('Matched', 'Unmatched', 'Exception')),
                transaction_date TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS anomalies (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE ON DELETE RESTRICT,
                category TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount >= 0),
                risk TEXT NOT NULL CHECK (risk IN ('Low', 'Medium', 'High')),
                status TEXT NOT NULL CHECK (status IN ('Open', 'Reviewed', 'Resolved')),
                detected TEXT NOT NULL,
                reason TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE ON DELETE RESTRICT,
                report_type TEXT NOT NULL,
                financial_year TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('Completed', 'Draft', 'Pending')),
                generated TEXT NOT NULL,
                stored_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                values_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL REFERENCES clients(id) ON UPDATE CASCADE ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_documents_client_status ON documents(client_id, status);
            CREATE INDEX IF NOT EXISTS idx_transactions_client_status ON transactions(client_id, status);
            CREATE INDEX IF NOT EXISTS idx_anomalies_client_status ON anomalies(client_id, status);
            CREATE INDEX IF NOT EXISTS idx_reports_client_status ON reports(client_id, status);
            CREATE INDEX IF NOT EXISTS idx_chat_client_created ON chat_messages(client_id, created_at);
            """
        )

        has_clients = connection.execute("SELECT 1 FROM clients LIMIT 1").fetchone()
        if has_clients:
            return

        today = date.today().strftime("%d %b %Y")
        clients = [
            ("CL-001", "ABC Enterprises", "Manufacturing", 32, "High", "06 Oct 2026"),
            ("CL-002", "Shree Traders", "Wholesale", 27, "Medium", "05 Oct 2026"),
            ("CL-003", "Patil Industries", "Engineering", 41, "Low", "04 Oct 2026"),
            ("CL-004", "Global Services", "IT Services", 19, "Low", "02 Oct 2026"),
        ]
        for client in clients:
            connection.execute(
                """INSERT INTO clients
                   (id, name, industry, document_count, risk, last_review, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (*client, today, today),
            )

        documents = [
            ("CL-001", "GST_Return_Q2.pdf", None, 2_516_582, "GST", "Reviewed", "FY 2026-27", "06 Oct 2026"),
            ("CL-002", "Bank_Statement_Sep.pdf", None, 4_299_162, "Bank Statement", "Pending", "FY 2026-27", "05 Oct 2026"),
            ("CL-003", "Invoice_1045.pdf", None, 1_887_437, "Invoice", "Flagged", "FY 2026-27", "04 Oct 2026"),
            ("CL-004", "Balance_Sheet_FY26.pdf", None, 3_774_874, "Balance Sheet", "Reviewed", "FY 2025-26", "02 Oct 2026"),
        ]
        connection.executemany(
            """INSERT INTO documents
               (client_id, name, stored_name, file_size, document_type, status, financial_year, upload_date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(*item, today) for item in documents],
        )

        transactions = [
            ("TXN-1001", "CL-001", 85000, 85000, 0, "Matched", "06 Oct 2026"),
            ("TXN-1002", "CL-002", 52500, 50000, 2500, "Unmatched", "05 Oct 2026"),
            ("TXN-1003", "CL-003", 125000, 118000, 7000, "Exception", "04 Oct 2026"),
            ("TXN-1004", "CL-004", 96000, 96000, 0, "Matched", "02 Oct 2026"),
            ("TXN-1005", "CL-001", 43750, 45000, -1250, "Unmatched", "01 Oct 2026"),
        ]
        connection.executemany(
            """INSERT INTO transactions
               (id, client_id, bank_amount, book_amount, difference, status, transaction_date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            transactions,
        )

        anomalies = [
            ("AN-1001", "CL-001", "Duplicate Invoice", 85000, "High", "Open", "06 Oct 2026", "Two invoices with identical invoice number and amount were detected."),
            ("AN-1002", "CL-002", "GST Mismatch", 52500, "Medium", "Reviewed", "05 Oct 2026", "GST amount reported in the invoice does not match the accounting record."),
            ("AN-1003", "CL-003", "Unusual Transaction", 125000, "High", "Open", "04 Oct 2026", "Transaction value is significantly higher than the client’s normal transaction pattern."),
            ("AN-1004", "CL-004", "Round Amount", 96000, "Low", "Resolved", "02 Oct 2026", "Large round-value transaction was flagged for routine verification."),
            ("AN-1005", "CL-001", "Bank Reconciliation", 43750, "Medium", "Open", "01 Oct 2026", "Bank statement amount differs from the accounting ledger."),
        ]
        connection.executemany(
            """INSERT INTO anomalies
               (id, client_id, category, amount, risk, status, detected, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            anomalies,
        )

        reports = [
            ("REP-1001", "CL-001", "Audit Summary", "2026–27", "Completed", "06 Oct 2026"),
            ("REP-1002", "CL-002", "GST Compliance", "2026–27", "Completed", "05 Oct 2026"),
            ("REP-1003", "CL-003", "Risk Assessment", "2026–27", "Draft", "04 Oct 2026"),
            ("REP-1004", "CL-004", "Financial Review", "2026–27", "Pending", "02 Oct 2026"),
            ("REP-1005", "CL-001", "Reconciliation Report", "2026–27", "Completed", "01 Oct 2026"),
        ]
        connection.executemany(
            """INSERT INTO reports
               (id, client_id, report_type, financial_year, status, generated, stored_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(*item, f"{item[0]}.txt") for item in reports],
        )
        connection.execute(
            "INSERT INTO settings (id, values_json, updated_at) VALUES (1, ?, ?)",
            (json.dumps(DEFAULT_SETTINGS), today),
        )

