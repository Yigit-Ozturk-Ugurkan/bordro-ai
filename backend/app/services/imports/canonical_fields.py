"""Bordro-owned registry of scalar payroll concepts understood by the domain."""

from dataclasses import dataclass

from app.models.enums import PayrollCanonicalValueType


@dataclass(frozen=True, slots=True)
class CanonicalFieldDefinition:
    canonical_key: str
    section_key: str
    value_type: PayrollCanonicalValueType
    required_for_future_materialization: bool
    target: str
    financial: bool
    automatic_mapping_allowed: bool


_DEFINITIONS = (
    CanonicalFieldDefinition("employee_identifier", "IDENTITY", PayrollCanonicalValueType.IDENTIFIER, True, "Employee.employee_no", False, True),
    CanonicalFieldDefinition("period_year", "PERIOD", PayrollCanonicalValueType.INTEGER, True, "Payroll.period_year", False, True),
    CanonicalFieldDefinition("period_month", "PERIOD", PayrollCanonicalValueType.INTEGER, True, "Payroll.period_month", False, True),
    CanonicalFieldDefinition("gross_earnings", "EARNINGS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.gross_earnings", True, True),
    CanonicalFieldDefinition("sgk_base", "BASES", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.sgk_base", True, True),
    CanonicalFieldDefinition("income_tax_base", "BASES", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.income_tax_base", True, True),
    CanonicalFieldDefinition("stamp_tax_base", "BASES", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.stamp_tax_base", True, True),
    CanonicalFieldDefinition("employee_sgk", "DEDUCTIONS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.employee_sgk", True, True),
    CanonicalFieldDefinition("employee_unemployment", "DEDUCTIONS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.employee_unemployment", True, True),
    CanonicalFieldDefinition("income_tax", "DEDUCTIONS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.income_tax", True, True),
    CanonicalFieldDefinition("stamp_tax", "DEDUCTIONS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.stamp_tax", True, True),
    CanonicalFieldDefinition("total_earnings", "TOTALS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.total_earnings", True, True),
    CanonicalFieldDefinition("total_deductions", "TOTALS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.total_deductions", True, True),
    CanonicalFieldDefinition("net_pay", "TOTALS", PayrollCanonicalValueType.DECIMAL, True, "PayrollVersion.net_pay", True, True),
    CanonicalFieldDefinition("paid_days", "ATTENDANCE", PayrollCanonicalValueType.DAY_COUNT, True, "PayrollVersion.paid_days", False, True),
    CanonicalFieldDefinition("missing_days", "ATTENDANCE", PayrollCanonicalValueType.DAY_COUNT, True, "PayrollVersion.missing_days", False, True),
    CanonicalFieldDefinition("cumulative_income_tax_base", "TAX_CONTEXT", PayrollCanonicalValueType.DECIMAL, False, "TaxCumulativeRecord.closing_cumulative_base", True, True),
)

CANONICAL_FIELDS = {definition.canonical_key: definition for definition in _DEFINITIONS}
CANONICAL_KEYS = tuple(CANONICAL_FIELDS)
REQUIRED_CANONICAL_FIELDS = tuple(
    definition for definition in _DEFINITIONS
    if definition.required_for_future_materialization
)


def get_canonical_field(canonical_key: str) -> CanonicalFieldDefinition:
    try:
        return CANONICAL_FIELDS[canonical_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported canonical payroll key: {canonical_key}") from exc


__all__ = [
    "CANONICAL_FIELDS", "CANONICAL_KEYS", "REQUIRED_CANONICAL_FIELDS",
    "CanonicalFieldDefinition", "get_canonical_field",
]
