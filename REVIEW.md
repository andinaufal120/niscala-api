# Review instructions

Key words in all capitals (MUST, SHOULD, MAY, etc.) follow BCP 14 (RFC 2119, RFC 8174), as in `CLAUDE.md`.

## What Important means here

Reserve Important for findings that would break behavior or break a project rule that `CLAUDE.md` marks MUST or MUST NOT:

- Incorrect logic, crashes, or data loss
- A permission check missing or weaker than `docs/SPEC.md` §4 allows
- Business rules placed in database constraints instead of application code
- An AI failure or timeout that blocks or rolls back saving data
- A breaking OpenAPI change without a matching PR in `andinaufal120/niscala-app`
- Changes under `tests/` in an implementation commit
- Code that contradicts `docs/SPEC.md`, or implements an item from its §10 "Undecided" by assumption

Doc drift SHOULD be marked Important: a PR that changes behavior, structure, or conventions described in `docs/SPEC.md`, `ARCHITECTURE.md`, `CLAUDE.md`, or `REVIEW.md` without updating that doc in the same PR. A change to a shared block in `docs/SPEC.md` without a linked PR making the same change in `andinaufal120/niscala-app` is also Important. `README.md` drift is Nit.

Report findings only. Don't edit code, push commits, or apply fixes unless explicitly told to.

Everything else, including style, naming, and refactoring suggestions, is Nit at most.

## Don't push complexity

The project favors the simplest code that satisfies the request. Don't report:

- Missing abstractions, extension points, or configurability for cases the spec doesn't require
- Extra validation, error handling, or defensive checks for situations that can't occur
- Alternative designs that are equivalent rather than better

A suggestion that adds code without fixing a real defect is not a finding.

## Cap the nits

Report at most three Nits per review. If you found more, say "plus N similar items" in the summary instead of posting them inline. If everything you found is a Nit, lead the summary with "No blocking issues."

After the first review of a PR, post Important findings only.

## Do not report

- Anything `ruff check` or `ruff format` already enforces
- `uv.lock`, `.venv/`, and `__pycache__/`
- Failing tests in a test-only commit from `test-writer`, as long as the PR's final commit passes
