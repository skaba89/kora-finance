"""Versions commerciales globales, sans données comptables ni droits tenant."""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from kora.db.base import Base


class CommercialOfferVersion(Base):
    __tablename__ = "commercial_offer_versions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    modules: Mapped[list[str]] = mapped_column(ARRAY(String(32)))

    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("code <> '' AND code = btrim(code)", name="code_valid"),
        CheckConstraint("cardinality(modules) > 0", name="modules_nonempty"),
        CheckConstraint("array_position(modules, NULL) IS NULL", name="modules_not_null"),
    )
