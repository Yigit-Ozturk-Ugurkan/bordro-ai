"""
Demo Payroll Seed V1.

Creates entirely fictitious data for local development and API tests. No
real employee, company, or identifying data appears here.

What it builds:
- Organization DEMO_COMPANY and employee DEMO001
- Fictitious employee, HR, payroll-admin, and auditor login accounts
- January 2026 and February 2026 payrolls, each with a current revision
- Earning and deduction lines for both months, including a code that
  appears in only one month (BONUS) so per-code deltas are exercised
- An unpaid-absence scenario in February (2 missing days)
- Tax cumulative ledger records for both months, so the tax-status and
  dashboard tax sections have a real progressive position to report

Idempotency:
    Every entity is created through a get-or-create keyed on its natural
    key, so running the seed twice creates nothing the second time and
    returns the same rows. This is asserted by
    tests/integration/test_demo_seed.py.

Note on demo withholding figures:
    ``PayrollVersion.income_tax`` here is a simplified round number chosen
    for readable demo output. It is NOT the engine-derived monthly
    withholding implied by the cumulative ledger. The ledger records
    (built through TaxEngine) are the authoritative progressive position;
    the payroll withholding column is illustrative demo input.
"""

import uuid
from datetime import date
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.enums import (
    CalculationMode,
    EmployeeStatus,
    PayrollSourceType,
    PayrollVersionStatus,
    UserRoleType,
)
from app.models.organization import Organization
from app.models.payroll import Payroll, PayrollVersion
from app.models.payroll_detail import (
    PayrollAbsence,
    PayrollDeduction,
    PayrollEarning,
)
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord, TaxRuleSet
from app.models.user import User, UserRole
from app.core.config import get_settings
from app.services.auth.authentication import AuthenticationService
from app.services.taxation.tax_engine import TaxEngine
from app.services.taxation.tax_service import TaxService

DEMO_ORG_CODE = "DEMO_COMPANY"
DEMO_EMPLOYEE_NO = "DEMO001"
DEMO_RULE_SET_VERSION = "TR_PAYROLL_2026_V1"
DEMO_TAX_YEAR = 2026
DEMO_USER_EMAILS = {
    UserRoleType.EMPLOYEE: "employee@demo.local",
    UserRoleType.HR_ADMIN: "hr@demo.local",
    UserRoleType.PAYROLL_ADMIN: "payroll@demo.local",
    UserRoleType.AUDITOR: "auditor@demo.local",
}

# --------------------------------------------------------------------------
# Period definitions
#
# Each month's earning lines sum to gross_earnings and each month's
# deduction lines sum to total_deductions; test_demo_seed.py asserts this,
# so the demo data cannot silently drift out of balance.
# --------------------------------------------------------------------------

DEMO_PERIODS = [
    {
        "month": 1,
        "gross": Decimal("100000.00"),
        "income_tax_base": Decimal("100000.00"),
        "employee_sgk": Decimal("10000.00"),
        "employee_unemployment": Decimal("500.00"),
        "income_tax": Decimal("5000.00"),
        "stamp_tax": Decimal("100.00"),
        "total_deductions": Decimal("15600.00"),
        "net_pay": Decimal("84400.00"),
        "paid_days": Decimal("22.00"),
        "missing_days": Decimal("0.00"),
        "earnings": [
            ("BASE_SALARY", "Temel Maaş", "BASE", Decimal("90000.00")),
            ("MEAL_ALLOWANCE", "Yemek Yardımı", "ALLOWANCE", Decimal("6000.00")),
            ("TRANSPORT_ALLOWANCE", "Yol Yardımı", "ALLOWANCE", Decimal("4000.00")),
        ],
        "deductions": [
            ("SGK_EMPLOYEE", "SGK İşçi Payı", "STATUTORY", Decimal("10000.00"), True),
            ("UNEMPLOYMENT", "İşsizlik Sigortası", "STATUTORY", Decimal("500.00"), True),
            ("INCOME_TAX", "Gelir Vergisi", "TAX", Decimal("5000.00"), True),
            ("STAMP_TAX", "Damga Vergisi", "TAX", Decimal("100.00"), True),
        ],
        "absences": [],
    },
    {
        "month": 2,
        "gross": Decimal("110000.00"),
        "income_tax_base": Decimal("110000.00"),
        "employee_sgk": Decimal("11000.00"),
        "employee_unemployment": Decimal("550.00"),
        "income_tax": Decimal("5500.00"),
        "stamp_tax": Decimal("110.00"),
        "total_deductions": Decimal("17160.00"),
        "net_pay": Decimal("92840.00"),
        "paid_days": Decimal("20.00"),
        "missing_days": Decimal("2.00"),
        "earnings": [
            # Base salary is reduced by the two unpaid days (-6,000.00);
            # a one-off bonus more than offsets it. This makes the
            # per-code comparison genuinely interesting rather than a
            # uniform percentage bump.
            ("BASE_SALARY", "Temel Maaş", "BASE", Decimal("84000.00")),
            ("BONUS", "Prim", "BONUS", Decimal("16000.00")),
            ("MEAL_ALLOWANCE", "Yemek Yardımı", "ALLOWANCE", Decimal("6000.00")),
            ("TRANSPORT_ALLOWANCE", "Yol Yardımı", "ALLOWANCE", Decimal("4000.00")),
        ],
        "deductions": [
            ("SGK_EMPLOYEE", "SGK İşçi Payı", "STATUTORY", Decimal("11000.00"), True),
            ("UNEMPLOYMENT", "İşsizlik Sigortası", "STATUTORY", Decimal("550.00"), True),
            ("INCOME_TAX", "Gelir Vergisi", "TAX", Decimal("5500.00"), True),
            ("STAMP_TAX", "Damga Vergisi", "TAX", Decimal("110.00"), True),
        ],
        "absences": [
            (
                "UNPAID_LEAVE",
                "Ücretsiz izin (2 gün)",
                Decimal("2.00"),
                False,
                Decimal("-6000.00"),
            ),
        ],
    },
]


def seed_demo_payroll(
    db: Session,
) -> tuple[Organization, Employee, list[PayrollVersion]]:
    """
    Create (or return the existing) demo payroll data.

    Returns:
        (organization, employee, payroll_versions) - the same values on
        every run, whether or not this call created anything.

    Raises:
        RuntimeError: if the 2026 tax rule set has not been seeded yet
            (run app.seeds.tax_2026_seed first).
    """
    rule_set = db.execute(
        select(TaxRuleSet).where(TaxRuleSet.version == DEMO_RULE_SET_VERSION)
    ).scalar_one_or_none()
    if rule_set is None:
        raise RuntimeError(
            f"Tax rule set {DEMO_RULE_SET_VERSION} is missing. "
            "Run app.seeds.tax_2026_seed before the demo seed."
        )

    org = _get_or_create_organization(db)
    employee = _get_or_create_employee(db, org)
    _ensure_demo_users(db, org, employee)

    versions: list[PayrollVersion] = []
    for period in DEMO_PERIODS:
        version = _get_or_create_period(db, org, employee, period, rule_set)
        versions.append(version)

    db.flush()
    return org, employee, versions


# --------------------------------------------------------------------------
# Get-or-create helpers
# --------------------------------------------------------------------------


def _get_or_create_organization(db: Session) -> Organization:
    """Fetch or create the demo organization."""
    org = db.execute(
        select(Organization).where(Organization.code == DEMO_ORG_CODE)
    ).scalar_one_or_none()
    if org is not None:
        return org

    org = Organization(
        id=uuid.uuid4(),
        name="Demo Company",
        code=DEMO_ORG_CODE,
        timezone="Europe/Istanbul",
        is_active=True,
    )
    db.add(org)
    db.flush()
    return org


def _get_or_create_employee(db: Session, org: Organization) -> Employee:
    """Fetch or create the demo employee."""
    employee = db.execute(
        select(Employee).where(
            Employee.organization_id == org.id,
            Employee.employee_no == DEMO_EMPLOYEE_NO,
        )
    ).scalar_one_or_none()
    if employee is not None:
        return employee

    employee = Employee(
        id=uuid.uuid4(),
        organization_id=org.id,
        employee_no=DEMO_EMPLOYEE_NO,
        first_name="Demo",
        last_name="Employee",
        status=EmployeeStatus.ACTIVE,
        hire_date=date(2026, 1, 1),
    )
    db.add(employee)
    db.flush()
    return employee


@lru_cache(maxsize=4)
def _demo_password_hashes(password: str) -> dict[UserRoleType, str]:
    """Hash once per process while retaining distinct Argon2 salts per account."""
    return {
        role: AuthenticationService.hash_password(password)
        for role in DEMO_USER_EMAILS
    }


def _ensure_demo_users(
    db: Session, org: Organization, employee: Employee
) -> None:
    """Create idempotent fictitious role accounts and link the employee user."""
    configured_password = get_settings().demo_auth_password
    if configured_password is None:
        raise RuntimeError("DEMO_AUTH_PASSWORD is required to run the demo seed")
    password = configured_password.get_secret_value()
    password_hashes = _demo_password_hashes(password)

    for role, email in DEMO_USER_EMAILS.items():
        user = db.execute(
            select(User).where(
                User.organization_id == org.id,
                User.email == email,
            )
        ).scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                organization_id=org.id,
                email=email,
                password_hash=password_hashes[role],
                is_active=True,
            )
            db.add(user)
            db.flush()

        user_role = db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role == role,
            )
        ).scalar_one_or_none()
        if user_role is None:
            db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role=role))

        if role == UserRoleType.EMPLOYEE:
            if employee.user_id is not None and employee.user_id != user.id:
                raise RuntimeError("Demo employee is linked to an unexpected user")
            employee.user_id = user.id

    db.flush()


def _get_or_create_period(
    db: Session,
    org: Organization,
    employee: Employee,
    period: dict,
    rule_set: TaxRuleSet,
) -> PayrollVersion:
    """Fetch or create one month's payroll, revision, details and ledger."""
    month = period["month"]

    payroll = db.execute(
        select(Payroll).where(
            Payroll.employee_id == employee.id,
            Payroll.period_year == DEMO_TAX_YEAR,
            Payroll.period_month == month,
        )
    ).scalar_one_or_none()

    if payroll is None:
        payroll = Payroll(
            id=uuid.uuid4(),
            organization_id=org.id,
            employee_id=employee.id,
            period_year=DEMO_TAX_YEAR,
            period_month=month,
        )
        db.add(payroll)
        db.flush()

    version = db.execute(
        select(PayrollVersion).where(
            PayrollVersion.payroll_id == payroll.id,
            PayrollVersion.revision_no == 1,
        )
    ).scalar_one_or_none()

    if version is None:
        version = PayrollVersion(
            id=uuid.uuid4(),
            payroll_id=payroll.id,
            revision_no=1,
            # ACTIVE is the published state in PayrollVersionStatus. An
            # earlier revision of this seed used a PUBLISHED member that
            # does not exist on the enum, which made the seed unusable.
            status=PayrollVersionStatus.ACTIVE,
            source_type=PayrollSourceType.MANUAL,
            calculation_mode=CalculationMode.CALCULATED,
            currency="TRY",
            rule_set_id=rule_set.id,
            gross_earnings=period["gross"],
            sgk_base=period["gross"],
            income_tax_base=period["income_tax_base"],
            stamp_tax_base=period["gross"],
            employee_sgk=period["employee_sgk"],
            employee_unemployment=period["employee_unemployment"],
            income_tax=period["income_tax"],
            stamp_tax=period["stamp_tax"],
            total_earnings=period["gross"],
            total_deductions=period["total_deductions"],
            net_pay=period["net_pay"],
            paid_days=period["paid_days"],
            missing_days=period["missing_days"],
            # Flagged current so the repository resolves this revision as
            # authoritative rather than falling back to revision order.
            is_current=True,
        )
        db.add(version)
        db.flush()

    _ensure_earnings(db, version, period["earnings"])
    _ensure_deductions(db, version, period["deductions"])
    _ensure_absences(db, version, period["absences"])
    _ensure_cumulative_record(db, org, employee, version, period, rule_set)

    return version


def _ensure_earnings(db: Session, version: PayrollVersion, rows: list) -> None:
    """Create any missing earning lines for a revision."""
    existing = {
        code
        for code in db.execute(
            select(PayrollEarning.code).where(
                PayrollEarning.payroll_version_id == version.id
            )
        ).scalars()
    }

    for code, label, category, amount in rows:
        if code in existing:
            continue
        db.add(
            PayrollEarning(
                id=uuid.uuid4(),
                payroll_version_id=version.id,
                code=code,
                label=label,
                category=category,
                amount=amount,
                sgk_subject_amount=amount,
                income_tax_subject_amount=amount,
                stamp_tax_subject_amount=amount,
            )
        )
    db.flush()


def _ensure_deductions(db: Session, version: PayrollVersion, rows: list) -> None:
    """Create any missing deduction lines for a revision."""
    existing = {
        code
        for code in db.execute(
            select(PayrollDeduction.code).where(
                PayrollDeduction.payroll_version_id == version.id
            )
        ).scalars()
    }

    for code, label, category, amount, is_statutory in rows:
        if code in existing:
            continue
        db.add(
            PayrollDeduction(
                id=uuid.uuid4(),
                payroll_version_id=version.id,
                code=code,
                label=label,
                category=category,
                amount=amount,
                is_statutory=is_statutory,
                is_sensitive=False,
            )
        )
    db.flush()


def _ensure_absences(db: Session, version: PayrollVersion, rows: list) -> None:
    """Create any missing absence records for a revision."""
    existing = {
        code
        for code in db.execute(
            select(PayrollAbsence.reason_code).where(
                PayrollAbsence.payroll_version_id == version.id
            )
        ).scalars()
    }

    for reason_code, description, day_count, is_paid, gross_effect in rows:
        if reason_code in existing:
            continue
        db.add(
            PayrollAbsence(
                id=uuid.uuid4(),
                payroll_version_id=version.id,
                reason_code=reason_code,
                description=description,
                day_count=day_count,
                is_paid=is_paid,
                gross_effect=gross_effect,
            )
        )
    db.flush()


def _ensure_cumulative_record(
    db: Session,
    org: Organization,
    employee: Employee,
    version: PayrollVersion,
    period: dict,
    rule_set: TaxRuleSet,
) -> None:
    """
    Create the month's tax ledger entry if it is not already present.

    The tax figures are produced by TaxEngine from the seeded brackets, so
    the demo's progressive position is genuinely derived rather than
    transcribed. Existing records are never modified: the ledger is
    append-only.
    """
    month = period["month"]

    already = db.execute(
        select(TaxCumulativeRecord.id).where(
            TaxCumulativeRecord.employee_id == employee.id,
            TaxCumulativeRecord.tax_year == DEMO_TAX_YEAR,
            TaxCumulativeRecord.period_month == month,
        )
    ).scalar_one_or_none()
    if already is not None:
        return

    monthly_base = period["income_tax_base"]

    opening = Decimal("0.00")
    if month > 1:
        previous = db.execute(
            select(TaxCumulativeRecord)
            .where(
                TaxCumulativeRecord.employee_id == employee.id,
                TaxCumulativeRecord.tax_year == DEMO_TAX_YEAR,
                TaxCumulativeRecord.period_month == month - 1,
            )
            .order_by(TaxCumulativeRecord.period_month.desc())
            .limit(1)
        ).scalars().first()
        if previous is not None:
            opening = previous.closing_cumulative_base

    closing = opening + monthly_base

    engine = TaxEngine(db, TaxService(db))
    position = engine.calculate_progressive_tax(
        closing_cumulative_base=closing,
        monthly_taxable_base=monthly_base,
        rule_set=rule_set,
    )

    run = TaxCalculationRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        employee_id=employee.id,
        tax_year=DEMO_TAX_YEAR,
        rule_set_id=rule_set.id,
        trigger_type="MONTHLY_PAYROLL",
        status="COMPLETED",
        calculation_version="1.0",
    )
    db.add(run)
    db.flush()

    db.add(
        TaxCumulativeRecord(
            id=uuid.uuid4(),
            calculation_run_id=run.id,
            employee_id=employee.id,
            payroll_version_id=version.id,
            tax_year=DEMO_TAX_YEAR,
            period_month=month,
            opening_cumulative_base=opening,
            monthly_taxable_base=monthly_base,
            closing_cumulative_base=closing,
            gross_calculated_tax=position.calculated_tax,
            tax_exemptions=Decimal("0.00"),
            withholding_tax=position.calculated_tax,
            effective_tax_rate=position.effective_tax_rate,
        )
    )
    db.flush()


def main() -> None:
    """
    Entry point for running the demo seed as a module.

    Usage:
        cd backend
        .venv/Scripts/python.exe -m app.seeds.demo_payroll_seed

    ``seed_demo_payroll`` only flushes, so that callers inside a
    transaction (the test suite) keep control of the transaction boundary.
    This runner is the one that commits.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with SessionLocal() as session:
        org, employee, versions = seed_demo_payroll(session)
        session.commit()
        print(
            f"[SEED] Demo data ready: org={org.code} "
            f"employee={employee.employee_no} periods={len(versions)}"
        )


if __name__ == "__main__":
    main()
