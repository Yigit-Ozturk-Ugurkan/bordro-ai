"""PostgreSQL constraints and state-machine tests for V2.1A imports."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import PayrollImportStateConflictError
from app.models.enums import (
    PayrollImportFieldReviewStatus,
    PayrollImportStatus,
)
from app.models.organization import Organization
from app.models.payroll_import import (
    PayrollImport,
    PayrollImportDocument,
    PayrollImportField,
)
from app.models.user import User
from app.services.imports.state_machine import VALID_TRANSITIONS, transition


def add_user(session: Session, organization: Organization) -> User:
    user = User(
        id=uuid4(), organization_id=organization.id,
        email=f"import-{uuid4().hex}@test.invalid", password_hash="unused",
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def add_import(session: Session, organization: Organization, user: User,
               digest: str = "a" * 64) -> tuple[PayrollImport, PayrollImportDocument]:
    import_id = uuid4()
    document_id = uuid4()
    item = PayrollImport(
        id=import_id, organization_id=organization.id,
        uploaded_by_user_id=user.id, status=PayrollImportStatus.UPLOADED,
        source_type="DOCUMENT_UPLOAD", reader_provider="GENERAL_READER",
        source_document_id=document_id, content_sha256=digest,
        reader_table_count=0, reader_warnings=[], processing_attempt=0,
    )
    document = PayrollImportDocument(
        id=document_id, organization_id=organization.id,
        payroll_import_id=import_id, file_id=uuid4(),
        original_filename="generic.png", declared_mime_type="image/png",
        detected_mime_type="image/png", size_bytes=10, sha256=digest,
        storage_provider="LOCAL", storage_key=f"aa/{uuid4().hex}",
    )
    session.add_all([item, document])
    session.flush()
    return item, document


def test_import_creation_and_document_relationship(
    db_session: Session, sample_organization: Organization
):
    user = add_user(db_session, sample_organization)
    item, document = add_import(db_session, sample_organization, user)
    db_session.refresh(item)
    assert item.organization_id == sample_organization.id
    assert item.source_document_id == document.id
    assert item.documents[0].id == document.id
    assert document.payroll_import.id == item.id


def test_field_relationship_preserves_generic_observation(
    db_session: Session, sample_organization: Organization
):
    user = add_user(db_session, sample_organization)
    item, document = add_import(db_session, sample_organization, user)
    field = PayrollImportField(
        organization_id=sample_organization.id,
        payroll_import_id=item.id,
        payroll_import_document_id=document.id,
        source_field_id="generic-field", source_label="Generic field",
        source_text="Observed 12.34", raw_value="12.34",
        normalized_value="12.34", value_type="money",
        confidence="0.90000000", page_number=1,
        bbox=["0.1", "0.2", "0.3", "0.4"],
        coordinate_space="normalized_xyxy", extraction_source="rule",
        rule_index=0, review_status=PayrollImportFieldReviewStatus.UNREVIEWED,
    )
    db_session.add(field)
    db_session.flush()
    assert field.document.id == document.id
    assert field.payroll_import.id == item.id
    assert not hasattr(field, "canonical_key")


def test_document_organization_must_match_import(
    db_session: Session, sample_organization: Organization
):
    user = add_user(db_session, sample_organization)
    item, _ = add_import(db_session, sample_organization, user)
    other = Organization(
        id=uuid4(), name="Other", code=f"OTHER-{uuid4().hex[:8]}",
        timezone="Europe/Istanbul", is_active=True,
    )
    db_session.add(other)
    db_session.flush()
    bad = PayrollImportDocument(
        id=uuid4(), organization_id=other.id, payroll_import_id=item.id,
        file_id=uuid4(), original_filename="bad.png",
        declared_mime_type="image/png", detected_mime_type="image/png",
        size_bytes=1, sha256="b" * 64, storage_provider="LOCAL",
        storage_key=f"bb/{uuid4().hex}",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError, match="fk_import_document_import_org"):
        db_session.flush()


def test_duplicate_hash_same_organization_rejected(
    db_session: Session, sample_organization: Organization
):
    user = add_user(db_session, sample_organization)
    add_import(db_session, sample_organization, user, "c" * 64)
    with pytest.raises(IntegrityError, match="uq_payroll_import_org_content_sha256"):
        add_import(db_session, sample_organization, user, "c" * 64)


def test_same_hash_different_organizations_isolated(
    db_session: Session, sample_organization: Organization
):
    first_user = add_user(db_session, sample_organization)
    add_import(db_session, sample_organization, first_user, "d" * 64)
    other = Organization(
        id=uuid4(), name="Other", code=f"OTHER-{uuid4().hex[:8]}",
        timezone="Europe/Istanbul", is_active=True,
    )
    db_session.add(other)
    db_session.flush()
    other_user = add_user(db_session, other)
    second, _ = add_import(db_session, other, other_user, "d" * 64)
    assert second.organization_id == other.id


@pytest.mark.parametrize(
    ("source", "target"),
    [(source, target) for source, targets in VALID_TRANSITIONS.items() for target in targets],
)
def test_every_declared_state_transition_is_valid(source, target):
    item = PayrollImport(status=source)
    transition(item, target)
    assert item.status == target


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (PayrollImportStatus.UPLOADED, PayrollImportStatus.EXTRACTED),
        (PayrollImportStatus.EXTRACTED, PayrollImportStatus.PROCESSING),
        (PayrollImportStatus.REVIEW_REQUIRED, PayrollImportStatus.PROCESSING),
        (PayrollImportStatus.REJECTED, PayrollImportStatus.PROCESSING),
        (PayrollImportStatus.FAILED, PayrollImportStatus.EXTRACTED),
    ],
)
def test_illegal_state_transitions_are_rejected(source, target):
    item = PayrollImport(status=source)
    with pytest.raises(PayrollImportStateConflictError):
        transition(item, target)


def test_failed_import_remains_durable_and_can_retry(
    db_session: Session, sample_organization: Organization
):
    user = add_user(db_session, sample_organization)
    item, document = add_import(db_session, sample_organization, user)
    transition(item, PayrollImportStatus.PROCESSING)
    transition(item, PayrollImportStatus.FAILED)
    item.last_error_code = "GENERAL_READER_UNAVAILABLE"
    db_session.flush()
    db_session.expire_all()
    stored = db_session.get(PayrollImport, item.id)
    assert stored.status == PayrollImportStatus.FAILED
    assert stored.documents[0].id == document.id
    transition(stored, PayrollImportStatus.PROCESSING)
    assert stored.status == PayrollImportStatus.PROCESSING
