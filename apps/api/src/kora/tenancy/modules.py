"""Catalogue des capacités commerciales, indépendant du RBAC.

Ce premier lot est un moteur pur : aucune mutation tenant ni garde HTTP ne
consomme encore sa décision. Un module non livré ne peut jamais être activé.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class Module(StrEnum):
    SALES = "sales"
    PURCHASES = "purchases"
    ACCOUNTING = "accounting"
    TREASURY = "treasury"
    IMPORTS = "imports"
    FORECAST = "forecast"
    OFFLINE = "offline"
    EXPENSES = "expenses"
    DOCUMENTS = "documents"
    OCR = "ocr"
    ASSETS = "assets"
    ANALYTICS = "analytics"
    BUDGETS = "budgets"
    TAX_REPORTING = "tax_reporting"
    FIRM = "firm"
    FUNDING = "funding"
    AI = "ai"
    MAKITIPLUS = "makitiplus"
    PAYMENTS = "payments"


@dataclass(frozen=True)
class ModuleDefinition:
    released: bool
    dependencies: frozenset[Module] = frozenset()
    default_enabled: bool = False


CATALOG: Mapping[Module, ModuleDefinition] = MappingProxyType(
    {
        Module.SALES: ModuleDefinition(True, default_enabled=True),
        Module.PURCHASES: ModuleDefinition(True, default_enabled=True),
        Module.ACCOUNTING: ModuleDefinition(True, default_enabled=True),
        Module.TREASURY: ModuleDefinition(True, default_enabled=True),
        Module.IMPORTS: ModuleDefinition(False, frozenset({Module.ACCOUNTING})),
        Module.FORECAST: ModuleDefinition(True, frozenset({Module.TREASURY}), default_enabled=True),
        Module.OFFLINE: ModuleDefinition(True, frozenset({Module.ACCOUNTING}), default_enabled=True),
        Module.EXPENSES: ModuleDefinition(False),
        Module.DOCUMENTS: ModuleDefinition(False),
        Module.OCR: ModuleDefinition(False, frozenset({Module.DOCUMENTS})),
        Module.ASSETS: ModuleDefinition(False, frozenset({Module.ACCOUNTING})),
        Module.ANALYTICS: ModuleDefinition(False, frozenset({Module.ACCOUNTING})),
        Module.BUDGETS: ModuleDefinition(False, frozenset({Module.ANALYTICS})),
        Module.TAX_REPORTING: ModuleDefinition(False, frozenset({Module.ACCOUNTING})),
        Module.FIRM: ModuleDefinition(False),
        Module.FUNDING: ModuleDefinition(False, frozenset({Module.ACCOUNTING})),
        Module.AI: ModuleDefinition(False),
        Module.MAKITIPLUS: ModuleDefinition(False, frozenset({Module.SALES})),
        Module.PAYMENTS: ModuleDefinition(False, frozenset({Module.TREASURY})),
    }
)


class ModuleStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNRELEASED = "unreleased"
    DEPENDENCY_DISABLED = "dependency_disabled"


def resolve_modules(overrides: Mapping[Module, bool]) -> dict[Module, ModuleStatus]:
    """Les modules livrés restent actifs par défaut pour préserver les clients.

    Une configuration explicite ne peut pas rendre disponible une capacité
    non livrée. Les dépendances sont résolues en lecture, sans écraser les
    choix stockés : réactiver un prérequis restaure les choix précédents.
    """
    if not set(overrides).issubset(CATALOG):
        raise ValueError("Module inconnu.")
    resolved: dict[Module, ModuleStatus] = {}

    def resolve(module: Module, visiting: frozenset[Module]) -> ModuleStatus:
        if module in resolved:
            return resolved[module]
        if module in visiting:
            raise ValueError("Cycle dans les dépendances des modules.")
        definition = CATALOG[module]
        if not definition.released:
            status = ModuleStatus.UNRELEASED
        elif not overrides.get(module, definition.default_enabled):
            status = ModuleStatus.DISABLED
        elif any(
            resolve(dep, visiting | {module}) != ModuleStatus.ENABLED
            for dep in definition.dependencies
        ):
            status = ModuleStatus.DEPENDENCY_DISABLED
        else:
            status = ModuleStatus.ENABLED
        resolved[module] = status
        return status

    for module in Module:
        resolve(module, frozenset())
    return resolved
