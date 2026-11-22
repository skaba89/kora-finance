from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest

from kora.tenancy.licenses import LicenseKind, LicensePeriod, LicenseStatus
from kora.tenancy.modules import resolve_modules


def period() -> LicensePeriod:
    return LicensePeriod(
        tenant_id=UUID(int=1),
        offer_code="gestion",
        offer_version=1,
        kind=LicenseKind.PAID,
        starts_on=date(2026, 11, 1),
        ends_on=date(2026, 12, 1),
    )


@pytest.mark.parametrize(
    ("day", "status"),
    [
        (date(2026, 10, 31), LicenseStatus.SCHEDULED),
        (date(2026, 11, 1), LicenseStatus.ACTIVE),
        (date(2026, 11, 30), LicenseStatus.ACTIVE),
        (date(2026, 12, 1), LicenseStatus.EXPIRED),
    ],
)
def test_bornes_periode(day: date, status: LicenseStatus) -> None:
    assert period().status_on(day) == status


def test_essai_suspension_et_expiration() -> None:
    trial = replace(period(), kind=LicenseKind.TRIAL)
    assert trial.status_on(date(2026, 11, 1)) == LicenseStatus.TRIAL
    suspended = replace(trial, suspended=True)
    assert suspended.status_on(date(2026, 11, 1)) == LicenseStatus.SUSPENDED
    assert suspended.status_on(date(2026, 12, 1)) == LicenseStatus.EXPIRED
    assert trial.status_on(date(2026, 11, 1)) == LicenseStatus.TRIAL


def test_renouvellement_nouvelle_periode_sans_modifier_historique() -> None:
    initial = period()
    renewed = replace(initial, starts_on=initial.ends_on, ends_on=date(2027, 1, 1))
    assert initial.status_on(date(2026, 12, 1)) == LicenseStatus.EXPIRED
    assert renewed.status_on(date(2026, 12, 1)) == LicenseStatus.ACTIVE
    assert renewed.tenant_id == initial.tenant_id


def test_periode_invalide() -> None:
    with pytest.raises(ValueError, match="Période de licence invalide"):
        replace(period(), ends_on=period().starts_on)


@pytest.mark.parametrize("version", [0, -1, True])
def test_version_invalide(version: int) -> None:
    with pytest.raises(ValueError, match="Version d'offre invalide"):
        replace(period(), offer_version=version)


def test_aucun_effet_sur_configurations_existantes() -> None:
    before = resolve_modules({})
    assert period().status_on(date(2027, 1, 1)) == LicenseStatus.EXPIRED
    assert resolve_modules({}) == before
