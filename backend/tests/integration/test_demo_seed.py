"""
Demo seed integration tests.

The demo seed backs the API integration tests, so a silent regression here
would quietly weaken those. These tests assert three things:

1. The seed runs at all. The previous revision referenced a
   ``PayrollVersionStatus.PUBLISHED`` member that does not exist, so every
   call raised AttributeError.
2. It is genuinely idempotent - a second run creates nothing.
3. The data it produces is internally balanced (lines sum to totals) and
   contains the scenarios the MVP needs.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.enums import PayrollVersionStatus
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_detail import (
    PayrollAbsence,
    PayrollDeduction,
    PayrollEarning,
)
from app.models.tax import TaxCumulativeRecord
from app.seeds import demo_payroll_seed
from app.seeds.demo_payroll_seed import (
    DEMO_EMPLOYEE_NO,
    DEMO_ORG_CODE,
    DEMO_PERIODS,
    DEMO_TAX_YEAR,
    seed_demo_payroll,
)
from app.seeds.tax_2026_seed import seed_tax_2026


@pytest.fixture()
def seeded(db_session: Session) -> Session:
    """A session with tax rules and demo payroll data loaded."""
    seed_tax_2026(db_session)
    seed_demo_payroll(db_session)
    return db_session


def _counts(session: Session) -> dict[str, int]:
    """Row counts for every table the demo seed writes to."""
    return {
        "organizations": session.execute(
            select(func.count()).select_from(Organization)
        ).scalar_one(),
        "employees": session.execute(
            select(func.count()).select_from(Employee)
        ).scalar_one(),
        "payrolls": session.execute(
            select(func.count()).select_from(Payroll)
        ).scalar_one(),
        "versions": session.execute(
            select(func.count()).select_from(PayrollVersion)
        ).scalar_one(),
        "earnings": session.execute(
            select(func.count()).select_from(PayrollEarning)
        ).scalar_one(),
        "deductions": session.execute(
            select(func.count()).select_from(PayrollDeduction)
        ).scalar_one(),
        "absences": session.execute(
            select(func.count()).select_from(PayrollAbsence)
        ).scalar_one(),
        "cumulative": session.execute(
            select(func.count()).select_from(TaxCumulativeRecord)
        ).scalar_one(),
    }


class TestDemoSeedRuns:
    """The seed produces the data the MVP needs."""

    def test_seed_returns_org_employee_and_versions(self, db_session: Session) -> None:
        """A first run returns all three pieces, not a partial tuple."""
        seed_tax_2026(db_session)
        org, employee, versions = seed_demo_payroll(db_session)

        assert org.code == DEMO_ORG_CODE
        assert employee is not None
        assert employee.employee_no == DEMO_EMPLOYEE_NO
        assert len(versions) == len(DEMO_PERIODS)

    def test_versions_use_a_real_enum_status(self, seeded: Session) -> None:
        """Every seeded revision carries a valid PayrollVersionStatus."""
        versions = seeded.execute(select(PayrollVersion)).scalars().all()

        assert versions
        for version in versions:
            assert version.status in set(PayrollVersionStatus)

    def test_versions_are_flagged_current(self, seeded: Session) -> None:
        """Each period has exactly one revision flagged current."""
        employee = seeded.execute(
            select(Employee).where(Employee.employee_no == DEMO_EMPLOYEE_NO)
        ).scalar_one()

        for period in DEMO_PERIODS:
            payroll = seeded.execute(
                select(Payroll).where(
                    Payroll.employee_id == employee.id,
                    Payroll.period_year == DEMO_TAX_YEAR,
                    Payroll.period_month == period["month"],
                )
            ).scalar_one()

            current = [v for v in payroll.versions if v.is_current]
            assert len(current) == 1

    def test_requires_tax_rule_set(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Without the required tax rule set the seed fails loudly.

        A silent skip here would produce demo payrolls with no tax
        context, and the tax endpoints would then report an empty position
        that looks like real data.

        The guard is exercised by pointing the seed at a version that does
        not exist, rather than by deleting the real rule set. Deleting it
        would be unsound: other rows (tax_calculation_runs) carry a
        NOT NULL reference to it, so the delete outcome would depend on
        what else happens to be in the development database.
        """
        monkeypatch.setattr(
            demo_payroll_seed, "DEMO_RULE_SET_VERSION", "TR_PAYROLL_NONEXISTENT_V0"
        )

        with pytest.raises(RuntimeError, match="TR_PAYROLL_NONEXISTENT_V0"):
            seed_demo_payroll(db_session)


class TestDemoSeedIdempotency:
    """Running the seed twice must not duplicate anything."""

    def test_second_run_creates_nothing(self, seeded: Session) -> None:
        """Row counts are identical before and after a second run."""
        before = _counts(seeded)

        seed_demo_payroll(seeded)

        assert _counts(seeded) == before

    def test_second_run_returns_the_same_rows(self, seeded: Session) -> None:
        """The second run returns the same org, employee and versions."""
        org_a, employee_a, versions_a = seed_demo_payroll(seeded)
        org_b, employee_b, versions_b = seed_demo_payroll(seeded)

        assert org_a.id == org_b.id
        assert employee_a.id == employee_b.id
        assert [v.id for v in versions_a] == [v.id for v in versions_b]

    def test_tax_seed_is_idempotent(self, seeded: Session) -> None:
        """A second tax seed run creates no additional rule set."""
        result = seed_tax_2026(seeded)

        assert result["rule_set"] == 0
        assert result["brackets"] == 0
        assert result["parameters"] == 0


class TestDemoSeedDataIntegrity:
    """The seeded figures must be internally consistent."""

    def test_earning_lines_sum_to_gross(self, seeded: Session) -> None:
        """Each revision's earning lines add up to its gross earnings."""
        for period in DEMO_PERIODS:
            version = self._version_for(seeded, period["month"])
            total = sum(e.amount for e in version.earnings)

            assert total == period["gross"]
            assert total == version.gross_earnings

    def test_deduction_lines_sum_to_total_deductions(self, seeded: Session) -> None:
        """Each revision's deduction lines add up to its deductions total."""
        for period in DEMO_PERIODS:
            version = self._version_for(seeded, period["month"])
            total = sum(d.amount for d in version.deductions)

            assert total == period["total_deductions"]
            assert total == version.total_deductions

    def test_net_equals_gross_minus_deductions(self, seeded: Session) -> None:
        """Net pay reconciles with gross and total deductions."""
        for period in DEMO_PERIODS:
            version = self._version_for(seeded, period["month"])

            assert version.net_pay == (
                version.gross_earnings - version.total_deductions
            )

    def test_absence_scenario_exists(self, seeded: Session) -> None:
        """February carries an unpaid absence matching its missing days."""
        version = self._version_for(seeded, 2)

        assert len(version.absences) == 1
        absence = version.absences[0]
        assert absence.is_paid is False
        assert absence.day_count == version.missing_days
        # Negative gross_effect means the absence reduced gross earnings.
        assert absence.gross_effect < Decimal("0.00")

    def test_earning_codes_differ_between_months(self, seeded: Session) -> None:
        """
        The two months do not share an identical code set.

        Per-code comparison logic is only meaningfully exercised when a
        code appears in one month and not the other.
        """
        jan = {e.code for e in self._version_for(seeded, 1).earnings}
        feb = {e.code for e in self._version_for(seeded, 2).earnings}

        assert jan != feb
        assert feb - jan, "February should introduce at least one new code"

    def test_cumulative_ledger_is_chained(self, seeded: Session) -> None:
        """
        The ledger follows opening + monthly = closing, month over month.

        January opens at zero (year reset) and February opens where
        January closed.
        """
        records = (
            seeded.execute(
                select(TaxCumulativeRecord)
                .where(TaxCumulativeRecord.tax_year == DEMO_TAX_YEAR)
                .order_by(TaxCumulativeRecord.period_month)
            )
            .scalars()
            .all()
        )

        assert len(records) == len(DEMO_PERIODS)

        previous_closing = Decimal("0.00")
        for record in records:
            assert record.opening_cumulative_base == previous_closing
            assert record.closing_cumulative_base == (
                record.opening_cumulative_base + record.monthly_taxable_base
            )
            previous_closing = record.closing_cumulative_base

        assert records[0].opening_cumulative_base == Decimal("0.00")

    def test_cumulative_bases_match_payroll_tax_bases(self, seeded: Session) -> None:
        """Each ledger month's taxable base equals the payroll's tax base."""
        for period in DEMO_PERIODS:
            record = seeded.execute(
                select(TaxCumulativeRecord).where(
                    TaxCumulativeRecord.tax_year == DEMO_TAX_YEAR,
                    TaxCumulativeRecord.period_month == period["month"],
                )
            ).scalar_one()

            assert record.monthly_taxable_base == period["income_tax_base"]

    @staticmethod
    def _version_for(session: Session, month: int) -> PayrollVersion:
        """Fetch the demo revision for a month."""
        return session.execute(
            select(PayrollVersion)
            .join(Payroll, PayrollVersion.payroll_id == Payroll.id)
            .join(Employee, Payroll.employee_id == Employee.id)
            .where(
                Employee.employee_no == DEMO_EMPLOYEE_NO,
                Payroll.period_year == DEMO_TAX_YEAR,
                Payroll.period_month == month,
            )
        ).scalar_one()
