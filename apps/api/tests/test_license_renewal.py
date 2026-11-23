"""Garanties métier pures des renouvellements commerciaux."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from kora.tenancy.license_renewal import preview_renewal
from kora.tenancy.licenses import LicenseKind, LicensePeriod, LicenseStatus


def initial() -> LicensePeriod:
    return LicensePeriod(
        tenant_id=UUID(int=1),
        offer_code="gestion",
        offer_version=2,
        kind=LicenseKind.TRIAL,
        starts_on=date(2027, 1, 1),
        ends_on=date(2027, 2, 1),
    )


def test_renouvellement_adjacent_immuable() -> None:
    previous = initial()
    renewed = preview_renewal(previous, ends_on=date(2027, 3, 1))
    assert renewed.starts_on == previous.ends_on
    assert renewed.ends_on == date(2027, 3, 1)
    assert renewed.kind == LicenseKind.PAID
    assert renewed.tenant_id == previous.tenant_id
    assert (renewed.offer_code, renewed.offer_version) == (
        previous.offer_code, previous.offer_version
    )
    assert previous.kind == LicenseKind.TRIAL
    assert previous.status_on(date(2027, 2, 1)) == LicenseStatus.EXPIRED
    assert renewed.status_on(date(2027, 2, 1)) == LicenseStatus.ACTIVE


@pytest.mark.parametrize("end", [date(2027, 2, 1), date(2027, 1, 31)])
def test_renouvellement_sans_duree_refuse(end: date) -> None:
    with pytest.raises(ValueError, match="nouvelle fin"):
        preview_renewal(initial(), ends_on=end)


def test_renouvellement_suspendu_refuse() -> None:
    with pytest.raises(ValueError, match="suspendue"):
        preview_renewal(replace(initial(), suspended=True), ends_on=date(2027, 3, 1))


def test_renouvellement_permet_un_nouvel_essai_explicite() -> None:
    renewed = preview_renewal(
        initial(), ends_on=date(2027, 3, 1), kind=LicenseKind.TRIAL
    )
    assert renewed.status_on(date(2027, 2, 1)) == LicenseStatus.TRIAL


def test_renouvellement_refuse_une_date_avec_heure() -> None:

    with pytest.raises(ValueError, match="nouvelle fin"):
        preview_renewal(initial(), ends_on=datetime(2027, 3, 1, tzinfo=UTC))  # type: ignore[arg-type]
