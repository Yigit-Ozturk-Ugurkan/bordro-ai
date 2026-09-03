"""
Tax service: rule resolution and query infrastructure.

This service provides the data-access layer for tax rules and parameters.
It does NOT perform salary/tax calculations — that will be a separate
calculation engine in a future phase.

All queries use sync SQLAlchemy sessions (matching the project's test
and Alembic pattern on Windows). The FastAPI layer will use async
sessions; an async wrapper can be added when API endpoints are built.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tax import (
    PayrollParameter,
    TaxBracket,
    TaxRuleSet,
)


class TaxService:
    """
    Service for resolving and querying tax rules and payroll parameters.

    Methods:
    - get_rule_set_by_version: exact lookup by version string
    - resolve_rule_set: find the active rule set for a jurisdiction/date
    - get_tax_brackets: retrieve sorted brackets for a rule set
    - get_parameter: resolve a single parameter value for a date
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_rule_set_by_version(self, version: str) -> TaxRuleSet | None:
        """
        Look up a TaxRuleSet by its unique version string.

        Args:
            version: e.g., 'TR_PAYROLL_2026_V1'

        Returns:
            TaxRuleSet or None if not found.
        """
        stmt = select(TaxRuleSet).where(TaxRuleSet.version == version)
        return self._session.execute(stmt).scalar_one_or_none()

    def resolve_rule_set(
        self,
        target_date: date,
        jurisdiction: str,
        *,
        status: str = "ACTIVE",
    ) -> TaxRuleSet | None:
        """
        Find the rule set that is effective on target_date for the given
        jurisdiction and status.

        Uses [effective_from, effective_to) semantics:
        - effective_from <= target_date
        - effective_to IS NULL OR effective_to > target_date

        If multiple rule sets match (shouldn't happen with proper data),
        returns the one with the latest effective_from.

        Args:
            target_date: the date to resolve against
            jurisdiction: e.g., 'TR'
            status: rule set status filter (default: 'ACTIVE')

        Returns:
            TaxRuleSet or None.
        """
        stmt = (
            select(TaxRuleSet)
            .where(
                TaxRuleSet.jurisdiction == jurisdiction,
                TaxRuleSet.status == status,
                TaxRuleSet.effective_from <= target_date,
            )
            .where(
                (TaxRuleSet.effective_to.is_(None))
                | (TaxRuleSet.effective_to > target_date)
            )
            .order_by(TaxRuleSet.effective_from.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_tax_brackets(
        self,
        rule_set_id: "str | object",
        income_type: str,
        target_date: date | None = None,
    ) -> list[TaxBracket]:
        """
        Retrieve tax brackets for a rule set and income type, ordered by
        sort_order.

        If target_date is provided, filters brackets by effective date range.
        If not provided, returns all brackets for the rule set/income_type.

        Args:
            rule_set_id: UUID of the rule set
            income_type: e.g., 'EMPLOYMENT'
            target_date: optional date filter

        Returns:
            List of TaxBracket ordered by sort_order.
        """
        stmt = (
            select(TaxBracket)
            .where(
                TaxBracket.rule_set_id == rule_set_id,
                TaxBracket.income_type == income_type,
            )
            .order_by(TaxBracket.sort_order)
        )

        if target_date is not None:
            stmt = stmt.where(
                TaxBracket.effective_from <= target_date,
                (TaxBracket.effective_to.is_(None))
                | (TaxBracket.effective_to > target_date),
            )

        return list(self._session.execute(stmt).scalars().all())

    def get_parameter(
        self,
        rule_set_id: "str | object",
        key: str,
        target_date: date,
    ) -> PayrollParameter | None:
        """
        Resolve a single payroll parameter value effective on target_date.

        Uses [effective_from, effective_to) semantics.
        If multiple parameters match (shouldn't happen), returns the one
        with the latest effective_from.

        Args:
            rule_set_id: UUID of the rule set
            key: parameter key, e.g., 'MINIMUM_GROSS_WAGE'
            target_date: the date to resolve against

        Returns:
            PayrollParameter or None.
        """
        stmt = (
            select(PayrollParameter)
            .where(
                PayrollParameter.rule_set_id == rule_set_id,
                PayrollParameter.parameter_key == key,
                PayrollParameter.effective_from <= target_date,
            )
            .where(
                (PayrollParameter.effective_to.is_(None))
                | (PayrollParameter.effective_to > target_date)
            )
            .order_by(PayrollParameter.effective_from.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_parameter_decimal(
        self,
        rule_set_id: "str | object",
        key: str,
        target_date: date,
    ) -> Decimal | None:
        """
        Convenience method: resolve a parameter and return its decimal_value.

        Returns None if the parameter is not found or has no decimal_value.
        """
        param = self.get_parameter(rule_set_id, key, target_date)
        if param is None:
            return None
        return param.decimal_value
