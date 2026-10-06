import os
import tempfile
import unittest



TEST_DATA = tempfile.TemporaryDirectory(prefix="ca-copilot-api-test-")
os.environ["CA_COPILOT_DATA_DIR"] = TEST_DATA.name

from fastapi.testclient import TestClient

from backend.app.main import app


class ApiWorkflowTests(unittest.TestCase):
    def test_complete_local_api_workflow(self) -> None:
        with TestClient(app) as client:
            health = client.get("/api/health", headers={"Origin": "http://localhost:8000"})
            self.assertEqual(health.json()["status"], "ok")
            self.assertEqual(health.headers["access-control-allow-origin"], "http://localhost:8000")
            dashboard = client.get("/api/dashboard").json()
            self.assertEqual(dashboard["clients"], 4)
            self.assertEqual(
                [entry["id"] for entry in dashboard["activity"]],
                ["TXN-1005", "AN-1002", "TXN-1003"],
            )

            clients = client.get("/api/clients").json()
            self.assertEqual(clients["count"], 4)
            created_client = client.post(
                "/api/clients",
                json={"name": "Example Local Client", "industry": "Professional Services", "risk": "Medium"},
            )
            self.assertEqual(created_client.status_code, 201)
            self.assertEqual(created_client.json()["id"], "CL-005")
            self.assertEqual(client.patch(
                "/api/clients/CL-005",
                json={"risk": "High"},
            ).json()["risk"], "High")
            self.assertEqual(client.get("/api/clients", params={"risk": "High"}).json()["count"], 2)

            uploaded = client.post(
                "/api/documents",
                data={
                    "client_id": "CL-005",
                    "name": "Local Invoice.pdf",
                    "document_type": "Invoice",
                    "financial_year": "FY 2026-27",
                },
                files={"file": ("invoice.pdf", b"%PDF-1.7 local test file", "application/pdf")},
            )
            self.assertEqual(uploaded.status_code, 201)
            document_id = uploaded.json()["id"]
            self.assertTrue(uploaded.json()["available_for_download"])
            self.assertEqual(client.get("/api/documents", params={"status": "Pending"}).json()["count"], 2)
            self.assertEqual(client.get(f"/api/documents/{document_id}").status_code, 200)
            self.assertEqual(client.get(f"/api/documents/{document_id}/download").content, b"%PDF-1.7 local test file")
            rejected_upload = client.post(
                "/api/documents",
                data={
                    "client_id": "CL-005",
                    "name": "bad.exe",
                    "document_type": "Other",
                    "financial_year": "FY 2026-27",
                },
                files={"file": ("bad.exe", b"not allowed", "application/octet-stream")},
            )
            self.assertEqual(rejected_upload.status_code, 415)
            rejected_signature = client.post(
                "/api/documents",
                data={
                    "client_id": "CL-005",
                    "name": "spoofed.pdf",
                    "document_type": "Other",
                    "financial_year": "FY 2026-27",
                },
                files={"file": ("spoofed.pdf", b"not a PDF", "application/pdf")},
            )
            self.assertEqual(rejected_signature.status_code, 415)

            statement = client.post(
                "/api/reconciliation/statements",
                data={"client_id": "CL-005", "bank": "Local Test Bank", "financial_year": "FY 2026-27"},
                files={"file": ("statement.csv", b"date,amount\n", "text/csv")},
            )
            self.assertEqual(statement.status_code, 201)
            self.assertIn("not parsed", statement.json()["notice"])

            transaction = client.get("/api/transactions/TXN-1005").json()
            self.assertEqual(transaction["status"], "Unmatched")
            self.assertEqual(
                client.patch("/api/transactions/TXN-1005", json={"status": "Matched"}).json()["status"],
                "Matched",
            )
            self.assertEqual(client.get("/api/transactions", params={"status": "Matched"}).json()["count"], 3)

            anomaly = client.get("/api/anomalies/AN-1001").json()
            self.assertEqual(anomaly["status"], "Open")
            self.assertEqual(client.get("/api/anomalies", params={"status": "Open"}).json()["count"], 3)
            self.assertEqual(
                client.patch("/api/anomalies/AN-1001", json={"status": "Resolved"}).json()["status"],
                "Resolved",
            )
            self.assertEqual(client.get("/api/anomalies", params={"status": "Open"}).json()["count"], 2)
            scan = client.post("/api/anomalies/scan", json={}).json()
            self.assertEqual(scan["mode"], "rule_based_local")
            self.assertIn("no AI model", scan["notice"])

            answer = client.post(
                "/api/chat/ask",
                json={"client_id": "CL-002", "question": "Are there GST mismatches?"},
            ).json()
            self.assertEqual(answer["client"], "Shree Traders")
            self.assertIn("GST", answer["answer"])
            self.assertEqual(client.get("/api/chat/CL-002").json()["count"], 1)
            self.assertEqual(client.delete("/api/chat/CL-002").status_code, 204)

            report = client.post(
                "/api/reports",
                json={"client_id": "CL-005", "report_type": "Local Summary", "financial_year": "FY 2026-27"},
            )
            self.assertEqual(report.status_code, 201)
            self.assertEqual(report.json()["id"], "REP-1006")
            self.assertEqual(report.json()["status"], "Draft")
            self.assertEqual(client.get("/api/reports/REP-1006").status_code, 200)
            self.assertEqual(client.get("/api/reports", params={"status": "Draft", "search": "Local"}).json()["count"], 1)
            self.assertIn(b"Local Summary", client.get("/api/reports/REP-1006/download").content)

            settings = client.get("/api/settings").json()
            settings["fullName"] = "Saved Local User"
            self.assertEqual(client.put("/api/settings", json=settings).json()["fullName"], "Saved Local User")
            self.assertEqual(client.get("/api/settings").json()["fullName"], "Saved Local User")
            self.assertEqual(client.post("/api/settings/reset", json={}).json()["fullName"], "CA Admin")

            self.assertEqual(client.get("/api/clients/missing").status_code, 404)
            self.assertEqual(
                client.post("/api/clients", json={"name": "x", "industry": "y", "risk": "Unknown"}).status_code,
                422,
            )
            self.assertEqual(client.delete("/api/clients/CL-005").status_code, 409)
            disposable_client = client.post(
                "/api/clients",
                json={"name": "Disposable Local Client", "industry": "Testing", "risk": "Low"},
            )
            self.assertEqual(disposable_client.status_code, 201)
            self.assertEqual(
                client.delete("/api/clients/" + disposable_client.json()["id"]).status_code,
                204,
            )


if __name__ == "__main__":
    unittest.main()
