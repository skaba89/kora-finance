"""Préparation pure d'un renouvellement, sans écriture ni droits implicites."""

from datetime import date

from kora.tenancy.licenses import LicenseKind, LicensePeriod


def preview_renewal(
    previous: LicensePeriod, *, ends_on: date, kind: LicenseKind = LicenseKind.PAID
) -> LicensePeriod:
    """Renouvelle à la borne de fin exclusive de la période précédente.

    Ne prolonge ni ne modifie l'historique : la nouvelle période peut ensuite
    être enregistrée par assign_license, dont la contrainte GiST garantit
    l'absence de chevauchement concurrent. Pas d'accès, paiement ou commit.
    """
    if previous.suspended:
        raise ValueError("Une période suspendue exige une décision explicite.")
    if type(ends_on) is not date or ends_on <= previous.ends_on:
        raise ValueError("La nouvelle fin doit suivre la fin de la période précédente.")
    if not isinstance(kind, LicenseKind):
        raise ValueError("Type de licence invalide.")
    return LicensePeriod(
        tenant_id=previous.tenant_id,
        offer_code=previous.offer_code,
        offer_version=previous.offer_version,
        kind=kind,
        starts_on=previous.ends_on,
        ends_on=ends_on,
    )
