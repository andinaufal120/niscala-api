# niscala-api

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in BCP 14 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) when, and only when, they appear in all capitals, as shown here.

FastAPI backend (Python 3.14, managed with uv). Code lives in `src/app/`, tests in `tests/`.

This repo is the **backend only**. It owns all business rules and the API contract. The Flutter Android app lives in a separate repository, `andinaufal120/niscala-app`. See "Boundaries" below.

## Commands

- `uv sync`: install dependencies
- `uv run pytest`: run all tests; `uv run pytest tests/<file>.py` for one file
- `uv run ruff check`: lint
- `uv run ruff format`: format code
- `uv add <package>` / `uv add --dev <package>`: add a dependency

## Workflow

- Before a change is called done, `uv run ruff check` MUST report no issues and `uv run pytest` MUST pass.
- Edited `.py` files are auto-formatted by a hook in `.claude/settings.json`.
- Agents MUST NOT edit generated or environment files: `uv.lock`, `.venv/`, `__pycache__/`. Change `pyproject.toml` through `uv add` / `uv remove` instead.
- Test-Driven Development: tests for a use case MUST be written or updated before implementing it, by two separate subagents defined in `.claude/agents/`:
  1. `test-writer` writes an exhaustive set of tests from `docs/SPEC.md` and the approved plan. It MUST NOT write implementation code. Its output is committed on its own.
  2. `implementer` then writes the code to make those tests pass. It MUST NOT modify the tests. If a test looks wrong, it MUST stop and report the conflict instead.

  Hooks in `.claude/hooks/` limit `test-writer` to editing `tests/`, block `implementer` from editing `tests/`, and restrict both to a short list of Bash commands.
- Source files (code, tests, OpenAPI documents, manifests, config, etc.) SHOULD NOT contain transient information, such as roadmap notes, Jira keys, or references to Markdown docs and their IDs or sections (e.g. `UC-05`, `FR-13`, `docs/SPEC.md` §10). That context belongs in commits, PRs, and the docs themselves.
  - Docstrings and test names SHOULD describe behavior and contract: inputs, outputs, side effects, errors, and non-obvious reasons that stay true as long as the code does. Glossary code names (`Tenant`, `Lease`) are fine.
  - Rule of thumb: if it would go stale when a Jira issue closes or a doc is renumbered, it doesn't belong in source.

## Principles

- Agents SHOULD do the simplest thing that satisfies the request. If something extra seems needed, agents MUST ask first instead of adding it.
- The database enforces structural integrity only: NOT NULL, UNIQUE, foreign keys, simple value ranges, and enum-style CHECKs. Business rules live in application code.
- **Clarity:** clarity is better than cleverness.
- **Separation:** separate policy from mechanism.
- **Simplicity:** design for simplicity; add complexity only where you must.
- **Transparency:** design for visibility to make inspection and debugging easier.
- **Robustness:** robustness is the child of transparency and simplicity.
- **Representation:** fold knowledge into data, so program logic can be stupid and robust.
- **Silence:** when a program has nothing surprising to say, it should say nothing.
- **Repair:** repair what you can, but when you must fail, fail noisily and as soon as possible.
- **Optimization:** prototype before polishing. Get it working before you optimize it.
- Make common mistakes hard, and make rare mistakes recoverable.

These principles SHOULD guide every design decision. Deviating from one requires a stated reason.

## Git

Jira automation links work by the issue key (`NKMA-xx`). When the work has a Jira issue, the key MUST appear wherever the rules below require it. When it doesn't, the key MUST be left out; agents MUST NOT invent one.

- **Never work on `main`.** Before the first edit, agents MUST create a branch from an up-to-date `main` or switch to the task's existing branch. Agents MUST NOT commit or push to `main`; changes reach it only through a PR.
- **Atomic commits:** each commit MUST contain one logical change and MUST leave `uv run ruff check` clean and `uv run pytest` passing. Exception: the test-only commit from `test-writer` MAY fail both, as long as every failure comes from the not-yet-implemented code. The PR's final commit MUST pass both. Unrelated changes (e.g. a refactor and a feature, or formatting of untouched files) MUST NOT share a commit.
- **Atomic PRs:** each PR MUST cover one Jira issue or concern. If a task grows to cover something unrelated, it MUST be split into a separate branch and PR.
- **Branch:** MUST be named `<type>/<KEY>-<short-kebab-description>`, e.g. `feat/NKMA-14-set-up-claude-code`. Without an issue: `<type>/<short-kebab-description>`.
- **Commit:** MUST follow [Conventional Commits](https://www.conventionalcommits.org/), with the key in a `Refs:` footer:

  ```
  <type>[optional scope]: <description>

  [optional body]

  Refs: NKMA-14
  ```

- **PR title:** MUST use the same format as a commit subject, with the key appended: `feat: set up Claude Code (NKMA-14)`.
- **Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Breaking changes MUST be marked with `!` after the type/scope and a `BREAKING CHANGE:` footer.

## Project docs

- `docs/SPEC.md`: what the backend has to do: glossary, roles, statuses, server-side rules per use case (UC-xx), open decisions. Agents MUST read the relevant section before planning any feature. It is the only source of requirements; agents MUST NOT look for requirements anywhere else.
- `ARCHITECTURE.md`: how the backend is built. *(Not written yet.)*
- `README.md`: for humans. It MUST NOT be treated as a source of requirements.
- `REVIEW.md`: what code review flags and at what severity. See "Code review" below.

## Keeping docs accurate

Agents maintain the project docs (`docs/SPEC.md`, `ARCHITECTURE.md`, `README.md`, `CLAUDE.md`, `REVIEW.md`). Every change to them MUST be decided in Plan mode. Docs MUST be kept in sync with the code in the same PR, not in a follow-up.

- When a task changes what a doc describes, the plan MUST include the exact edits to that doc. They MUST be applied only after the plan is approved, in the same change as the code.
- If code and a doc disagree during implementation, or a doc is silent on something needed: agents MUST stop. Agents MUST NOT guess, and MUST NOT edit the doc to match the code. They MUST return to Plan mode and describe the conflict.

`README.md` is exempt from Plan mode: agents MAY fix or update it directly, but the change MUST still be in the same PR as the code it describes.

`docs/SPEC.md` has extra rules:

- An item listed under `docs/SPEC.md` §10 "Undecided" MUST NOT be implemented by assumption. It MUST be raised in Plan mode.
- Every edit to `docs/SPEC.md` MUST add a row to its changelog, naming the Jira issue (`NKMA-xx`) where it was decided.

### Shared sections

`docs/SPEC.md` here and `docs/SPEC.md` in `andinaufal120/niscala-app` share some content. Each shared block sits between `<!-- shared:begin -->` and `<!-- shared:end -->` markers, under a visible *Shared with niscala-app* note.

- Shared blocks MUST be identical in both repos.
- A change to a shared block MUST be made in both repos, in one PR per repo that link to each other and name the same Jira issue. Both SPEC changelogs get a row.
- If the two copies disagree, agents MUST stop and raise it in Plan mode. They MUST NOT pick one copy as correct.

## Vocabulary

- **Code:** identifiers MUST be English only, using the "Code name" column of the `docs/SPEC.md` glossary and status tables, in PEP 8 form: classes keep the name (`Tenant`, `RentBill`), attributes and functions use snake_case (`grace_period_days`), enum members use UPPER_SNAKE_CASE (`PaymentStatus.AWAITING_VERIFICATION`). The values these take on the wire are undecided (U-10 in `docs/SPEC.md` §10).
- **Writing:** em-dashes (—) MUST NOT be used in docs written for humans (`README.md`), code comments, commits, or PRs. Docs written for agents (`CLAUDE.md`, `REVIEW.md`, `docs/SPEC.md`, `ARCHITECTURE.md`, `.claude/agents/`) MAY use them.
- **Markdown docs:** domain terms MUST use the format *Original term (English term)*, e.g. *Penyewa (Tenant)*.
- **API messages:** MUST be English. Every error MUST carry an error code. The app's Indonesian text is keyed on the code, so a released code MUST NOT be renamed, removed, or change meaning. The response shape and code list are undecided (U-9 in `docs/SPEC.md` §10).
- **Commits, PRs and issue references:** MUST be in English, and SHOULD cite IDs (`UC-05`, `FR-13`, `NKMA-22`) where relevant.

## Boundaries

- The backend owns every business rule: permissions, billing and due dates, payment-pattern facts, risk flags, subscription gating, AI calls (Gemini), invitations and notifications. The app only renders what the API returns, so a rule that isn't enforced here isn't enforced anywhere.
- The OpenAPI document FastAPI generates from this code is the API contract. The app generates its Dart client from it. A breaking change (a removed or renamed path, field, enum value or error code, or a changed type) MUST be raised in Plan mode and released together with a PR in `andinaufal120/niscala-app`.
- App internals (screens, widgets, accessibility) MUST NOT be documented in this repo. What the app needs is stated in the shared `docs/SPEC.md` sections and the contract.

## CI

`.github/workflows/` runs Claude Code PR review (`claude-code-review.yml`) and `@claude` mentions (`claude.yml`).

## Code review

- When reviewing code, agents MUST follow `REVIEW.md`, including its severity definitions and nit cap.
- A review only reports findings. The reviewer MUST NOT edit code, push, or apply fixes unless explicitly told to (e.g. `/code-review --fix`).
- When explicitly asked to act on review findings, agents MAY decline a Nit, and MUST NOT add complexity only to satisfy one.
