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
