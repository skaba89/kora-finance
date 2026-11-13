"""Matrice des permissions par rôle sur un dossier d'entreprise.

Source de vérité unique : le backend décide, le frontend ne fait que masquer.
`docs/PERMISSIONS.md` est généré depuis ce module (`make permissions-doc`) et la CI
vérifie qu'il est à jour.

SUPER_ADMIN et PARTENAIRE_FINANCIER n'ont *aucune* permission sur un dossier :
- l'administrateur plateforme ne lit pas la comptabilité des clients (confidentialité) ;
- le partenaire financier n'accède qu'aux dossiers de financement explicitement
  partagés (phase 6), jamais au dossier lui-même.
"""

from enum import StrEnum

from kora.tenancy.roles import Role


class Permission(StrEnum):
    COMPANY_READ = "company:read"
    COMPANY_UPDATE = "company:update"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    FISCAL_YEARS_READ = "fiscal_years:read"
    FISCAL_YEARS_MANAGE = "fiscal_years:manage"
    FISCAL_YEARS_CLOSE = "fiscal_years:close"
    ACCOUNTS_READ = "accounts:read"
    ACCOUNTS_MANAGE = "accounts:manage"
    TAXES_READ = "taxes:read"
    TAXES_MANAGE = "taxes:manage"
    AUDIT_READ = "audit:read"
    JOURNALS_MANAGE = "journals:manage"
    ENTRIES_READ = "entries:read"
    ENTRIES_WRITE = "entries:write"
    ENTRIES_POST = "entries:post"
    LETTERING_MANAGE = "lettering:manage"
    TREASURY_READ = "treasury:read"
    TREASURY_MANAGE = "treasury:manage"
    PARTNERS_READ = "partners:read"
    PARTNERS_MANAGE = "partners:manage"


DESCRIPTIONS: dict[Permission, str] = {
    Permission.COMPANY_READ: "Consulter la fiche de l'entreprise",
    Permission.COMPANY_UPDATE: "Modifier la fiche de l'entreprise (raison sociale, RCCM, NIF…)",
    Permission.MEMBERS_READ: "Voir les utilisateurs ayant accès au dossier",
    Permission.MEMBERS_MANAGE: "Ajouter, modifier ou retirer des utilisateurs du dossier",
    Permission.FISCAL_YEARS_READ: "Consulter les exercices comptables",
    Permission.FISCAL_YEARS_MANAGE: "Créer des exercices et verrouiller des périodes",
    Permission.FISCAL_YEARS_CLOSE: "Clôturer, rouvrir un exercice et déverrouiller une période",
    Permission.ACCOUNTS_READ: "Consulter le plan comptable",
    Permission.ACCOUNTS_MANAGE: "Personnaliser le plan comptable",
    Permission.TAXES_READ: "Consulter les taux de taxes",
    Permission.TAXES_MANAGE: "Paramétrer les taux de taxes",
    Permission.AUDIT_READ: "Consulter et vérifier le journal d'audit",
    Permission.JOURNALS_MANAGE: "Créer et paramétrer les journaux comptables",
    Permission.ENTRIES_READ: "Consulter les journaux et les écritures",
    Permission.ENTRIES_WRITE: "Saisir et modifier des écritures en brouillon",
    Permission.ENTRIES_POST: "Valider des écritures (numérotation définitive) et les contre-passer",
    Permission.LETTERING_MANAGE: "Lettrer et délettrer les comptes de tiers",
    Permission.TREASURY_READ: (
        "Consulter les comptes de trésorerie (banques, caisses, Mobile Money) et leurs mouvements"
    ),
    Permission.TREASURY_MANAGE: (
        "Créer des comptes de trésorerie et enregistrer dépôts, retraits, "
        "frais et virements internes"
    ),
    Permission.PARTNERS_READ: "Consulter le référentiel des tiers (clients, fournisseurs)",
    Permission.PARTNERS_MANAGE: "Créer, modifier et désactiver des tiers",
}

_READ = frozenset(
    {
        Permission.COMPANY_READ,
        Permission.FISCAL_YEARS_READ,
        Permission.ACCOUNTS_READ,
        Permission.TAXES_READ,
        Permission.ENTRIES_READ,
        Permission.TREASURY_READ,
        Permission.PARTNERS_READ,
    }
)
_ACCOUNTING = _READ | {
    Permission.MEMBERS_READ,
    Permission.FISCAL_YEARS_MANAGE,
    Permission.ACCOUNTS_MANAGE,
    Permission.TAXES_MANAGE,
    Permission.JOURNALS_MANAGE,
    Permission.ENTRIES_WRITE,
    Permission.ENTRIES_POST,
    Permission.LETTERING_MANAGE,
    Permission.TREASURY_MANAGE,
    Permission.PARTNERS_MANAGE,
}
_FULL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.SUPER_ADMIN: frozenset(),
    Role.CABINET_ADMIN: _FULL,
    Role.CABINET_COLLABORATEUR: _ACCOUNTING,
    Role.PME_DIRIGEANT: _FULL,
    Role.PME_COMPTABLE: _ACCOUNTING | {Permission.AUDIT_READ},
    Role.PME_LECTEUR: _READ,
    Role.PARTENAIRE_FINANCIER: frozenset(),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def render_markdown() -> str:
    """Matrice lisible, committée dans docs/PERMISSIONS.md."""
    roles = list(Role)
    lines = [
        "# Matrice des permissions",
        "",
        "> Fichier généré depuis `apps/api/src/kora/tenancy/permissions.py` "
        "(`make permissions-doc`). Ne pas modifier à la main.",
        "",
        "| Permission | Description | " + " | ".join(r.value for r in roles) + " |",
        "|---|---|" + "|".join(":-:" for _ in roles) + "|",
    ]
    for permission in Permission:
        cells = ["✅" if permission in ROLE_PERMISSIONS[r] else "—" for r in roles]
        lines.append(
            f"| `{permission.value}` | {DESCRIPTIONS[permission]} | " + " | ".join(cells) + " |"
        )
    lines += [
        "",
        "SUPER_ADMIN : aucune permission sur les dossiers (administration de la plateforme "
        "uniquement). PARTENAIRE_FINANCIER : accès limité aux dossiers de financement "
        "partagés (phase 6).",
        "",
    ]
    return "\n".join(lines)
