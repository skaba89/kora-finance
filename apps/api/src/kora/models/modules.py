"""Choix explicites de modules par tenant (les valeurs par défaut restent dans le catalogue)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base


class TenantModuleOverride(Base):
    __tablename__ = "tenant_module_overrides"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    module: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column()
    revision: Mapped[int] = mapped_column()
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint("module ~ '^[a-z][a-z_]{0,31}$'", name="module_key_valid"),
    )
