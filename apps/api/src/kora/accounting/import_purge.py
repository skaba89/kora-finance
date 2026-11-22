"""Maintenance interne des imports expirés (jamais des écritures comptables)."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.identity import Company
from kora.models.imports import ImportBatch
from kora.storage import objects


def purge_expired_imports(company_id: uuid.UUID, *, limit: int = 100) -> int:
    """Purge bornée, par dossier, destinée exclusivement au worker de confiance.

    Le verrou du dossier est celui utilisé par le dépôt. La référence n'est
    supprimée qu'après confirmation S3 ; un rollback conserve la possibilité
    de réessayer la suppression idempotente. Aucun accès hors RLS.
    """
    if not 1 <= limit <= 100:
        raise ValueError("La limite de purge doit être comprise entre 1 et 100.")
    cutoff = utcnow()
    with get_sessionmaker()() as session:
        bind_tenant(session, company_id)
        ids = list(
            session.scalars(
                select(ImportBatch.id)
                .where(ImportBatch.tenant_id == company_id, ImportBatch.expires_at <= cutoff)
                .order_by(ImportBatch.expires_at, ImportBatch.id)
                .limit(limit)
            )
        )
    removed = 0
    for batch_id in ids:
        with get_sessionmaker()() as session, session.begin():
            bind_tenant(session, company_id)
            company = session.scalar(
                select(Company.id).where(Company.id == company_id).with_for_update()
            )
            if company is None:
                break
            batch = session.scalar(
                select(ImportBatch)
                .where(
                    ImportBatch.tenant_id == company_id,
                    ImportBatch.id == batch_id,
                    ImportBatch.expires_at <= cutoff,
                )
                .with_for_update()
            )
            if batch is None:
                continue
            objects.delete(batch.storage_key)
            session.delete(batch)
        removed += 1
    return removed


def purge_orphan_page(
    company_id: uuid.UUID, *, cursor: str | None = None
) -> tuple[int, str | None]:
    """Réconcilie une page d'objets d'un dossier existant, sans toucher aux pièces.

    Délai de grâce de 48 h et vérification sous le verrou du dépôt : un objet
    référencé, même expiré, relève exclusivement de la purge des références.
    Un dossier absent n'est pas traité par ce service tenant.
    """
    prefix = f"imports/{company_id}/"
    cutoff = utcnow() - timedelta(hours=48)
    candidates, next_cursor = objects.list_page(prefix, cursor=cursor)
    removed = 0
    for key, modified in candidates:
        if modified.tzinfo is None or modified > cutoff or not key.startswith(prefix):
            continue
        try:
            batch_id = uuid.UUID(key.removeprefix(prefix))
        except ValueError:
            continue
        if key != f"{prefix}{batch_id}":
            continue
        with get_sessionmaker()() as session, session.begin():
            bind_tenant(session, company_id)
            company = session.scalar(
                select(Company.id).where(Company.id == company_id).with_for_update()
            )
            if company is None:
                return removed, None
            existing = session.scalar(
                select(ImportBatch.id).where(
                    ImportBatch.tenant_id == company_id, ImportBatch.id == batch_id
                )
            )
            if existing is not None:
                continue
            objects.delete(key)
        removed += 1
    return removed, next_cursor
