from inspect import signature
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import PayrollApprovalDecision
from app.schemas.payroll_approval import PayrollRejectRequest
from app.services.imports.payroll_approval_service import PayrollApprovalService


def evidence(**overrides):
    values = {
        "organization_id": uuid4(), "import_id": uuid4(), "snapshot_id": uuid4(),
        "snapshot_checksum": "a" * 64, "validation_run_id": uuid4(),
        "validation_result_checksum": "b" * 64, "ruleset_version": 1,
        "decision": PayrollApprovalDecision.APPROVED,
        "decision_reason": "Reviewed",
        "acknowledged_warning_result_ids": (uuid4(), uuid4()),
    }
    values.update(overrides)
    return values


def test_approval_checksum_is_deterministic_and_covers_material_evidence():
    values = evidence()
    checksum = PayrollApprovalService.approval_checksum(**values)
    assert checksum == PayrollApprovalService.approval_checksum(**values)
    assert checksum == PayrollApprovalService.approval_checksum(
        **{**values, "acknowledged_warning_result_ids": tuple(
            reversed(values["acknowledged_warning_result_ids"])
        )},
    )
    assert checksum != PayrollApprovalService.approval_checksum(
        **{**values, "decision": PayrollApprovalDecision.REJECTED},
    )
    assert checksum != PayrollApprovalService.approval_checksum(
        **{**values, "acknowledged_warning_result_ids": values[
            "acknowledged_warning_result_ids"
        ][:1]},
    )
    assert checksum != PayrollApprovalService.approval_checksum(
        **{**values, "validation_result_checksum": "c" * 64},
    )
    assert len(checksum) == 64
    assert "decided_at" not in signature(
        PayrollApprovalService.approval_checksum
    ).parameters


def test_rejection_reason_rejects_missing_or_whitespace_values():
    with pytest.raises(ValidationError):
        PayrollRejectRequest(reason="   ")
    with pytest.raises(ValidationError):
        PayrollRejectRequest.model_validate({})
    assert PayrollRejectRequest(reason="  unusable document  ").reason == "unusable document"
