"""Préparation des opérations plateforme, sans accès aux données comptables."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.core.errors import BusinessRuleError, ForbiddenError, NotFoundError
from kora.db.tenant import bind_tenant, current_tenant
from kora.models.identity import Company
from kora.tenancy.module_config import require_platform_admin


@dataclass(frozen=True)
class ModuleClient:
    id: uuid.UUID
    legal_name: str


@dataclass(frozen=True)
class ModuleClientPage:
    items: list[ModuleClient]
    total: int
    limit: int
    offset: int


def _require_platform(session: Session, actor_id: uuid.UUID) -> None:
    if current_tenant(session) is not None:
        raise ForbiddenError("Contexte plateforme obligatoire.")
    require_platform_admin(session, actor_id)


def list_module_clients(
    session: Session, actor_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> ModuleClientPage:
    """Annuaire minimal paginé : aucun NIF, contact ou élément financier."""
    _require_platform(session, actor_id)
    if not 1 <= limit <= 200 or offset < 0:
        raise BusinessRuleError("Pagination invalide.")
    total = session.scalar(select(func.count()).select_from(Company)) or 0
    rows = session.execute(
        select(Company.id, Company.legal_name)
        .order_by(Company.legal_name, Company.id)
        .offset(offset)
        .limit(limit)
    )
    return ModuleClientPage(
        [ModuleClient(row.id, row.legal_name) for row in rows], total, limit, offset
    )


def bind_module_client(session: Session, actor_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """Prépare une session dédiée à une seule opération de configuration.

    L'appelant ferme la session après l'opération ; aucune permission métier
    n'est créée. Ne pas réutiliser cette session pour des routes comptables.
    """
    _require_platform(session, actor_id)
    if session.scalar(select(Company.id).where(Company.id == company_id)) is None:
        raise NotFoundError("Dossier introuvable.")
    bind_tenant(session, company_id)
