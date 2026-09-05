from collections import Counter
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import PayrollImportNotFoundError
from app.models.enums import (
    PayrollCanonicalValueType,
    PayrollFieldMappingScope,
    PayrollFieldMappingStatus,
    PayrollImportFieldReviewStatus,
    PayrollImportStatus,
)
from app.models.organization import Organization
from app.models.payroll import PayrollVersion
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_import import (
    PayrollFieldMapping,
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
    PayrollImportMappedField,
)
from app.models.tax import TaxCalculationRun, TaxCumulativeRecord
from app.models.user import User
from app.repositories.payroll_mapping_repository import PayrollMappingRepository
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.canonical_fields import get_canonical_field
from app.services.imports.label_normalization import normalize_source_label
from app.services.imports.payroll_adapter_service import PayrollAdapterService


def add_import(sync: Session, *, label: str = "adapter"):
    organization = Organization(
        id=uuid4(), name=f"Adapter {label}", code=f"ADP-{uuid4().hex[:8]}",
        timezone="Europe/Istanbul", is_active=True,
    )
    user_row = User(
        id=uuid4(), organization_id=organization.id,
        email=f"{label}-{uuid4().hex}@test.invalid", password_hash="unused", is_active=True,
    )
    import_id, document_id = uuid4(), uuid4()
    item = PayrollImport(
        id=import_id, organization_id=organization.id, uploaded_by_user_id=user_row.id,
        status=PayrollImportStatus.REVIEW_REQUIRED, source_type="DOCUMENT_UPLOAD",
        reader_provider="GENERAL_READER", source_document_id=document_id,
        content_sha256=uuid4().hex * 2, template_external_id="tpl-1",
        reader_table_count=0, reader_warnings=[], processing_attempt=1,
    )
    document = PayrollImportDocument(
        id=document_id, organization_id=organization.id, payroll_import_id=import_id,
        file_id=uuid4(), original_filename="payroll.png", declared_mime_type="image/png",
        detected_mime_type="image/png", size_bytes=10, sha256=item.content_sha256,
        storage_provider="LOCAL", storage_key=f"adapter/{uuid4().hex}",
    )
    sync.add_all([organization, user_row])
    sync.flush()
    sync.add_all([item, document])
    sync.flush()
    user = AuthenticatedUser(
        id=user_row.id, organization_id=organization.id, roles=frozenset(), employee_id=None,
    )
    return user, item, document


def add_field(sync: Session, item, document, source_id, label, raw,
              *, confidence="0.99", extraction_source="rule",
              review_status=PayrollImportFieldReviewStatus.UNREVIEWED):
    field = PayrollImportField(
        id=uuid4(), organization_id=item.organization_id, payroll_import_id=item.id,
        payroll_import_document_id=document.id, source_field_id=source_id,
        source_label=label, raw_value=raw, normalized_value=raw,
        value_type="text", confidence=confidence, page_number=1,
        extraction_source=extraction_source, review_status=review_status,
    )
    sync.add(field)
    sync.flush()
    return field


def add_mapping(sync: Session, *, scope, label, canonical_key, organization_id=None,
                provider=None, template_id=None, priority=0, active=True, source_field_id=None):
    definition = get_canonical_field(canonical_key)
    mapping = PayrollFieldMapping(
        id=uuid4(), organization_id=organization_id, scope=scope,
        template_provider=provider, template_external_id=template_id,
        source_field_id=source_field_id,
        source_label_normalized=normalize_source_label(label),
        canonical_key=canonical_key, section_key=definition.section_key,
        target_value_type=definition.value_type, priority=priority,
        version=1, is_active=active,
    )
    sync.add(mapping)
    sync.flush()
    return mapping


@pytest.mark.asyncio
async def test_mapping_precedence_tenant_template_activity_priority_and_ambiguity(
    async_db_session: AsyncSession,
):
    def seed(sync: Session):
        user, item, _ = add_import(sync, label="precedence")
        other, _, _ = add_import(sync, label="other")
        label = f"Precedence {uuid4().hex}"
        system = add_mapping(sync, scope=PayrollFieldMappingScope.SYSTEM, label=label,
                             canonical_key="gross_earnings")
        organization = add_mapping(
            sync, scope=PayrollFieldMappingScope.ORGANIZATION, label=label,
            canonical_key="total_earnings", organization_id=item.organization_id,
        )
        add_mapping(sync, scope=PayrollFieldMappingScope.ORGANIZATION, label=label,
                    canonical_key="net_pay", organization_id=other.organization_id, priority=99)
        add_mapping(sync, scope=PayrollFieldMappingScope.TEMPLATE, label=label,
                    canonical_key="income_tax", organization_id=item.organization_id,
                    provider="GENERAL_READER", template_id="other", priority=99)
        add_mapping(sync, scope=PayrollFieldMappingScope.TEMPLATE, label=label,
                    canonical_key="stamp_tax", organization_id=item.organization_id,
                    provider="GENERAL_READER", template_id="tpl-1", active=False, priority=99)
        template = add_mapping(sync, scope=PayrollFieldMappingScope.TEMPLATE, label=label,
                    canonical_key="net_pay", organization_id=item.organization_id,
                    provider="GENERAL_READER", template_id="tpl-1", priority=3)
        return user, item, label, system, organization, template

    user, item, label, system, organization, template = await async_db_session.run_sync(seed)

    def resolve(sync: Session):
        repo = PayrollMappingRepository(sync)
        candidates = repo.candidates(item, "source", normalize_source_label(label))
        return PayrollAdapterService._winning_candidates(candidates)

    assert [value.id for value in await async_db_session.run_sync(resolve)] == [template.id]

    def remove_template(sync: Session):
        sync.delete(sync.get(PayrollFieldMapping, template.id)); sync.flush()
    await async_db_session.run_sync(remove_template)
    assert [value.id for value in await async_db_session.run_sync(resolve)] == [organization.id]

    def priority_and_conflict(sync: Session):
        organization.priority = 5
        add_mapping(sync, scope=PayrollFieldMappingScope.ORGANIZATION, label=label,
                    canonical_key="income_tax", organization_id=item.organization_id, priority=4)
        sync.flush()
    await async_db_session.run_sync(priority_and_conflict)
    assert [value.id for value in await async_db_session.run_sync(resolve)] == [organization.id]

    def equal_conflict(sync: Session):
        add_mapping(sync, scope=PayrollFieldMappingScope.ORGANIZATION, label=label,
                    canonical_key="income_tax", organization_id=item.organization_id, priority=5)
        sync.flush()
    await async_db_session.run_sync(equal_conflict)
    winners = await async_db_session.run_sync(resolve)
    assert len(winners) == 2
    assert system not in winners


@pytest.mark.asyncio
async def test_adapter_outputs_all_states_missing_and_is_idempotent_without_side_effects(
    async_db_session: AsyncSession,
):
    def seed(sync: Session):
        user, item, document = add_import(sync, label="flow")
        fields = [
            add_field(sync, item, document, "net", "Net Ücret", "210.000,00"),
            add_field(sync, item, document, "unknown", "Banka Şubesi", "Kadıköy"),
            add_field(sync, item, document, "amb", "Çakışan Alan", "12"),
            add_field(sync, item, document, "bad", "Bozuk Tutar", "12,34,56"),
            add_field(sync, item, document, "low", "SGK Matrahı", "1000,00", confidence="0.50"),
            add_field(sync, item, document, "llm", "Damga Vergisi", "10,00", extraction_source="llm"),
            add_field(
                sync, item, document, "missing-source", "Toplam Kesinti", None,
                review_status=PayrollImportFieldReviewStatus.MISSING,
            ),
        ]
        add_mapping(sync, scope=PayrollFieldMappingScope.ORGANIZATION,
                    label="Çakışan Alan", canonical_key="gross_earnings",
                    organization_id=item.organization_id, priority=2)
        add_mapping(sync, scope=PayrollFieldMappingScope.ORGANIZATION,
                    label="Çakışan Alan", canonical_key="total_earnings",
                    organization_id=item.organization_id, priority=2)
        add_mapping(sync, scope=PayrollFieldMappingScope.ORGANIZATION,
                    label="Bozuk Tutar", canonical_key="income_tax",
                    organization_id=item.organization_id)
        source_snapshot = [(field.id, field.source_label, field.raw_value) for field in fields]
        tracked = [PayrollVersion, PayrollEarning, PayrollDeduction, PayrollAbsence,
                   TaxCalculationRun, TaxCumulativeRecord]
        counts = {model: sync.scalar(select(func.count()).select_from(model)) for model in tracked}
        return user, item.id, source_snapshot, counts

    user, import_id, source_snapshot, before = await async_db_session.run_sync(seed)
    service = PayrollAdapterService(async_db_session)
    first = await service.run(user, import_id)
    assert (first.mapped_count, first.unmapped_count, first.ambiguous_count,
            first.parse_failed_count) == (3, 1, 1, 2)
    assert first.missing_count == 13

    output = await service.mapped_fields(user, import_id)
    by_source = {row.source_external_field_id: row for row in output.items}
    assert by_source["net"].typed_value.value == "210000.00"
    assert by_source["net"].review_status == PayrollImportFieldReviewStatus.UNREVIEWED
    assert by_source["unknown"].mapping_status == PayrollFieldMappingStatus.UNMAPPED
    assert by_source["amb"].mapping_status == PayrollFieldMappingStatus.AMBIGUOUS
    assert by_source["amb"].candidate_canonical_keys == ["gross_earnings", "total_earnings"]
    assert by_source["bad"].mapping_status == PayrollFieldMappingStatus.PARSE_FAILED
    assert by_source["bad"].typed_value is None
    assert "LOW_CONFIDENCE_SOURCE" in by_source["low"].review_reason_codes
    assert "LLM_SOURCE" in by_source["llm"].review_reason_codes
    assert by_source["missing-source"].mapping_status == PayrollFieldMappingStatus.PARSE_FAILED
    assert "SOURCE_MISSING" in by_source["missing-source"].review_reason_codes
    assert any(issue.canonical_key == "total_deductions" for issue in first.issues)

    second = await service.run(user, import_id)
    assert second.model_dump(exclude={"issues"}) == first.model_dump(exclude={"issues"})

    def verify(sync: Session):
        rows = sync.scalars(select(PayrollImportMappedField).where(
            PayrollImportMappedField.payroll_import_id == import_id
        )).all()
        source_after = [(field.id, field.source_label, field.raw_value) for field in sync.scalars(
            select(PayrollImportField).where(PayrollImportField.payroll_import_id == import_id)
            .order_by(PayrollImportField.created_at, PayrollImportField.id)
        ).all()]
        after = {model: sync.scalar(select(func.count()).select_from(model)) for model in before}
        return len(rows), source_after, after

    row_count, source_after, after = await async_db_session.run_sync(verify)
    assert row_count == len(source_snapshot)
    assert Counter(source_after) == Counter(source_snapshot)
    assert after == before


@pytest.mark.asyncio
async def test_adapter_cross_organization_access_is_non_disclosing(async_db_session: AsyncSession):
    def seed(sync: Session):
        owner, item, document = add_import(sync, label="owner")
        outsider, _, _ = add_import(sync, label="outsider")
        add_field(sync, item, document, "net", "Net Ücret", "1.000,00")
        return owner, outsider, item.id
    owner, outsider, import_id = await async_db_session.run_sync(seed)
    await PayrollAdapterService(async_db_session).run(owner, import_id)
    with pytest.raises(PayrollImportNotFoundError):
        await PayrollAdapterService(async_db_session).run(outsider, import_id)
    with pytest.raises(PayrollImportNotFoundError):
        await PayrollAdapterService(async_db_session).mapped_fields(outsider, import_id)
    with pytest.raises(PayrollImportNotFoundError):
        await PayrollAdapterService(async_db_session).summary(outsider, import_id)


@pytest.mark.asyncio
async def test_abbreviated_label_maps_only_after_explicit_configuration(
    async_db_session: AsyncSession,
):
    def seed(sync: Session):
        user, item, document = add_import(sync, label="explicit-alias")
        add_field(sync, item, document, "dev-base", "DEV. VERGİ MATRAHI", "210.000,00")
        return user, item

    user, item = await async_db_session.run_sync(seed)
    import_id = item.id
    service = PayrollAdapterService(async_db_session)
    first = await service.run(user, import_id)
    assert first.unmapped_count == 1

    def configure(sync: Session):
        add_mapping(
            sync, scope=PayrollFieldMappingScope.ORGANIZATION,
            label="Dev. Vergi Matrahı", canonical_key="cumulative_income_tax_base",
            organization_id=user.organization_id,
        )
    await async_db_session.run_sync(configure)
    second = await service.run(user, import_id)
    assert second.mapped_count == 1
    row = (await service.mapped_fields(user, import_id)).items[0]
    assert row.canonical_key == "cumulative_income_tax_base"
    assert row.typed_value.value == "210000.00"
