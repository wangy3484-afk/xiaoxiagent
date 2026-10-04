"""Keep documented authentication examples aligned with generated OpenAPI."""

import re
from pathlib import Path
from typing import Any, cast

import pytest

from api.support import api_test_context

PROJECT_ROOT = Path(__file__).parents[3]
CONTRACT_PATTERN = re.compile(
    r"<!-- CONTRACT: (GET|POST|PATCH|DELETE) ([^ ]+) -->"
)
EXPECTED_CONTRACTS = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/briefs"),
    ("GET", "/api/v1/briefs/{brief_id}"),
    ("GET", "/api/v1/jobs/{job_id}"),
    ("GET", "/api/v1/evidence/{evidence_id}"),
    ("GET", "/api/v1/reports/{report_id}"),
    ("GET", "/api/v1/exports/{export_id}"),
    ("POST", "/api/v1/reports/{report_version_id}/exports"),
    ("GET", "/api/v1/exports/{export_id}/download"),
}


@pytest.mark.asyncio
async def test_documented_auth_contracts_exist_in_openapi() -> None:
    documentation = (PROJECT_ROOT / "docs" / "authentication.md").read_text(
        encoding="utf-8"
    )
    documented = set(CONTRACT_PATTERN.findall(documentation))
    assert documented == EXPECTED_CONTRACTS

    async with api_test_context() as context:
        schema = context.app.openapi()
    paths = cast(dict[str, dict[str, Any]], schema["paths"])
    for method, path in documented:
        assert path in paths
        assert method.lower() in paths[path]

    brief_create = paths["/api/v1/briefs"]["post"]
    header_parameters = {
        parameter["name"]: parameter
        for parameter in brief_create["parameters"]
        if parameter["in"] == "header"
    }
    assert header_parameters["Idempotency-Key"]["required"] is True


def test_security_document_states_cookie_and_oidc_boundaries() -> None:
    documentation = (PROJECT_ROOT / "docs" / "authentication.md").read_text(
        encoding="utf-8"
    )
    for required_term in (
        "Argon2",
        "Secure",
        "HttpOnly",
        "SameSite",
        "CSRF",
        "RESOURCE_NOT_FOUND",
        "OIDC",
        "AuthorizationSubject",
    ):
        assert required_term in documentation
