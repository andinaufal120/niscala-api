"""End-to-end scenarios.

This is a package so that its `conftest.py` does not shadow the shared
`tests/conftest.py`, which other test modules import by the name `conftest`.
Helpers are imported as `e2e.e2e_people` and `e2e.e2e_world`.
"""
