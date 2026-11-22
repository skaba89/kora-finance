"""Périodes commerciales persistées, sans effet sur les autorisations métier."""

import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, ForeignKeyConstraint, String, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base
from kora.models.common import uuid_pk


class CommercialLicensePeriod(Base):
    __tablename__ = "commercial_license_periods"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    offer_code: Mapped[str] = mapped_column(String(64))
    offer_version: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(16))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    suspended: Mapped[bool] = mapped_column(server_default=text("false"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["offer_code", "offer_version"],
            ["commercial_offer_versions.code", "commercial_offer_versions.version"],
        ),
        CheckConstraint("ends_on > starts_on", name="dates_ordered"),
        CheckConstraint("kind IN ('trial', 'paid')", name="kind_valid"),
        ExcludeConstraint(
            ("tenant_id", "="),
            (text("daterange(starts_on, ends_on, '[)')"), "&&"),
            name="commercial_license_periods_no_overlap",
            using="gist",
        ),
    )
