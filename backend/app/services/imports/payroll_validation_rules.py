"""Code-owned, deterministic rules for immutable payroll review snapshots."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from uuid import UUID

from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollValidationCategory,
    PayrollValidationSeverity,
)
from app.models.payroll_review import PayrollImportReviewSnapshotField
from app.services.imports.canonical_fields import (
    CANONICAL_KEYS,
    REQUIRED_CANONICAL_FIELDS,
    get_canonical_field,
)

RULESET_VERSION = 1


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    version: int
    category: PayrollValidationCategory
    severity: PayrollValidationSeverity
    message: str
    canonical_key: str | None = None
    related_snapshot_field_ids: tuple[UUID, ...] = ()
    expected_value: str | None = None
    actual_value: str | None = None
    details: dict = field(default_factory=dict)

    @property
    def blocks_future_approval(self) -> bool:
        return self.severity in {
            PayrollValidationSeverity.ERROR,
            PayrollValidationSeverity.BLOCKING,
        }


@dataclass
class ValidationContext:
    fields: tuple[PayrollImportReviewSnapshotField, ...]
    matching_employee_ids: tuple[UUID, ...] = ()
    existing_current_payroll_id: UUID | None = None

    def by_key(self, key: str) -> tuple[PayrollImportReviewSnapshotField, ...]:
        return tuple(row for row in self.fields if row.effective_canonical_key == key)

    def scalar(self, key: str):
        rows = self.by_key(key)
        if len(rows) != 1 or not _valid_shape(rows[0]):
            return None
        row = rows[0]
        return next(value for value in (
            row.value_decimal, row.value_integer, row.value_date, row.value_text,
        ) if value is not None)


RuleValidator = Callable[[ValidationContext, "ValidationRule"], list[ValidationFinding]]


@dataclass(frozen=True)
class ValidationRule:
    code: str
    version: int
    category: PayrollValidationCategory
    severity: PayrollValidationSeverity
    required_canonical_inputs: tuple[str, ...]
    description: str
    validator: RuleValidator


def _finding(rule: ValidationRule, message: str, *, severity=None, **kwargs):
    return ValidationFinding(
        code=rule.code, version=rule.version, category=rule.category,
        severity=severity or rule.severity, message=message, **kwargs,
    )


def _required(context: ValidationContext, rule: ValidationRule):
    counts = Counter(row.effective_canonical_key for row in context.fields)
    return [
        _finding(
            rule, f"Required canonical field '{key}' is missing.",
            canonical_key=key, expected_value="exactly one", actual_value="missing",
        )
        for key in rule.required_canonical_inputs if counts[key] == 0
    ]


def _duplicates(context: ValidationContext, rule: ValidationRule):
    findings = []
    for key in sorted(CANONICAL_KEYS):
        rows = context.by_key(key)
        if len(rows) > 1:
            findings.append(_finding(
                rule, f"Canonical field '{key}' has multiple scalar values.",
                canonical_key=key,
                related_snapshot_field_ids=tuple(sorted((row.id for row in rows), key=str)),
                expected_value="1", actual_value=str(len(rows)),
            ))
    return findings


def _valid_shape(row: PayrollImportReviewSnapshotField) -> bool:
    values = (row.value_text, row.value_decimal, row.value_integer, row.value_date)
    if sum(value is not None for value in values) != 1:
        return False
    if row.value_type in {PayrollCanonicalValueType.DECIMAL, PayrollCanonicalValueType.DAY_COUNT}:
        return isinstance(row.value_decimal, Decimal)
    if row.value_type == PayrollCanonicalValueType.INTEGER:
        return isinstance(row.value_integer, int) and not isinstance(row.value_integer, bool)
    if row.value_type == PayrollCanonicalValueType.DATE:
        return isinstance(row.value_date, date) and not isinstance(row.value_date, datetime)
    if row.value_type in {PayrollCanonicalValueType.IDENTIFIER, PayrollCanonicalValueType.TEXT}:
        return isinstance(row.value_text, str) and bool(row.value_text.strip())
    return False


def _types(context: ValidationContext, rule: ValidationRule):
    findings = []
    for row in sorted(context.fields, key=lambda item: str(item.id)):
        expected_type = (
            get_canonical_field(row.effective_canonical_key).value_type
            if row.effective_canonical_key else row.value_type
        )
        if not _valid_shape(row) or row.value_type != expected_type:
            findings.append(_finding(
                rule, "Snapshot field has an invalid typed-value shape.",
                canonical_key=row.effective_canonical_key,
                related_snapshot_field_ids=(row.id,),
                expected_value=expected_type.value,
                actual_value=getattr(row.value_type, "value", str(row.value_type)),
            ))
    return findings


def _identity(context: ValidationContext, rule: ValidationRule):
    rows = context.by_key("employee_identifier")
    if len(rows) != 1 or context.scalar("employee_identifier") is None:
        return [_finding(
            rule, "Employee identity validation is not applicable because its input is invalid.",
            severity=PayrollValidationSeverity.INFO, canonical_key="employee_identifier",
            details={"applicability": "NOT_APPLICABLE"},
        )]
    identifier = str(context.scalar("employee_identifier"))
    if len(context.matching_employee_ids) != 1:
        return [_finding(
            rule, "Employee identifier did not resolve to exactly one employee in this organization.",
            canonical_key="employee_identifier", related_snapshot_field_ids=(rows[0].id,),
            expected_value="exactly one same-organization employee",
            actual_value=str(len(context.matching_employee_ids)),
            details={"employee_identifier": identifier},
        )]
    return [_finding(
        rule, "Employee identifier resolved within the organization.",
        severity=PayrollValidationSeverity.INFO, canonical_key="employee_identifier",
        related_snapshot_field_ids=(rows[0].id,),
        details={"resolved_employee_id": str(context.matching_employee_ids[0])},
    )]


def _period(context: ValidationContext, rule: ValidationRule):
    year, month = context.scalar("period_year"), context.scalar("period_month")
    rows = context.by_key("period_year") + context.by_key("period_month")
    if not isinstance(year, int) or isinstance(year, bool) or not isinstance(month, int) or isinstance(month, bool):
        return [_finding(
            rule, "Period validation is not applicable because its inputs are invalid.",
            severity=PayrollValidationSeverity.INFO,
            related_snapshot_field_ids=tuple(row.id for row in rows),
            details={"applicability": "NOT_APPLICABLE"},
        )]
    if not 1 <= year <= 9999 or not 1 <= month <= 12:
        return [_finding(
            rule, "Payroll period is structurally invalid.",
            related_snapshot_field_ids=tuple(row.id for row in rows),
            expected_value="year 1..9999 and month 1..12",
            actual_value=f"{year}-{month}",
        )]
    return [_finding(
        rule, "Payroll period is structurally valid.",
        severity=PayrollValidationSeverity.INFO,
        related_snapshot_field_ids=tuple(row.id for row in rows),
        actual_value=f"{year:04d}-{month:02d}",
    )]


def _net_pay(context: ValidationContext, rule: ValidationRule):
    rows = tuple(row for key in rule.required_canonical_inputs for row in context.by_key(key))
    earnings = context.scalar("total_earnings")
    deductions = context.scalar("total_deductions")
    actual = context.scalar("net_pay")
    if not all(isinstance(value, Decimal) for value in (earnings, deductions, actual)):
        return [_finding(
            rule, "Net-pay reconciliation is not applicable because an input is missing or invalid.",
            severity=PayrollValidationSeverity.INFO,
            related_snapshot_field_ids=tuple(row.id for row in rows),
            details={"applicability": "NOT_APPLICABLE"},
        )]
    expected = earnings - deductions
    severity = PayrollValidationSeverity.INFO if expected == actual else rule.severity
    message = "Net pay exactly matches earnings less deductions." if expected == actual else "Net pay does not equal earnings less deductions."
    return [_finding(
        rule, message, severity=severity,
        related_snapshot_field_ids=tuple(row.id for row in rows),
        expected_value=format(expected, "f"), actual_value=format(actual, "f"),
        details={"comparison": "exact_decimal"},
    )]


def _existing_payroll(context: ValidationContext, rule: ValidationRule):
    if context.existing_current_payroll_id is None:
        return []
    return [_finding(
        rule, "A current payroll already exists for this employee and period.",
        details={"existing_payroll_id": str(context.existing_current_payroll_id)},
    )]


def _not_applicable(message: str):
    def validator(context: ValidationContext, rule: ValidationRule):
        return [_finding(
            rule, message, severity=PayrollValidationSeverity.INFO,
            details={"applicability": "NOT_APPLICABLE"},
        )]
    return validator


VALIDATION_RULES = (
    ValidationRule("REQUIRED_CANONICAL_FIELDS", 1, PayrollValidationCategory.STRUCTURAL,
                   PayrollValidationSeverity.BLOCKING,
                   tuple(item.canonical_key for item in REQUIRED_CANONICAL_FIELDS),
                   "Require one value for every required canonical concept.", _required),
    ValidationRule("DUPLICATE_CANONICAL_FIELDS", 1, PayrollValidationCategory.STRUCTURAL,
                   PayrollValidationSeverity.BLOCKING, tuple(CANONICAL_KEYS),
                   "Reject repeated canonical scalar values.", _duplicates),
    ValidationRule("SNAPSHOT_VALUE_TYPES", 1, PayrollValidationCategory.STRUCTURAL,
                   PayrollValidationSeverity.BLOCKING, (),
                   "Verify immutable snapshot typed-value storage.", _types),
    ValidationRule("EMPLOYEE_IDENTITY", 1, PayrollValidationCategory.IDENTITY,
                   PayrollValidationSeverity.BLOCKING, ("employee_identifier",),
                   "Resolve employee only inside the snapshot organization.", _identity),
    ValidationRule("PERIOD_VALIDITY", 1, PayrollValidationCategory.PERIOD,
                   PayrollValidationSeverity.BLOCKING, ("period_year", "period_month"),
                   "Validate structural year and month bounds.", _period),
    ValidationRule("EXISTING_PAYROLL_PERIOD", 1, PayrollValidationCategory.DUPLICATE_CONTEXT,
                   PayrollValidationSeverity.WARNING,
                   ("employee_identifier", "period_year", "period_month"),
                   "Warn when a current payroll already exists.", _existing_payroll),
    ValidationRule("NET_PAY_RECONCILIATION", 1, PayrollValidationCategory.ARITHMETIC,
                   PayrollValidationSeverity.ERROR,
                   ("total_earnings", "total_deductions", "net_pay"),
                   "Compare net pay with earnings less deductions using exact Decimal arithmetic.", _net_pay),
    ValidationRule("TOTAL_EARNINGS_DETAIL_RECONCILIATION", 1, PayrollValidationCategory.ARITHMETIC,
                   PayrollValidationSeverity.INFO, ("total_earnings",),
                   "Compare earning detail when reviewed rows exist.",
                   _not_applicable("Earning-detail reconciliation is unavailable because reviewed table rows are not staged.")),
    ValidationRule("TOTAL_DEDUCTIONS_DETAIL_RECONCILIATION", 1, PayrollValidationCategory.ARITHMETIC,
                   PayrollValidationSeverity.INFO, ("total_deductions",),
                   "Compare deduction detail when reviewed rows exist.",
                   _not_applicable("Deduction-detail reconciliation is unavailable because reviewed table rows are not staged.")),
    ValidationRule("TAX_RECONCILIATION", 1, PayrollValidationCategory.TAX_RECONCILIATION,
                   PayrollValidationSeverity.INFO,
                   ("employee_identifier", "period_year", "period_month", "income_tax_base", "income_tax"),
                   "Compare tax values only through a side-effect-free reference calculator.",
                   _not_applicable("Tax, cumulative tax, stamp-tax, and SGK reconciliation are deferred because current calculation entry points persist ledger records.")),
)


def execute_rules(context: ValidationContext) -> list[ValidationFinding]:
    return [finding for rule in VALIDATION_RULES for finding in rule.validator(context, rule)]


__all__ = [
    "RULESET_VERSION", "VALIDATION_RULES", "ValidationContext", "ValidationFinding",
    "ValidationRule", "execute_rules",
]
