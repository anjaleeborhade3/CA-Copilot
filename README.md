# FinPilot local frontend and backend

FinPilot is a local frontend prototype with a FastAPI service and SQLite persistence. It does not connect to a hosted service, external API, or AI model.

## Run locally

From the project folder, create the Python environment and install the backend requirements:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Start the backend in one terminal:

```bash
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

Start the static frontend from the project folder in another terminal:

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/`. The API health endpoint and interactive API documentation are available at `http://127.0.0.1:8001/api/health` and `http://127.0.0.1:8001/docs`.

To run the API integration tests, install the test requirements and run:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest backend.tests.test_api -v
```

## Data and prototype limitations

- SQLite data is stored in `backend/data/ca_copilot.sqlite3`; uploaded files and generated text reports are stored in the sibling `uploads/` and `reports/` folders. Set `CA_COPILOT_DATA_DIR` to use a different local data directory.
- The API seeds the existing sample clients, documents, transactions, anomalies, and reports into an empty database.
- Bank statement files are stored as documents. The prototype does not parse statements into transactions.
- Risk scanning applies a documented local rule to stored unmatched/exception transactions. Client-file answers are rule-based summaries of local records; neither feature uses AI.
- Generated reports are local text summaries of stored records, not audited or certified reports.
- The change-password flow is a frontend demo. Theme and layout values persist, but do not currently restyle the pages.
- The API is intended for local development, not production deployment; it does not provide authentication or user accounts.
