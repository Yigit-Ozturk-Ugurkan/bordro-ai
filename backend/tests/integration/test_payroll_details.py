"""
Integration tests for payroll detail models: PayrollEarning,
PayrollDeduction, PayrollAbsence.

Tests cover:
- Database CHECK constraint enforcement
- FK CASCADE delete behavior
- Relationship loading
- Valid data acceptance
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.payroll import PayrollVersion
from app.models.payroll_detail import (
    PayrollAbsence,
    PayrollDeduction,
    PayrollEarning,
)


# ===================================================================
# Helper factory functions
# ===================================================================


def _make_earning(
    payroll_version_id: uuid.UUID,
    *,
    code: str = "BASE_SALARY",
    label: str = "Temel Maaş",
    category: str = "SALARY",
    amount: Decimal = Decimal("15000.00"),
    sgk_subject_amount: Decimal = Decimal("15000.00"),
    income_tax_subject_amount: Decimal = Decimal("12900.00"),
    stamp_tax_subject_amount: Decimal = Decimal("15000.00"),
    quantity: Decimal | None = None,
    unit_amount: Decimal | None = None,
) -> PayrollEarning:
    return PayrollEarning(
        id=uuid.uuid4(),
        payroll_version_id=payroll_version_id,
        code=code,
        label=label,
        category=category,
        quantity=quantity,
        unit_amount=unit_amount,
        amount=amount,
        sgk_subject_amount=sgk_subject_amount,
        income_tax_subject_amount=income_tax_subject_amount,
        stamp_tax_subject_amount=stamp_tax_subject_amount,
    )


def _make_deduction(
    payroll_version_id: uuid.UUID,
    *,
    code: str = "SGK_EMPLOYEE",
    label: str = "SGK İşçi Payı",
    category: str = "SOCIAL_SECURITY",
    amount: Decimal = Decimal("2100.00"),
    base_amount: Decimal | None = Decimal("15000.00"),
    rate: Decimal | None = Decimal("0.140000"),
    is_statutory: bool = True,
    is_sensitive: bool = False,
) -> PayrollDeduction:
    return PayrollDeduction(
        id=uuid.uuid4(),
        payroll_version_id=payroll_version_id,
        code=code,
        label=label,
        category=category,
        amount=amount,
        base_amount=base_amount,
        rate=rate,
        is_statutory=is_statutory,
        is_sensitive=is_sensitive,
    )


def _make_absence(
    payroll_version_id: uuid.UUID,
    *,
    reason_code: str = "SICK_LEAVE",
    description: str | None = "Hastalık izni",
    day_count: Decimal = Decimal("2.00"),
    is_paid: bool = False,
    gross_effect: Decimal | None = Decimal("-1000.00"),
) -> PayrollAbsence:
    return PayrollAbsence(
        id=uuid.uuid4(),
        payroll_version_id=payroll_version_id,
        reason_code=reason_code,
        description=description,
        day_count=day_count,
        is_paid=is_paid,
        gross_effect=gross_effect,
    )


# ===================================================================
# PayrollEarning constraint tests
# ===================================================================


class TestPayrollEarningConstraints:
    """Test CHECK constraints on payroll_earnings table."""

    def test_negative_amount_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """amount < 0 should violate ck_payroll_earning_amount_non_negative."""
        earning = _make_earning(
            sample_payroll_version.id,
            amount=Decimal("-100.00"),
        )
        db_session.add(earning)
        with pytest.raises(IntegrityError, match="ck_payroll_earning_amount_non_negative"):
            db_session.flush()

    def test_negative_sgk_subject_amount_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """sgk_subject_amount < 0 should be rejected."""
        earning = _make_earning(
            sample_payroll_version.id,
            sgk_subject_amount=Decimal("-1.00"),
        )
        db_session.add(earning)
        with pytest.raises(IntegrityError, match="ck_payroll_earning_sgk_subject_non_negative"):
            db_session.flush()

    def test_negative_income_tax_subject_amount_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """income_tax_subject_amount < 0 should be rejected."""
        earning = _make_earning(
            sample_payroll_version.id,
            income_tax_subject_amount=Decimal("-0.01"),
        )
        db_session.add(earning)
        with pytest.raises(IntegrityError, match="ck_payroll_earning_income_tax_subject_non_negative"):
            db_session.flush()

    def test_negative_stamp_tax_subject_amount_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """stamp_tax_subject_amount < 0 should be rejected."""
        earning = _make_earning(
            sample_payroll_version.id,
            stamp_tax_subject_amount=Decimal("-500.00"),
        )
        db_session.add(earning)
        with pytest.raises(IntegrityError, match="ck_payroll_earning_stamp_tax_subject_non_negative"):
            db_session.flush()

    def test_valid_earning_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """A valid earning with all non-negative amounts should be persisted."""
        earning = _make_earning(sample_payroll_version.id)
        db_session.add(earning)
        db_session.flush()

        loaded = db_session.get(PayrollEarning, earning.id)
        assert loaded is not None
        assert loaded.code == "BASE_SALARY"
        assert loaded.amount == Decimal("15000.00")

    def test_zero_amount_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """amount = 0 should be valid (e.g. informational earning line)."""
        earning = _make_earning(
            sample_payroll_version.id,
            amount=Decimal("0.00"),
            sgk_subject_amount=Decimal("0.00"),
            income_tax_subject_amount=Decimal("0.00"),
            stamp_tax_subject_amount=Decimal("0.00"),
        )
        db_session.add(earning)
        db_session.flush()
        assert earning.amount == Decimal("0.00")


# ===================================================================
# PayrollDeduction constraint tests
# ===================================================================


class TestPayrollDeductionConstraints:
    """Test CHECK constraints on payroll_deductions table."""

    def test_negative_amount_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """amount < 0 should violate ck_payroll_deduction_amount_non_negative."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            amount=Decimal("-50.00"),
        )
        db_session.add(deduction)
        with pytest.raises(IntegrityError, match="ck_payroll_deduction_amount_non_negative"):
            db_session.flush()

    def test_negative_base_amount_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """base_amount < 0 should violate ck_payroll_deduction_base_amount_non_negative."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            base_amount=Decimal("-1000.00"),
        )
        db_session.add(deduction)
        with pytest.raises(IntegrityError, match="ck_payroll_deduction_base_amount_non_negative"):
            db_session.flush()

    def test_rate_below_zero_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """rate < 0 should violate ck_payroll_deduction_rate_valid_range."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            rate=Decimal("-0.010000"),
        )
        db_session.add(deduction)
        with pytest.raises(IntegrityError, match="ck_payroll_deduction_rate_valid_range"):
            db_session.flush()

    def test_rate_above_one_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """rate > 1 should violate ck_payroll_deduction_rate_valid_range."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            rate=Decimal("1.000001"),
        )
        db_session.add(deduction)
        with pytest.raises(IntegrityError, match="ck_payroll_deduction_rate_valid_range"):
            db_session.flush()

    def test_rate_exactly_one_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """rate = 1.000000 should be valid (100% deduction)."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            rate=Decimal("1.000000"),
        )
        db_session.add(deduction)
        db_session.flush()
        assert deduction.rate == Decimal("1.000000")

    def test_null_rate_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """NULL rate should be valid (e.g., fixed-amount deduction)."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            rate=None,
            base_amount=None,
        )
        db_session.add(deduction)
        db_session.flush()
        assert deduction.rate is None

    def test_null_base_amount_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """NULL base_amount should be valid."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            base_amount=None,
        )
        db_session.add(deduction)
        db_session.flush()
        assert deduction.base_amount is None

    def test_valid_deduction_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """Valid deduction should be persisted."""
        deduction = _make_deduction(sample_payroll_version.id)
        db_session.add(deduction)
        db_session.flush()

        loaded = db_session.get(PayrollDeduction, deduction.id)
        assert loaded is not None
        assert loaded.code == "SGK_EMPLOYEE"
        assert loaded.is_statutory is True
        assert loaded.is_sensitive is False

    def test_sensitive_deduction_flag(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """is_sensitive=True should be persisted (for future RBAC/AI filtering)."""
        deduction = _make_deduction(
            sample_payroll_version.id,
            code="GARNISHMENT",
            label="İcra Kesintisi",
            category="LEGAL",
            is_sensitive=True,
        )
        db_session.add(deduction)
        db_session.flush()
        assert deduction.is_sensitive is True


# ===================================================================
# PayrollAbsence constraint tests
# ===================================================================


class TestPayrollAbsenceConstraints:
    """Test CHECK constraints on payroll_absences table."""

    def test_zero_day_count_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """day_count = 0 should violate ck_payroll_absence_day_count_positive."""
        absence = _make_absence(
            sample_payroll_version.id,
            day_count=Decimal("0.00"),
        )
        db_session.add(absence)
        with pytest.raises(IntegrityError, match="ck_payroll_absence_day_count_positive"):
            db_session.flush()

    def test_negative_day_count_rejected(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """day_count < 0 should violate ck_payroll_absence_day_count_positive."""
        absence = _make_absence(
            sample_payroll_version.id,
            day_count=Decimal("-1.00"),
        )
        db_session.add(absence)
        with pytest.raises(IntegrityError, match="ck_payroll_absence_day_count_positive"):
            db_session.flush()

    def test_valid_day_count_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """Positive day_count should be accepted."""
        absence = _make_absence(
            sample_payroll_version.id,
            day_count=Decimal("3.50"),
        )
        db_session.add(absence)
        db_session.flush()

        loaded = db_session.get(PayrollAbsence, absence.id)
        assert loaded is not None
        assert loaded.day_count == Decimal("3.50")
        assert loaded.reason_code == "SICK_LEAVE"

    def test_half_day_absence_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """day_count = 0.50 (half day) should be accepted."""
        absence = _make_absence(
            sample_payroll_version.id,
            day_count=Decimal("0.50"),
        )
        db_session.add(absence)
        db_session.flush()
        assert absence.day_count == Decimal("0.50")

    def test_negative_gross_effect_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """Negative gross_effect is the standard convention (reduces gross)."""
        absence = _make_absence(
            sample_payroll_version.id,
            gross_effect=Decimal("-1200.00"),
        )
        db_session.add(absence)
        db_session.flush()
        assert absence.gross_effect == Decimal("-1200.00")

    def test_null_gross_effect_accepted(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """NULL gross_effect is valid (financial impact not yet calculated)."""
        absence = _make_absence(
            sample_payroll_version.id,
            gross_effect=None,
        )
        db_session.add(absence)
        db_session.flush()
        assert absence.gross_effect is None

    def test_paid_absence_with_zero_effect(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """Paid leave: is_paid=True, gross_effect=0 (no salary reduction)."""
        absence = _make_absence(
            sample_payroll_version.id,
            reason_code="ANNUAL_LEAVE",
            description="Yıllık izin",
            is_paid=True,
            gross_effect=Decimal("0.00"),
        )
        db_session.add(absence)
        db_session.flush()
        assert absence.is_paid is True
        assert absence.gross_effect == Decimal("0.00")


# ===================================================================
# Relationship tests
# ===================================================================


class TestPayrollVersionRelationships:
    """Test that PayrollVersion correctly loads related detail records."""

    def test_relationships_populated(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """
        Add 2 earnings, 2 deductions, 1 absence to a PayrollVersion
        and verify relationships load correctly.
        """
        version_id = sample_payroll_version.id

        # 2 earnings
        e1 = _make_earning(version_id, code="BASE_SALARY", label="Temel Maaş")
        e2 = _make_earning(
            version_id,
            code="OVERTIME",
            label="Fazla Mesai",
            amount=Decimal("2500.00"),
            sgk_subject_amount=Decimal("2500.00"),
            income_tax_subject_amount=Decimal("2500.00"),
            stamp_tax_subject_amount=Decimal("2500.00"),
        )

        # 2 deductions
        d1 = _make_deduction(version_id, code="SGK_EMPLOYEE", label="SGK İşçi Payı")
        d2 = _make_deduction(
            version_id,
            code="INCOME_TAX",
            label="Gelir Vergisi",
            category="TAX",
            amount=Decimal("1935.00"),
            base_amount=Decimal("12900.00"),
            rate=Decimal("0.150000"),
        )

        # 1 absence
        a1 = _make_absence(version_id)

        db_session.add_all([e1, e2, d1, d2, a1])
        db_session.flush()

        # Expire and reload to test relationship loading
        db_session.expire(sample_payroll_version)

        loaded = db_session.get(PayrollVersion, version_id)
        assert loaded is not None
        assert len(loaded.earnings) == 2
        assert len(loaded.deductions) == 2
        assert len(loaded.absences) == 1

        # Verify content
        earning_codes = {e.code for e in loaded.earnings}
        assert earning_codes == {"BASE_SALARY", "OVERTIME"}

        deduction_codes = {d.code for d in loaded.deductions}
        assert deduction_codes == {"SGK_EMPLOYEE", "INCOME_TAX"}

        assert loaded.absences[0].reason_code == "SICK_LEAVE"

    def test_empty_relationships(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """PayrollVersion with no details should have empty lists."""
        db_session.expire(sample_payroll_version)
        loaded = db_session.get(PayrollVersion, sample_payroll_version.id)
        assert loaded is not None
        assert loaded.earnings == []
        assert loaded.deductions == []
        assert loaded.absences == []


# ===================================================================
# CASCADE delete tests
# ===================================================================


class TestCascadeDelete:
    """
    Test that deleting a PayrollVersion cascades to detail records.

    NOTE: This tests the ON DELETE CASCADE FK behavior. In production,
    published PayrollVersions are treated as immutable at the service
    layer. These tests use draft/test data only.
    """

    def test_delete_version_cascades_to_details(
        self,
        db_session: Session,
        sample_payroll_version: PayrollVersion,
    ) -> None:
        """
        Deleting a PayrollVersion should delete all associated
        earnings, deductions, and absences.
        """
        version_id = sample_payroll_version.id

        # Add detail records
        e1 = _make_earning(version_id, code="BASE_SALARY")
        e2 = _make_earning(version_id, code="BONUS", label="Prim", amount=Decimal("3000.00"))
        d1 = _make_deduction(version_id, code="SGK_EMPLOYEE")
        d2 = _make_deduction(
            version_id,
            code="STAMP_TAX",
            label="Damga Vergisi",
            category="TAX",
            amount=Decimal("113.85"),
            rate=None,
            base_amount=None,
        )
        a1 = _make_absence(version_id)

        db_session.add_all([e1, e2, d1, d2, a1])
        db_session.flush()

        earning_ids = [e1.id, e2.id]
        deduction_ids = [d1.id, d2.id]
        absence_id = a1.id

        # Delete the PayrollVersion
        db_session.delete(sample_payroll_version)
        db_session.flush()

        # Verify all detail records are gone
        for eid in earning_ids:
            assert db_session.get(PayrollEarning, eid) is None
        for did in deduction_ids:
            assert db_session.get(PayrollDeduction, did) is None
        assert db_session.get(PayrollAbsence, absence_id) is None

    def test_delete_version_does_not_affect_other_versions(
        self,
        db_session: Session,
        sample_payroll: "Payroll",
    ) -> None:
        """
        Deleting one PayrollVersion should not affect detail records
        of another PayrollVersion under the same Payroll.
        """
        from app.models.enums import CalculationMode, PayrollSourceType, PayrollVersionStatus

        # Create two versions for the same payroll
        v1 = PayrollVersion(
            id=uuid.uuid4(),
            payroll_id=sample_payroll.id,
            revision_no=1,
            status=PayrollVersionStatus.SUPERSEDED,
            source_type=PayrollSourceType.MANUAL,
            currency="TRY",
            calculation_mode=CalculationMode.IMPORTED,
            is_current=False,
        )
        v2 = PayrollVersion(
            id=uuid.uuid4(),
            payroll_id=sample_payroll.id,
            revision_no=2,
            status=PayrollVersionStatus.DRAFT,
            source_type=PayrollSourceType.MANUAL,
            currency="TRY",
            calculation_mode=CalculationMode.IMPORTED,
            is_current=True,
        )
        db_session.add_all([v1, v2])
        db_session.flush()

        # Add earnings to both versions
        e1 = _make_earning(v1.id, code="BASE_SALARY")
        e2 = _make_earning(v2.id, code="BASE_SALARY")
        db_session.add_all([e1, e2])
        db_session.flush()

        e2_id = e2.id

        # Delete v1 only
        db_session.delete(v1)
        db_session.flush()

        # v2's earning should still exist
        assert db_session.get(PayrollEarning, e1.id) is None
        assert db_session.get(PayrollEarning, e2_id) is not None


# ===================================================================
# Pydantic schema validation tests
# ===================================================================


class TestPayrollEarningSchema:
    """Test Pydantic schema validation for PayrollEarning."""

    def test_negative_amount_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollEarningCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="amount"):
            PayrollEarningCreate(
                code="BASE_SALARY",
                label="Temel Maaş",
                category="SALARY",
                amount=Decimal("-1.00"),
                sgk_subject_amount=Decimal("0.00"),
                income_tax_subject_amount=Decimal("0.00"),
                stamp_tax_subject_amount=Decimal("0.00"),
            )

    def test_negative_subject_amount_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollEarningCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="sgk_subject_amount"):
            PayrollEarningCreate(
                code="BASE_SALARY",
                label="Temel Maaş",
                category="SALARY",
                amount=Decimal("1000.00"),
                sgk_subject_amount=Decimal("-1.00"),
                income_tax_subject_amount=Decimal("0.00"),
                stamp_tax_subject_amount=Decimal("0.00"),
            )

    def test_valid_earning_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollEarningCreate

        schema = PayrollEarningCreate(
            code="BASE_SALARY",
            label="Temel Maaş",
            category="SALARY",
            amount=Decimal("15000.00"),
            sgk_subject_amount=Decimal("15000.00"),
            income_tax_subject_amount=Decimal("12900.00"),
            stamp_tax_subject_amount=Decimal("15000.00"),
        )
        assert schema.amount == Decimal("15000.00")


class TestPayrollDeductionSchema:
    """Test Pydantic schema validation for PayrollDeduction."""

    def test_rate_above_one_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollDeductionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="rate"):
            PayrollDeductionCreate(
                code="SGK_EMPLOYEE",
                label="SGK İşçi Payı",
                category="SOCIAL_SECURITY",
                amount=Decimal("2100.00"),
                rate=Decimal("1.5"),
                is_statutory=True,
            )

    def test_negative_rate_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollDeductionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="rate"):
            PayrollDeductionCreate(
                code="SGK_EMPLOYEE",
                label="SGK İşçi Payı",
                category="SOCIAL_SECURITY",
                amount=Decimal("2100.00"),
                rate=Decimal("-0.1"),
                is_statutory=True,
            )

    def test_negative_amount_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollDeductionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="amount"):
            PayrollDeductionCreate(
                code="SGK_EMPLOYEE",
                label="SGK İşçi Payı",
                category="SOCIAL_SECURITY",
                amount=Decimal("-100.00"),
                is_statutory=True,
            )

    def test_negative_base_amount_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollDeductionCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="base_amount"):
            PayrollDeductionCreate(
                code="SGK_EMPLOYEE",
                label="SGK İşçi Payı",
                category="SOCIAL_SECURITY",
                amount=Decimal("2100.00"),
                base_amount=Decimal("-500.00"),
                is_statutory=True,
            )


class TestPayrollAbsenceSchema:
    """Test Pydantic schema validation for PayrollAbsence."""

    def test_zero_day_count_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollAbsenceCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="day_count"):
            PayrollAbsenceCreate(
                reason_code="SICK_LEAVE",
                day_count=Decimal("0"),
                is_paid=False,
            )

    def test_negative_day_count_rejected_by_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollAbsenceCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="day_count"):
            PayrollAbsenceCreate(
                reason_code="SICK_LEAVE",
                day_count=Decimal("-1"),
                is_paid=False,
            )

    def test_valid_absence_schema(self) -> None:
        from app.schemas.payroll_detail import PayrollAbsenceCreate

        schema = PayrollAbsenceCreate(
            reason_code="SICK_LEAVE",
            description="Hastalık izni",
            day_count=Decimal("2.50"),
            is_paid=False,
            gross_effect=Decimal("-1000.00"),
        )
        assert schema.day_count == Decimal("2.50")
        assert schema.gross_effect == Decimal("-1000.00")
