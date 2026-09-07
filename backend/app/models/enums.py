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
    DOCUMENT = "DOCUMENT"
    API = "API"
    CALCULATED = "CALCULATED"


class CalculationMode(StrEnum):
    IMPORTED = "IMPORTED"
    CALCULATED = "CALCULATED"
    RECONCILED = "RECONCILED"


class PayrollImportStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class PayrollImportFieldReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MISSING = "MISSING"


class PayrollFieldMappingScope(StrEnum):
    SYSTEM = "SYSTEM"
    ORGANIZATION = "ORGANIZATION"
    TEMPLATE = "TEMPLATE"


class PayrollCanonicalValueType(StrEnum):
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    DAY_COUNT = "DAY_COUNT"
    DATE = "DATE"
    TEXT = "TEXT"
    IDENTIFIER = "IDENTIFIER"


class PayrollFieldMappingStatus(StrEnum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"
    AMBIGUOUS = "AMBIGUOUS"
    PARSE_FAILED = "PARSE_FAILED"


class PayrollFieldParseStatus(StrEnum):
    PARSED = "PARSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    FAILED = "FAILED"


class PayrollImportReviewStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_SNAPSHOT = "READY_FOR_SNAPSHOT"
    SNAPSHOTTED = "SNAPSHOTTED"


class PayrollReviewCorrectionAction(StrEnum):
    APPLY = "APPLY"
    REVERT = "REVERT"


class PayrollReviewFieldStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    STALE = "STALE"


class PayrollReviewValueProvenance(StrEnum):
    ADAPTER = "ADAPTER"
    REVIEWER_CORRECTION = "REVIEWER_CORRECTION"


class PayrollValidationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PayrollValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


class PayrollValidationCategory(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    ARITHMETIC = "ARITHMETIC"
    IDENTITY = "IDENTITY"
    PERIOD = "PERIOD"
    TAX_RECONCILIATION = "TAX_RECONCILIATION"
    DUPLICATE_CONTEXT = "DUPLICATE_CONTEXT"


class PayrollValidationReadiness(StrEnum):
    READY_FOR_FUTURE_APPROVAL = "READY_FOR_FUTURE_APPROVAL"
    NOT_READY = "NOT_READY"


class PayrollApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PayrollApprovalStatus(StrEnum):
    NOT_DECIDED = "NOT_DECIDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
