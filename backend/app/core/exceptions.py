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


class PayrollImportTableNotFoundError(NotFoundError):
    code = "IMPORT_TABLE_NOT_FOUND"
    default_message = "Payroll import table not found"


class PayrollDetailStateConflictError(BordroError):
    status_code = 409
    code = "DETAIL_STATE_CONFLICT"
    default_message = "Payroll detail evidence conflicts with this operation"


class PayrollDetailNotReadyError(BordroError):
    status_code = 422
    code = "DETAIL_NOT_READY"
    default_message = "Payroll detail review is not ready"


class PayrollDetailNotFoundError(NotFoundError):
    code = "DETAIL_NOT_FOUND"
    default_message = "Payroll detail evidence not found"


class PayrollDetailIntegrityError(BordroError):
    status_code = 409
    code = "DETAIL_INTEGRITY_FAILED"
    default_message = "Payroll detail evidence failed integrity verification"


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


class PayrollApprovalNotFoundError(NotFoundError):
    code = "APPROVAL_NOT_FOUND"
    default_message = "Payroll import approval not found"


class PayrollApprovalValidationRequiredError(BordroError):
    status_code = 409
    code = "APPROVAL_VALIDATION_REQUIRED"
    default_message = "A validation run is required before an approval decision"


class PayrollApprovalValidationNotCompletedError(BordroError):
    status_code = 409
    code = "APPROVAL_VALIDATION_NOT_COMPLETED"
    default_message = "The validation run is not completed"


class PayrollApprovalValidationNotReadyError(BordroError):
    status_code = 409
    code = "APPROVAL_VALIDATION_NOT_READY"
    default_message = "The validation run is not ready for approval"


class PayrollApprovalWarningsUnacknowledgedError(BordroError):
    status_code = 409
    code = "APPROVAL_WARNINGS_UNACKNOWLEDGED"
    default_message = "All validation warnings must be acknowledged before approval"


class PayrollApprovalAlreadyDecidedError(BordroError):
    status_code = 409
    code = "APPROVAL_ALREADY_DECIDED"
    default_message = "This validation run already has a terminal approval decision"


class PayrollApprovalStateConflictError(BordroError):
    status_code = 409
    code = "APPROVAL_STATE_CONFLICT"
    default_message = "The payroll approval state conflicts with this operation"


class InvalidWarningAcknowledgementError(BordroError):
    status_code = 422
    code = "INVALID_WARNING_ACKNOWLEDGEMENT"
    default_message = "Only a warning from the exact validation run can be acknowledged"


class WarningAlreadyAcknowledgedError(BordroError):
    status_code = 409
    code = "WARNING_ALREADY_ACKNOWLEDGED"
    default_message = "This validation warning is already acknowledged"


class PayrollApprovalContextStaleError(BordroError):
    status_code = 409
    code = "APPROVAL_CONTEXT_STALE"
    default_message = "The immutable snapshot and validation evidence do not match"


class PayrollMaterializationNotApprovedError(BordroError):
    status_code = 409
    code = "MATERIALIZATION_NOT_APPROVED"
    default_message = "An exact current approved decision is required for materialization"


class PayrollMaterializationContextStaleError(BordroError):
    status_code = 409
    code = "MATERIALIZATION_CONTEXT_STALE"
    default_message = "The approved evidence is no longer the current materialization context"


class PayrollMaterializationIdentityInvalidError(BordroError):
    status_code = 422
    code = "MATERIALIZATION_IDENTITY_INVALID"
    default_message = "The approved employee identity does not resolve exactly"


class PayrollMaterializationPeriodInvalidError(BordroError):
    status_code = 422
    code = "MATERIALIZATION_PERIOD_INVALID"
    default_message = "The approved payroll period is invalid"


class PayrollMaterializationRequiredFieldMissingError(BordroError):
    status_code = 422
    code = "MATERIALIZATION_REQUIRED_FIELD_MISSING"
    default_message = "A required authoritative snapshot field is missing"


class PayrollMaterializationFieldTypeInvalidError(BordroError):
    status_code = 422
    code = "MATERIALIZATION_FIELD_TYPE_INVALID"
    default_message = "An authoritative snapshot field has an invalid type or precision"


class PayrollMaterializationStateConflictError(BordroError):
    status_code = 409
    code = "MATERIALIZATION_STATE_CONFLICT"
    default_message = "The authoritative payroll state conflicts with materialization"


class PayrollMaterializationIntegrityFailedError(BordroError):
    status_code = 409
    code = "MATERIALIZATION_INTEGRITY_FAILED"
    default_message = "The approved materialization evidence failed integrity verification"


class TaxSyncNotMaterializedError(BordroError):
    status_code = 409
    code = "TAX_SYNC_NOT_MATERIALIZED"
    default_message = "An authoritative payroll materialization is required for tax sync"


class TaxSyncVersionNotCurrentError(BordroError):
    status_code = 409
    code = "TAX_SYNC_VERSION_NOT_CURRENT"
    default_message = "Only the active current payroll revision can start a tax sync"


class TaxSyncRuleSetNotFoundError(BordroError):
    status_code = 409
    code = "TAX_SYNC_RULESET_NOT_FOUND"
    default_message = "No deterministic tax rule set covers the payroll period"


class TaxSyncPriorPeriodRequiredError(BordroError):
    status_code = 409
    code = "TAX_SYNC_PRIOR_PERIOD_REQUIRED"
    default_message = "An earlier authoritative payroll period must be tax-synchronized first"


class TaxSyncDownstreamRebuildRequiredError(BordroError):
    status_code = 409
    code = "TAX_SYNC_DOWNSTREAM_REBUILD_REQUIRED"
    default_message = "Later synchronized periods require an explicit downstream rebuild"


class TaxSyncReconciliationFailedError(BordroError):
    status_code = 409
    code = "TAX_SYNC_RECONCILIATION_FAILED"
    default_message = "Calculated withholding does not match the authoritative payroll"


class TaxSyncContextStaleError(BordroError):
    status_code = 409
    code = "TAX_SYNC_CONTEXT_STALE"
    default_message = "The payroll tax synchronization context is stale"


class TaxSyncIntegrityFailedError(BordroError):
    status_code = 409
    code = "TAX_SYNC_INTEGRITY_FAILED"
    default_message = "Payroll tax synchronization integrity verification failed"


class TaxSyncStateConflictError(BordroError):
    status_code = 409
    code = "TAX_SYNC_STATE_CONFLICT"
    default_message = "The payroll tax ledger conflicts with this synchronization"


class TaxRebuildNotFoundError(NotFoundError):
    code = "TAX_REBUILD_NOT_FOUND"
    default_message = "Tax rebuild plan not found"


class TaxRebuildNotRequiredError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_NOT_REQUIRED"
    default_message = "No downstream cumulative-tax rebuild is required"


class TaxRebuildPlanStaleError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_PLAN_STALE"
    default_message = "The persisted tax rebuild plan no longer matches authoritative state"


class TaxRebuildAlreadyCompletedError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_ALREADY_COMPLETED"
    default_message = "The tax rebuild plan is already completed"


class TaxRebuildAlreadyRunningError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_ALREADY_RUNNING"
    default_message = "The tax rebuild plan is already running"


class TaxRebuildPriorContextRequiredError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_PRIOR_CONTEXT_REQUIRED"
    default_message = "The rebuild requires an exact current prior-period tax context"


class TaxRebuildReconciliationFailedError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_RECONCILIATION_FAILED"
    default_message = "A rebuilt period does not reconcile with authoritative payroll"


class TaxRebuildRuleSetNotFoundError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_RULESET_NOT_FOUND"
    default_message = "No deterministic tax rule set covers a rebuilt period"


class TaxRebuildStateConflictError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_STATE_CONFLICT"
    default_message = "The tax rebuild state conflicts with this operation"


class TaxRebuildIntegrityFailedError(BordroError):
    status_code = 409
    code = "TAX_REBUILD_INTEGRITY_FAILED"
    default_message = "Tax rebuild evidence failed integrity verification"
