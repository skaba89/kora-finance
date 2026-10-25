"""Pièces justificatives attachées aux écritures (table tenant, RLS).

Le fichier est stocké chiffré hors de la base (service S3) ; la base conserve sa
référence, son empreinte SHA-256 (contrôle d'intégrité à chaque lecture) et la clé
de l'objet chiffrée par les clés maîtres. Garanties portées par la base (migration
0008) : une pièce n'est jamais modifiée, et la pièce d'une écriture validée ne peut
plus être supprimée (conservation des justificatifs).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, uuid_pk


class AttachmentType(StrEnum):
    PDF = "application/pdf"
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    entry_id: Mapped[uuid.UUID]
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        # Même fichier envoyé deux fois sur la même écriture (réessai en 3G) : une seule pièce.
        UniqueConstraint("tenant_id", "entry_id", "sha256"),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["journal_entries.tenant_id", "journal_entries.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')",
            name="content_type_valid",
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("length(trim(filename)) > 0", name="filename_not_blank"),
    )
