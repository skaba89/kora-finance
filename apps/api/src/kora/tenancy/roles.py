"""Rôles RBAC de la plateforme (cahier des charges, section « Clients et rôles »)."""

from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    CABINET_ADMIN = "CABINET_ADMIN"
    CABINET_COLLABORATEUR = "CABINET_COLLABORATEUR"
    PME_DIRIGEANT = "PME_DIRIGEANT"
    PME_COMPTABLE = "PME_COMPTABLE"
    PME_LECTEUR = "PME_LECTEUR"
    PARTENAIRE_FINANCIER = "PARTENAIRE_FINANCIER"


# Rôles attribuables directement sur un dossier d'entreprise.
COMPANY_ROLES = (Role.PME_DIRIGEANT, Role.PME_COMPTABLE, Role.PME_LECTEUR)
# Rôles au sein d'un cabinet comptable.
FIRM_ROLES = (Role.CABINET_ADMIN, Role.CABINET_COLLABORATEUR)
