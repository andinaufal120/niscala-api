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
│   ├── push.py        # PushSender protocol; the FCM sender, or the console sender (logs only) when no credentials are set
│   ├── storage.py     # FileStore protocol; the R2 store, or a local directory when R2 is not configured
│   ├── google_play.py # GooglePlay protocol; the Android Publisher client, or an unavailable client when not configured; the Pub/Sub token verifier
│   ├── email.py       # EmailSender protocol; the console sender only logs codes and links
│   ├── ai/            # ComplaintClassifier protocol, the Gemini classifier and the dependency that supplies it
│   ├── plans.py       # Limits, ranks, prices and Google Play ids per subscription plan, as data
│   ├── cli.py         # `niscala-api` command: grant-subscription, seed-rent-bills, seed-demo and create-admin (development tools)
│   ├── access.py      # require_roles and the property access queries (owner: own, manager: assigned)
│   ├── services/      # Business rules per area; routers call them (sessions, accounts, passwords, email verification, subscriptions, properties, rooms, leases, invitations, activation, complaints, rent bills, dashboard, managers, user accounts, password reset, notifications, demo data)
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
                                  +--> Google (sign-in token check)
                                  +--> Google Play (subscription purchases)
                                  +--> email sender                          (not built yet)
```

The generated OpenAPI document is the contract with the app. Routers stay thin; rules belong in services, which raise `ApiError`.

## 3. Core Components

### 3.1. App

The Flutter Android app lives in `andinaufal120/niscala-app`. It generates its Dart client from this API's OpenAPI document and renders what the API returns. Nothing about its internals is documented here.

### 3.2. Backend

- **Routers** (`routers/`): FastAPI `APIRouter`s grouped by resource. Endpoints not implemented yet answer `501`. `routers/health.py` is public and checks the database with `SELECT 1`.
- **Schemas** (`schemas/`): Pydantic models on `ApiModel`, which exposes snake_case attributes as camelCase fields.
- **Errors** (`errors.py`): every error response is `{"code", "field", "message"}`. Services raise `ApiError(status_code, code, message, field)`. Request validation errors become `VALIDATION_FAILED` with the first failing field. Any other `HTTPException` gets its status phrase as code (`NOT_FOUND`), and an unexpected exception becomes `INTERNAL_ERROR` without leaking its text.
- **Settings** (`config.py`): `get_settings()` returns a cached `Settings` read from the environment.
- **Logging** (`main.py`): logs go to stderr; INFO records from the `app` loggers are shown, including the verification codes the console email sender prints in development.
- **Database** (`db.py`): `get_session()` yields a SQLAlchemy `Session`; endpoints and dependencies declare it as `SessionDep`, a function-scope dependency. It commits when the handler returns and rolls back when it raises, so a failed request saves nothing. Function scope makes the commit happen before the response is sent, so a failed commit becomes an error response. The database enforces structural integrity only; business rules live in code.
- **Rent bills** (`services/rent_bills.py`): a bill, its status history and its transfer receipt are three tables. The receipt image is stored in object storage under a new key per upload; the row keeps the key. The new object is deleted if the request rolls back, and the replaced one only after the commit, so a failed request saves nothing. The type is read from the file signature. Dates that depend on the calendar day (current period, future-date checks, payment date of a verified receipt) are read in Asia/Jakarta through `today_jakarta()`. A status change notifies through `notify_status_change` (see Notifications); a status change clears the tenant's payment-pattern summary and the router schedules its regeneration after the commit (see Payment patterns); bills are created only by the development seed command, since bill generation is undecided.
- **Payment patterns** (`services/payment_patterns.py`): the facts (on-time count, average days late, arrears, at-risk flag) are computed on every read by a pure function from a lease's bills. Only the AI summary is stored, one row per lease. A payment status change deletes it in the same transaction; after the commit a background task of the same request regenerates it in its own session, for subscribed Owners only, through the `PaymentPatternSummarizer` protocol with a 10 second timeout, and saves the result only if the facts are unchanged.
- **Complaints** (`services/complaints.py`): a complaint, its status history and its classification are stored together; classification runs after the save in a background task. Moving a complaint to its next status calls `notify_complaint_status_change`, which creates the tenant's notification; a failing notification is logged and never undoes the change. The photo is stored the same way as a receipt.
- **Managers** (`services/managers.py`): a Manager is a login account (role manager, shared by every Owner the person works for) plus one `managers` record per Owner, which holds that Owner's nickname and phone and when the Manager activated. Property access still comes from `manager_assignments`, keyed by the account. Invitations belong to either a tenant or a manager record (exactly one is set).
- **Tenants** (`services/tenants.py`): a Tenant is a login account (role tenant) plus one `tenants` record per tenancy, holding phone, occupation, emergency contacts and the lease. The record's id is the tenant id of the API. Accepting an invitation moves the record to the accepting account.
- **Notifications** (`services/notifications.py`): events call small hooks (`notify_status_change`, `notify_complaint_status_change`, `notify_complaint_submitted`, `notify_tenant_activated`, `notify_manager_activated`) that store one row per recipient with a snapshot of the facts as they were. Rows are created in a savepoint in the event's own transaction, so a failure is logged and never undoes the event. A push is queued for every live session of a recipient that has a token, when the category is switched on, and sent through `push.get_push_sender()` only after the outermost commit of the event's session (a rollback drops the queue). Each push is tried once; when FCM reports a token as unregistered or invalid, `push_token` is cleared on that session (only if it still holds that token). The late push of a high-urgency complaint to `highOnly` recipients is queued before the classification commit. Due-date reminders and overdue notices are daily jobs; bill-issued is not built.
- **Daily jobs** (`routers/jobs.py`, `services/jobs.py`): `POST /internal/jobs/daily` is left out of the OpenAPI document and needs `Authorization: Bearer <JOBS_SECRET>` (404 when the secret is unset). It runs each job in its own transaction; a failure is logged, the rest still run, and the answer is 500. Jobs are idempotent, so a repeated run is harmless. Jobs: ending sessions past the idle or 1-year limit, sending due-date reminders, sending overdue notices, fetching again the subscriptions near their end from Google Play (`reconcile_google_play_subscriptions`) and applying plan limits. The reconcile job always runs before `apply_plan_limits`, and it logs and skips a purchase Google Play cannot return instead of failing.
- **Subscriptions** (`services/subscriptions.py`): the plan data (limits, rank, prices, Google Play product and base plan ids) is in `plans.py`; services only look values up. An order expires 3 days after it was created, and it is computed on read: any read of an Owner's orders first saves as `expired` the ones awaiting payment with no purchase token and a past `expires_at`. The current plan always comes from `current_plan` (the running paid period, otherwise free). A scheduled downgrade is only a stored confirmation; the daily job `apply_plan_limits` applies it after the paid period ends (see section 3.4), and `restore_editability` undoes view-only state when the plan goes up. An order that holds a purchase token no longer expires by time.
- **Google Play billing** (`google_play.py`, `services/subscriptions.py`, `routers/google_play.py`): purchase verification (`verify_purchase`) fetches the token from Google Play, checks the owner (obfuscated account id) and the product, and maps Google's state to the order and the subscription through one pure function shared with `sync_purchase`. `POST /internal/google-play/notifications` is left out of the OpenAPI document, answers 404 when `GOOGLE_PLAY_RTDN_AUDIENCE` is unset, checks the Pub/Sub OIDC bearer token (audience, and the verified email of `GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT`) and the package name, then calls `sync_purchase(db, play, token)`. That function finds the owner by the purchase's obfuscated account id and adopts the purchase when it is the current one, replaces it, belongs to an order awaiting payment, or the owner has no running subscription. Both paths lock the owner's account row so concurrent calls for one owner run one after the other. The endpoint answers 503 when Google Play is unreachable so Pub/Sub delivers again. The daily job `reconcile_google_play_subscriptions` calls `sync_purchase` for every subscription ending from 3 days ago to 1 day ahead. See section 3.5.

Technologies: Python 3.14, FastAPI, Pydantic, pydantic-settings, SQLAlchemy 2, Alembic, psycopg 3, managed with uv.

### 3.3. Google sign-in flow

Google replaces the password at login. The app still ends up with this API's own session tokens, and Google is not involved in any later request.

```
Flutter app (Android)               Google                        FastAPI
  |-- Google Sign-In SDK ----------->|                              |
  |   (serverClientId = Web client)  |  checks the Android client:  |
  |<-- ID token (signed JWT) --------|  package name + SHA-1        |
  |-- POST /auth/login/google {idToken, device} ------------------->|
  |                                  |   verifies signature, issuer, expiry and
  |                                  |   that aud is in GOOGLE_CLIENT_IDS;
  |                                  |   finds the account by sub
  |<-- this API's access token + refresh token ---------------------|
  |-- later requests: Authorization: Bearer <access token> -------->|
```

- **App side:** the app asks the Google Sign-In SDK for an ID token and passes the Web client ID as `serverClientId`, so the token's audience (`aud`) is the Web client. The Android OAuth client (package name and signing certificate SHA-1) is only how Google recognises the app. Both clients live in the same Google Cloud project.
- **Backend side:** `google.py` verifies the token against Google's public signing keys and accepts it only when `aud` is listed in `GOOGLE_CLIENT_IDS`. The identity is the token's `sub`; an account is never found by email. Only the ID token is used: no Google access token, no authorization code, and the Web client's secret is not used by this API.
- **After verification:** the API issues its own access and refresh tokens (section 7). The Google token is not stored. The account keeps only `google_subject` and `google_email`, and the session records the login method `google`.
- **Endpoints:** `POST /auth/register/google` (Owner, optional `name`), `POST /auth/login/google`, `POST /invitations/activations/google` (Tenant and Manager), `POST /me/google-link`, `POST /me/local-password` and `POST /me/reauthentication/google`. Rules and error codes are in `docs/SPEC.md` section 7.
- **Not done:** there is no `nonce` check, so a stolen but still valid ID token (Google ID tokens last about an hour) could be replayed against these endpoints until it expires.

### 3.4. Subscription downgrade flow

A downgrade is confirmed while the paid period runs and applied by the daily job once it has ended. The app only stores the Owner's choice of what stays editable; the plan itself changes when the period ends, through Google Play.

```
Owner app                                  FastAPI                                      Daily job
|                                             |                                             |
|-- PUT /subscription/scheduled-downgrade --->|                                             |
|                                             |  lower plan while paid?                     |
|                                             |  KEPT_PROPERTIES / KEPT_ROOMS valid?        |
|                                             |  upsert scheduled_downgrades                |
|<------ downgrade, effectiveDate = end + 1 --|                                             |
|                                             |                                             |
|  stop or change renewal                     |                                             |
|  in Google Play                             |                                             |
|                                             |                                             |
|                                             |  paid period ends:                          |
|                                             |  effective plan drops                       |
|                                             |<----------------------- apply_plan_limits --|
|                                             |  editable > new limit?                      |
|                                             |  confirmation plan == effective plan?       |
|                                             |    yes: keep the confirmed ids              |
|                                             |    no: earliest properties; Gratis:         |
|                                             |        occupied rooms, then lowest          |
|                                             |  set view_only on the rest                  |
|                                             |  delete the scheduled downgrade             |
|                                             |                                             |
|-- later upgrade (verify or grant) --------->|                                             |
|                                             |  restore_editability:                       |
|                                             |    every property and room editable         |
|                                             |    scheduled downgrade removed              |
|                                             |                                             |
```

### 3.5. Google Play billing flow

Paid plans are bought in Google Play. The backend learns the outcome in three ways: the app sends the purchase token for verification, Google Play sends real-time developer notifications through Cloud Pub/Sub, and a daily job fetches again the subscriptions near their end. Each way ends in the same state mapping.

First purchase or upgrade. A pending payment (for example at a convenience store) is checked again when the app sends the same token. Verification is idempotent.

```
Owner app                                  FastAPI                                     Google Play
|                                             |                                             |
|-- GET /subscription-plans ----------------->|                                             |
|<------------ plans, productId, basePlanId --|                                             |
|                                             |                                             |
|-- POST /subscription/orders --------------->|                                             |
|                                             |  rank > effective plan?                     |
|                                             |    no: 409 SUBSCRIPTION_NOT_AN_UPGRADE      |
|                                             |  expire earlier open orders                 |
|<------------- 201 order (awaitingPayment) --|                                             |
|                                             |                                             |
|-- launchBillingFlow(productId, basePlanId, obfuscatedAccountId) ------------------------->|
|<------------------------------------------------------------------------- purchaseToken --|
|                                             |                                             |
|-- POST .../purchase-verification ---------->|                                             |
|                                             |-- subscriptionsv2.get(token) -------------->|
|                                             |<------------------ state, product, expiry --|
|                                             |  check owner, product, token                |
|                                             |  ACTIVE:                                    |
|                                             |-- acknowledge ----------------------------->|
|                                             |    order succeeded                          |
|                                             |    subscription active                      |
|                                             |    restore_editability                      |
|                                             |  PENDING: keep token, order waits           |
|                                             |  EXPIRED: order failed                      |
|<------------------- order with its status --|                                             |
|                                             |                                             |
```

Renewal, cancellation or refund through a real-time developer notification:

```
Pub/Sub                                    FastAPI                                     Google Play
|                                             |                                             |
|<----------------------------------------------------- publish subscription notification --|
|-- push, Bearer OIDC JWT ------------------->|                                             |
|                                             |  POST /internal/google-play/                |
|                                             |       notifications                         |
|                                             |  verify JWT audience and email              |
|                                             |  decode message.data                        |
|                                             |  check packageName                          |
|                                             |  not a subscription notification: 204      |
|                                             |  sync_purchase(token):                      |
|                                             |-- subscriptionsv2.get(token) -------------->|
|                                             |<------ state, product, expiry, account id --|
|                                             |    owner = obfuscatedAccountId              |
|                                             |    adopt if current, linked, or none        |
|                                             |    update plan, ends_at, auto_renew         |
|                                             |    update matching pending order            |
|<---------- 204, or 503 so Pub/Sub retries --|                                             |
|                                             |                                             |
```

Daily safety net:

```
pg_cron                                    FastAPI                                     Google Play
|                                             |                                             |
|-- 07:00 WIB POST /internal/jobs/daily ----->|                                             |
|                                             |  existing jobs (sessions, reminders)        |
|                                             |  reconcile_google_play_subscriptions:       |
|                                             |    each subscription ending in              |
|                                             |    [now - 3 days, now + 1 day]              |
|                                             |-- subscriptionsv2.get(token) -------------->|
|                                             |<--------------------------- current state --|
|                                             |    sync_purchase as above                   |
|                                             |  apply_plan_limits (flow C)                 |
|<------------- 204, or 500 if a job failed --|                                             |
|                                             |                                             |
```

## 4. Data Stores

PostgreSQL (Supabase on the deployed server), reached through `DATABASE_URL`. Schema changes are Alembic revisions in `migrations/`; a test checks that the migrated schema matches the models. Tables so far: `user_accounts`, `sessions`, `used_refresh_tokens`, `email_verification_codes`, `login_failures`, `properties`, `manager_assignments`, `subscriptions`, `rooms`, `tenants`, `emergency_contacts`, `leases`, `invitations`, `complaints`, `complaint_status_changes`, `complaint_photos`, `email_change_requests`, `password_reset_tokens`, `notifications`, `notification_settings`, `payment_pattern_summaries`, `subscription_orders` (purchase attempts, with status, optional purchase token and expiry) and `scheduled_downgrades` (one row per Owner: the target plan and the kept property and room ids, as UUID arrays). Facility tags are a text-array column on the room. Uploaded files (receipts, complaint photos) are in the Cloudflare R2 bucket named by `R2_BUCKET`, private, read only by the API.

## 5. External Integrations / APIs

- **Gemini** (complaint classification, built; payment-pattern summaries, built): `ai/gemini.py` calls the `google-genai` SDK with the model in `GEMINI_MODEL`, sends the instructions as a system instruction and the complaint wrapped in a per-request random tag, asks for a JSON answer restricted to the complaint categories, and turns any SDK error, bad JSON, unknown category or suspicious suggested action (too long, a link, an HTML tag, 8 or more digits in a row ignoring spaces, dots and dashes) into `ClassificationUnavailable`. Without `GEMINI_API_KEY` the unavailable classifier is used. Complaint classification runs through the `ComplaintClassifier` protocol: the complaint is saved and committed first, then a background task of the same request calls the classifier once with a 10 second timeout, in its own database session. Any failure leaves the complaint saved in the state *awaitingClassification*. Payment-pattern summaries go through the `PaymentPatternSummarizer` protocol the same way: one request with a 10 second timeout, only the computed facts and counted bills sent, and any error, empty answer, answer over 500 characters, link or HTML tag treated as a failure (`SummaryUnavailable`); without a key the unavailable summarizer is used.
- **Firebase Cloud Messaging** (push, built): `push.py` calls the `firebase-admin` SDK with the service account in `FIREBASE_CREDENTIALS`. Without it the console sender is used.
- **Cloudflare R2** (file storage, built): `storage.py` uses boto3 against R2's S3 API with `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_BUCKET`. Without them, files go to the local directory in `FILE_STORAGE_DIR`.
- **Google Sign-In** (ID token verification, built): `google.py` verifies ID tokens with `google-auth` against the audiences in `GOOGLE_CLIENT_IDS`; without any, every token is rejected. Tests replace the verifier through `get_google_verifier`. The flow is described in section 3.3.
- **Google Play Developer API** (subscription verification, built): `google_play.py` calls the Android Publisher v3 REST API (`purchases.subscriptionsv2.get` and `purchases.subscriptions.acknowledge`) for `GOOGLE_PLAY_PACKAGE_NAME` with an authorized session from the service account in `GOOGLE_PLAY_CREDENTIALS` and a 10 second timeout. Without both settings the unavailable client is used and every call fails as unreachable. Pub/Sub pushes are checked with `google-auth` against `GOOGLE_PLAY_RTDN_AUDIENCE` and `GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT`. Tests replace the client through `get_google_play` and the token verifier through `get_pubsub_token_verifier`. The flow is described in section 3.5.

## 6. Deployment & Infrastructure

The shared development server is the Fly.io app `niscala-api-dev` at `https://dev-api-niscala.andinaufal.com` (also reachable at `niscala-api-dev.fly.dev`), in region `sin` (Singapore, next to the database). It is built from `Dockerfile` and configured in `fly.toml`. Its database is the Supabase project *niscala-api-dev* (ap-southeast-1), reached through the Supavisor session pooler, with Supabase's Data API turned off because only the backend uses the database. `DATABASE_URL`, `JWT_SECRET`, `INVITATION_ENCRYPTION_KEY`, `GEMINI_API_KEY`, `FIREBASE_CREDENTIALS`, `GOOGLE_CLIENT_IDS`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `JOBS_SECRET`, `GOOGLE_PLAY_CREDENTIALS`, `GOOGLE_PLAY_PACKAGE_NAME`, `GOOGLE_PLAY_RTDN_AUDIENCE` and `GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT` are Fly secrets (`GOOGLE_CLIENT_IDS` holds public OAuth client IDs, not a secret value). Deploys run from GitHub Actions (`cd.yml`) after CI passes on `main`, when the version in `pyproject.toml` has no `v<version>` tag yet; the workflow tags the commit once the deploy succeeded, using the `FLY_API_TOKEN` GitHub secret (a Fly deploy token for `niscala-api-dev`). `fly deploy` by hand still works. Each deploy runs `alembic upgrade head` as Fly's release command before the new version starts. The machine stops when idle and starts again on the next request. Production is *not set up yet.* GitHub Actions runs format, lint and test checks (`ci.yml`) and Claude Code review on pull requests (`.github/workflows/`).

Supabase `pg_cron` calls the daily jobs endpoint at 00:00 UTC (07:00 WIB) through `pg_net`, with the secret read from Supabase Vault (`jobs_secret`):

```sql
select cron.schedule(
  'niscala-daily-jobs',
  '0 0 * * *',
  $$ select net.http_post(
    url := 'https://dev-api-niscala.andinaufal.com/internal/jobs/daily',
    headers := jsonb_build_object(
      'Authorization',
      'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'jobs_secret')
    )
  ) $$
);
```

The extensions `pg_cron` and `pg_net` and the Vault secret are set up in the Supabase dashboard, not by a migration.

## 7. Security Considerations

- Authentication: a bearer JWT access token (HS256, 15 minutes, signed with `JWT_SECRET`), declared as `bearerAuth` in the OpenAPI document. `get_current_user` validates it and also loads the session row, so an ended session stops working at once. The refresh token is opaque, stored only as a SHA-256 hash, and rotated on every use; presenting a rotated one ends the session. Each session is a token family: every hash it has rotated away from stays in `used_refresh_tokens` until the session ends, so reuse of any of them is detected, and a `SELECT ... FOR UPDATE` on the session row makes concurrent refreshes with the same token run one after the other. Sessions end after 90 days idle or 1 year after login.
- Invitation links carry a random token: the database keeps its SHA-256 hash for lookup and a Fernet-encrypted copy (key `INVITATION_ENCRYPTION_KEY`) so the link can be shown again while it is valid.
- Passwords are hashed with argon2id. New passwords are checked against the common-password list and a few pattern rules (`services/passwords.py`). Failed logins are counted per email and lock it for 15 minutes after 5 failures (`login_failures`). Email verification codes are stored as SHA-256 hashes, valid 10 minutes and voided after 5 wrong attempts. Until the email is verified, `get_verified_user` answers `EMAIL_NOT_VERIFIED`; `get_current_user` is for the few endpoints open to unverified accounts.
- Authorization: role and property access are enforced by the backend (`docs/SPEC.md` §4). `require_roles` checks the role after the session and email checks, and `require_recent_reauthentication` requires the session to have confirmed the password or a Google token within the last 5 minutes. `get_accessible_property` and `accessible_properties` (in `access.py`) are the only way to reach a property: an inaccessible one answers `PROPERTY_NOT_FOUND`, the same as a missing one.
- Transport: HTTPS only.

## 8. Development & Testing Environment

- `uv sync` installs dependencies; `uv run pytest` runs the tests; `uv run ruff check` and `uv run ruff format` lint and format.
- Tests run in parallel with pytest-xdist (`-n auto --dist loadfile` in `pyproject.toml`); `uv run pytest -n0` runs them serially, e.g. for debugging. Tests that touch the database start a throwaway PostgreSQL container (testcontainers), one per worker, so Docker must be running. Tests that don't need it run without Docker. Tables are emptied after each test.
- `uv run alembic upgrade head` applies migrations to the database in `DATABASE_URL`.
- Tests come first: `test-writer` and `implementer` subagents (`.claude/agents/`) work in two steps, as described in `CLAUDE.md`.

## 9. Future Considerations

Open architecture questions are listed in `docs/SPEC.md` §10 (for example U-9 error codes in OpenAPI, U-15 conflict detection).

## 10. Project Identification

- Project: niscala-api
- Repository: https://github.com/andinaufal120/niscala-api
- Last updated: 2026-10-18

## 11. Glossary

Domain terms and code names are in `docs/SPEC.md` §3.
