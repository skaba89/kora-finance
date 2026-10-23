"""Journal d'audit infalsifiable : une chaîne SHA-256 par dossier, plus une chaîne plateforme.

Chaque événement contient le hash du précédent ; modifier, supprimer ou insérer un
événement casse la chaîne et est détecté par `kora.audit.service.verify_chain`.
La table est en ajout seul : UPDATE/DELETE refusés par trigger et par privilèges.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base

# Hash précédent du premier événement d'une chaîne.
GENESIS_HASH = "0" * 64


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # NULL = chaîne plateforme (connexions, comptes utilisateurs…).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column()
    seq: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        # Unicité de la séquence par chaîne (NULL = plateforme traité comme une valeur).
        UniqueConstraint("tenant_id", "seq", postgresql_nulls_not_distinct=True),
        Index("ix_audit_events_tenant_occurred", "tenant_id", "occurred_at"),
    )


class AuditChainHead(Base):
    """Tête de chaîne : verrouillée (FOR UPDATE) pour sérialiser les ajouts par chaîne."""

    __tablename__ = "audit_chain_heads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column()
    last_seq: Mapped[int] = mapped_column(BigInteger)
    last_hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("tenant_id", postgresql_nulls_not_distinct=True),)
