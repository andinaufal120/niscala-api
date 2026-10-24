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
│   ├── models/        # SQLAlchemy tables: user_accounts, sessions, email_verification_codes (declarative Base with a constraint naming convention)
│   ├── security.py    # bearerAuth scheme and the get_current_user dependency
│   ├── email.py       # EmailSender protocol; the console sender only logs the code
│   ├── ai/            # ComplaintClassifier protocol, the Gemini classifier and the dependency that supplies it
│   ├── plans.py       # Plan limits per subscription plan, as data
│   ├── cli.py         # `niscala-api` command: grant-subscription, seed-rent-bills and seed-demo (development tools)
│   ├── access.py      # require_roles and the property access queries (owner: own, manager: assigned)
│   ├── services/      # Business rules per area; routers call them (sessions, accounts, passwords, email verification, subscriptions, properties, rooms, leases, invitations, activation, complaints, rent bills, dashboard, managers, demo data)
│   ├── routers/       # One module per resource: parse the request, return a schema
│   └── schemas/       # Pydantic request and response models; they define the OpenAPI contract
├── data/              # common-passwords.txt: the 100,000 most used passwords (SecLists, MIT license)
├── migrations/        # Alembic environment and revisions (alembic.ini at the root)
├── tests/             # pytest: contract tests against the generated OpenAPI document, and tests against a throwaway PostgreSQL
├── docs/SPEC.md       # Requirements, glossary and endpoint table
├── .claude/           # Agent definitions and hooks for the test-first workflow
└── .github/workflows/ # Claude Code review
```

*Not built yet:* the other services.

## 2. High-Level System Diagram

```
Flutter app --HTTPS/JSON--> FastAPI (routers -> schemas) --> PostgreSQL
                                  |
                                  +--> Gemini (classification)
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
- **Logging** (`main.py`): logs go to stderr; INFO records from the `app` loggers are shown, including the verification codes the console email sender prints in development.
- **Database** (`db.py`): `get_session()` yields a SQLAlchemy `Session`; endpoints and dependencies declare it as `SessionDep`, a function-scope dependency. It commits when the handler returns and rolls back when it raises, so a failed request saves nothing. Function scope makes the commit happen before the response is sent, so a failed commit becomes an error response. The database enforces structural integrity only; business rules live in code.
- **Rent bills** (`services/rent_bills.py`): a bill, its status history and its transfer receipt are three tables. The receipt image is stored in the database as bytes (one per bill, replaced on re-upload) so a failed request saves nothing; the type is read from the file signature. Dates that depend on the calendar day (current period, future-date checks, payment date of a verified receipt) are read in Asia/Jakarta through `today_jakarta()`. Notifying the tenant and regenerating the payment-pattern summary after a status change have named empty hooks (`notify_status_change`, `regenerate_payment_pattern`) until those features are built; bills are created only by the development seed command, since bill generation is undecided.
- **Complaints** (`services/complaints.py`): a complaint, its status history and its classification are stored together; classification runs after the save in a background task. Moving a complaint to its next status calls `notify_complaint_status_change`, an empty hook until notifications are built; a failing hook is logged and never undoes the change.
- **Managers** (`services/managers.py`): a Manager is a login account (role manager, shared by every Owner the person works for) plus one `managers` record per Owner, which holds that Owner's nickname and phone and when the Manager activated. Property access still comes from `manager_assignments`, keyed by the account. Invitations belong to either a tenant or a manager record (exactly one is set).

Technologies: Python 3.14, FastAPI, Pydantic, pydantic-settings, SQLAlchemy 2, Alembic, psycopg 3, managed with uv.

## 4. Data Stores

PostgreSQL (Supabase on the deployed server), reached through `DATABASE_URL`. Schema changes are Alembic revisions in `migrations/`; a test checks that the migrated schema matches the models. Tables so far: `user_accounts`, `sessions`, `used_refresh_tokens`, `email_verification_codes`, `login_failures`, `properties`, `manager_assignments`, `subscriptions`, `rooms`, `tenants`, `emergency_contacts`, `leases`, `invitations`, `complaints` and `complaint_status_changes`. Facility tags are a text-array column on the room.

## 5. External Integrations / APIs

- **Gemini** (complaint classification, built; payment-pattern summaries, not built yet): `ai/gemini.py` calls the `google-genai` SDK with the model in `GEMINI_MODEL`, asks for a JSON answer restricted to the complaint categories, and turns any SDK error, bad JSON or unknown category into `ClassificationUnavailable`. Without `GEMINI_API_KEY` the unavailable classifier is used. Complaint classification runs through the `ComplaintClassifier` protocol: the complaint is saved and committed first, then a background task of the same request calls the classifier once with a 10 second timeout, in its own database session. Any failure leaves the complaint saved in the state *awaitingClassification*.
- **Google Play Developer API** (subscription verification) and **Firebase Cloud Messaging** (push): *not built yet.*

## 6. Deployment & Infrastructure

The shared development server is the Fly.io app `niscala-api-dev` at `https://dev-api-niscala.andinaufal.com` (also reachable at `niscala-api-dev.fly.dev`), in region `sin` (Singapore, next to the database). It is built from `Dockerfile` and configured in `fly.toml`. Its database is the Supabase project *niscala-api-dev* (ap-southeast-1), reached through the Supavisor session pooler, with Supabase's Data API turned off because only the backend uses the database. `DATABASE_URL`, `JWT_SECRET`, `INVITATION_ENCRYPTION_KEY` and `GEMINI_API_KEY` are Fly secrets. Deploys are manual (`fly deploy`), and each one runs `alembic upgrade head` as Fly's release command before the new version starts. The machine stops when idle and starts again on the next request. Production is *not set up yet.* GitHub Actions runs Claude Code review on pull requests (`.github/workflows/`).

## 7. Security Considerations

- Authentication: a bearer JWT access token (HS256, 15 minutes, signed with `JWT_SECRET`), declared as `bearerAuth` in the OpenAPI document. `get_current_user` validates it and also loads the session row, so an ended session stops working at once. The refresh token is opaque, stored only as a SHA-256 hash, and rotated on every use; presenting a rotated one ends the session. Each session is a token family: every hash it has rotated away from stays in `used_refresh_tokens` until the session ends, so reuse of any of them is detected, and a `SELECT ... FOR UPDATE` on the session row makes concurrent refreshes with the same token run one after the other. Sessions end after 90 days idle or 1 year after login.
- Invitation links carry a random token: the database keeps its SHA-256 hash for lookup and a Fernet-encrypted copy (key `INVITATION_ENCRYPTION_KEY`) so the link can be shown again while it is valid.
- Passwords are hashed with argon2id. New passwords are checked against the common-password list and a few pattern rules (`services/passwords.py`). Failed logins are counted per email and lock it for 15 minutes after 5 failures (`login_failures`). Email verification codes are stored as SHA-256 hashes, valid 10 minutes and voided after 5 wrong attempts. Until the email is verified, `get_verified_user` answers `EMAIL_NOT_VERIFIED`; `get_current_user` is for the few endpoints open to unverified accounts.
- Authorization: role and property access are enforced by the backend (`docs/SPEC.md` §4). `require_roles` checks the role after the session and email checks, and `require_recent_reauthentication` requires the session to have confirmed the password within the last 5 minutes. `get_accessible_property` and `accessible_properties` (in `access.py`) are the only way to reach a property: an inaccessible one answers `PROPERTY_NOT_FOUND`, the same as a missing one.
- Transport: HTTPS only.

## 8. Development & Testing Environment

- `uv sync` installs dependencies; `uv run pytest` runs the tests; `uv run ruff check` and `uv run ruff format` lint and format.
- Tests that touch the database start a throwaway PostgreSQL container (testcontainers), so Docker must be running. Tests that don't need it run without Docker. Tables are emptied after each test.
- `uv run alembic upgrade head` applies migrations to the database in `DATABASE_URL`.
- Tests come first: `test-writer` and `implementer` subagents (`.claude/agents/`) work in two steps, as described in `CLAUDE.md`.

## 9. Future Considerations

Open architecture questions are listed in `docs/SPEC.md` §10 (for example U-9 error codes in OpenAPI, U-15 conflict detection, TBD-3 Google Play integration).

Not built yet: a cleanup job for sessions that passed the idle or maximum age limit without a later refresh attempt. Their `used_refresh_tokens` rows stay until that attempt ends the session.

## 10. Project Identification

- Project: niscala-api
- Repository: https://github.com/andinaufal120/niscala-api
- Last updated: 2026-10-18

## 11. Glossary

Domain terms and code names are in `docs/SPEC.md` §3.
