from inspect import signature
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import (
    PayrollMaterializationFieldTypeInvalidError,
    PayrollMaterializationRequiredFieldMissingError,
    PayrollMaterializationStateConflictError,
)
from app.models.enums import PayrollCanonicalValueType, PayrollSourceType
from app.services.imports.payroll_materialization_service import (
    PAYROLL_VERSION_FIELD_SPECS,
    PayrollMaterializationService,
)


def checksum_evidence(**overrides):
    values = {
        "organization_id": uuid4(), "import_id": uuid4(),
        "approval_id": uuid4(), "approval_checksum": "a" * 64,
        "snapshot_id": uuid4(), "snapshot_checksum": "b" * 64,
        "validation_run_id": uuid4(), "validation_result_checksum": "c" * 64,
        "payroll_id": uuid4(), "payroll_version_id": uuid4(), "revision_no": 1,
    }
    values.update(overrides)
    return values


def test_materialization_checksum_is_deterministic_and_covers_identity():
    values = checksum_evidence()
    checksum = PayrollMaterializationService.materialization_checksum(**values)
    assert checksum == PayrollMaterializationService.materialization_checksum(**values)
    assert checksum != PayrollMaterializationService.materialization_checksum(
        **{**values, "approval_checksum": "d" * 64},
    )
    assert checksum != PayrollMaterializationService.materialization_checksum(
        **{**values, "payroll_version_id": uuid4()},
    )
    assert checksum != PayrollMaterializationService.materialization_checksum(
        **{**values, "revision_no": 2},
    )
    assert len(checksum) == 64
    parameters = signature(
        PayrollMaterializationService.materialization_checksum,
    ).parameters
    assert "materialized_at" not in parameters
    assert "created_at" not in parameters


def test_document_source_type_is_additive_and_preserves_existing_semantics():
    assert PayrollSourceType.DOCUMENT.value == "DOCUMENT"
    assert {
        source_type.value
        for source_type in (
            PayrollSourceType.MANUAL,
            PayrollSourceType.CSV,
            PayrollSourceType.XLSX,
            PayrollSourceType.PDF,
            PayrollSourceType.API,
            PayrollSourceType.CALCULATED,
        )
    } == {"MANUAL", "CSV", "XLSX", "PDF", "API", "CALCULATED"}


@pytest.mark.parametrize("value,precision,scale", [
    (1.25, 18, 2),
    (Decimal("1.234"), 18, 2),
    (Decimal("1000.00"), 5, 2),
])
def test_decimal_guard_rejects_float_scale_loss_and_precision_overflow(
    value, precision, scale,
):
    with pytest.raises(PayrollMaterializationFieldTypeInvalidError):
        PayrollMaterializationService._exact_decimal(
            "field", value, precision, scale,
        )


def authoritative_fields():
    fields = [
        SimpleNamespace(
            effective_canonical_key="employee_identifier",
            value_type=PayrollCanonicalValueType.IDENTIFIER,
            value_text="EMP-42", value_integer=None, value_decimal=None,
        ),
        SimpleNamespace(
            effective_canonical_key="period_year",
            value_type=PayrollCanonicalValueType.INTEGER,
            value_text=None, value_integer=2026, value_decimal=None,
        ),
        SimpleNamespace(
            effective_canonical_key="period_month",
            value_type=PayrollCanonicalValueType.INTEGER,
            value_text=None, value_integer=9, value_decimal=None,
        ),
    ]
    fields.extend(SimpleNamespace(
        effective_canonical_key=key, value_type=expected_type,
        value_text=None, value_integer=None, value_decimal=Decimal("10.00"),
    ) for key, (_, expected_type, _, _) in PAYROLL_VERSION_FIELD_SPECS.items())
    fields.append(SimpleNamespace(
        effective_canonical_key=None, value_type=PayrollCanonicalValueType.TEXT,
        value_text="preserved generic fact", value_integer=None, value_decimal=None,
    ))
    return fields


def test_canonical_extraction_ignores_generic_fields_and_fails_closed():
    fields = authoritative_fields()
    employee_no, year, month, values = (
        PayrollMaterializationService._extract_authoritative_values(fields)
    )
    assert (employee_no, year, month) == ("EMP-42", 2026, 9)
    assert set(values) == {
        value[0] for value in PAYROLL_VERSION_FIELD_SPECS.values()
    }
    assert all(value == Decimal("10.00") for value in values.values())

    with pytest.raises(PayrollMaterializationRequiredFieldMissingError):
        PayrollMaterializationService._extract_authoritative_values(fields[1:])

    with pytest.raises(PayrollMaterializationStateConflictError):
        PayrollMaterializationService._extract_authoritative_values(
            fields + [fields[3]],
        )

    invalid = authoritative_fields()
    invalid[3] = SimpleNamespace(
        effective_canonical_key=invalid[3].effective_canonical_key,
        value_type=PayrollCanonicalValueType.TEXT,
        value_text="10.00", value_integer=None, value_decimal=None,
    )
    with pytest.raises(PayrollMaterializationFieldTypeInvalidError):
        PayrollMaterializationService._extract_authoritative_values(invalid)
