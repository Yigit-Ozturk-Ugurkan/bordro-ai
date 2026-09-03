"""
API Integration Tests for the read-only payroll endpoints (V1).

Recreated after the previous handoff deleted the original file rather than
fixing the failures it exposed. These tests drive the real ASGI app over
HTTP against real database rows, so they cover the whole chain:

    route -> service -> repository -> PostgreSQL

Covered here:
    GET /health
    GET /health/db
    GET /api/v1/system/info
    GET /api/v1/employees/{id}/payrolls
    GET /api/v1/employees/{id}/payrolls/{year}/{month}
    GET /api/v1/employees/{id}/payrolls/{year}/{month}/comparison
    GET /api/v1/employees/{id}/tax-status
    GET /api/v1/employees/{id}/dashboard/{year}/{month}

Money assertions compare ``Decimal`` values parsed from the response
strings. Nothing is compared as float, and no expected value is copied
back out of a response - every figure is derived from the demo seed
definition or from the 2026 bracket table.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.seeds.demo_payroll_seed import DEMO_PERIODS

# The demo periods, keyed by month, so expectations are stated in terms of
# the seed definition rather than transcribed constants.
JANUARY = next(p for p in DEMO_PERIODS if p["month"] == 1)
FEBRUARY = next(p for p in DEMO_PERIODS if p["month"] == 2)

# 2026 employment brackets (from tax_2026_seed): bracket 1 covers
# [0, 190000) at 15%, bracket 2 covers [190000, 400000) at 20%, bracket 3
# covers [400000, 1500000) at 27%.
BRACKET_1_UPPER = Decimal("190000.00")
BRACKET_2_UPPER = Decimal("400000.00")
BRACKET_1_RATE = Decimal("0.15")
BRACKET_2_RATE = Decimal("0.20")
BRACKET_3_RATE = Decimal("0.27")


def money(value) -> Decimal:
    """Parse a money field from a response body into a Decimal."""
    assert value is not None, "expected a money value, got null"
    return Decimal(str(value))


class TestSystemEndpoints:
    """Health and service metadata."""

    async def test_health(self, api_client: AsyncClient) -> None:
        """The liveness probe reports ok."""
        response = await api_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_health_db(self, api_client: AsyncClient) -> None:
        """
        The database probe actually reaches PostgreSQL.

        This is the endpoint that fails outright when the async driver
        cannot run on the host event loop, so it is a real regression
        guard rather than a formality.
        """
        response = await api_client.get("/health/db")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}

    async def test_system_info(self, api_client: AsyncClient) -> None:
        """System info exposes the configured app identity."""
        response = await api_client.get("/api/v1/system/info")

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"name", "environment", "version"}
        assert body["name"]
        assert body["version"]


class TestPayrollListAPI:
    """GET /api/v1/employees/{id}/payrolls"""

    async def test_lists_all_periods_newest_first(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Both seeded periods are returned, newest period first."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls"
        )

        assert response.status_code == 200
        body = response.json()

        assert body["employee_id"] == str(demo_employee_id)
        assert body["count"] == len(DEMO_PERIODS)
        assert [(p["year"], p["month"]) for p in body["periods"]] == [
            (2026, 2),
            (2026, 1),
        ]

    async def test_period_entries_carry_current_revision(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Each period resolves to its flagged-current revision."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls"
        )
        periods = {p["month"]: p for p in response.json()["periods"]}

        for period in DEMO_PERIODS:
            entry = periods[period["month"]]
            assert entry["payroll_version_id"] is not None
            assert entry["revision_no"] == 1
            assert entry["is_current"] is True
            assert money(entry["gross_earnings"]) == period["gross"]
            assert money(entry["net_pay"]) == period["net_pay"]

    async def test_unknown_employee_returns_404(
        self, seeded_api_client: AsyncClient
    ) -> None:
        """An employee that does not exist is a 404, not an empty list."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{uuid4()}/payrolls"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_malformed_employee_id_returns_422(
        self, api_client: AsyncClient
    ) -> None:
        """A non-UUID employee id fails path validation."""
        response = await api_client.get("/api/v1/employees/not-a-uuid/payrolls")

        assert response.status_code == 422


class TestPayrollDetailAPI:
    """GET /api/v1/employees/{id}/payrolls/{year}/{month}"""

    async def test_january_detail(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """January detail reports period, revision, gross and net."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1"
        )

        assert response.status_code == 200
        body = response.json()

        assert body["year"] == 2026
        assert body["month"] == 1
        assert body["employee_id"] == str(demo_employee_id)

        revision = body["revision"]
        assert revision["revision_no"] == 1
        assert revision["is_current"] is True
        assert revision["currency"] == "TRY"

        assert money(body["gross"]) == JANUARY["gross"]
        assert money(body["net"]) == JANUARY["net_pay"]

    async def test_detail_earnings_breakdown_matches_seed(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Every seeded earning line appears, and the lines sum to gross."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1"
        )
        earnings = response.json()["earnings"]

        by_code = {item["code"]: money(item["amount"]) for item in earnings["items"]}
        expected = {code: amount for code, _, _, amount in JANUARY["earnings"]}

        assert by_code == expected
        assert sum(by_code.values()) == JANUARY["gross"]
        assert money(earnings["total"]) == JANUARY["gross"]

    async def test_detail_deductions_breakdown_matches_seed(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Every seeded deduction line appears and the lines sum to the total."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1"
        )
        deductions = response.json()["deductions"]

        by_code = {item["code"]: money(item["amount"]) for item in deductions["items"]}
        expected = {
            code: amount for code, _, _, amount, _ in JANUARY["deductions"]
        }

        assert by_code == expected
        assert sum(by_code.values()) == JANUARY["total_deductions"]
        assert money(deductions["total"]) == JANUARY["total_deductions"]

    async def test_detail_reports_missing_days_and_absences(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """February carries 2 missing days backed by an absence record."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2"
        )
        attendance = response.json()["attendance"]

        assert money(attendance["paid_days"]) == FEBRUARY["paid_days"]
        assert money(attendance["missing_days"]) == FEBRUARY["missing_days"]

        assert len(attendance["absences"]) == len(FEBRUARY["absences"])
        absence = attendance["absences"][0]
        reason, _, day_count, is_paid, gross_effect = FEBRUARY["absences"][0]
        assert absence["reason_code"] == reason
        assert money(absence["day_count"]) == day_count
        assert absence["is_paid"] is is_paid
        assert money(absence["gross_effect"]) == gross_effect

        # The absence day count must agree with the revision's missing_days.
        assert money(absence["day_count"]) == money(attendance["missing_days"])

    async def test_detail_january_has_no_absences(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """A clean month reports zero missing days and no absence rows."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1"
        )
        attendance = response.json()["attendance"]

        assert money(attendance["missing_days"]) == Decimal("0.00")
        assert attendance["absences"] == []

    async def test_unknown_period_returns_404(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """A period with no payroll is a 404 carrying a domain message."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/7"
        )

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "2026-07" in detail

    async def test_unknown_employee_returns_404(
        self, seeded_api_client: AsyncClient
    ) -> None:
        """An unknown employee is a 404 on the detail route too."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{uuid4()}/payrolls/2026/1"
        )

        assert response.status_code == 404

    async def test_out_of_range_month_returns_422(
        self, api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Month 13 is rejected by path validation."""
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/13"
        )

        assert response.status_code == 422


class TestPayrollComparisonAPI:
    """GET /api/v1/employees/{id}/payrolls/{year}/{month}/comparison"""

    async def test_february_net_comparison(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Net previous/current/delta and percentage delta are all reported."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2/comparison"
        )

        assert response.status_code == 200
        net = response.json()["net"]

        expected_delta = FEBRUARY["net_pay"] - JANUARY["net_pay"]
        expected_percent = (
            expected_delta / JANUARY["net_pay"] * Decimal("100")
        ).quantize(Decimal("0.01"))

        assert money(net["previous"]) == JANUARY["net_pay"]
        assert money(net["current"]) == FEBRUARY["net_pay"]
        assert money(net["delta"]) == expected_delta
        assert money(net["delta_percent"]) == expected_percent

    async def test_february_earnings_and_deductions_deltas(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Earnings and deductions totals carry deltas and percentages."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2/comparison"
        )
        body = response.json()

        earnings = body["earnings"]
        assert money(earnings["previous"]) == JANUARY["gross"]
        assert money(earnings["current"]) == FEBRUARY["gross"]
        assert money(earnings["delta"]) == FEBRUARY["gross"] - JANUARY["gross"]

        deductions = body["deductions"]
        assert money(deductions["previous"]) == JANUARY["total_deductions"]
        assert money(deductions["current"]) == FEBRUARY["total_deductions"]
        assert (
            money(deductions["delta"])
            == FEBRUARY["total_deductions"] - JANUARY["total_deductions"]
        )

    async def test_missing_days_delta(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """The two February absence days show up as a missing-days delta."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2/comparison"
        )
        attendance = response.json()["attendance"]

        assert money(attendance["previous_missing_days"]) == JANUARY["missing_days"]
        assert money(attendance["current_missing_days"]) == FEBRUARY["missing_days"]
        assert (
            money(attendance["missing_days_delta"])
            == FEBRUARY["missing_days"] - JANUARY["missing_days"]
        )

    async def test_earning_code_level_deltas(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        Per-code earning deltas cover the union of both months' codes.

        BASE_SALARY falls (unpaid days) while BONUS appears only in
        February; both must be visible, and a code absent from one month
        must report 0.00 on that side rather than being dropped.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2/comparison"
        )
        by_code = response.json()["earnings"]["by_code"]

        jan = {code: amount for code, _, _, amount in JANUARY["earnings"]}
        feb = {code: amount for code, _, _, amount in FEBRUARY["earnings"]}

        assert set(by_code) == set(jan) | set(feb)

        for code in by_code:
            expected_prev = jan.get(code, Decimal("0.00"))
            expected_curr = feb.get(code, Decimal("0.00"))
            entry = by_code[code]
            assert money(entry["previous"]) == expected_prev
            assert money(entry["current"]) == expected_curr
            assert money(entry["delta"]) == expected_curr - expected_prev

        # The bonus exists only in February, so it must be a pure addition.
        assert money(by_code["BONUS"]["previous"]) == Decimal("0.00")
        assert money(by_code["BONUS"]["delta"]) == feb["BONUS"]

        # Base salary genuinely decreased.
        assert money(by_code["BASE_SALARY"]["delta"]) < Decimal("0.00")

        # Per-code deltas must reconcile to the reported earnings delta.
        assert sum(money(v["delta"]) for v in by_code.values()) == (
            FEBRUARY["gross"] - JANUARY["gross"]
        )

    async def test_deduction_code_level_deltas(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Per-code deduction deltas reconcile to the deductions delta."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2/comparison"
        )
        by_code = response.json()["deductions"]["by_code"]

        jan = {code: amount for code, _, _, amount, _ in JANUARY["deductions"]}
        feb = {code: amount for code, _, _, amount, _ in FEBRUARY["deductions"]}

        assert set(by_code) == set(jan) | set(feb)

        for code, entry in by_code.items():
            assert money(entry["previous"]) == jan.get(code, Decimal("0.00"))
            assert money(entry["current"]) == feb.get(code, Decimal("0.00"))

        assert sum(money(v["delta"]) for v in by_code.values()) == (
            FEBRUARY["total_deductions"] - JANUARY["total_deductions"]
        )

    async def test_comparison_makes_no_causal_claims(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        The payload is factual only.

        Comparison must not ship explanatory prose; attributing a net
        change to a cause needs a counterfactual engine that does not
        exist. Guard the contract so no future change smuggles one in.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2/comparison"
        )
        body = response.json()

        forbidden = {"reason", "reasons", "explanation", "cause", "causes", "because"}
        assert not (forbidden & set(body))
        for section in ("net", "earnings", "deductions", "attendance"):
            assert not (forbidden & set(body[section]))

    async def test_january_comparison_returns_400(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        January has no predecessor, so the request is a 400.

        Month 1 is a legal path value, so this must not surface as a 422
        validation error, and must not be a 500.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/1/comparison"
        )

        assert response.status_code == 400
        assert "january" in response.json()["detail"].lower()

    async def test_comparison_missing_previous_month_returns_404(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """A month whose predecessor has no payroll is a 404."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/payrolls/2026/5/comparison"
        )

        assert response.status_code == 404

    async def test_comparison_unknown_employee_returns_404(
        self, seeded_api_client: AsyncClient
    ) -> None:
        """An unknown employee is a 404 on the comparison route."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{uuid4()}/payrolls/2026/2/comparison"
        )

        assert response.status_code == 404


class TestTaxStatusAPI:
    """GET /api/v1/employees/{id}/tax-status"""

    async def test_january_tax_position(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        After January the employee sits in bracket 1.

        Cumulative base equals January's taxable base, and the distance to
        bracket 2 is the remaining room below its lower limit.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/tax-status",
            params={"year": 2026, "month": 1},
        )

        assert response.status_code == 200
        body = response.json()

        assert body["tax_year"] == 2026
        assert body["period_month"] == 1
        assert money(body["monthly_taxable_base"]) == JANUARY["income_tax_base"]
        assert money(body["cumulative_taxable_base"]) == JANUARY["income_tax_base"]

        current = body["current_bracket"]
        assert money(current["lower_limit"]) == Decimal("0.00")
        assert money(current["upper_limit"]) == BRACKET_1_UPPER
        assert money(current["rate"]) == BRACKET_1_RATE

        next_bracket = body["next_bracket"]
        assert money(next_bracket["lower_limit"]) == BRACKET_1_UPPER
        assert money(next_bracket["rate"]) == BRACKET_2_RATE

        assert money(body["distance_to_next_bracket"]) == (
            BRACKET_1_UPPER - JANUARY["income_tax_base"]
        )

    async def test_february_crosses_into_second_bracket(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        The cumulative base after February pushes into bracket 2.

        This is the behaviour that makes cumulative tracking worth having:
        the same monthly salary lands in a different bracket once the
        year-to-date base has accumulated.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/tax-status",
            params={"year": 2026, "month": 2},
        )

        assert response.status_code == 200
        body = response.json()

        expected_cumulative = (
            JANUARY["income_tax_base"] + FEBRUARY["income_tax_base"]
        )
        assert money(body["cumulative_taxable_base"]) == expected_cumulative
        assert money(body["monthly_taxable_base"]) == FEBRUARY["income_tax_base"]

        current = body["current_bracket"]
        assert money(current["lower_limit"]) == BRACKET_1_UPPER
        assert money(current["rate"]) == BRACKET_2_RATE

        assert money(body["next_bracket"]["rate"]) == BRACKET_3_RATE
        assert money(body["distance_to_next_bracket"]) == (
            BRACKET_2_UPPER - expected_cumulative
        )

    async def test_reports_rule_set_version(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """The rule set version is reported for audit traceability."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/tax-status",
            params={"year": 2026, "month": 1},
        )

        assert response.json()["rule_set_version"] == "TR_PAYROLL_2026_V1"

    async def test_defaults_to_latest_recorded_month(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """Without a month, the latest recorded month is reported."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/tax-status",
            params={"year": 2026},
        )

        assert response.status_code == 200
        assert response.json()["period_month"] == 2

    async def test_unpublished_tax_year_returns_404_and_leaves_history_intact(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        Asking about 2027 is a 404, and it does not disturb 2026.

        The seeded rule set covers [2026-01-01, 2027-01-01), so no rules
        are published for 2027 yet. Reporting a bracket position with no
        applicable rule set would be inventing tax law, so the endpoint
        refuses rather than defaulting to the previous year's brackets.

        The second half of this test is the part that matters for the
        annual ledger: querying a later year must not consume or rewrite
        the earlier year's records. (The reset arithmetic itself is
        covered by test_cumulative_tax_service.test_year_reset_on_new_year.)
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/tax-status",
            params={"year": 2027},
        )

        assert response.status_code == 404
        assert "rule set" in response.json()["detail"].lower()

        # 2026 must still report its accumulated position, unchanged.
        still_there = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/tax-status",
            params={"year": 2026, "month": 2},
        )
        assert still_there.status_code == 200
        assert money(still_there.json()["cumulative_taxable_base"]) == (
            JANUARY["income_tax_base"] + FEBRUARY["income_tax_base"]
        )

    async def test_unknown_employee_returns_404(
        self, seeded_api_client: AsyncClient
    ) -> None:
        """An unknown employee is a 404, not a fabricated zero position."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{uuid4()}/tax-status",
            params={"year": 2026},
        )

        assert response.status_code == 404


class TestPayrollDashboardAPI:
    """GET /api/v1/employees/{id}/dashboard/{year}/{month}"""

    async def test_dashboard_has_all_required_sections(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """The dashboard exposes every section the MVP contract requires."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/1"
        )

        assert response.status_code == 200
        body = response.json()

        for section in (
            "period",
            "salary",
            "attendance",
            "earnings",
            "deductions",
            "tax",
        ):
            assert section in body, f"dashboard missing section: {section}"

    async def test_dashboard_january(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """January's period, salary and attendance match the seeded payroll."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/1"
        )
        body = response.json()

        assert body["employee_id"] == str(demo_employee_id)
        assert body["period"] == {"year": 2026, "month": 1}

        salary = body["salary"]
        assert money(salary["gross"]) == JANUARY["gross"]
        assert money(salary["net"]) == JANUARY["net_pay"]
        # January has no predecessor, so these are genuinely absent.
        assert salary["previous_net"] is None
        assert salary["net_delta"] is None

        attendance = body["attendance"]
        assert money(attendance["paid_days"]) == JANUARY["paid_days"]
        assert money(attendance["missing_days"]) == JANUARY["missing_days"]

    async def test_dashboard_february_reports_previous_net_and_delta(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """February carries January's net and the delta between them."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
        )
        salary = response.json()["salary"]

        assert money(salary["gross"]) == FEBRUARY["gross"]
        assert money(salary["net"]) == FEBRUARY["net_pay"]
        assert money(salary["previous_net"]) == JANUARY["net_pay"]
        assert money(salary["net_delta"]) == (
            FEBRUARY["net_pay"] - JANUARY["net_pay"]
        )

    async def test_dashboard_reports_net_delta_percent(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """February reports the percentage change in net salary."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
        )
        salary = response.json()["salary"]

        expected = (
            (FEBRUARY["net_pay"] - JANUARY["net_pay"])
            / JANUARY["net_pay"]
            * Decimal("100")
        ).quantize(Decimal("0.01"))

        assert money(salary["net_delta_percent"]) == expected

    async def test_dashboard_january_has_no_delta_percent(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """With no previous month, the percentage is absent, not zero."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/1"
        )

        assert response.json()["salary"]["net_delta_percent"] is None

    async def test_dashboard_exposes_full_bracket_objects(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        The tax section carries whole brackets, not just their rates.

        Limits come from the seeded TaxBracket rows, so a legislative
        change is a data change and this assertion tracks it.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
        )
        tax = response.json()["tax"]

        current = tax["current_bracket"]
        assert money(current["lower_limit"]) == BRACKET_1_UPPER
        assert money(current["upper_limit"]) == BRACKET_2_UPPER
        assert money(current["rate"]) == BRACKET_2_RATE

        next_bracket = tax["next_bracket"]
        assert money(next_bracket["lower_limit"]) == BRACKET_2_UPPER
        assert money(next_bracket["rate"]) == BRACKET_3_RATE

        # The scalar rate fields must agree with the bracket objects.
        assert money(tax["current_bracket_rate"]) == money(current["rate"])
        assert money(tax["next_bracket_rate"]) == money(next_bracket["rate"])

    async def test_dashboard_breakdowns_come_from_detail_rows(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        Earnings and deductions breakdowns are the real detail lines.

        An earlier implementation synthesised a single "GROSS" line here,
        which disagreed with the stored PayrollEarning rows. The breakdown
        must be the stored lines and must sum to the reported total.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
        )
        body = response.json()

        earnings = {
            item["code"]: money(item["amount"])
            for item in body["earnings"]["items"]
        }
        assert earnings == {
            code: amount for code, _, _, amount in FEBRUARY["earnings"]
        }
        assert sum(earnings.values()) == money(body["earnings"]["total"])

        deductions = {
            item["code"]: money(item["amount"])
            for item in body["deductions"]["items"]
        }
        assert deductions == {
            code: amount for code, _, _, amount, _ in FEBRUARY["deductions"]
        }
        assert sum(deductions.values()) == money(body["deductions"]["total"])

    async def test_dashboard_tax_section_agrees_with_tax_status(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        The dashboard's tax figures match the tax-status endpoint exactly.

        Both read the same service, so any divergence would mean a second
        competing source of truth had appeared.
        """
        dashboard = (
            await seeded_api_client.get(
                f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
            )
        ).json()["tax"]
        status = (
            await seeded_api_client.get(
                f"/api/v1/employees/{demo_employee_id}/tax-status",
                params={"year": 2026, "month": 2},
            )
        ).json()

        assert money(dashboard["cumulative_tax_base"]) == money(
            status["cumulative_taxable_base"]
        )
        assert money(dashboard["monthly_taxable_base"]) == money(
            status["monthly_taxable_base"]
        )
        assert money(dashboard["current_bracket_rate"]) == money(
            status["current_bracket"]["rate"]
        )
        assert money(dashboard["next_bracket_rate"]) == money(
            status["next_bracket"]["rate"]
        )
        assert money(dashboard["distance_to_next_bracket"]) == money(
            status["distance_to_next_bracket"]
        )
        assert dashboard["rule_set_version"] == status["rule_set_version"]

    async def test_dashboard_income_tax_matches_payroll_record(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """The month's income tax equals the stored payroll withholding."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
        )

        assert money(response.json()["tax"]["income_tax"]) == FEBRUARY["income_tax"]

    async def test_dashboard_agrees_with_payroll_detail(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """
        Dashboard and payroll-detail report the same underlying revision.

        They are separate endpoints over the same repository, so their
        shared figures must not drift apart.
        """
        dashboard = (
            await seeded_api_client.get(
                f"/api/v1/employees/{demo_employee_id}/dashboard/2026/2"
            )
        ).json()
        detail = (
            await seeded_api_client.get(
                f"/api/v1/employees/{demo_employee_id}/payrolls/2026/2"
            )
        ).json()

        assert money(dashboard["salary"]["gross"]) == money(detail["gross"])
        assert money(dashboard["salary"]["net"]) == money(detail["net"])
        assert money(dashboard["earnings"]["total"]) == money(
            detail["earnings"]["total"]
        )
        assert money(dashboard["deductions"]["total"]) == money(
            detail["deductions"]["total"]
        )
        assert money(dashboard["attendance"]["missing_days"]) == money(
            detail["attendance"]["missing_days"]
        )

    async def test_dashboard_unknown_period_returns_404(
        self, seeded_api_client: AsyncClient, demo_employee_id: UUID
    ) -> None:
        """A period with no payroll is a 404 with a domain message."""
        response = await seeded_api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/9"
        )

        assert response.status_code == 404
        assert "2026-09" in response.json()["detail"]

    async def test_dashboard_unknown_employee_returns_404(
        self, seeded_api_client: AsyncClient
    ) -> None:
        """
        An unknown employee is a 404.

        This is the exact case the deleted test asserted and the old
        implementation answered with a 500.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{uuid4()}/dashboard/2026/1"
        )

        assert response.status_code == 404

    async def test_errors_do_not_leak_database_internals(
        self, seeded_api_client: AsyncClient
    ) -> None:
        """
        Error bodies carry a domain message, not driver or SQL text.

        A 404 must not expose table names, SQL, or psycopg/SQLAlchemy
        exception text to a caller.
        """
        response = await seeded_api_client.get(
            f"/api/v1/employees/{uuid4()}/dashboard/2026/1"
        )

        assert response.status_code == 404
        detail = response.json()["detail"].lower()
        for leak in ("select", "psycopg", "sqlalchemy", "traceback", "payroll_versions"):
            assert leak not in detail

    @pytest.mark.parametrize("month", [0, 13, 99])
    async def test_invalid_month_returns_422(
        self, api_client: AsyncClient, demo_employee_id: UUID, month: int
    ) -> None:
        """Out-of-range months are rejected by path validation."""
        response = await api_client.get(
            f"/api/v1/employees/{demo_employee_id}/dashboard/2026/{month}"
        )

        assert response.status_code == 422
