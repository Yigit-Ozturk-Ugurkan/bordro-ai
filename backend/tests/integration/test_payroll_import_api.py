import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_document_storage, get_general_reader_client
from app.core.config import get_settings
from app.integrations.general_reader.schemas import ExtractionResultV1
from app.main import app
from app.models.enums import UserRoleType
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.seeds.demo_payroll_seed import DEMO_USER_EMAILS
from app.services.auth.authentication import AuthenticatedUser, AuthenticationService
from app.storage.document_storage import LocalDocumentStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"api-test-document"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "general_reader_extraction_v1.json"
settings = get_settings()


class FakeReader:
    def __init__(self) -> None:
        self.calls = []
        self.include_tables = False

    async def extract(self, document, **kwargs):
        self.calls.append(kwargs)
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["request_id"] = kwargs["request_id"]
        payload["correlation_id"] = kwargs["request_id"]
        payload["tenant_context"]["tenant_id"] = str(kwargs["organization_id"])
        payload["document"]["sha256"] = kwargs["content_sha256"]
        payload["fields"] = payload["fields"][:1]
        payload["missing_fields"] = []
        if self.include_tables:
            payload["tables"][0]["columns"].append({
                "column_id": "c2", "source_label": "Amount", "value_type": "text",
            })
            payload["tables"][0]["rows"][0]["cells"][0].update({
                "confidence": 0.87,
                "bbox": [0.1, 0.2, 0.3, 0.4],
            })
            payload["tables"][0]["rows"].append({
                "row_index": 1,
                "page_number": 1,
                "bbox": [0.2, 0.3, 0.8, 0.4],
                "coordinate_space": "normalized_xyxy",
                "extraction_source": "rule",
                "cells": [{
                    "column_id": "c1",
                    "source_label": "Column",
                    "raw_value": None,
                    "normalized_value": None,
                    "value_type": "text",
                    "confidence": None,
                    "bbox": None,
                    "coordinate_space": "normalized_xyxy",
                    "extraction_source": "rule",
                }, {
                    "column_id": "c2",
                    "source_label": "Amount",
                    "raw_value": "14.000,00-",
                    "normalized_value": "-14000.00",
                    "value_type": "text",
                    "confidence": 0.91,
                    "bbox": [0.4, 0.3, 0.8, 0.4],
                    "coordinate_space": "normalized_xyxy",
                    "extraction_source": "rule",
                }],
            })
        else:
            payload["tables"] = []
        payload["warnings"] = []
        return ExtractionResultV1.model_validate(payload)


async def login_as(client: AsyncClient, role: UserRoleType) -> str:
    assert settings.demo_auth_password is not None
    response = await client.post("/api/v1/auth/login", json={
        "email": DEMO_USER_EMAILS[role],
        "password": settings.demo_auth_password.get_secret_value(),
    })
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def import_api(
    api_client: AsyncClient, seeded_async_session: AsyncSession, tmp_path: Path
):
    storage = LocalDocumentStorage(tmp_path)
    reader = FakeReader()
    app.dependency_overrides[get_document_storage] = lambda: storage
    app.dependency_overrides[get_general_reader_client] = lambda: reader
    try:
        yield api_client, storage, reader
    finally:
        app.dependency_overrides.pop(get_document_storage, None)
        app.dependency_overrides.pop(get_general_reader_client, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN])
async def test_writer_roles_can_multipart_upload_read_and_process(import_api, role):
    client, _storage, reader = import_api
    token = await login_as(client, role)
    expected_organization_id = AuthenticationService().decode_token(
        token, "access"
    ).organization_id
    headers = bearer(token)
    uploaded = await client.post(
        "/api/v1/payroll-imports", headers=headers,
        files={"file": ("C:\\client\\generic.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["status"] == "UPLOADED"
    assert body["document"]["original_filename"] == "generic.png"
    assert "storage_key" not in body["document"]
    import_id = body["id"]

    detail = await client.get(f"/api/v1/payroll-imports/{import_id}", headers=headers)
    assert detail.status_code == 200
    processed = await client.post(
        f"/api/v1/payroll-imports/{import_id}/process", headers=headers
    )
    assert processed.status_code == 200, processed.text
    assert processed.json()["status"] == "EXTRACTED"
    fields = await client.get(
        f"/api/v1/payroll-imports/{import_id}/fields", headers=headers
    )
    assert fields.status_code == 200
    assert fields.json()["count"] == 1
    assert fields.json()["items"][0]["review_status"] == "UNREVIEWED"
    assert reader.calls[0]["organization_id"] == expected_organization_id


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN])
async def test_writer_roles_can_reprocess_review_required_import(import_api, role):
    client, _storage, reader = import_api
    reader.include_tables = True
    headers = bearer(await login_as(client, role))
    uploaded = await client.post(
        "/api/v1/payroll-imports", headers=headers,
        files={"file": ("reprocess.png", PNG, "image/png")},
    )
    import_id = uploaded.json()["id"]
    first = await client.post(
        f"/api/v1/payroll-imports/{import_id}/process", headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "REVIEW_REQUIRED"

    refreshed = await client.post(
        f"/api/v1/payroll-imports/{import_id}/reprocess", headers=headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "REVIEW_REQUIRED"
    assert refreshed.json()["processing_attempt"] == 2
    assert len(reader.calls) == 2


@pytest.mark.asyncio
async def test_auditor_is_read_only(import_api):
    client, _storage, _reader = import_api
    writer = bearer(await login_as(client, UserRoleType.PAYROLL_ADMIN))
    auditor = bearer(await login_as(client, UserRoleType.AUDITOR))
    uploaded = await client.post(
        "/api/v1/payroll-imports", headers=writer,
        files={"file": ("audit.png", PNG, "image/png")},
    )
    import_id = uploaded.json()["id"]
    assert (await client.get("/api/v1/payroll-imports", headers=auditor)).status_code == 200
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}", headers=auditor
    )).status_code == 200
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}/fields", headers=auditor
    )).status_code == 200
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}/tables", headers=auditor
    )).status_code == 200
    assert (await client.post(
        "/api/v1/payroll-imports", headers=auditor,
        files={"file": ("denied.png", PNG, "image/png")},
    )).status_code == 403
    assert (await client.post(
        f"/api/v1/payroll-imports/{import_id}/process", headers=auditor
    )).status_code == 403
    assert (await client.post(
        f"/api/v1/payroll-imports/{import_id}/reprocess", headers=auditor
    )).status_code == 403


@pytest.mark.asyncio
async def test_employee_has_no_import_access(import_api):
    client, _storage, _reader = import_api
    employee = bearer(await login_as(client, UserRoleType.EMPLOYEE))
    assert (await client.get("/api/v1/payroll-imports", headers=employee)).status_code == 403
    assert (await client.get(
        f"/api/v1/payroll-imports/{uuid4()}/tables", headers=employee
    )).status_code == 403
    assert (await client.post(
        "/api/v1/payroll-imports", headers=employee,
        files={"file": ("denied.png", PNG, "image/png")},
    )).status_code == 403


@pytest.mark.asyncio
async def test_system_admin_has_no_implicit_import_access(
    import_api, seeded_async_session: AsyncSession
):
    client, _storage, _reader = import_api

    def create(sync: Session) -> AuthenticatedUser:
        organization = sync.query(Organization).filter_by(code="DEMO_COMPANY").one()
        user = User(
            id=uuid4(), organization_id=organization.id,
            email=f"system-{uuid4().hex}@test.invalid", password_hash="unused",
            is_active=True,
        )
        sync.add(user)
        sync.flush()
        sync.add(UserRole(id=uuid4(), user_id=user.id, role=UserRoleType.SYSTEM_ADMIN))
        sync.flush()
        return AuthenticatedUser(
            id=user.id, organization_id=organization.id,
            roles=frozenset({UserRoleType.SYSTEM_ADMIN}), employee_id=None,
        )

    user = await seeded_async_session.run_sync(create)
    token = AuthenticationService().create_access_token(user)
    assert (await client.get(
        "/api/v1/payroll-imports", headers=bearer(token)
    )).status_code == 403
    assert (await client.get(
        f"/api/v1/payroll-imports/{uuid4()}/tables", headers=bearer(token)
    )).status_code == 403


@pytest.mark.asyncio
async def test_cross_organization_ids_are_404_non_disclosing(
    import_api, seeded_async_session: AsyncSession
):
    client, _storage, _reader = import_api
    writer = bearer(await login_as(client, UserRoleType.PAYROLL_ADMIN))
    uploaded = await client.post(
        "/api/v1/payroll-imports", headers=writer,
        files={"file": ("owner.png", PNG, "image/png")},
    )
    import_id = uploaded.json()["id"]

    def create_other(sync: Session) -> AuthenticatedUser:
        organization = Organization(
            id=uuid4(), name="Other API Org", code=f"API-{uuid4().hex[:8]}",
            timezone="Europe/Istanbul", is_active=True,
        )
        user = User(
            id=uuid4(), organization_id=organization.id,
            email=f"other-{uuid4().hex}@test.invalid", password_hash="unused",
            is_active=True,
        )
        sync.add_all([organization, user])
        sync.flush()
        sync.add(UserRole(id=uuid4(), user_id=user.id, role=UserRoleType.HR_ADMIN))
        sync.flush()
        return AuthenticatedUser(
            id=user.id, organization_id=organization.id,
            roles=frozenset({UserRoleType.HR_ADMIN}), employee_id=None,
        )

    outsider = await seeded_async_session.run_sync(create_other)
    await seeded_async_session.commit()
    outsider_headers = bearer(AuthenticationService().create_access_token(outsider))
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}", headers=outsider_headers
    )).status_code == 404
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}/fields", headers=outsider_headers
    )).status_code == 404
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}/tables", headers=outsider_headers
    )).status_code == 404
    assert (await client.get(
        f"/api/v1/payroll-imports/{import_id}/tables/{uuid4()}",
        headers=outsider_headers,
    )).status_code == 404
    assert (await client.post(
        f"/api/v1/payroll-imports/{import_id}/process", headers=outsider_headers
    )).status_code == 404
    assert (await client.post(
        f"/api/v1/payroll-imports/{import_id}/reprocess", headers=outsider_headers
    )).status_code == 404
    listing = await client.get("/api/v1/payroll-imports", headers=outsider_headers)
    assert listing.status_code == 200
    assert listing.json()["count"] == 0


@pytest.mark.asyncio
async def test_table_read_api_preserves_raw_evidence_and_rbac(import_api):
    client, _storage, reader = import_api
    reader.include_tables = True
    writer = bearer(await login_as(client, UserRoleType.PAYROLL_ADMIN))
    uploaded = await client.post(
        "/api/v1/payroll-imports", headers=writer,
        files={"file": ("table.png", PNG, "image/png")},
    )
    import_id = uploaded.json()["id"]
    processed = await client.post(
        f"/api/v1/payroll-imports/{import_id}/process", headers=writer,
    )
    assert processed.status_code == 200, processed.text
    assert len(reader.calls) == 1

    for role in (
        UserRoleType.PAYROLL_ADMIN, UserRoleType.HR_ADMIN, UserRoleType.AUDITOR,
    ):
        role_headers = bearer(await login_as(client, role))
        response = await client.get(
            f"/api/v1/payroll-imports/{import_id}/tables",
            headers=role_headers,
        )
        assert response.status_code == 200
        assert response.json()["count"] == 1
        role_table_id = response.json()["items"][0]["id"]
        assert (await client.get(
            f"/api/v1/payroll-imports/{import_id}/tables/{role_table_id}",
            headers=role_headers,
        )).status_code == 200

    listing = await client.get(
        f"/api/v1/payroll-imports/{import_id}/tables", headers=writer,
    )
    table_id = listing.json()["items"][0]["id"]
    detail = await client.get(
        f"/api/v1/payroll-imports/{import_id}/tables/{table_id}", headers=writer,
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [row["row_index"] for row in body["rows"]] == [0, 1]
    assert Decimal(body["rows"][0]["cells"][0]["confidence"]) == Decimal("0.87")
    assert body["rows"][0]["cells"][0]["bbox"] == ["0.1", "0.2", "0.3", "0.4"]
    assert body["rows"][1]["cells"][0]["raw_value"] is None
    assert body["rows"][1]["cells"][1]["raw_value"] == "14.000,00-"


@pytest.mark.asyncio
async def test_wrong_content_type_and_duplicate_upload_are_stable_errors(import_api):
    client, _storage, _reader = import_api
    writer = bearer(await login_as(client, UserRoleType.PAYROLL_ADMIN))
    wrong = await client.post(
        "/api/v1/payroll-imports", headers={**writer, "Content-Type": "application/json"},
        content=b"{}",
    )
    assert wrong.status_code == 422

    first = await client.post(
        "/api/v1/payroll-imports", headers=writer,
        files={"file": ("one.png", PNG, "image/png")},
    )
    assert first.status_code == 201
    duplicate = await client.post(
        "/api/v1/payroll-imports", headers=writer,
        files={"file": ("renamed.png", PNG, "image/png")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "detail": "This document has already been imported",
        "code": "DUPLICATE_DOCUMENT",
    }
