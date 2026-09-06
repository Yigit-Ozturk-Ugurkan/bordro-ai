"""
Domain exceptions for the Bordro AI backend.

These are raised by the service layer and translated to HTTP responses by
a single exception handler registered on the FastAPI app. Routes therefore
never build error payloads themselves, and raw database/driver exceptions
are never rendered into a response body.
"""


class BordroError(Exception):
    """Base class for all domain errors."""

    status_code: int = 500
    default_message: str = "Internal error"
    code: str | None = None

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class NotFoundError(BordroError):
    """A requested resource does not exist."""

    status_code = 404
    default_message = "Resource not found"


class AuthorizationDeniedError(BordroError):
    """An authenticated principal lacks permission for the resource."""

    status_code = 403
    default_message = "Not authorized to access this employee"


class EmployeeNotFoundError(NotFoundError):
    """The employee does not exist."""

    default_message = "Employee not found"

    def __init__(self, employee_id: object) -> None:
        super().__init__(f"Employee {employee_id} not found")


class PayrollNotFoundError(NotFoundError):
    """No payroll exists for the requested employee/period."""

    default_message = "Payroll not found"

    def __init__(self, employee_id: object, year: int, month: int) -> None:
        super().__init__(
            f"No payroll found for employee {employee_id} "
            f"in period {year}-{month:02d}"
        )


class ComparisonNotAvailableError(BordroError):
    """
    A comparison was requested for a period that has no comparable
    predecessor (for example January, which has no previous month inside
    the same tax year).
    """

    status_code = 400
    default_message = "Comparison not available for this period"


class TaxRuleSetNotFoundError(NotFoundError):
    """No active tax rule set covers the requested period."""

    default_message = "Tax rule set not found"


class DocumentUploadError(BordroError):
    status_code = 400
    code = "INVALID_DOCUMENT_UPLOAD"
    default_message = "The document upload is invalid"


class DocumentTooLargeError(DocumentUploadError):
    status_code = 413
    code = "DOCUMENT_TOO_LARGE"
    default_message = "The document exceeds the configured upload limit"


class UnsupportedDocumentTypeError(DocumentUploadError):
    status_code = 415
    code = "UNSUPPORTED_DOCUMENT_TYPE"
    default_message = "The document type is not supported"


class DuplicateDocumentError(BordroError):
    status_code = 409
    code = "DUPLICATE_DOCUMENT"
    default_message = "This document has already been imported"


class PayrollImportNotFoundError(NotFoundError):
    code = "IMPORT_NOT_FOUND"
    default_message = "Payroll import not found"


class PayrollImportStateConflictError(BordroError):
    status_code = 409
    code = "IMPORT_STATE_CONFLICT"
    default_message = "The payroll import cannot transition from its current state"


class GeneralReaderUnavailableError(BordroError):
    status_code = 503
    code = "GENERAL_READER_UNAVAILABLE"
    default_message = "The document extraction service is unavailable"


class GeneralReaderRejectedError(BordroError):
    status_code = 502
    code = "GENERAL_READER_REJECTED"
    default_message = "The document extraction service rejected the document"


class GeneralReaderContractInvalidError(BordroError):
    status_code = 502
    code = "GENERAL_READER_CONTRACT_INVALID"
    default_message = "The document extraction response is invalid"


class ImportProcessingFailedError(BordroError):
    status_code = 500
    code = "IMPORT_PROCESSING_FAILED"
    default_message = "The payroll import could not be processed"


class PayrollImportMappingConflictError(BordroError):
    status_code = 409
    code = "IMPORT_MAPPING_CONFLICT"
    default_message = "The payroll import is not ready for canonical mapping"


class PayrollMappingConfigurationError(BordroError):
    status_code = 500
    code = "MAPPING_CONFIGURATION_INVALID"
    default_message = "Payroll field mapping configuration is invalid"


class PayrollReviewNotFoundError(NotFoundError):
    code = "REVIEW_NOT_FOUND"
    default_message = "Payroll import review not found"


class PayrollReviewStateConflictError(BordroError):
    status_code = 409
    code = "REVIEW_STATE_CONFLICT"
    default_message = "The payroll import is not ready for review"


class PayrollReviewVersionConflictError(BordroError):
    status_code = 409
    code = "REVIEW_VERSION_CONFLICT"
    default_message = "The payroll import review has changed"


class PayrollReviewFieldNotFoundError(NotFoundError):
    code = "REVIEW_FIELD_NOT_FOUND"
    default_message = "Payroll import review field not found"


class InvalidCanonicalOverrideError(BordroError):
    status_code = 422
    code = "INVALID_CANONICAL_OVERRIDE"
    default_message = "The canonical payroll field override is invalid"


class InvalidReviewValueError(BordroError):
    status_code = 422
    code = "INVALID_REVIEW_VALUE"
    default_message = "The corrected payroll field value is invalid"


class CorrectionStaleError(BordroError):
    status_code = 409
    code = "CORRECTION_STALE"
    default_message = "The correction no longer matches the adapter output"


class PayrollReviewIncompleteError(BordroError):
    status_code = 409
    code = "REVIEW_INCOMPLETE"
    default_message = "The payroll import review is incomplete"


class PayrollReviewSnapshotNotFoundError(NotFoundError):
    code = "SNAPSHOT_NOT_FOUND"
    default_message = "Payroll import review snapshot not found"


class PayrollValidationRunNotFoundError(NotFoundError):
    code = "VALIDATION_RUN_NOT_FOUND"
    default_message = "Payroll import validation run not found"


class PayrollValidationRulesetUnsupportedError(BordroError):
    status_code = 422
    code = "VALIDATION_RULESET_UNSUPPORTED"
    default_message = "Payroll validation ruleset is not supported"
