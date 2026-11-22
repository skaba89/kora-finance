"""Définition commerciale indépendante des droits métier et du RBAC."""

from dataclasses import dataclass

from kora.tenancy.modules import CATALOG, Module, ModuleStatus, resolve_modules


@dataclass(frozen=True, slots=True, kw_only=True)
class OfferVersion:
    """Instantané immuable d'une offre, sans prix ni attribution à un client."""

    code: str
    version: int
    modules: frozenset[Module]

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip():
            raise ValueError("Code d'offre invalide.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("Version d'offre invalide.")
        if not isinstance(self.modules, frozenset) or not self.modules:
            raise ValueError("Une offre doit contenir des modules immuables.")
        for module in self.modules:
            if not isinstance(module, Module) or not CATALOG[module].released:
                raise ValueError("Module non disponible dans une offre.")
        states = resolve_modules({module: module in self.modules for module in Module})
        if any(states[module] != ModuleStatus.ENABLED for module in self.modules):
            raise ValueError("Les prérequis des modules doivent être inclus dans l'offre.")
