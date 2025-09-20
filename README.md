# GreenBucks Backend

FastAPI-based backend scaffold for GreenBucks.

## Features

- Health endpoint at `GET /health`
- Root info endpoint at `GET /`
- Centralized configuration via `.env` using `pydantic-settings`
- CORS enabled (allow all by default — adjust for production)

## Project Structure

```
backend/
  app/
    api/
      routes/
        health.py
    core/
      config.py
    __init__.py
    main.py
  __init__.py
requirements.txt
README.md
.env.example
```

## Setup

1. Create and activate a virtual environment

   macOS/Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   Windows (PowerShell):
   ```powershell
   python -m venv .venv
   .venv\\Scripts\\Activate.ps1
   ```

2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment
   - Copy `.env.example` to `.env` and fill values as needed.

4. Run the server (development)
   ```bash
   uvicorn backend.app.main:app --reload --port 8000
   ```

   The API will be available at http://127.0.0.1:8000

   - Docs: http://127.0.0.1:8000/docs
   - Health: http://127.0.0.1:8000/health

## Environment Variables

All configuration is managed in `backend/app/core/config.py` via `Settings`. The app reads `.env` from the repository root.

- App
  - `APP_NAME` (default: `GreenBucks API`)
  - `ENVIRONMENT` (default: `development`)
  - `DEBUG` (default: `true`)

- Database
  - `DATABASE_URL` (e.g., `postgresql+psycopg://user:pass@localhost:5432/greenbucks`)

- Object Storage (S3-compatible)
  - `S3_ENDPOINT_URL`
  - `S3_BUCKET_NAME`

- Plaid
  - `PLAID_CLIENT_ID`
  - `PLAID_SECRET`

- Cerebras
  - `CEREBRAS_API_KEY`

## Next Steps

- Add database models and migrations (SQLAlchemy + Alembic)
- Implement auth (JWT) and user endpoints
- Add services for Plaid, OCR, and Eco-Scoring
- Wire up S3 client

## Database

This project uses SQLAlchemy 2.0 and Alembic for migrations.

By default, it runs against a local SQLite database for easy development.

- Default URL: `sqlite:///./greenbucks.db` (configured in `backend/app/core/config.py`)

To use PostgreSQL, set `DATABASE_URL` in your `.env`, for example:

```
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/greenbucks
```

### Create and run migrations

1. Ensure your virtual environment is active and dependencies installed:

```bash
pip install -r requirements.txt
```

2. Apply migrations (creates tables):

```bash
alembic upgrade head
```

3. To generate a new migration after changing models, run:

```bash
alembic revision --autogenerate -m "your message"
alembic upgrade head
```

Alembic is preconfigured in `alembic/env.py` to read `DATABASE_URL` from your app settings and auto-import models from `backend/app/models/`.
