"""Explicit V2.1A payroll-import state transitions."""

from app.core.exceptions import PayrollImportStateConflictError
from app.models.enums import PayrollImportStatus
from app.models.payroll_import import PayrollImport


VALID_TRANSITIONS = {
    PayrollImportStatus.UPLOADED: frozenset({
        PayrollImportStatus.PROCESSING, PayrollImportStatus.REJECTED,
    }),
    PayrollImportStatus.PROCESSING: frozenset({
        PayrollImportStatus.EXTRACTED,
        PayrollImportStatus.REVIEW_REQUIRED,
        PayrollImportStatus.FAILED,
    }),
    PayrollImportStatus.FAILED: frozenset({PayrollImportStatus.PROCESSING}),
    PayrollImportStatus.EXTRACTED: frozenset({PayrollImportStatus.REJECTED}),
    PayrollImportStatus.REVIEW_REQUIRED: frozenset({PayrollImportStatus.REJECTED}),
    PayrollImportStatus.REJECTED: frozenset(),
}


def transition(item: PayrollImport, target: PayrollImportStatus) -> None:
    if target not in VALID_TRANSITIONS[item.status]:
        raise PayrollImportStateConflictError()
    item.status = target


__all__ = ["VALID_TRANSITIONS", "transition"]
