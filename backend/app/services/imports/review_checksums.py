"""Deterministic SHA-256 canonicalization for review validity and snapshots."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from app.models.payroll_import import PayrollImportField, PayrollImportMappedField
from app.models.payroll_review import PayrollImportFieldCorrection


def canonical_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def sha256_canonical(payload: Any) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def source_payload(source: PayrollImportField) -> dict[str, Any]:
    return {
        "bbox": [canonical_scalar(value) for value in source.bbox] if source.bbox else None,
        "confidence": canonical_scalar(source.confidence),
        "coordinate_space": source.coordinate_space,
        "extraction_source": source.extraction_source,
        "id": str(source.id),
        "missing_reason_code": source.missing_reason_code,
        "normalized_value": source.normalized_value,
        "page_number": source.page_number,
        "raw_value": source.raw_value,
        "review_status": canonical_scalar(source.review_status),
        "source_field_id": source.source_field_id,
        "source_label": source.source_label,
        "source_text": source.source_text,
        "value_type": source.value_type,
    }


def adapter_payload(row: PayrollImportMappedField) -> dict[str, Any]:
    return {
        "candidate_canonical_keys": sorted(row.candidate_canonical_keys),
        "canonical_key": row.canonical_key,
        "mapping_id": str(row.mapping_id) if row.mapping_id else None,
        "mapping_status": canonical_scalar(row.mapping_status),
        "mapping_version": row.mapping_version,
        "parse_status": canonical_scalar(row.parse_status),
        "review_reason_codes": sorted(row.review_reason_codes),
        "review_status": canonical_scalar(row.review_status),
        "section_key": row.section_key,
        "source": source_payload(row.source_field),
        "target_value_type": canonical_scalar(row.target_value_type),
        "value_date": canonical_scalar(row.value_date),
        "value_decimal": canonical_scalar(row.value_decimal),
        "value_integer": row.value_integer,
        "value_text": row.value_text,
    }


def adapter_fingerprint(row: PayrollImportMappedField) -> str:
    """Fingerprint stable across identical adapter reruns; mapped row IDs are excluded."""
    return sha256_canonical(adapter_payload(row))


def source_staging_checksum(rows: list[PayrollImportMappedField]) -> str:
    payload = sorted(
        (source_payload(row.source_field) for row in rows), key=lambda value: value["id"],
    )
    return sha256_canonical(payload)


def adapter_output_checksum(rows: list[PayrollImportMappedField]) -> str:
    payload = sorted(
        (adapter_payload(row) for row in rows), key=lambda value: value["source"]["id"],
    )
    return sha256_canonical(payload)


def corrections_checksum(rows: list[PayrollImportFieldCorrection]) -> str:
    payload = [{
        "action": canonical_scalar(row.action),
        "adapter_fingerprint": row.adapter_fingerprint,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "id": str(row.id),
        "original_canonical_key": row.original_canonical_key,
        "original_mapping_status": canonical_scalar(row.original_mapping_status),
        "original_value_date": canonical_scalar(row.original_value_date),
        "original_value_decimal": canonical_scalar(row.original_value_decimal),
        "original_value_integer": row.original_value_integer,
        "original_value_text": row.original_value_text,
        "original_value_type": canonical_scalar(row.original_value_type),
        "override_canonical_key": row.override_canonical_key,
        "payroll_import_field_id": str(row.payroll_import_field_id),
        "reason": row.reason,
        "reviewer_user_id": str(row.reviewer_user_id),
        "revision": row.revision,
        "section_key": row.section_key,
        "supersedes_correction_id": (
            str(row.supersedes_correction_id) if row.supersedes_correction_id else None
        ),
        "value_date": canonical_scalar(row.value_date),
        "value_decimal": canonical_scalar(row.value_decimal),
        "value_integer": row.value_integer,
        "value_text": row.value_text,
        "value_type": canonical_scalar(row.value_type),
    } for row in sorted(rows, key=lambda value: (
        str(value.payroll_import_field_id), value.revision, str(value.id)
    ))]
    return sha256_canonical(payload)


__all__ = [
    "adapter_fingerprint", "adapter_output_checksum", "canonical_scalar",
    "corrections_checksum", "sha256_canonical", "source_staging_checksum",
]
