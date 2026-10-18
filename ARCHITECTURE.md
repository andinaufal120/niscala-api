# Architecture Overview

How the Niscala backend is built. What it has to do is in `docs/SPEC.md`; this file does not repeat it. Update this file in the same PR as any change to the structure it describes. Parts marked *not built yet* are planned and have no code.

## 1. Project Structure

```
niscala-api/
├── src/app/
│   ├── main.py        # FastAPI app: includes the routers, registers the error handlers
│   ├── config.py      # Settings read from environment variables (.env supported)
│   ├── errors.py      # ApiError and the handlers that give every error one JSON shape
│   ├── db.py          # SQLAlchemy engine and the per-request session dependency
│   ├── models/        # SQLAlchemy tables: user_accounts, sessions (declarative Base with a constraint naming convention)
│   ├── security.py    # bearerAuth scheme and the get_current_user dependency
│   ├── services/      # Business rules per area; routers call them (sessions so far)
│   ├── routers/       # One module per resource: parse the request, return a schema
│   └── schemas/       # Pydantic request and response models; they define the OpenAPI contract
├── migrations/        # Alembic environment and revisions (alembic.ini at the root)
├── tests/             # pytest: contract tests against the generated OpenAPI document, and tests against a throwaway PostgreSQL
├── docs/SPEC.md       # Requirements, glossary and endpoint table
├── .claude/           # Agent definitions and hooks for the test-first workflow
└── .github/workflows/ # Claude Code review
```

*Not built yet:* the other services, `ai/` (Gemini classifier), `email.py` and `cli.py`.

## 2. High-Level System Diagram

```
Flutter app --HTTPS/JSON--> FastAPI (routers -> schemas) --> PostgreSQL
                                  |
                                  +--> Gemini (classification)               (not built yet)
                                  +--> email sender                          (not built yet)
```

The generated OpenAPI document is the contract with the app. Routers stay thin; rules belong in services, which raise `ApiError`.

## 3. Core Components

### 3.1. App

The Flutter Android app lives in `andinaufal120/niscala-app`. It generates its Dart client from this API's OpenAPI document and renders what the API returns. Nothing about its internals is documented here.

### 3.2. Backend

- **Routers** (`routers/`): FastAPI `APIRouter`s grouped by resource. Endpoints not implemented yet answer `501`.
- **Schemas** (`schemas/`): Pydantic models on `ApiModel`, which exposes snake_case attributes as camelCase fields.
- **Errors** (`errors.py`): every error response is `{"code", "field", "message"}`. Services raise `ApiError(status_code, code, message, field)`. Request validation errors become `VALIDATION_FAILED` with the first failing field. Any other `HTTPException` gets its status phrase as code (`NOT_FOUND`), and an unexpected exception becomes `INTERNAL_ERROR` without leaking its text.
- **Settings** (`config.py`): `get_settings()` returns a cached `Settings` read from the environment.
- **Database** (`db.py`): `get_session()` is a request dependency that yields a SQLAlchemy `Session`. It commits when the handler returns and rolls back when it raises, so a failed request saves nothing. The database enforces structural integrity only; business rules live in code.

Technologies: Python 3.14, FastAPI, Pydantic, pydantic-settings, SQLAlchemy 2, Alembic, psycopg 3, managed with uv.

## 4. Data Stores

PostgreSQL (Supabase in production), reached through `DATABASE_URL`. Schema changes are Alembic revisions in `migrations/`; a test checks that the migrated schema matches the models. Tables so far: `user_accounts` and `sessions`. Facility tags will be a text-array column on the room.

## 5. External Integrations / APIs

- **Gemini** (complaint classification, payment-pattern summaries): *not built yet.*
- **Google Play Developer API** (subscription verification) and **Firebase Cloud Messaging** (push): *not built yet.*

## 6. Deployment & Infrastructure

Fly.io for the API and Supabase for the database are planned; *not set up yet.* GitHub Actions runs Claude Code review on pull requests (`.github/workflows/`).

## 7. Security Considerations

- Authentication: a bearer JWT access token (HS256, 15 minutes, signed with `JWT_SECRET`), declared as `bearerAuth` in the OpenAPI document. `get_current_user` validates it and also loads the session row, so an ended session stops working at once. The refresh token is opaque, stored only as a SHA-256 hash, and rotated on every use; presenting a rotated one ends the session. Sessions end after 90 days idle or 1 year after login.
- Authorization: role and property access are enforced by the backend (`docs/SPEC.md` §4).
- Transport: HTTPS only.

## 8. Development & Testing Environment

- `uv sync` installs dependencies; `uv run pytest` runs the tests; `uv run ruff check` and `uv run ruff format` lint and format.
- Tests that touch the database start a throwaway PostgreSQL container (testcontainers), so Docker must be running. Tests that don't need it run without Docker. Tables are emptied after each test.
- `uv run alembic upgrade head` applies migrations to the database in `DATABASE_URL`.
- Tests come first: `test-writer` and `implementer` subagents (`.claude/agents/`) work in two steps, as described in `CLAUDE.md`.

## 9. Future Considerations

Open architecture questions are listed in `docs/SPEC.md` §10 (for example U-9 error codes in OpenAPI, U-15 conflict detection, TBD-3 Google Play integration).

## 10. Project Identification

- Project: niscala-api
- Repository: https://github.com/andinaufal120/niscala-api
- Last updated: 2026-10-18

## 11. Glossary

Domain terms and code names are in `docs/SPEC.md` §3.
