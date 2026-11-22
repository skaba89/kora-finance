"""Cycle de vie commercial pur, sans effet sur les permissions ou les données."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class LicenseKind(StrEnum):
    TRIAL = "trial"
    PAID = "paid"


class LicenseStatus(StrEnum):
    SCHEDULED = "scheduled"
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True, kw_only=True)
class LicensePeriod:
    """Période contractuelle d'un dossier, liée à une version d'offre.

    Dates civiles explicites, début inclus et fin exclue. Aucun accès métier
    n'est déterminé par ce modèle ; aucun paiement n'est enregistré.
    """

    tenant_id: UUID
    offer_code: str
    offer_version: int
    kind: LicenseKind
    starts_on: date
    ends_on: date
    suspended: bool = False

    def __post_init__(self) -> None:
        if not self.offer_code or self.offer_code != self.offer_code.strip():
            raise ValueError("Code d'offre invalide.")
        if type(self.offer_version) is not int or self.offer_version < 1:
            raise ValueError("Version d'offre invalide.")
        if not isinstance(self.kind, LicenseKind):
            raise ValueError("Type de licence invalide.")
        if type(self.starts_on) is not date or type(self.ends_on) is not date:
            raise ValueError("Dates civiles requises.")
        if self.ends_on <= self.starts_on:
            raise ValueError("Période de licence invalide.")

    def status_on(self, day: date) -> LicenseStatus:
        """Calcul déterministe, sans horloge implicite ni mutation."""
        if type(day) is not date:
            raise ValueError("Date civile requise.")
        if day < self.starts_on:
            return LicenseStatus.SCHEDULED
        if day >= self.ends_on:
            return LicenseStatus.EXPIRED
        if self.suspended:
            return LicenseStatus.SUSPENDED
        if self.kind == LicenseKind.TRIAL:
            return LicenseStatus.TRIAL
        return LicenseStatus.ACTIVE
