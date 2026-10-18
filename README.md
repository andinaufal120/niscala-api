# niscala-api

Backend for Niscala ("Kelola Kost Tanpa Ribet"), an Android app that helps boarding-house (kos) owners and managers handle properties, rooms, tenants, rent payments and maintenance complaints.

This repository holds the FastAPI service. It owns the business rules and the API contract. The Flutter app lives in [niscala-app](https://github.com/andinaufal120/niscala-app).

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.14 (uv installs it if missing)
- Docker, for the tests that use a database (they start a throwaway PostgreSQL container)
- A PostgreSQL database to run the API against (see `DATABASE_URL` below)

## Development

```sh
uv sync                    # install dependencies
uv run pytest              # run tests
uv run ruff check          # lint
uv run ruff format         # format
uv run alembic upgrade head   # apply database migrations to DATABASE_URL
```

## Configuration

Settings are read from environment variables, or from a `.env` file in the project root. Every variable has a default except `JWT_SECRET`, which MUST be set.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://niscala:niscala@localhost:5432/niscala` | PostgreSQL connection URL |
| `JWT_SECRET` | none (required) | Key that signs access tokens; use a long random value |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model used for AI features |
| `GEMINI_API_KEY` | none | Gemini API key |
| `INVITATION_BASE_URL` | `https://niscala.app` | Base of the invitation links |

## Docs

- `docs/SPEC.md`: what the backend has to do
- `ARCHITECTURE.md`: how the backend is built
- `CLAUDE.md`: conventions for coding agents (and a good summary for people)
- `REVIEW.md`: what code review checks

## License

[MIT](LICENSE)
