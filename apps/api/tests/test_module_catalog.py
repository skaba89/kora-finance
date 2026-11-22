from kora.tenancy.modules import CATALOG, Module, ModuleStatus, resolve_modules


def test_catalogue_couvre_tous_les_modules() -> None:
    assert set(CATALOG) == set(Module)
    assert all(definition.dependencies <= set(Module) for definition in CATALOG.values())


def test_compatibilite_clients_existants() -> None:
    states = resolve_modules({})
    assert states[Module.ACCOUNTING] == ModuleStatus.ENABLED
    assert states[Module.SALES] == ModuleStatus.ENABLED
    assert states[Module.PURCHASES] == ModuleStatus.ENABLED
    assert states[Module.TREASURY] == ModuleStatus.ENABLED
    assert states[Module.OFFLINE] == ModuleStatus.ENABLED
    assert states[Module.FORECAST] == ModuleStatus.ENABLED


def test_module_non_livre_ne_peut_pas_etre_active() -> None:
    states = resolve_modules({Module.OCR: True, Module.IMPORTS: True})
    assert states[Module.OCR] == ModuleStatus.UNRELEASED
    assert states[Module.IMPORTS] == ModuleStatus.UNRELEASED


def test_dependances_et_reactivation() -> None:
    states = resolve_modules({Module.ACCOUNTING: False, Module.OFFLINE: True})
    assert states[Module.ACCOUNTING] == ModuleStatus.DISABLED
    assert states[Module.OFFLINE] == ModuleStatus.DEPENDENCY_DISABLED
    assert states[Module.SALES] == ModuleStatus.ENABLED
    assert resolve_modules({Module.ACCOUNTING: True})[Module.OFFLINE] == ModuleStatus.ENABLED


def test_configurations_independantes_et_choix_explicite() -> None:
    first = resolve_modules({Module.TREASURY: False})
    second = resolve_modules({Module.FORECAST: False})
    assert first[Module.FORECAST] == ModuleStatus.DEPENDENCY_DISABLED
    assert second[Module.TREASURY] == ModuleStatus.ENABLED
    assert second[Module.FORECAST] == ModuleStatus.DISABLED
