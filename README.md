# niscala-api

Backend for Niscala ("Kelola Kost Tanpa Ribet"), an Android app that helps boarding-house (kos) owners and managers handle properties, rooms, tenants, rent payments and maintenance complaints.

This repository holds the FastAPI service. It owns the business rules and the API contract. The Flutter app lives in [niscala-app](https://github.com/andinaufal120/niscala-app).

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.14 (uv installs it if missing)
- Docker, for the tests that use a database (they start a throwaway PostgreSQL container)
- A PostgreSQL database to run the API against (see `DATABASE_URL` below)

## Running the API for the app

These steps start the API on your machine with a ready-made *Pemilik Kost (Owner)* and *Penyewa (Tenant)*, so you can log in from the Android app straight away. Run them from the project root.

1. Start a PostgreSQL database. This one matches the default `DATABASE_URL`:

   ```sh
   docker run -d --name niscala-pg -e POSTGRES_USER=niscala -e POSTGRES_PASSWORD=niscala \
     -e POSTGRES_DB=niscala -p 5432:5432 postgres:17
   ```

2. Create a `.env` file in the project root (it is not committed) with two secrets:

   ```sh
   uv sync
   echo "JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" >> .env
   echo "INVITATION_ENCRYPTION_KEY=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> .env
   ```

3. Create the tables and the demo data:

   ```sh
   uv run alembic upgrade head
   uv run niscala-api seed-demo
   ```

   `seed-demo` prints the two logins. Both use the password `Demo-Kost-2026!`:

   | Role | Email |
   |---|---|
   | Owner | `owner@example.com` |
   | Tenant | `tenant@example.com` |

   The Owner has one property, *Kost Melati*, with room 101. The Tenant lives in that room with an active monthly lease. Both emails are already verified. Running `seed-demo` again changes nothing.

4. Start the API:

   ```sh
   uv run fastapi run src/app/main.py --host 0.0.0.0 --port 8000
   ```

   Use `uv run fastapi dev src/app/main.py` instead to restart on every code change. The interactive API docs are at `http://localhost:8000/docs`.

5. Point the app at the API. From the Android emulator the host machine is `http://10.0.2.2:8000`. From a physical phone on the same network use `http://<your-computer-IP>:8000`.

Good to know:

- Accounts you create through the API (sign up, or a Tenant accepting an invitation) must confirm their email. There is no mail service yet, so the 6-digit code is written to the server output as `Verification code for <email>: <code>`.
- To get a billing history for the demo Tenant, run `uv run niscala-api seed-rent-bills tenant@example.com`.
- To start over, stop the server, run `docker rm -f niscala-pg`, and repeat steps 1 and 3.

## Shared development server

A shared copy of the API runs on Fly.io at `https://dev-api-niscala.andinaufal.com` (interactive docs at `/docs`). Point the debug APK at this URL. The demo logins from the steps above work there too.

- The machine stops when idle, so the first request after a quiet period takes a few seconds.
- Verification codes are written to the server log: `fly logs -a niscala-api-dev`.
- Development commands run on the server: `fly ssh console -a niscala-api-dev -C "niscala-api seed-rent-bills tenant@example.com"` (same for `grant-subscription`).
- To deploy a new version, see "Deploying" below.
- Secrets are set with `fly secrets set NAME=value -a niscala-api-dev`.

### Deploying

Releases are automatic. release-please (`.github/workflows/release-please.yml`) keeps a release pull request open on GitHub, built from the Conventional Commits merged to `main`. Merging that pull request bumps `version` in `pyproject.toml` and `uv.lock`, writes `CHANGELOG.md`, tags `v<version>`, publishes the GitHub release and calls the `CD` workflow (`.github/workflows/cd.yml`), which runs `fly deploy`. Do not bump the version or edit `CHANGELOG.md` by hand. Only `feat`, `fix`, `perf` and `revert` commits appear in the changelog.

One-time setup on GitHub:

- Settings, Actions, General: turn on "Allow GitHub Actions to create and approve pull requests", or release-please cannot open its pull request.
- Secret `FLY_API_TOKEN` (`fly tokens create deploy -a niscala-api-dev`).
- Optional secret `RELEASE_PLEASE_TOKEN`, a personal access token with `contents` and `pull requests` write access. Pull requests opened with the default token do not start CI, so the release pull request would have no checks.

The `version` in `pyproject.toml` is the version the API reports in its OpenAPI document (`info.version`, shown at `/docs` and `/openapi.json`). The build installs with `uv sync --locked`, so `pyproject.toml` and `uv.lock` must always agree; release-please updates both. On your machine `uv run` and `uv sync` reinstall the project after a release, so restart the server to see the new version.

To redeploy a tag, run the `CD` workflow from the Actions tab and give the tag (for example `v0.7.0`). To deploy from your machine instead:

1. Update and check your copy of `main`:

   ```sh
   git switch main && git pull
   git status                           # clean working tree
   uv run alembic heads                 # exactly one head
   fly secrets list -a niscala-api-dev  # JWT_SECRET, INVITATION_ENCRYPTION_KEY and the database URL are set
   ```

2. Deploy:

   ```sh
   fly deploy -a niscala-api-dev
   ```

   The deploy builds the image from the `Dockerfile` and runs `alembic upgrade head` as its release command. If a migration fails, the deploy stops and the old machines keep running.
3. Check that it worked: `fly status -a niscala-api-dev`, `fly logs -a niscala-api-dev`, then open `/docs` on the server and try a login. The first request can be slow because the machine stops when idle.

To roll back, find the previous release with `fly releases -a niscala-api-dev` and run `fly deploy -a niscala-api-dev --image <previous-image>`. A rollback does not undo migrations. To revert one, run `fly ssh console -a niscala-api-dev -C "alembic downgrade -1"`, after checking that the old code works with the older schema.

## Development

```sh
uv sync                    # install dependencies
uv run pytest              # run tests
uv run pytest -n0          # run tests serially (for debugging)
uv run ruff check          # lint
uv run ruff format         # format
uv run alembic upgrade head   # apply database migrations to DATABASE_URL
```

### Granting a subscription (development only)

AI features need an Owner with a paid plan. To skip buying one through Google Play, this command gives an existing Owner a paid period in the database in `DATABASE_URL`:

```sh
uv run niscala-api grant-subscription owner@example.com basic          # 30 days
uv run niscala-api grant-subscription owner@example.com pro --days 90
```

Running it again replaces the Owner's current period. It also makes all of the Owner's properties and rooms editable again and removes a scheduled downgrade. It is a development tool, not part of the API.

### Seeding rent bills (development only)

Bills are not generated automatically yet. This command creates the billing history of a Tenant's active lease (the oldest one, when the account rents in several places) in the database in `DATABASE_URL`: paid bills for the past periods (some paid late) and an unpaid bill for the current period.

```sh
uv run niscala-api seed-rent-bills tenant@example.com              # last 12 periods
uv run niscala-api seed-rent-bills tenant@example.com --months 24
```

Running it again skips periods that already have a bill. It is a development tool, not part of the API.

### Creating an Admin

Admins cannot sign up through the API. This command creates one in the database in `DATABASE_URL`, with a verified email. The password comes from `--password` or, if that is absent, from the `NISCALA_ADMIN_PASSWORD` environment variable, and follows the same rules as sign-up:

```sh
NISCALA_ADMIN_PASSWORD='a-long-unguessable-password' uv run niscala-api create-admin admin@example.com --name "Sari Admin"
```

It fails if the email already belongs to an account. Prefer the environment variable, since a `--password` value stays in the shell history.

## Configuration

Settings are read from environment variables, or from a `.env` file in the project root. Every variable has a default except `JWT_SECRET` and `INVITATION_ENCRYPTION_KEY`, which must be set.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://niscala:niscala@localhost:5432/niscala` | PostgreSQL connection URL |
| `JWT_SECRET` | none (required) | Key that signs access tokens; use a long random value |
| `INVITATION_ENCRYPTION_KEY` | none (required) | Fernet key that encrypts invitation tokens; make one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model used for AI features |
| `GEMINI_API_KEY` | none | Gemini API key |
| `INVITATION_BASE_URL` | `https://niscala.app` | Base of the invitation links |
| `FIREBASE_CREDENTIALS` | none | Content of a Firebase service account JSON file, on one line; enables push through FCM |
| `GOOGLE_CLIENT_IDS` | none | Comma-separated OAuth client IDs accepted as the audience of Google ID tokens; without it Google sign-in is refused |
| `JOBS_SECRET` | none | Bearer secret for `POST /internal/jobs/daily`; without it (or blank) that endpoint answers 404 |
| `R2_ACCOUNT_ID` | none | Cloudflare account ID of the R2 bucket that stores receipts and complaint photos |
| `R2_ACCESS_KEY_ID` | none | Access key ID of an R2 API token with read and write access to the bucket |
| `R2_SECRET_ACCESS_KEY` | none | Secret access key of that token |
| `R2_BUCKET` | none | Name of the R2 bucket; keep it private |
| `FILE_STORAGE_DIR` | `var/files` | Local directory for uploaded files, used when any of the four `R2_*` variables is missing or blank |
| `GOOGLE_PLAY_PACKAGE_NAME` | none | Package name of the app in Google Play |
| `GOOGLE_PLAY_CREDENTIALS` | none | Content of the Google Cloud service account JSON key that may read subscriptions in Play Console; without it (or the package name) every purchase check answers 503 |
| `GOOGLE_PLAY_RTDN_AUDIENCE` | none | Audience set on the Pub/Sub push subscription; without it `POST /internal/google-play/notifications` answers 404 |
| `GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT` | none | Email of the service account that the Pub/Sub push subscription signs its requests with |

Until a mail service is set up, email verification codes are written to the server log instead of being emailed.

Without `FIREBASE_CREDENTIALS`, push notifications are written to the server log instead of being sent. To send them for real, create a service account key in the Firebase console (Project settings, Service accounts, Generate new private key) and put its JSON on one line in `.env`, or on the deployed server:

```sh
fly secrets set FIREBASE_CREDENTIALS="$(cat service-account.json)" -a niscala-api-dev
```

Do not commit the key file.

Without all four `R2_*` variables, uploaded files are written to `FILE_STORAGE_DIR` on the machine running the API, and a warning is logged. That is fine for local development but not for the deployed server, whose disk is not kept between deploys.

## Google Play billing setup

Paid plans are bought in Google Play and checked by the API. Do this once per environment.

1. In Play Console, create two subscription products, `niscala_basic` and `niscala_pro`. Give each two base plans, `monthly` and `yearly`.
2. In Google Cloud, enable the Google Play Android Developer API, create a service account and download a JSON key for it. In Play Console under Users and permissions, invite the service account's email and give it the permissions "View financial data" and "Manage orders and subscriptions".
3. Create a Pub/Sub topic and give `google-play-developer-notifications@system.gserviceaccount.com` the Publisher role on it.
4. Create a push subscription on the topic. Set the endpoint to `https://dev-api-niscala.andinaufal.com/internal/google-play/notifications`, turn on authentication with a service account, and choose an audience (any string; use the endpoint URL).
5. In Play Console under Monetization setup, set the topic and send a test notification. The API answers 204 and logs it (`fly logs -a niscala-api-dev`).
6. To try a purchase, add license testers in Play Console and install a build from the internal testing track.
7. Set the four variables on the server. `GOOGLE_PLAY_CREDENTIALS` is the content of the JSON key:

   ```sh
   fly secrets set \
     GOOGLE_PLAY_PACKAGE_NAME=<package name of the app> \
     GOOGLE_PLAY_CREDENTIALS="$(cat google-play-service-account.json)" \
     GOOGLE_PLAY_RTDN_AUDIENCE=<audience from step 4> \
     GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT=<email of the push subscription's service account> \
     -a niscala-api-dev
   ```

Do not commit the key file. `grant-subscription` stays available for development without Google Play.

## Docs

- `docs/SPEC.md`: what the backend has to do
- `ARCHITECTURE.md`: how the backend is built
- `CLAUDE.md`: conventions for coding agents (and a good summary for people)
- `REVIEW.md`: what code review checks

## License

[MIT](LICENSE)

`data/common-passwords.txt` is the 100,000 most used passwords from [SecLists](https://github.com/danielmiessler/SecLists) (MIT license). New passwords are checked against it.
