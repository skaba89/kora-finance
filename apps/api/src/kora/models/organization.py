"""Tables tenant de l'organisation : exercices comptables."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import created_at_column, uuid_pk


class FiscalYearStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FiscalYear(Base):
    __tablename__ = "fiscal_years"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), server_default=FiscalYearStatus.OPEN.value)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # Période verrouillée : aucune écriture datée de ce jour ou avant ne peut être créée,
    # modifiée ou validée (déclaration de TVA faite, mois arrêté…).
    locked_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("end_date > start_date", name="dates_ordered"),
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="status_valid"),
        CheckConstraint(
            "locked_until IS NULL OR locked_until BETWEEN start_date AND end_date",
            name="lock_within_year",
        ),
        # Deux exercices d'un même dossier ne peuvent pas se chevaucher.
        ExcludeConstraint(
            ("tenant_id", "="),
            (text("daterange(start_date, end_date, '[]')"), "&&"),
            name="fiscal_years_no_overlap",
            using="gist",
        ),
    )
