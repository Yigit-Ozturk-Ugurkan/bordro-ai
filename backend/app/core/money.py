"""
Money policy helpers.

Every financial value in this project is a ``decimal.Decimal``. Floats are
never used for money, rates, or day counts, because binary floating point
cannot represent decimal currency amounts exactly.

Conventions:
- Money is stored as NUMERIC(18,2) and quantized to 2 decimals.
- Rates are stored as NUMERIC(9,6) and quantized to 6 decimals.
- Day counts are stored as NUMERIC(5,2) and quantized to 2 decimals.
- Rounding is always ROUND_HALF_UP, matching Turkish payroll practice.
"""

from decimal import Decimal, ROUND_HALF_UP

MONEY_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.000001")
DAYS_QUANTUM = Decimal("0.01")

ZERO_MONEY = Decimal("0.00")


def quantize_money(value: Decimal | None) -> Decimal:
    """Round a money amount to 2 decimals (ROUND_HALF_UP). None -> 0.00."""
    if value is None:
        return ZERO_MONEY
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_rate(value: Decimal | None) -> Decimal | None:
    """Round a rate to 6 decimals (ROUND_HALF_UP). None stays None."""
    if value is None:
        return None
    return Decimal(value).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_days(value: Decimal | None) -> Decimal:
    """Round a day count to 2 decimals (ROUND_HALF_UP). None -> 0.00."""
    if value is None:
        return ZERO_MONEY
    return Decimal(value).quantize(DAYS_QUANTUM, rounding=ROUND_HALF_UP)


def percent_change(delta: Decimal, previous: Decimal) -> Decimal | None:
    """
    Percentage change of ``delta`` relative to ``previous``.

    Returns None when ``previous`` is zero, because the percentage change
    from zero is undefined. A zero ``delta`` over a non-zero ``previous``
    correctly yields Decimal("0.00"), not None.
    """
    if previous == 0:
        return None
    return (delta / previous * Decimal("100")).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )


def money_str(value: Decimal | None) -> str | None:
    """
    Serialize a money amount for a transport dict.

    None is preserved as None; it means "not applicable", which is
    distinct from Decimal("0.00") meaning "zero".
    """
    if value is None:
        return None
    return str(quantize_money(value))
