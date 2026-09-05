"""Explicit V1 system aliases. Persistence is PostgreSQL; this catalog is seed input."""

from dataclasses import dataclass


SYSTEM_MAPPING_CATALOG_VERSION = 1


@dataclass(frozen=True, slots=True)
class SystemMappingSeed:
    id: str
    source_label: str
    canonical_key: str


SYSTEM_MAPPING_SEEDS = (
    SystemMappingSeed("21000000-0000-0000-0000-000000000001", "Personel No", "employee_identifier"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000002", "Dönem Yılı", "period_year"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000003", "Dönem Ayı", "period_month"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000004", "Brüt Kazanç", "gross_earnings"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000005", "SGK Matrahı", "sgk_base"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000006", "Gelir Vergisi Matrahı", "income_tax_base"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000007", "Damga Vergisi Matrahı", "stamp_tax_base"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000008", "SGK İşçi Payı", "employee_sgk"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000009", "İşsizlik Sigortası İşçi Payı", "employee_unemployment"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000010", "Gelir Vergisi", "income_tax"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000011", "Damga Vergisi", "stamp_tax"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000012", "Toplam Kazanç", "total_earnings"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000013", "Toplam Kesinti", "total_deductions"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000014", "Net Ücret", "net_pay"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000015", "Prim Ödeme Gün Sayısı", "paid_days"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000016", "Eksik Gün", "missing_days"),
    SystemMappingSeed("21000000-0000-0000-0000-000000000017", "Kümülatif Gelir Vergisi Matrahı", "cumulative_income_tax_base"),
)


__all__ = ["SYSTEM_MAPPING_CATALOG_VERSION", "SYSTEM_MAPPING_SEEDS", "SystemMappingSeed"]
