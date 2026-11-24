"""Autorisation plateforme, état concurrent et audit des suspensions."""

import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from kora.audit.service import verify_chain
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.identity import User
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.license_suspension import change_license_suspension
from tests.conftest import CompanyFixture, UserFixture


def test_suspension_reactivation_audit_et_rollback(
    db: Session,
    owner_engine: Engine,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    company, other = make_company(), make_company()
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    identifier = uuid.uuid4()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as owner:
        bind_tenant(owner, company.id)
        owner.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        owner.flush()
        owner.add(
            CommercialLicensePeriod(
                id=identifier,
                tenant_id=company.id,
                offer_code=code,
                offer_version=1,
                kind="paid",
                starts_on=date(2027, 1, 1),
                ends_on=date(2027, 2, 1),
            )
        )
        owner.commit()

    def change(value: bool, expected: bool) -> bool:
        bind_tenant(db, None)
        return change_license_suspension(
            db,
            actor_id=admin.id,
            company_id=company.id,
            license_id=identifier,
            suspended=value,
            expected_suspended=expected,
            reason="Recette sécurité",
        )

    with pytest.raises(ForbiddenError):
        change_license_suspension(
            db,
            actor_id=other.owner.id,
            company_id=company.id,
            license_id=identifier,
            suspended=True,
            expected_suspended=False,
            reason="Recette sécurité",
        )
    bind_tenant(db, other.id)
    with pytest.raises(ForbiddenError):
        change_license_suspension(
            db,
            actor_id=admin.id,
            company_id=company.id,
            license_id=identifier,
            suspended=True,
            expected_suspended=False,
            reason="Recette sécurité",
        )
    bind_tenant(db, None)
    with pytest.raises(NotFoundError):
        change_license_suspension(
            db,
            actor_id=admin.id,
            company_id=other.id,
            license_id=identifier,
            suspended=True,
            expected_suspended=False,
            reason="Recette sécurité",
        )
    assert change(True, False)
    assert db.get_one(CommercialLicensePeriod, identifier).suspended is True
    with pytest.raises(ConflictError):
        change(False, False)
    assert not change(True, True)
    assert verify_chain(db).ok
    assert change(False, True)
    assert verify_chain(db).ok
    reactivated = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "commercial.license_reactivated",
            AuditEvent.entity_id == str(identifier),
        )
    )
    assert reactivated is not None
    assert reactivated.payload["reason"] == "Recette sécurité"
    assert (
        db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "commercial.license_reactivated",
                AuditEvent.entity_id == str(identifier),
                AuditEvent.tenant_id == company.id,
            )
        )
        is not None
    )
    db.rollback()
    bind_tenant(db, company.id)
    assert db.get_one(CommercialLicensePeriod, identifier).suspended is False


def test_privileges_suspension_colonne_seule(db: Session) -> None:
    rights = db.execute(
        text("""
        SELECT has_column_privilege('commercial_license_periods', 'suspended', 'UPDATE'),
               has_column_privilege('commercial_license_periods', 'starts_on', 'UPDATE'),
               has_column_privilege('commercial_license_periods', 'tenant_id', 'UPDATE'),
               has_table_privilege('commercial_license_periods', 'DELETE')
        """)
    ).one()
    assert tuple(rights) == (True, False, False, False)


@pytest.mark.parametrize("reason", ["", "  ab  ", "x" * 501, "motif\x00nul", 12])
def test_suspension_exige_motif_valide_avant_acces(db: Session, reason: object) -> None:
    with pytest.raises(BusinessRuleError):
        change_license_suspension(
            db,
            actor_id=uuid.uuid4(),
            company_id=uuid.uuid4(),
            license_id=uuid.uuid4(),
            suspended=True,
            expected_suspended=False,
            reason=reason,  # type: ignore[arg-type]
        )


def test_suspension_refuse_type_non_booleen(db: Session) -> None:
    with pytest.raises(BusinessRuleError):
        change_license_suspension(
            db,
            actor_id=uuid.uuid4(),
            company_id=uuid.uuid4(),
            license_id=uuid.uuid4(),
            suspended=1,  # type: ignore[arg-type]
            expected_suspended=False,
            reason="Recette sécurité",
        )
