"""Contexte tenant appliqué à PostgreSQL pour la Row-Level Security.

Le tenant courant est mémorisé dans `session.info` et réappliqué au début de *chaque*
transaction via `set_config('app.tenant_id', …, true)` (portée : la transaction). Une
connexion rendue au pool ne garde donc jamais le tenant d'une requête précédente, et
une session sans tenant ne voit aucune ligne des tables tenant (échec fermé).
"""

import uuid

from sqlalchemy import Connection, event, text
from sqlalchemy.orm import Session, SessionTransaction

_TENANT_KEY = "kora_tenant_id"
_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


def _apply(connection: Connection, tenant_id: uuid.UUID | None) -> None:
    connection.execute(_SET_TENANT, {"tenant_id": str(tenant_id) if tenant_id else ""})


@event.listens_for(Session, "after_begin")
def _apply_tenant_on_begin(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    _apply(connection, session.info.get(_TENANT_KEY))


def bind_tenant(session: Session, tenant_id: uuid.UUID | None) -> None:
    """Fixe (ou retire, avec None) le tenant de la session, y compris en cours de transaction."""
    session.info[_TENANT_KEY] = tenant_id
    if session.in_transaction():
        _apply(session.connection(), tenant_id)


def current_tenant(session: Session) -> uuid.UUID | None:
    tenant_id = session.info.get(_TENANT_KEY)
    if tenant_id is not None and not isinstance(tenant_id, uuid.UUID):
        raise TypeError(f"Contexte tenant invalide : {tenant_id!r}")
    return tenant_id
