"""Deterministic table-row mapping, review, snapshots, and detail materialization."""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    PayrollDetailIntegrityError, PayrollDetailNotFoundError,
    PayrollDetailNotReadyError, PayrollDetailStateConflictError,
    PayrollImportNotFoundError,
)
from app.models.enums import (
    PayrollApprovalDecision, PayrollCanonicalValueType,
    PayrollDetailMappingStatus, PayrollDetailReviewStatus, PayrollDetailType,
    PayrollFieldMappingScope, PayrollImportStatus,
)
from app.models.payroll_approval import PayrollImportApproval
from app.models.payroll_detail import PayrollAbsence, PayrollDeduction, PayrollEarning
from app.models.payroll_detail_mapping import (
    PayrollDetailMapping, PayrollImportDetailCorrection,
    PayrollImportDetailMaterialization, PayrollImportDetailReview,
    PayrollImportDetailSnapshot, PayrollImportDetailSnapshotRow,
    PayrollImportMappedDetail,
)
from app.models.payroll_import import PayrollImport, PayrollImportTable, PayrollImportTableRow
from app.models.payroll_materialization import PayrollImportMaterialization
from app.schemas.payroll_detail_mapping import (
    PayrollDetailCorrectionRead, PayrollDetailCorrectionRequest,
    PayrollDetailMaterializationRead, PayrollDetailReviewRead,
    PayrollDetailSnapshotRead, PayrollMappedDetailList,
)
from app.services.auth.authentication import AuthenticatedUser
from app.services.imports.label_normalization import normalize_source_label
from app.services.imports.review_checksums import sha256_canonical
from app.services.imports.value_parsing import ValueParseError, parse_typed_value

_SCOPE_RANK = {
    PayrollFieldMappingScope.SYSTEM: 1,
    PayrollFieldMappingScope.ORGANIZATION: 2,
    PayrollFieldMappingScope.TEMPLATE: 3,
}


class PayrollDetailMappingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, user: AuthenticatedUser, import_id: UUID) -> PayrollMappedDetailList:
        def work(sync):
            item = self._import(sync, user.organization_id, import_id, lock=True)
            if item.status not in {
                PayrollImportStatus.EXTRACTED, PayrollImportStatus.REVIEW_REQUIRED,
            }:
                raise PayrollDetailStateConflictError(
                    "Detail mapping requires completed import extraction"
                )
            if sync.scalar(select(PayrollImportApproval.id).where(
                PayrollImportApproval.organization_id == user.organization_id,
                PayrollImportApproval.payroll_import_id == import_id,
            ).limit(1)) is not None:
                raise PayrollDetailStateConflictError()
            review = sync.scalar(select(PayrollImportDetailReview).where(
                PayrollImportDetailReview.organization_id == user.organization_id,
                PayrollImportDetailReview.payroll_import_id == import_id,
            ).with_for_update())
            if review is not None and sync.scalar(select(
                PayrollImportDetailCorrection.id,
            ).where(
                PayrollImportDetailCorrection.organization_id == user.organization_id,
                PayrollImportDetailCorrection.payroll_import_id == import_id,
            ).limit(1)) is not None:
                raise PayrollDetailStateConflictError(
                    "Detail mapping cannot be replaced after human review"
                )
            mappings = list(sync.scalars(select(PayrollDetailMapping).where(
                PayrollDetailMapping.is_active.is_(True),
                or_(PayrollDetailMapping.organization_id.is_(None),
                    PayrollDetailMapping.organization_id == user.organization_id),
            )))
            results = []
            for table in sorted(item.tables, key=lambda value: value.source_table_index):
                for row in sorted(table.rows, key=lambda value: value.row_index):
                    results.append(self._map_row(item, table, row, mappings))
            if not results:
                raise PayrollDetailNotReadyError("No staged detail rows are available")
            checksum = self.mapping_checksum(results)
            sync.execute(delete(PayrollImportMappedDetail).where(
                PayrollImportMappedDetail.organization_id == user.organization_id,
                PayrollImportMappedDetail.payroll_import_id == import_id,
            ))
            sync.add_all(results)
            sync.flush()
            if review is None:
                review = PayrollImportDetailReview(
                    organization_id=user.organization_id, payroll_import_id=import_id,
                    status=PayrollDetailReviewStatus.IN_PROGRESS, row_version=1,
                    mapping_checksum=checksum,
                )
                sync.add(review)
            else:
                review.mapping_checksum = checksum
                review.row_version += 1
                review.status = PayrollDetailReviewStatus.IN_PROGRESS
                review.current_snapshot_id = None
            sync.flush()
            return self._mapped_list(import_id, checksum, results)
        return await self._commit(work)

    async def mapped(self, user: AuthenticatedUser, import_id: UUID) -> PayrollMappedDetailList:
        def work(sync):
            self._require_import(sync, user.organization_id, import_id)
            rows = self._mapped_rows(sync, user.organization_id, import_id)
            review = sync.scalar(select(PayrollImportDetailReview).where(
                PayrollImportDetailReview.organization_id == user.organization_id,
                PayrollImportDetailReview.payroll_import_id == import_id,
            ))
            return self._mapped_list(import_id, review.mapping_checksum if review else None, rows)
        return await self._session.run_sync(work)

    async def review(self, user: AuthenticatedUser, import_id: UUID) -> PayrollDetailReviewRead:
        def work(sync):
            item = self._require_import(sync, user.organization_id, import_id)
            review = sync.scalar(select(PayrollImportDetailReview).where(
                PayrollImportDetailReview.organization_id == user.organization_id,
                PayrollImportDetailReview.payroll_import_id == import_id,
            ))
            if review is None:
                raise PayrollDetailNotFoundError()
            mapped = self._mapped_rows(sync, user.organization_id, import_id)
            current_checksums = self._current_source_checksums(item)
            if any(current_checksums.get(row.source_row_id) != row.source_checksum
                   for row in mapped):
                raise PayrollDetailNotReadyError("Detail source evidence has changed")
            corrections = self._latest_corrections(sync, user.organization_id, import_id)
            return self._review_read(review, mapped, corrections)
        return await self._session.run_sync(work)

    async def correct(self, user: AuthenticatedUser, import_id: UUID,
                      mapped_id: UUID, request: PayrollDetailCorrectionRequest):
        def work(sync):
            item = self._require_import(sync, user.organization_id, import_id)
            review = sync.scalar(select(PayrollImportDetailReview).where(
                PayrollImportDetailReview.organization_id == user.organization_id,
                PayrollImportDetailReview.payroll_import_id == import_id,
            ).with_for_update())
            mapped = sync.scalar(select(PayrollImportMappedDetail).where(
                PayrollImportMappedDetail.id == mapped_id,
                PayrollImportMappedDetail.organization_id == user.organization_id,
                PayrollImportMappedDetail.payroll_import_id == import_id,
            ))
            if review is None or mapped is None:
                raise PayrollDetailNotFoundError()
            if review.row_version != request.expected_row_version:
                raise PayrollDetailStateConflictError("The detail review has changed")
            if mapped.source_checksum != request.expected_source_checksum:
                raise PayrollDetailStateConflictError("The source detail evidence is stale")
            if self._current_source_checksums(item).get(mapped.source_row_id) != mapped.source_checksum:
                raise PayrollDetailStateConflictError("The source detail evidence is stale")
            self._validate_identity(request.detail_type, request.canonical_code,
                                    request.canonical_name, request.category,
                                    request.ignored)
            amount = self._parse_optional(request.amount)
            quantity = self._parse_optional(request.quantity)
            rate = self._parse_optional(request.rate)
            revision = (sync.scalar(select(func.max(
                PayrollImportDetailCorrection.revision,
            )).where(PayrollImportDetailCorrection.mapped_detail_id == mapped.id)) or 0) + 1
            row = PayrollImportDetailCorrection(
                organization_id=user.organization_id, payroll_import_id=import_id,
                mapped_detail_id=mapped.id, source_checksum=mapped.source_checksum,
                revision=revision, detail_type=request.detail_type,
                canonical_code=request.canonical_code, canonical_name=request.canonical_name,
                category=request.category, amount=amount, quantity=quantity, rate=rate,
                target_values=request.target_values, ignored=request.ignored,
                reason=request.reason, reviewed_by_user_id=user.id,
                created_at=datetime.now(timezone.utc),
            )
            sync.add(row)
            review.row_version += 1
            review.current_snapshot_id = None
            sync.flush()
            mapped_rows = self._mapped_rows(sync, user.organization_id, import_id)
            corrections = self._latest_corrections(
                sync, user.organization_id, import_id,
            )
            review.status = (
                PayrollDetailReviewStatus.READY_FOR_SNAPSHOT
                if self._ready(mapped_rows, corrections)
                else PayrollDetailReviewStatus.IN_PROGRESS
            )
            sync.flush()
            return PayrollDetailCorrectionRead.model_validate(row)
        return await self._commit(work)

    async def finalize(self, user: AuthenticatedUser, import_id: UUID,
                       expected_row_version: int) -> PayrollDetailSnapshotRead:
        def work(sync):
            item = self._require_import(sync, user.organization_id, import_id)
            review = sync.scalar(select(PayrollImportDetailReview).where(
                PayrollImportDetailReview.organization_id == user.organization_id,
                PayrollImportDetailReview.payroll_import_id == import_id,
            ).with_for_update())
            if review is None:
                raise PayrollDetailNotFoundError()
            if review.row_version != expected_row_version:
                raise PayrollDetailStateConflictError("The detail review has changed")
            mapped = self._mapped_rows(sync, user.organization_id, import_id)
            current_checksums = self._current_source_checksums(item)
            if any(current_checksums.get(row.source_row_id) != row.source_checksum
                   for row in mapped):
                raise PayrollDetailNotReadyError("Detail source evidence has changed")
            corrections = self._latest_corrections(sync, user.organization_id, import_id)
            if len(corrections) != len(mapped):
                raise PayrollDetailNotReadyError("Every extracted row requires explicit review")
            effective = []
            identities = set()
            for order, mapped_row in enumerate(mapped):
                correction = corrections.get(mapped_row.id)
                if correction is None or correction.source_checksum != mapped_row.source_checksum:
                    raise PayrollDetailNotReadyError("A detail correction is stale")
                self._validate_effective(correction)
                if not correction.ignored:
                    identity = (correction.detail_type.value, correction.canonical_code)
                    if identity in identities:
                        raise PayrollDetailNotReadyError("Duplicate canonical detail identity")
                    identities.add(identity)
                effective.append((order, mapped_row, correction))
            corrections_checksum = sha256_canonical([
                self._correction_payload(value[2]) for value in effective
            ])
            revision = (sync.scalar(select(func.max(
                PayrollImportDetailSnapshot.revision,
            )).where(PayrollImportDetailSnapshot.payroll_import_id == import_id)) or 0) + 1
            snapshot_payload = [self._frozen_payload(*value) for value in effective]
            snapshot_checksum = sha256_canonical({
                "mapping_checksum": review.mapping_checksum,
                "corrections_checksum": corrections_checksum,
                "rows": snapshot_payload,
            })
            now = datetime.now(timezone.utc)
            snapshot = PayrollImportDetailSnapshot(
                organization_id=user.organization_id, payroll_import_id=import_id,
                revision=revision, mapping_checksum=review.mapping_checksum,
                corrections_checksum=corrections_checksum,
                snapshot_checksum=snapshot_checksum, row_count=len(effective),
                finalized_by_user_id=user.id, finalized_at=now, created_at=now,
            )
            for order, mapped_row, correction in effective:
                snapshot.rows.append(PayrollImportDetailSnapshotRow(
                    organization_id=user.organization_id, payroll_import_id=import_id,
                    source_table_id=mapped_row.source_table_id,
                    source_row_id=mapped_row.source_row_id, correction_id=correction.id,
                    row_order=order, source_checksum=mapped_row.source_checksum,
                    detail_type=correction.detail_type,
                    canonical_code=correction.canonical_code,
                    canonical_name=correction.canonical_name,
                    category=correction.category, amount=correction.amount,
                    quantity=correction.quantity, rate=correction.rate,
                    target_values=correction.target_values, ignored=correction.ignored,
                    reviewed_by_user_id=correction.reviewed_by_user_id,
                    reviewed_at=correction.created_at,
                ))
            sync.add(snapshot)
            sync.flush()
            review.current_snapshot_id = snapshot.id
            review.status = PayrollDetailReviewStatus.SNAPSHOTTED
            review.row_version += 1
            sync.flush()
            return PayrollDetailSnapshotRead.model_validate(snapshot)
        return await self._commit(work)

    async def snapshot(self, user: AuthenticatedUser, import_id: UUID,
                       snapshot_id: UUID | None = None) -> PayrollDetailSnapshotRead:
        def work(sync):
            self._require_import(sync, user.organization_id, import_id)
            selected_id = snapshot_id
            if selected_id is None:
                selected_id = sync.scalar(select(PayrollImportDetailReview.current_snapshot_id).where(
                    PayrollImportDetailReview.organization_id == user.organization_id,
                    PayrollImportDetailReview.payroll_import_id == import_id,
                ))
            row = self._snapshot(sync, user.organization_id, import_id, selected_id)
            if row is None:
                raise PayrollDetailNotFoundError()
            return PayrollDetailSnapshotRead.model_validate(row)
        return await self._session.run_sync(work)

    async def materialize(self, user: AuthenticatedUser,
                          import_id: UUID) -> PayrollDetailMaterializationRead:
        def work(sync):
            item = self._require_import(sync, user.organization_id, import_id)
            scalar = sync.scalar(select(PayrollImportMaterialization).where(
                PayrollImportMaterialization.organization_id == user.organization_id,
                PayrollImportMaterialization.payroll_import_id == import_id,
            ).with_for_update())
            if scalar is None:
                raise PayrollDetailNotReadyError("PayrollVersion materialization is required")
            existing = sync.scalar(select(PayrollImportDetailMaterialization).where(
                PayrollImportDetailMaterialization.payroll_materialization_id == scalar.id,
            ))
            if existing is not None:
                return self._materialization_read(sync, existing)
            approval = sync.get(PayrollImportApproval, scalar.approval_id)
            if (approval is None or approval.decision != PayrollApprovalDecision.APPROVED
                    or approval.detail_snapshot_id is None):
                raise PayrollDetailNotReadyError("Approved detail evidence is required")
            snapshot = self._snapshot(sync, user.organization_id, import_id,
                                      approval.detail_snapshot_id)
            if (snapshot is None
                    or snapshot.snapshot_checksum != approval.detail_snapshot_checksum
                    or not self.verify_snapshot(snapshot)
                    or not self.verify_sources(item, snapshot)):
                raise PayrollDetailIntegrityError()
            counts = Counter(row.detail_type for row in snapshot.rows if not row.ignored)
            checksum = sha256_canonical({
                "approval_id": str(approval.id), "detail_snapshot_id": str(snapshot.id),
                "payroll_materialization_id": str(scalar.id),
                "payroll_version_id": str(scalar.payroll_version_id),
                "snapshot_checksum": snapshot.snapshot_checksum,
            })
            now = datetime.now(timezone.utc)
            action = PayrollImportDetailMaterialization(
                organization_id=user.organization_id, payroll_import_id=import_id,
                detail_snapshot_id=snapshot.id, approval_id=approval.id,
                payroll_materialization_id=scalar.id,
                payroll_id=scalar.payroll_id,
                payroll_version_id=scalar.payroll_version_id,
                materialization_checksum=checksum,
                earning_count=counts[PayrollDetailType.EARNING],
                deduction_count=counts[PayrollDetailType.DEDUCTION],
                absence_count=counts[PayrollDetailType.ABSENCE],
                materialized_by_user_id=user.id, materialized_at=now, created_at=now,
            )
            sync.add(action)
            sync.flush()
            for row in snapshot.rows:
                if row.ignored:
                    continue
                common = dict(
                    organization_id=user.organization_id,
                    payroll_version_id=scalar.payroll_version_id,
                    source_import_id=import_id, source_table_id=row.source_table_id,
                    source_row_id=row.source_row_id, detail_snapshot_row_id=row.id,
                    detail_materialization_id=action.id,
                )
                if row.detail_type == PayrollDetailType.EARNING:
                    sync.add(PayrollEarning(
                        **common, code=row.canonical_code, label=row.canonical_name,
                        category=row.category, quantity=row.quantity,
                        unit_amount=self._target_decimal(row.target_values, "unit_amount", False),
                        amount=row.amount,
                        sgk_subject_amount=self._target_decimal(row.target_values, "sgk_subject_amount", True),
                        income_tax_subject_amount=self._target_decimal(row.target_values, "income_tax_subject_amount", True),
                        stamp_tax_subject_amount=self._target_decimal(row.target_values, "stamp_tax_subject_amount", True),
                    ))
                elif row.detail_type == PayrollDetailType.DEDUCTION:
                    sync.add(PayrollDeduction(
                        **common, code=row.canonical_code, label=row.canonical_name,
                        category=row.category, amount=row.amount,
                        base_amount=self._target_decimal(row.target_values, "base_amount", False),
                        rate=row.rate, is_statutory=row.target_values["is_statutory"],
                        is_sensitive=row.target_values["is_sensitive"],
                    ))
                else:
                    sync.add(PayrollAbsence(
                        **common, reason_code=row.canonical_code,
                        description=row.canonical_name, day_count=row.quantity,
                        is_paid=row.target_values["is_paid"], gross_effect=row.amount,
                    ))
            sync.flush()
            return self._materialization_read(sync, action)
        return await self._commit(work)

    async def materialized(self, user: AuthenticatedUser,
                           import_id: UUID) -> PayrollDetailMaterializationRead:
        def work(sync):
            self._require_import(sync, user.organization_id, import_id)
            row = sync.scalar(select(PayrollImportDetailMaterialization).where(
                PayrollImportDetailMaterialization.organization_id == user.organization_id,
                PayrollImportDetailMaterialization.payroll_import_id == import_id,
            ))
            if row is None:
                raise PayrollDetailNotFoundError()
            return self._materialization_read(sync, row)
        return await self._session.run_sync(work)

    @staticmethod
    def _import(sync, organization_id, import_id, lock=False):
        query = select(PayrollImport).where(
            PayrollImport.id == import_id, PayrollImport.organization_id == organization_id,
        ).options(selectinload(PayrollImport.tables).selectinload(PayrollImportTable.rows)
                  .selectinload(PayrollImportTableRow.cells))
        if lock:
            query = query.with_for_update()
        row = sync.scalar(query)
        if row is None:
            raise PayrollImportNotFoundError()
        return row

    @classmethod
    def _require_import(cls, sync, organization_id, import_id):
        return cls._import(sync, organization_id, import_id)

    @classmethod
    def _map_row(cls, item, table, row, mappings):
        cells = {cell.source_column_id: cell for cell in row.cells}
        candidates = []
        for mapping in mappings:
            if mapping.scope == PayrollFieldMappingScope.TEMPLATE and (
                item.template_external_id != mapping.template_external_id
            ):
                continue
            label_cell = cells.get(mapping.label_column_id)
            if label_cell and label_cell.raw_value and normalize_source_label(
                label_cell.raw_value
            ) == mapping.source_label_normalized:
                candidates.append(mapping)
        mapping = None
        status = PayrollDetailMappingStatus.UNMAPPED
        if candidates:
            best = max((_SCOPE_RANK[value.scope], value.priority) for value in candidates)
            winners = [value for value in candidates
                       if (_SCOPE_RANK[value.scope], value.priority) == best]
            if len(winners) == 1:
                mapping, status = winners[0], PayrollDetailMappingStatus.MAPPED
            else:
                status = PayrollDetailMappingStatus.AMBIGUOUS
        source_values = [{
            "column_index": cell.column_index, "source_column_id": cell.source_column_id,
            "column_label": cell.column_label, "raw_value": cell.raw_value,
        } for cell in sorted(row.cells, key=lambda value: value.column_index)]
        source_checksum = cls._source_checksum(table, row)
        values = {"amount": None, "quantity": None, "rate": None}
        if mapping is not None:
            try:
                for key, column_id in (
                    ("amount", mapping.amount_column_id),
                    ("quantity", mapping.quantity_column_id),
                    ("rate", mapping.rate_column_id),
                ):
                    if column_id is not None:
                        cell = cells.get(column_id)
                        if cell is None:
                            raise ValueParseError("Configured detail column is missing")
                        values[key] = parse_typed_value(
                            cell.raw_value, PayrollCanonicalValueType.DECIMAL,
                        ).value
            except ValueParseError:
                status = PayrollDetailMappingStatus.PARSE_FAILED
        return PayrollImportMappedDetail(
            organization_id=item.organization_id, payroll_import_id=item.id,
            source_table_id=table.id, source_row_id=row.id,
            source_table_index=table.source_table_index,
            source_row_index=row.row_index,
            mapping_id=mapping.id if mapping else None,
            mapping_version=mapping.version if mapping else None,
            source_label=(cells[mapping.label_column_id].raw_value if mapping else None),
            source_values=source_values, source_checksum=source_checksum,
            detail_type=mapping.detail_type if mapping else PayrollDetailType.UNMAPPED,
            canonical_code=mapping.canonical_code if mapping else None,
            canonical_name=mapping.canonical_name if mapping else None,
            category=mapping.category if mapping else None,
            amount=values["amount"], quantity=values["quantity"], rate=values["rate"],
            target_values=mapping.target_values if mapping else {},
            mapping_status=status, review_required=True,
        )

    @staticmethod
    def _source_checksum(table, row):
        source_values = [{
            "column_index": cell.column_index,
            "source_column_id": cell.source_column_id,
            "column_label": cell.column_label,
            "raw_value": cell.raw_value,
        } for cell in sorted(row.cells, key=lambda value: value.column_index)]
        return sha256_canonical({
            "table_checksum": table.source_checksum, "row_index": row.row_index,
            "page_number": row.page_number, "cells": source_values,
        })

    @classmethod
    def _current_source_checksums(cls, item):
        return {
            row.id: cls._source_checksum(table, row)
            for table in item.tables for row in table.rows
        }

    @classmethod
    def verify_sources(cls, item, snapshot):
        current = cls._current_source_checksums(item)
        return all(current.get(row.source_row_id) == row.source_checksum
                   for row in snapshot.rows)

    @staticmethod
    def mapping_checksum(rows):
        return sha256_canonical([{
            "source_row_id": str(row.source_row_id), "source_checksum": row.source_checksum,
            "mapping_id": str(row.mapping_id) if row.mapping_id else None,
            "mapping_version": row.mapping_version,
            "detail_type": row.detail_type.value, "canonical_code": row.canonical_code,
            "canonical_name": row.canonical_name, "category": row.category,
            "amount": str(row.amount) if row.amount is not None else None,
            "quantity": str(row.quantity) if row.quantity is not None else None,
            "rate": str(row.rate) if row.rate is not None else None,
            "target_values": row.target_values,
            "mapping_status": row.mapping_status.value,
        } for row in rows])

    @staticmethod
    def _mapped_rows(sync, organization_id, import_id):
        return list(sync.scalars(select(PayrollImportMappedDetail).where(
            PayrollImportMappedDetail.organization_id == organization_id,
            PayrollImportMappedDetail.payroll_import_id == import_id,
        ).order_by(PayrollImportMappedDetail.source_table_index,
                   PayrollImportMappedDetail.source_row_index)))

    @staticmethod
    def _latest_corrections(sync, organization_id, import_id):
        rows = list(sync.scalars(select(PayrollImportDetailCorrection).where(
            PayrollImportDetailCorrection.organization_id == organization_id,
            PayrollImportDetailCorrection.payroll_import_id == import_id,
        ).order_by(PayrollImportDetailCorrection.mapped_detail_id,
                   PayrollImportDetailCorrection.revision)))
        return {row.mapped_detail_id: row for row in rows}

    @classmethod
    def _ready(cls, mapped, corrections):
        if len(mapped) != len(corrections):
            return False
        identities = set()
        try:
            for mapped_row in mapped:
                correction = corrections.get(mapped_row.id)
                if (correction is None
                        or correction.source_checksum != mapped_row.source_checksum):
                    return False
                cls._validate_effective(correction)
                if not correction.ignored:
                    identity = (
                        correction.detail_type.value, correction.canonical_code,
                    )
                    if identity in identities:
                        return False
                    identities.add(identity)
        except PayrollDetailNotReadyError:
            return False
        return True

    @staticmethod
    def _mapped_list(import_id, checksum, rows):
        return PayrollMappedDetailList(import_id=import_id, count=len(rows),
                                       mapping_checksum=checksum, items=rows)

    @staticmethod
    def _review_read(review, mapped, corrections):
        current = list(corrections.values())
        resolved = sum(correction.source_checksum == next(
            row.source_checksum for row in mapped if row.id == correction.mapped_detail_id
        ) for correction in current) if mapped else 0
        return PayrollDetailReviewRead(
            import_id=review.payroll_import_id, status=review.status,
            row_version=review.row_version, mapping_checksum=review.mapping_checksum,
            current_snapshot_id=review.current_snapshot_id, mapped_count=len(mapped),
            corrected_count=len(current), unresolved_count=len(mapped) - resolved,
            corrections=[PayrollDetailCorrectionRead.model_validate(row) for row in current],
        )

    @staticmethod
    def _parse_optional(value):
        if value is None:
            return None
        try:
            return parse_typed_value(value, PayrollCanonicalValueType.DECIMAL).value
        except ValueParseError as exc:
            raise PayrollDetailNotReadyError("Detail numeric value is invalid") from exc

    @staticmethod
    def _validate_identity(detail_type, code, name, category, ignored):
        if ignored:
            if detail_type != PayrollDetailType.UNMAPPED:
                raise PayrollDetailNotReadyError("Ignored rows must remain UNMAPPED")
            return
        if detail_type == PayrollDetailType.UNMAPPED or not code or not name or not category:
            raise PayrollDetailNotReadyError("Mapped detail identity is incomplete")

    @classmethod
    def _validate_effective(cls, row):
        cls._validate_identity(row.detail_type, row.canonical_code, row.canonical_name,
                               row.category, row.ignored)
        if row.ignored:
            return
        if row.detail_type in {PayrollDetailType.EARNING, PayrollDetailType.DEDUCTION}:
            if row.amount is None or row.amount < 0:
                raise PayrollDetailNotReadyError("A non-negative detail amount is required")
        if row.detail_type == PayrollDetailType.EARNING:
            for key in ("sgk_subject_amount", "income_tax_subject_amount",
                        "stamp_tax_subject_amount"):
                value = cls._target_decimal(row.target_values, key, True)
                if value < 0:
                    raise PayrollDetailNotReadyError("Subject amounts must be non-negative")
        elif row.detail_type == PayrollDetailType.DEDUCTION:
            if not all(isinstance(row.target_values.get(key), bool)
                       for key in ("is_statutory", "is_sensitive")):
                raise PayrollDetailNotReadyError("Deduction flags require explicit review")
            if row.rate is not None and not Decimal("0") <= row.rate <= Decimal("1"):
                raise PayrollDetailNotReadyError("Deduction rate is outside 0..1")
        elif row.detail_type == PayrollDetailType.ABSENCE:
            if row.quantity is None or row.quantity <= 0:
                raise PayrollDetailNotReadyError("Absence day count must be positive")
            if not isinstance(row.target_values.get("is_paid"), bool):
                raise PayrollDetailNotReadyError("Absence paid status requires explicit review")

    @staticmethod
    def _target_decimal(values, key, required):
        raw = values.get(key)
        if raw is None:
            if required:
                raise PayrollDetailNotReadyError(f"{key} requires explicit review")
            return None
        if not isinstance(raw, str):
            raise PayrollDetailNotReadyError(f"{key} must be a decimal string")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise PayrollDetailNotReadyError(f"{key} is invalid") from exc
        if not value.is_finite() or value.as_tuple().exponent < -2:
            raise PayrollDetailNotReadyError(f"{key} exceeds supported precision")
        return value

    @staticmethod
    def _correction_payload(row):
        return {
            "id": str(row.id), "mapped_detail_id": str(row.mapped_detail_id),
            "source_checksum": row.source_checksum, "revision": row.revision,
            "detail_type": row.detail_type.value, "canonical_code": row.canonical_code,
            "canonical_name": row.canonical_name, "category": row.category,
            "amount": str(row.amount) if row.amount is not None else None,
            "quantity": str(row.quantity) if row.quantity is not None else None,
            "rate": str(row.rate) if row.rate is not None else None,
            "target_values": row.target_values, "ignored": row.ignored,
            "reason": row.reason,
            "reviewed_by_user_id": str(row.reviewed_by_user_id),
            "created_at": row.created_at.isoformat(),
        }

    @classmethod
    def _frozen_payload(cls, order, mapped, correction):
        return {
            "row_order": order,
            "source_table_id": str(mapped.source_table_id),
            "source_row_id": str(mapped.source_row_id),
            "correction_id": str(correction.id),
            "source_checksum": mapped.source_checksum,
            "detail_type": correction.detail_type.value,
            "canonical_code": correction.canonical_code,
            "canonical_name": correction.canonical_name,
            "category": correction.category,
            "amount": str(correction.amount) if correction.amount is not None else None,
            "quantity": str(correction.quantity) if correction.quantity is not None else None,
            "rate": str(correction.rate) if correction.rate is not None else None,
            "target_values": correction.target_values,
            "ignored": correction.ignored,
            "reviewed_by_user_id": str(correction.reviewed_by_user_id),
            "reviewed_at": correction.created_at.isoformat(),
        }

    @staticmethod
    def _snapshot(sync, organization_id, import_id, snapshot_id):
        if snapshot_id is None:
            return None
        return sync.scalar(select(PayrollImportDetailSnapshot).where(
            PayrollImportDetailSnapshot.id == snapshot_id,
            PayrollImportDetailSnapshot.organization_id == organization_id,
            PayrollImportDetailSnapshot.payroll_import_id == import_id,
        ).options(selectinload(PayrollImportDetailSnapshot.rows)))

    @classmethod
    def verify_snapshot(cls, snapshot):
        payload = [{
            "row_order": row.row_order, "source_table_id": str(row.source_table_id),
            "source_row_id": str(row.source_row_id),
            "correction_id": str(row.correction_id),
            "source_checksum": row.source_checksum,
            "detail_type": row.detail_type.value,
            "canonical_code": row.canonical_code, "canonical_name": row.canonical_name,
            "category": row.category,
            "amount": str(row.amount) if row.amount is not None else None,
            "quantity": str(row.quantity) if row.quantity is not None else None,
            "rate": str(row.rate) if row.rate is not None else None,
            "target_values": row.target_values, "ignored": row.ignored,
            "reviewed_by_user_id": str(row.reviewed_by_user_id),
            "reviewed_at": row.reviewed_at.isoformat(),
        } for row in snapshot.rows]
        expected = sha256_canonical({
            "mapping_checksum": snapshot.mapping_checksum,
            "corrections_checksum": snapshot.corrections_checksum,
            "rows": payload,
        })
        return snapshot.row_count == len(snapshot.rows) and expected == snapshot.snapshot_checksum

    @staticmethod
    def _materialization_read(sync, row):
        values = PayrollDetailMaterializationRead.model_validate({
            **{column.name: getattr(row, column.name) for column in row.__table__.columns},
            "earnings": list(sync.scalars(select(PayrollEarning).where(
                PayrollEarning.detail_materialization_id == row.id,
                PayrollEarning.organization_id == row.organization_id,
            ).order_by(PayrollEarning.id))),
            "deductions": list(sync.scalars(select(PayrollDeduction).where(
                PayrollDeduction.detail_materialization_id == row.id,
                PayrollDeduction.organization_id == row.organization_id,
            ).order_by(PayrollDeduction.id))),
            "absences": list(sync.scalars(select(PayrollAbsence).where(
                PayrollAbsence.detail_materialization_id == row.id,
                PayrollAbsence.organization_id == row.organization_id,
            ).order_by(PayrollAbsence.id))),
        })
        return values

    async def _commit(self, work):
        try:
            result = await self._session.run_sync(work)
            await self._session.commit()
            return result
        except IntegrityError as exc:
            await self._session.rollback()
            raise PayrollDetailIntegrityError() from exc
        except Exception:
            await self._session.rollback()
            raise


__all__ = ["PayrollDetailMappingService"]
