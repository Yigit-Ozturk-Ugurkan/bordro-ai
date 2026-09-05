"""Exact client for General Reader's private HMAC integration API."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import BinaryIO, Callable
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    GeneralReaderContractInvalidError,
    GeneralReaderRejectedError,
    GeneralReaderUnavailableError,
)
from app.integrations.general_reader.schemas import ExtractionResultV1

API_VERSION = "1"
EXTRACTION_PATH = "/internal/v1/extractions"
TENANT_NAMESPACE = "bordro-ai"


@dataclass(frozen=True)
class SignedRequestContext:
    client_id: str
    timestamp: int
    nonce: str
    tenant_namespace: str
    tenant_id: str
    content_sha256: str
    allow_llm: bool
    api_version: str = API_VERSION


def canonical_payload(method: str, path: str,
                      context: SignedRequestContext) -> bytes:
    value = {
        "allow_llm": context.allow_llm,
        "api_version": context.api_version,
        "client_id": context.client_id,
        "content_sha256": context.content_sha256,
        "method": method.upper(),
        "nonce": context.nonce,
        "path": path,
        "tenant_id": context.tenant_id,
        "tenant_namespace": context.tenant_namespace,
        "timestamp": context.timestamp,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def sign_request(secret: str, method: str, path: str,
                 context: SignedRequestContext) -> str:
    digest = hmac.new(secret.encode("utf-8"),
                      canonical_payload(method, path, context),
                      hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class GeneralReaderClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._clock = clock
        self._nonce_factory = nonce_factory

    async def extract(
        self,
        document: BinaryIO,
        *,
        filename: str,
        mime_type: str,
        content_sha256: str,
        organization_id: UUID,
        request_id: str,
    ) -> ExtractionResultV1:
        client_id, secret, base_url = self._validated_configuration()
        context = SignedRequestContext(
            client_id=client_id,
            timestamp=int(self._clock()),
            nonce=self._nonce_factory(),
            tenant_namespace=TENANT_NAMESPACE,
            tenant_id=str(organization_id),
            content_sha256=content_sha256,
            allow_llm=self._settings.general_reader_allow_llm,
        )
        headers = {
            "X-GR-Client-ID": context.client_id,
            "X-GR-Timestamp": str(context.timestamp),
            "X-GR-Nonce": context.nonce,
            "X-GR-Tenant-Namespace": context.tenant_namespace,
            "X-GR-Tenant-ID": context.tenant_id,
            "X-GR-Content-SHA256": context.content_sha256,
            "X-GR-Allow-LLM": "true" if context.allow_llm else "false",
            "X-GR-API-Version": API_VERSION,
            "X-GR-Signature": sign_request(secret, "POST", EXTRACTION_PATH, context),
            "X-Request-ID": request_id,
            "X-Correlation-ID": request_id,
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._settings.general_reader_timeout_seconds,
            ) as client:
                response = await client.post(
                    base_url + EXTRACTION_PATH,
                    headers=headers,
                    files={"file": (filename, document, mime_type)},
                )
        except httpx.TimeoutException as exc:
            raise GeneralReaderUnavailableError() from exc
        except httpx.RequestError as exc:
            raise GeneralReaderUnavailableError() from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise GeneralReaderRejectedError()
        try:
            result = ExtractionResultV1.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise GeneralReaderContractInvalidError() from exc
        if (
            result.tenant_context.namespace != TENANT_NAMESPACE
            or result.tenant_context.tenant_id != str(organization_id)
            or result.document.sha256 != content_sha256
            or result.request_id != request_id
            or result.correlation_id != request_id
        ):
            raise GeneralReaderContractInvalidError()
        return result

    def _validated_configuration(self) -> tuple[str, str, str]:
        client_id = self._settings.general_reader_client_id.strip()
        secret_value = self._settings.general_reader_shared_secret
        secret = secret_value.get_secret_value() if secret_value is not None else ""
        base_url = self._settings.general_reader_base_url.rstrip("/")
        parsed = urlparse(base_url)
        if (
            not client_id
            or len(client_id) > 128
            or len(secret.encode("utf-8")) < 32
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise GeneralReaderUnavailableError(
                "The document extraction service is not configured"
            )
        return client_id, secret, base_url


__all__ = [
    "API_VERSION", "EXTRACTION_PATH", "TENANT_NAMESPACE", "GeneralReaderClient",
    "SignedRequestContext", "canonical_payload", "sign_request",
]
