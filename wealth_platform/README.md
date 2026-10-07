# WealthFlow

Advanced async wealth and expense management platform using FastAPI, Pydantic v2, SQLAlchemy AsyncIO, PostgreSQL/SQLite, Tailwind CDN, ApexCharts, and vanilla ES6.

## Windows setup

1. Install Python 3.12+.
2. Open this folder in VS Code.
3. Create a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

4. Install dependencies:

```powershell
pip install -r requirements.txt
```

5. Copy `.env.example` to `.env`.

6. Start the application:

```powershell
uvicorn main:app --reload
```

7. Open:

http://127.0.0.1:8000

The default database is SQLite, so PostgreSQL is not required for the first run. To use PostgreSQL, set DATABASE_URL in `.env`, for example:

DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/wealthflow

## Included

- JWT authentication with HttpOnly cookie and Bearer-token fallback
- bcrypt password hashing
- user-isolated records
- async SQLAlchemy 2 models
- recurring transaction worker
- multi-currency conversion architecture
- spending velocity and month-end projection
- budget threshold date calculation
- ApexCharts income/expense timeline
- category donut drill-down
- ledger search, kind and amount filters
- CSV and XLSX export
- responsive Tailwind dashboard
