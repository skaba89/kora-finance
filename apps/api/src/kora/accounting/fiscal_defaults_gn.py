"""Taux de taxes proposés par défaut aux dossiers guinéens.

⚠ À vérifier auprès de la DGI (Direction générale des impôts de Guinée) et à valider
par un expert-comptable guinéen. Ces valeurs sont créées *non vérifiées* : l'interface
le signale tant qu'un utilisateur habilité ne les a pas confirmées. Elles sont
modifiables par dossier (nouvelle version datée).

Seuls les taux dont la valeur est raisonnablement établie figurent ici ; les taux
réduits ou spécifiques éventuels ne sont pas inventés et doivent être ajoutés par le
dossier.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DefaultTaxRate:
    code: str
    label: str
    kind: str
    rate_basis_points: int
    collected_account_number: str | None
    deductible_account_number: str | None
    note: str


# Date d'effet conventionnelle des valeurs par défaut : à remplacer par la date
# d'entrée en vigueur réelle lors de la vérification.
DEFAULT_VALID_FROM = date(2000, 1, 1)

DEFAULT_TAX_RATES: tuple[DefaultTaxRate, ...] = (
    DefaultTaxRate(
        code="TVA_NORMAL",
        label="TVA – taux normal",
        kind="TVA",
        rate_basis_points=1800,
        collected_account_number="4431",
        deductible_account_number="4452",
        note="Valeur par défaut 18 % : à vérifier auprès de la DGI.",
    ),
    DefaultTaxRate(
        code="TVA_EXONERE",
        label="Opérations exonérées de TVA",
        kind="TVA",
        rate_basis_points=0,
        collected_account_number=None,
        deductible_account_number=None,
        note="Liste des opérations exonérées : à vérifier auprès de la DGI.",
    ),
)
