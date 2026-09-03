from enum import StrEnum


class UserRoleType(StrEnum):
    EMPLOYEE = "EMPLOYEE"
    PAYROLL_ADMIN = "PAYROLL_ADMIN"
    HR_ADMIN = "HR_ADMIN"
    AUDITOR = "AUDITOR"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class EmployeeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    TERMINATED = "TERMINATED"


class PayrollVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class PayrollSourceType(StrEnum):
    MANUAL = "MANUAL"
    CSV = "CSV"
    XLSX = "XLSX"
    PDF = "PDF"
    API = "API"
    CALCULATED = "CALCULATED"


class CalculationMode(StrEnum):
    IMPORTED = "IMPORTED"
    CALCULATED = "CALCULATED"
    RECONCILED = "RECONCILED"
