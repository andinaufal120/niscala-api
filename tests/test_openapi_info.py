"""The generated OpenAPI document reports the project identity and version."""

import tomllib
from importlib.metadata import version
from pathlib import Path

DISTRIBUTION = "niscala-api"
FASTAPI_DEFAULT_VERSION = "0.1.0"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def project_version_from_pyproject() -> str:
    with PYPROJECT.open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def test_info_version_matches_installed_package_metadata(openapi):
    assert openapi.document["info"]["version"] == version(DISTRIBUTION)


def test_info_version_matches_pyproject_version(openapi):
    assert openapi.document["info"]["version"] == project_version_from_pyproject()


def test_info_version_is_not_the_framework_default_unless_project_is(openapi):
    reported = openapi.document["info"]["version"]
    if project_version_from_pyproject() != FASTAPI_DEFAULT_VERSION:
        assert reported != FASTAPI_DEFAULT_VERSION


def test_info_version_is_a_non_empty_string(openapi):
    reported = openapi.document["info"]["version"]
    assert isinstance(reported, str)
    assert reported.strip() != ""


def test_info_title_is_niscala_api(openapi):
    assert openapi.document["info"]["title"] == "Niscala API"


def test_openapi_endpoint_serves_the_same_version(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == project_version_from_pyproject()
