from datetime import date
from decimal import Decimal

import pytest

from app.models.employee import Employee
from app.models.enums import PayrollCanonicalValueType
from app.models.payroll import Payroll, PayrollVersion
from app.models.tax import TaxCumulativeRecord
from app.services.imports.canonical_fields import CANONICAL_FIELDS
from app.services.imports.label_normalization import normalize_source_label
from app.services.imports.system_mapping_catalog import SYSTEM_MAPPING_SEEDS
from app.services.imports.value_parsing import ValueParseError, parse_typed_value


@pytest.mark.parametrize("label", [
    "Dev. Vergi Matrahı",
    "DEV. VERGİ MATRAHI",
    "Dev Vergi Matrahı",
    "  Dev.\tVergi\nMatrahı  ",
    "Ｄｅｖ． Vergi Matrahı",
])
def test_turkish_label_normalization_is_unicode_stable(label):
    assert normalize_source_label(label) == "dev vergi matrahı"


@pytest.mark.parametrize(("upper", "lower"), [
    ("İ", "i"), ("I", "ı"), ("Ş", "ş"), ("Ğ", "ğ"),
    ("Ü", "ü"), ("Ö", "ö"), ("Ç", "ç"),
])
def test_turkish_case_pairs(upper, lower):
    assert normalize_source_label(upper) == lower


def test_safe_punctuation_variants_and_material_differences():
    assert normalize_source_label("Dev, Vergi: Matrahı;") == "dev vergi matrahı"
    assert normalize_source_label("SGK—İşçi") == "sgk-işçi"
    assert normalize_source_label("SGK/İşçi") != normalize_source_label("SGK İşçi")
    assert normalize_source_label("Gelir Vergisi") != normalize_source_label("Gelir Vergisi Matrahı")


@pytest.mark.parametrize(("raw", "expected"), [
    ("210.000,00", Decimal("210000.00")),
    ("4.250,75", Decimal("4250.75")),
    ("0,10", Decimal("0.10")),
    ("210000.00", Decimal("210000.00")),
    ("4250.75", Decimal("4250.75")),
    ("9999999999999999.99", Decimal("9999999999999999.99")),
    ("-4.250,75", Decimal("-4250.75")),
])
def test_decimal_parser_is_exact(raw, expected):
    result = parse_typed_value(raw, PayrollCanonicalValueType.DECIMAL)
    assert result.value == expected
    assert isinstance(result.value, Decimal)


@pytest.mark.parametrize("raw", [
    "", "money", "1,234", "1.234", "12,3456", "1,23,4", "1 2 3x", "99999999999999999.99",
])
def test_decimal_parser_rejects_invalid_or_ambiguous_values(raw):
    with pytest.raises(ValueParseError):
        parse_typed_value(raw, PayrollCanonicalValueType.DECIMAL)


def test_other_typed_parsers_are_deterministic():
    assert parse_typed_value("2026", PayrollCanonicalValueType.INTEGER).value == 2026
    assert parse_typed_value("30,50", PayrollCanonicalValueType.DAY_COUNT).value == Decimal("30.50")
    assert parse_typed_value("2026-09-05", PayrollCanonicalValueType.DATE).value == date(2026, 9, 5)
    assert parse_typed_value("05.09.2026", PayrollCanonicalValueType.DATE).value == date(2026, 9, 5)
    assert parse_typed_value("  EMP  001 ", PayrollCanonicalValueType.IDENTIFIER).value == "EMP 001"
    assert parse_typed_value(" Bordro notu ", PayrollCanonicalValueType.TEXT).value == "Bordro notu"
    with pytest.raises(ValueParseError):
        parse_typed_value("05/09/2026", PayrollCanonicalValueType.DATE)


def test_registry_targets_only_real_bordro_domain_attributes():
    classes = {
        "Employee": Employee,
        "Payroll": Payroll,
        "PayrollVersion": PayrollVersion,
        "TaxCumulativeRecord": TaxCumulativeRecord,
    }
    for definition in CANONICAL_FIELDS.values():
        class_name, attribute = definition.target.split(".")
        assert hasattr(classes[class_name], attribute), definition.canonical_key
    assert len(CANONICAL_FIELDS) == len(set(CANONICAL_FIELDS))


def test_system_alias_catalog_is_explicit_valid_and_avoids_uncertain_abbreviation():
    assert all(seed.canonical_key in CANONICAL_FIELDS for seed in SYSTEM_MAPPING_SEEDS)
    assert all(normalize_source_label(normalize_source_label(seed.source_label))
               == normalize_source_label(seed.source_label)
               for seed in SYSTEM_MAPPING_SEEDS)
    assert not any("dev" in normalize_source_label(seed.source_label).split()
                   for seed in SYSTEM_MAPPING_SEEDS)
