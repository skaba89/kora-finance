"""Cas d'usage : consultation et personnalisation du plan comptable, taux de taxes."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.auth.service import RequestContext
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account, TaxRate
from kora.models.common import utcnow

MAX_ACCOUNT_DIGITS = 12


@dataclass(frozen=True)
class Actor:
    company_id: uuid.UUID
    user_id: uuid.UUID


def _audit(
    session: Session,
    actor: Actor,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict[str, object],
    ctx: RequestContext,
) -> None:
    record_event(
        session,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        actor_user_id=actor.user_id,
        ip_address=ctx.ip_address,
    )


# --- Plan comptable


def _accounts_query(
    company_id: uuid.UUID, search: str | None, account_class: int | None, active_only: bool
) -> Select[Account]:
    query = select(Account).where(Account.tenant_id == company_id)
    if account_class is not None:
        query = query.where(Account.number.startswith(str(account_class)))
    if active_only:
        query = query.where(Account.is_active.is_(True))
    if search:
        term = search.strip()
        if term.isdigit():
            query = query.where(Account.number.startswith(term))
        else:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Account.label.ilike(f"%{escaped}%", escape="\\"))
    return query


def list_accounts(
    session: Session,
    company_id: uuid.UUID,
    *,
    search: str | None,
    account_class: int | None,
    active_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[Account], int]:
    query = _accounts_query(company_id, search, account_class, active_only)
    total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    items = session.execute(query.order_by(Account.number).limit(limit).offset(offset)).scalars()
    return list(items), total


def create_account(
    session: Session, actor: Actor, *, number: str, label: str, ctx: RequestContext
) -> Account:
    """Crée un sous-compte. Il doit se rattacher à un compte existant du plan
    (son numéro commence par celui d'un compte existant)."""
    number = number.strip()
    if not number.isdigit() or number.startswith("0"):
        raise BusinessRuleError("Le numéro de compte ne doit contenir que des chiffres.")
    if len(number) > MAX_ACCOUNT_DIGITS:
        raise BusinessRuleError(f"Le numéro de compte est limité à {MAX_ACCOUNT_DIGITS} chiffres.")
    if number.startswith("9"):
        raise BusinessRuleError("La classe 9 n'est pas gérée par le plan comptable du dossier.")
    prefixes = [number[:i] for i in range(1, len(number))]
    parent = session.execute(
        select(Account)
        .where(Account.tenant_id == actor.company_id, Account.number.in_(prefixes))
        .order_by(func.length(Account.number).desc())
        .limit(1)
    ).scalar_one_or_none()
    if parent is None:
        raise BusinessRuleError("Ce numéro ne se rattache à aucun compte du plan.")
    account = Account(tenant_id=actor.company_id, number=number, label=label.strip())
    session.add(account)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"Le compte {number} existe déjà.") from exc
    _audit(
        session,
        actor,
        action="account.created",
        entity_type="account",
        entity_id=account.id,
        payload={"numero": number, "libelle": account.label, "parent": parent.number},
        ctx=ctx,
    )
    session.commit()
    return account


def update_account(
    session: Session,
    actor: Actor,
    account_id: uuid.UUID,
    *,
    label: str | None,
    is_active: bool | None,
    ctx: RequestContext,
) -> Account:
    account = session.execute(
        select(Account).where(Account.id == account_id, Account.tenant_id == actor.company_id)
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("Compte introuvable.")
    changes: dict[str, object] = {}
    if label is not None and label.strip() != account.label:
        if account.reference is not None:
            raise BusinessRuleError(
                "Le libellé d'un compte du référentiel SYSCOHADA n'est pas modifiable ; "
                "créez un sous-compte avec votre propre libellé."
            )
        changes["libelle"] = {"avant": account.label, "apres": label.strip()}
        account.label = label.strip()
    if is_active is not None and is_active != account.is_active:
        changes["actif"] = {"avant": account.is_active, "apres": is_active}
        account.is_active = is_active
    if changes:
        _audit(
            session,
            actor,
            action="account.updated",
            entity_type="account",
            entity_id=account.id,
            payload={"numero": account.number, **changes},
            ctx=ctx,
        )
    session.commit()
    return account


# --- Taux de taxes


def list_tax_rates(session: Session, company_id: uuid.UUID) -> list[TaxRate]:
    return list(
        session.execute(
            select(TaxRate)
            .where(TaxRate.tenant_id == company_id)
            .order_by(TaxRate.code, TaxRate.valid_from.desc())
        ).scalars()
    )


@dataclass(frozen=True)
class TaxRateData:
    code: str
    label: str
    kind: str
    rate_basis_points: int
    valid_from: date
    collected_account_number: str | None
    deductible_account_number: str | None
    note: str | None


def _check_account_exists(session: Session, company_id: uuid.UUID, number: str | None) -> None:
    if number is None:
        return
    exists = session.execute(
        select(Account.id).where(Account.tenant_id == company_id, Account.number == number)
    ).scalar_one_or_none()
    if exists is None:
        raise BusinessRuleError(f"Le compte {number} n'existe pas dans le plan du dossier.")


def add_tax_rate_version(
    session: Session, actor: Actor, data: TaxRateData, ctx: RequestContext
) -> TaxRate:
    """Ajoute un taux, ou une nouvelle version datée d'un taux existant.

    La version en cours est close la veille de `valid_from`. Une version ne peut pas
    être insérée dans le passé d'une autre (pas de réécriture de l'historique fiscal).
    """
    _check_account_exists(session, actor.company_id, data.collected_account_number)
    _check_account_exists(session, actor.company_id, data.deductible_account_number)
    current = (
        session.execute(
            select(TaxRate)
            .where(
                TaxRate.tenant_id == actor.company_id,
                TaxRate.code == data.code,
                or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= data.valid_from),
            )
            .order_by(TaxRate.valid_from.desc())
            .with_for_update()
        )
        .scalars()
        .all()
    )
    if len(current) > 1 or (current and current[0].valid_from >= data.valid_from):
        raise ConflictError(
            "Une version de ce taux s'applique déjà à cette date ou après : la nouvelle "
            "version doit commencer après la version en cours."
        )
    if current:
        current[0].valid_to = data.valid_from - timedelta(days=1)

    rate = TaxRate(
        tenant_id=actor.company_id,
        code=data.code,
        label=data.label.strip(),
        kind=data.kind,
        rate_basis_points=data.rate_basis_points,
        valid_from=data.valid_from,
        collected_account_number=data.collected_account_number,
        deductible_account_number=data.deductible_account_number,
        note=data.note,
        # Saisi par un utilisateur habilité : considéré comme vérifié par lui.
        verified_at=utcnow(),
        verified_by_user_id=actor.user_id,
    )
    session.add(rate)
    session.flush()
    _audit(
        session,
        actor,
        action="tax_rate.version_added",
        entity_type="tax_rate",
        entity_id=rate.id,
        payload={
            "code": rate.code,
            "taux_points_de_base": rate.rate_basis_points,
            "valable_du": rate.valid_from.isoformat(),
            "version_precedente": str(current[0].id) if current else None,
        },
        ctx=ctx,
    )
    session.commit()
    return rate


def verify_tax_rate(
    session: Session, actor: Actor, tax_rate_id: uuid.UUID, ctx: RequestContext
) -> TaxRate:
    """Confirme qu'un taux par défaut a été vérifié (auprès de la DGI) par l'utilisateur."""
    rate = session.execute(
        select(TaxRate).where(TaxRate.id == tax_rate_id, TaxRate.tenant_id == actor.company_id)
    ).scalar_one_or_none()
    if rate is None:
        raise NotFoundError("Taux introuvable.")
    if rate.verified_at is None:
        rate.verified_at = utcnow()
        rate.verified_by_user_id = actor.user_id
        _audit(
            session,
            actor,
            action="tax_rate.verified",
            entity_type="tax_rate",
            entity_id=rate.id,
            payload={"code": rate.code, "taux_points_de_base": rate.rate_basis_points},
            ctx=ctx,
        )
    session.commit()
    return rate
