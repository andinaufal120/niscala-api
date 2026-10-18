# Architecture Overview

How the Niscala backend is built. What it has to do is in `docs/SPEC.md`; this file does not repeat it. Update this file in the same PR as any change to the structure it describes. Parts marked *not built yet* are planned and have no code.

## 1. Project Structure

```
niscala-api/
├── src/app/
│   ├── main.py        # FastAPI app: includes the routers, registers the error handlers
│   ├── config.py      # Settings read from environment variables (.env supported)
│   ├── errors.py      # ApiError and the handlers that give every error one JSON shape
│   ├── security.py    # bearerAuth scheme declared on operations that need a session
│   ├── routers/       # One module per resource: parse the request, return a schema
│   └── schemas/       # Pydantic request and response models; they define the OpenAPI contract
├── tests/             # pytest: contract tests against the generated OpenAPI document
├── docs/SPEC.md       # Requirements, glossary and endpoint table
├── .claude/           # Agent definitions and hooks for the test-first workflow
└── .github/workflows/ # Claude Code review
```

*Not built yet:* `services/` (business rules per area), `models/` and `db.py` (SQLAlchemy tables), `ai/` (Gemini classifier), `email.py`, `cli.py` and `migrations/` (Alembic).

## 2. High-Level System Diagram

```
Flutter app --HTTPS/JSON--> FastAPI (routers -> schemas) --> PostgreSQL     (not built yet)
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

Technologies: Python 3.14, FastAPI, Pydantic, pydantic-settings, managed with uv.

## 4. Data Stores

PostgreSQL (Supabase in production) with SQLAlchemy and Alembic. *Not built yet.*

## 5. External Integrations / APIs

- **Gemini** (complaint classification, payment-pattern summaries): *not built yet.*
- **Google Play Developer API** (subscription verification) and **Firebase Cloud Messaging** (push): *not built yet.*

## 6. Deployment & Infrastructure

Fly.io for the API and Supabase for the database are planned; *not set up yet.* GitHub Actions runs Claude Code review on pull requests (`.github/workflows/`).

## 7. Security Considerations

- Authentication: bearer JWT access token, declared as `bearerAuth` in the OpenAPI document. Token issuing and checking are *not built yet*.
- Authorization: role and property access are enforced by the backend (`docs/SPEC.md` §4).
- Transport: HTTPS only.

## 8. Development & Testing Environment

- `uv sync` installs dependencies; `uv run pytest` runs the tests; `uv run ruff check` and `uv run ruff format` lint and format.
- Tests come first: `test-writer` and `implementer` subagents (`.claude/agents/`) work in two steps, as described in `CLAUDE.md`.

## 9. Future Considerations

Open architecture questions are listed in `docs/SPEC.md` §10 (for example U-9 error codes in OpenAPI, U-15 conflict detection, TBD-3 Google Play integration).

## 10. Project Identification

- Project: niscala-api
- Repository: https://github.com/andinaufal120/niscala-api
- Last updated: 2026-10-18

## 11. Glossary

Domain terms and code names are in `docs/SPEC.md` §3.
