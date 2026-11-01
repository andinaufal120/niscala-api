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

Deploy from an up-to-date `main`. A version bump is optional. The `version` in `pyproject.toml` is the version the API reports in its OpenAPI document (`info.version`, shown at `/docs` and `/openapi.json`), so bump it when a release should show a new number. The build installs with `uv sync --locked`, so `pyproject.toml` and `uv.lock` must always agree.

1. Optional: bump the version. Create a branch, change `version` in `pyproject.toml`, then run `uv lock` so `uv.lock` follows. Do not edit `uv.lock` by hand. Check that `git diff --stat` shows only those two files and that `uv lock --check` passes. Commit both together (`chore: bump the version to X.Y.Z`), open a pull request and merge it. The deployed API reports the new version after the next deploy. On your machine `uv run` and `uv sync` reinstall the project, so restart the server to see it.
2. Update and check your copy of `main`:

   ```sh
   git switch main && git pull
   git status                           # clean working tree
   uv run alembic heads                 # exactly one head
   fly secrets list -a niscala-api-dev  # JWT_SECRET, INVITATION_ENCRYPTION_KEY and the database URL are set
   ```

3. Deploy:

   ```sh
   fly deploy -a niscala-api-dev
   ```

   The deploy builds the image from the `Dockerfile` and runs `alembic upgrade head` as its release command. If a migration fails, the deploy stops and the old machines keep running.
4. Check that it worked: `fly status -a niscala-api-dev`, `fly logs -a niscala-api-dev`, then open `/docs` on the server and try a login. The first request can be slow because the machine stops when idle.

To roll back, find the previous release with `fly releases -a niscala-api-dev` and run `fly deploy -a niscala-api-dev --image <previous-image>`. A rollback does not undo migrations. To revert one, run `fly ssh console -a niscala-api-dev -C "alembic downgrade -1"`, after checking that the old code works with the older schema.

## Development

```sh
uv sync                    # install dependencies
uv run pytest              # run tests
uv run ruff check          # lint
uv run ruff format         # format
uv run alembic upgrade head   # apply database migrations to DATABASE_URL
```

### Granting a subscription (development only)

AI features need an Owner with a paid plan, and buying one through Google Play is not built yet. This command gives an existing Owner a paid period in the database in `DATABASE_URL`:

```sh
uv run niscala-api grant-subscription owner@example.com basic          # 30 days
uv run niscala-api grant-subscription owner@example.com pro --days 90
```

Running it again replaces the Owner's current period. It is a development tool, not part of the API.

### Seeding rent bills (development only)

Bills are not generated automatically yet. This command creates the billing history of a Tenant's active lease in the database in `DATABASE_URL`: paid bills for the past periods (some paid late) and an unpaid bill for the current period.

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

Until a mail service is set up, email verification codes are written to the server log instead of being emailed.

## Docs

- `docs/SPEC.md`: what the backend has to do
- `ARCHITECTURE.md`: how the backend is built
- `CLAUDE.md`: conventions for coding agents (and a good summary for people)
- `REVIEW.md`: what code review checks

## License

[MIT](LICENSE)

`data/common-passwords.txt` is the 100,000 most used passwords from [SecLists](https://github.com/danielmiessler/SecLists) (MIT license). New passwords are checked against it.
