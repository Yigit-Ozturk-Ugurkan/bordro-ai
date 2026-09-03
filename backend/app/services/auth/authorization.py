"""Testable RBAC and tenant-isolation policy for payroll resources."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationDeniedError, EmployeeNotFoundError
from app.models.employee import Employee
from app.models.enums import UserRoleType
from app.services.auth.authentication import AuthenticatedUser


class PayrollAuthorizationPolicy:
    """Explicit policy for employee-scoped payroll reads and future writes."""

    ORGANIZATION_READ_ROLES = frozenset(
        {
            UserRoleType.HR_ADMIN,
            UserRoleType.PAYROLL_ADMIN,
            UserRoleType.AUDITOR,
        }
    )

    def require_employee_read(
        self, session: Session, user: AuthenticatedUser, employee_id: UUID
    ) -> Employee:
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise EmployeeNotFoundError(employee_id)

        same_organization = employee.organization_id == user.organization_id
        owns_resource = (
            UserRoleType.EMPLOYEE in user.roles
            and user.employee_id == employee.id
            and same_organization
        )
        scoped_reader = bool(user.roles & self.ORGANIZATION_READ_ROLES)

        if owns_resource or (scoped_reader and same_organization):
            return employee
        raise AuthorizationDeniedError()

    @staticmethod
    def can_write_payroll(
        user: AuthenticatedUser, employee_organization_id: UUID
    ) -> bool:
        """Future write policy: auditors/HR/employees/system admins are excluded."""
        return (
            UserRoleType.PAYROLL_ADMIN in user.roles
            and user.organization_id == employee_organization_id
        )
