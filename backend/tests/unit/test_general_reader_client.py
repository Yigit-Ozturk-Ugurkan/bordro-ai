import json
import re
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.exceptions import (
    GeneralReaderContractInvalidError,
    GeneralReaderRejectedError,
    GeneralReaderUnavailableError,
)
from app.integrations.general_reader.client import (
    EXTRACTION_PATH,
    GeneralReaderClient,
    SignedRequestContext,
    canonical_payload,
    sign_request,
)

ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
REQUEST_ID = "22222222-2222-2222-2222-222222222222"
SECRET = "test-only-shared-secret-with-at-least-32-bytes"
DIGEST = "0" * 64
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "general_reader_extraction_v1.json"


def settings(**updates):
    base = get_settings()
    values = {
        "general_reader_base_url": "http://reader.test:8010",
        "general_reader_client_id": "bordro-test",
        "general_reader_shared_secret": SecretStr(SECRET),
        "general_reader_timeout_seconds": 2,
        "general_reader_allow_llm": False,
    }
    values.update(updates)
    return base.model_copy(update=values)


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_payload_and_signature_match_general_reader_head_fixture():
    context = SignedRequestContext(
        client_id="bordro-test", timestamp=1788550000,
        nonce="contractnonce00000001", tenant_namespace="bordro-ai",
        tenant_id=str(ORG_ID), content_sha256=DIGEST, allow_llm=False,
    )
    assert canonical_payload("post", EXTRACTION_PATH, context) == (
        b'{"allow_llm":false,"api_version":"1","client_id":"bordro-test",'
        b'"content_sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
        b'"method":"POST","nonce":"contractnonce00000001",'
        b'"path":"/internal/v1/extractions",'
        b'"tenant_id":"11111111-1111-1111-1111-111111111111",'
        b'"tenant_namespace":"bordro-ai","timestamp":1788550000}'
    )
    assert sign_request(SECRET, "POST", EXTRACTION_PATH, context) == (
        "sha256=d788053197f070d8f10c8c0affe95afaf96b3fb8c151f970ae75795c9cf6d16c"
    )


@pytest.mark.asyncio
async def test_required_headers_tenant_nonce_timestamp_hash_and_response_parse():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        assert request.url.path == EXTRACTION_PATH
        assert b'name="file"' in await request.aread()
        return httpx.Response(200, json=fixture_payload())

    client = GeneralReaderClient(
        settings(), transport=httpx.MockTransport(handler),
        clock=lambda: 1788550000,
        nonce_factory=lambda: "contractnonce00000001",
    )
    result = await client.extract(
        __import__("io").BytesIO(b"document"), filename="generic.png",
        mime_type="image/png", content_sha256=DIGEST,
        organization_id=ORG_ID, request_id=REQUEST_ID,
    )
    assert result.schema_version == "1.0"
    assert captured["x-gr-client-id"] == "bordro-test"
    assert captured["x-gr-timestamp"] == "1788550000"
    assert captured["x-gr-nonce"] == "contractnonce00000001"
    assert captured["x-gr-tenant-namespace"] == "bordro-ai"
    assert captured["x-gr-tenant-id"] == str(ORG_ID)
    assert captured["x-gr-content-sha256"] == DIGEST
    assert captured["x-gr-allow-llm"] == "false"
    assert captured["x-gr-api-version"] == "1"
    assert captured["x-gr-signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_default_nonce_is_cryptographically_sized_and_header_safe():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["nonce"] = request.headers["X-GR-Nonce"]
        return httpx.Response(200, json=fixture_payload())

    await GeneralReaderClient(settings(), transport=httpx.MockTransport(handler)).extract(
        __import__("io").BytesIO(b"x"), filename="generic.png",
        mime_type="image/png", content_sha256=DIGEST,
        organization_id=ORG_ID, request_id=REQUEST_ID,
    )
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", captured["nonce"])


@pytest.mark.asyncio
async def test_llm_policy_is_server_config_only_and_signed():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["allow"] = request.headers["X-GR-Allow-LLM"]
        captured["signature"] = request.headers["X-GR-Signature"]
        return httpx.Response(200, json=fixture_payload())

    client = GeneralReaderClient(
        settings(general_reader_allow_llm=True),
        transport=httpx.MockTransport(handler),
        clock=lambda: 1788550000,
        nonce_factory=lambda: "contractnonce00000001",
    )
    await client.extract(
        __import__("io").BytesIO(b"x"), filename="generic.png",
        mime_type="image/png", content_sha256=DIGEST,
        organization_id=ORG_ID, request_id=REQUEST_ID,
    )
    context = SignedRequestContext(
        client_id="bordro-test", timestamp=1788550000,
        nonce="contractnonce00000001", tenant_namespace="bordro-ai",
        tenant_id=str(ORG_ID), content_sha256=DIGEST, allow_llm=True,
    )
    assert captured == {
        "allow": "true",
        "signature": sign_request(SECRET, "POST", EXTRACTION_PATH, context),
    }


@pytest.mark.asyncio
async def test_remote_structured_error_is_mapped_without_raw_details():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {
            "code": "INVALID_DOCUMENT", "message": "raw secret/path"
        }})

    client = GeneralReaderClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(GeneralReaderRejectedError) as caught:
        await client.extract(
            __import__("io").BytesIO(b"x"), filename="generic.png",
            mime_type="image/png", content_sha256=DIGEST,
            organization_id=ORG_ID, request_id=REQUEST_ID,
        )
    assert "raw secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_is_safely_mapped():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("raw remote URL and details", request=request)

    client = GeneralReaderClient(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(GeneralReaderUnavailableError):
        await client.extract(
            __import__("io").BytesIO(b"x"), filename="generic.png",
            mime_type="image/png", content_sha256=DIGEST,
            organization_id=ORG_ID, request_id=REQUEST_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", [
        "schema", "extra", "tenant", "hash", "request", "correlation",
        "negative_table_row", "malformed_cell_bbox", "invalid_cell_confidence",
    ]
)
async def test_invalid_or_mismatched_response_is_rejected(mutation: str):
    payload = fixture_payload()
    if mutation == "schema":
        payload["schema_version"] = "2.0"
    elif mutation == "extra":
        payload["mongo_id"] = "not-allowed"
    elif mutation == "tenant":
        payload["tenant_context"]["tenant_id"] = str(UUID(int=3))
    elif mutation == "hash":
        payload["document"]["sha256"] = "1" * 64
    elif mutation == "request":
        payload["request_id"] = "different"
    elif mutation == "correlation":
        payload["correlation_id"] = "different"
    elif mutation == "negative_table_row":
        payload["tables"][0]["rows"][0]["row_index"] = -1
    elif mutation == "malformed_cell_bbox":
        payload["tables"][0]["rows"][0]["cells"][0]["bbox"] = [0.1, 0.2]
    else:
        payload["tables"][0]["rows"][0]["cells"][0]["confidence"] = 1.1

    client = GeneralReaderClient(
        settings(), transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        )
    )
    with pytest.raises(GeneralReaderContractInvalidError):
        await client.extract(
            __import__("io").BytesIO(b"x"), filename="generic.png",
            mime_type="image/png", content_sha256=DIGEST,
            organization_id=ORG_ID, request_id=REQUEST_ID,
        )


@pytest.mark.asyncio
async def test_invalid_service_configuration_fails_closed_before_http():
    client = GeneralReaderClient(settings(general_reader_shared_secret=SecretStr("short")))
    with pytest.raises(GeneralReaderUnavailableError):
        await client.extract(
            __import__("io").BytesIO(b"x"), filename="generic.png",
            mime_type="image/png", content_sha256=DIGEST,
            organization_id=ORG_ID, request_id=REQUEST_ID,
        )


@pytest.mark.asyncio
async def test_base_url_path_prefix_is_rejected_because_signed_path_is_exact():
    client = GeneralReaderClient(settings(
        general_reader_base_url="http://reader.test:8010/prefix"
    ))
    with pytest.raises(GeneralReaderUnavailableError):
        await client.extract(
            __import__("io").BytesIO(b"x"), filename="generic.png",
            mime_type="image/png", content_sha256=DIGEST,
            organization_id=ORG_ID, request_id=REQUEST_ID,
        )
