"""Métadonnées des fichiers d'import comptable en attente de traitement."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, uuid_pk


class ImportBatch(Base):
    """Référence d'un objet chiffré, jamais le contenu du fichier en clair."""

    __tablename__ = "accounting_import_batches"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    format: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    delimiter: Mapped[str] = mapped_column(String(4))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "sha256", "format", "currency", "delimiter"),
        CheckConstraint("format IN ('csv', 'fec', 'xlsx')", name="format_valid"),
        CheckConstraint("currency = 'GNF'", name="currency_valid"),
        CheckConstraint(
            "(format = 'fec' AND delimiter IN ('PIPE', 'TAB')) OR "
            "(format <> 'fec' AND delimiter = 'NONE')",
            name="delimiter_valid",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= CASE WHEN format = 'xlsx' "
            "THEN 16777216 ELSE 33554432 END",
            name="size_valid",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("expires_at > created_at", name="expiry_valid"),
        CheckConstraint(
            "storage_key = 'imports/' || tenant_id::text || '/' || id::text",
            name="storage_key_valid",
        ),
        CheckConstraint("octet_length(wrapped_key) > 0", name="wrapped_key_present"),
        Index("ix_accounting_import_batches_tenant_expiry", "tenant_id", "expires_at"),
    )
