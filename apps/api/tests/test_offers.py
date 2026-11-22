import pytest

from kora.tenancy.modules import Module, resolve_modules
from kora.tenancy.offers import OfferVersion


def test_offre_versionnee_sans_modifier_les_droits_existants() -> None:
    before = resolve_modules({})
    offer = OfferVersion(code="gestion", version=1, modules=frozenset({Module.SALES}))
    assert offer.modules == frozenset({Module.SALES})
    assert resolve_modules({}) == before


@pytest.mark.parametrize(
    ("modules", "message"),
    [
        (frozenset(), "Une offre doit contenir des modules immuables"),
        (frozenset({Module.OCR}), "Module non disponible dans une offre"),
    ],
)
def test_offre_refuse_les_modules_indisponibles_ou_absents(
    modules: frozenset[Module], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        OfferVersion(code="gestion", version=1, modules=modules)


def test_offre_exige_les_prerequis() -> None:
    with pytest.raises(ValueError, match="prérequis"):
        OfferVersion(code="gestion", version=1, modules=frozenset({Module.FORECAST}))
    offer = OfferVersion(
        code="gestion", version=1, modules=frozenset({Module.FORECAST, Module.TREASURY})
    )
    assert Module.TREASURY in offer.modules


@pytest.mark.parametrize("version", [0, -1, True])
def test_offre_refuse_une_version_invalide(version: int) -> None:
    with pytest.raises(ValueError, match="Version"):
        OfferVersion(code="gestion", version=version, modules=frozenset({Module.SALES}))


@pytest.mark.parametrize("code", ["", " gestion "])
def test_offre_refuse_un_code_invalide(code: str) -> None:
    with pytest.raises(ValueError, match="Code"):
        OfferVersion(code=code, version=1, modules=frozenset({Module.SALES}))
