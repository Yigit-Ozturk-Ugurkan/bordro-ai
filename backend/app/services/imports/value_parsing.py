"""Strict, locale-aware typed parsing for untrusted staging text."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.models.enums import PayrollCanonicalValueType


class ValueParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedValue:
    value_type: PayrollCanonicalValueType
    value: Decimal | int | date | str


def _decimal_text(value: str) -> str:
    text = "".join(value.strip().split())
    if not text or not re.fullmatch(r"[+-]?\d[\d.,]*", text):
        raise ValueParseError("Value is not a supported decimal")
    sign = ""
    if text[0] in "+-":
        sign, text = text[0], text[1:]

    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        integer_part, fraction = text.rsplit(decimal_separator, 1)
        if not 1 <= len(fraction) <= 2 or not fraction.isdigit():
            raise ValueParseError("Decimal precision is unsupported")
        groups = integer_part.split(grouping_separator)
        if not groups[0] or not groups[0].isdigit() or any(
            len(group) != 3 or not group.isdigit() for group in groups[1:]
        ):
            raise ValueParseError("Thousands grouping is invalid")
        text = "".join(groups) + "." + fraction
    elif "," in text or "." in text:
        separator = "," if "," in text else "."
        if text.count(separator) != 1:
            groups = text.split(separator)
            if not groups[0] or not groups[0].isdigit() or any(
                len(group) != 3 or not group.isdigit() for group in groups[1:]
            ):
                raise ValueParseError("Thousands grouping is invalid")
            text = "".join(groups)
        else:
            integer_part, suffix = text.split(separator)
            if not integer_part.isdigit() or not suffix.isdigit():
                raise ValueParseError("Decimal syntax is invalid")
            if len(suffix) == 3:
                raise ValueParseError("Single separator with three trailing digits is ambiguous")
            if not 1 <= len(suffix) <= 2:
                raise ValueParseError("Decimal precision is unsupported")
            text = integer_part + "." + suffix
    try:
        parsed = Decimal(sign + text)
    except InvalidOperation as exc:
        raise ValueParseError("Value is not a supported decimal") from exc
    digits = parsed.as_tuple().digits
    exponent = parsed.as_tuple().exponent
    integer_digits = max(len(digits) + exponent, 0)
    fractional_digits = max(-exponent, 0)
    if integer_digits > 16 or fractional_digits > 2:
        raise ValueParseError("Value exceeds NUMERIC(18,2)")
    return format(parsed, "f")


def parse_typed_value(raw_value: str | None, value_type: PayrollCanonicalValueType) -> ParsedValue:
    if raw_value is None or not raw_value.strip():
        raise ValueParseError("Value is empty")
    if value_type in {PayrollCanonicalValueType.DECIMAL, PayrollCanonicalValueType.DAY_COUNT}:
        parsed = Decimal(_decimal_text(raw_value))
        return ParsedValue(value_type, parsed)
    if value_type == PayrollCanonicalValueType.INTEGER:
        text = raw_value.strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            raise ValueParseError("Value is not an integer")
        return ParsedValue(value_type, int(text))
    if value_type == PayrollCanonicalValueType.DATE:
        text = raw_value.strip()
        formats = ("%Y-%m-%d", "%d.%m.%Y")
        for pattern in formats:
            try:
                return ParsedValue(value_type, datetime.strptime(text, pattern).date())
            except ValueError:
                pass
        raise ValueParseError("Value is not an unambiguous supported date")
    text = " ".join(raw_value.split())
    if not text:
        raise ValueParseError("Value is empty")
    return ParsedValue(value_type, text)


__all__ = ["ParsedValue", "ValueParseError", "parse_typed_value"]
