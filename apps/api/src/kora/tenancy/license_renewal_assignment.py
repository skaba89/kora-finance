"""Renouvellement commercial persisté, sans droit métier ni paiement implicite."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, NotFoundError
from kora.db.tenant import bind_tenant
from kora.models.common import utcnow
from kora.models.licenses import CommercialLicensePeriod
from kora.tenancy.license_assignment import assign_license
from kora.tenancy.license_renewal import preview_renewal
from kora.tenancy.license_suspension import clean_reason
from kora.tenancy.licenses import LicenseKind, LicensePeriod
from kora.tenancy.module_admin import bind_module_client


def renew_license(
    session: Session,
    *,
    actor_id: uuid.UUID,
    company_id: uuid.UUID,
    previous_id: uuid.UUID,
    ends_on: date,
    kind: LicenseKind = LicenseKind.PAID,
    today: date | None = None,
    reason: str,
) -> uuid.UUID:
    """Ajoute une période adjacente, via les protections d'assign_license.

    Un admin plateforme actif est exigé. L'ancienne période reste immuable,
    le renouvellement ne confère aucun droit ni ne constate de paiement.
    Le verrou empêche une suspension concurrente non prise en compte ; la
    contrainte GiST empêche les périodes chevauchantes. Pas de commit interne.
    Pas de renouvellement rétroactif (décision métier du 2026-11-24) : une
    période source expirée exige une nouvelle attribution. `today` est
    injectable pour les tests ; par défaut, date UTC (Guinée : UTC+0).
    """
    if (
        type(ends_on) is not date
        or not isinstance(kind, LicenseKind)
        or (today is not None and type(today) is not date)
    ):
        raise BusinessRuleError("Date ou type de renouvellement invalide.")
    cleaned_reason = clean_reason(reason)
    bind_module_client(session, actor_id, company_id)
    previous = session.scalar(
        select(CommercialLicensePeriod)
        .where(
            CommercialLicensePeriod.id == previous_id,
            CommercialLicensePeriod.tenant_id == company_id,
        )
        .with_for_update(of=CommercialLicensePeriod)
        # Relit la ligne verrouillée : un objet déjà chargé ne doit pas masquer
        # une suspension validée entre-temps par une autre transaction.
        .execution_options(populate_existing=True)
    )
    if previous is None:
        raise NotFoundError("Période précédente introuvable.")
    period = LicensePeriod(
        tenant_id=previous.tenant_id,
        offer_code=previous.offer_code,
        offer_version=previous.offer_version,
        kind=LicenseKind(previous.kind),
        starts_on=previous.starts_on,
        ends_on=previous.ends_on,
        suspended=previous.suspended,
    )
    try:
        proposed = preview_renewal(period, ends_on=ends_on, kind=kind)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc
    if proposed.starts_on < (today or utcnow().date()):
        raise BusinessRuleError(
            "Renouvellement rétroactif refusé : la période commencerait dans le passé ; "
            "créez une nouvelle attribution."
        )
    # assign_license revalide les privilèges plateforme avant de lier le dossier.
    bind_tenant(session, None)
    new_id = assign_license(session, actor_id=actor_id, period=proposed)
    # assign_license a relié le dossier : l'événement rejoint sa chaîne d'audit.
    record_event(
        session,
        action="commercial.license_renewed",
        entity_type="commercial_license",
        entity_id=new_id,
        actor_user_id=actor_id,
        payload={
            "previous_license_id": str(previous_id),
            "starts_on": proposed.starts_on.isoformat(),
            "ends_on": proposed.ends_on.isoformat(),
            "kind": proposed.kind.value,
            "reason": cleaned_reason,
        },
    )
    return new_id
