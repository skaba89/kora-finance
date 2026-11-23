"""Attribution commerciale contrôlée, sans effet sur les droits métier."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.licenses import LicensePeriod
from kora.tenancy.module_admin import bind_module_client
from kora.tenancy.modules import Module
from kora.tenancy.offers import OfferVersion


def assign_license(
    session: Session, *, actor_id: uuid.UUID, period: LicensePeriod
) -> uuid.UUID:
    """Insère une période dans une transaction possédée par l'appelant.

    L'admin est vérifié avant de lier le dossier à la RLS. La contrainte
    d'exclusion PostgreSQL sérialise les chevauchements concurrents.
    Aucun module effectif, rôle ou paiement n'est modifié.
    """
    bind_module_client(session, actor_id, period.tenant_id)
    if (
        len(period.offer_code) > 64
        or "\x00" in period.offer_code
        or period.offer_version > 2_147_483_647
    ):
        raise BusinessRuleError("Identifiant d'offre invalide.")
    published = session.get(
        CommercialOfferVersion, (period.offer_code, period.offer_version)
    )
    if published is None:
        raise NotFoundError("Version d'offre non publiée.")
    try:
        OfferVersion(
            code=published.code,
            version=published.version,
            modules=frozenset(Module(value) for value in published.modules),
        )
    except (ValueError, KeyError) as exc:
        raise BusinessRuleError("Version d'offre devenue indisponible.") from exc

    identifier = uuid.uuid4()
    # SAVEPOINT : une collision ne doit pas invalider la transaction de l'appelant.
    try:
        with session.begin_nested():
            session.add(
                CommercialLicensePeriod(
                    id=identifier,
                    tenant_id=period.tenant_id,
                    offer_code=period.offer_code,
                    offer_version=period.offer_version,
                    kind=period.kind.value,
                    starts_on=period.starts_on,
                    ends_on=period.ends_on,
                    suspended=period.suspended,
                )
            )
            session.flush()
    except IntegrityError as exc:
        # La base reste l'autorité finale pour dates et chevauchements.
        if getattr(exc.orig, "sqlstate", None) == "23P01":
            raise ConflictError("Une période commerciale chevauche déjà ces dates.") from exc
        raise

    record_event(
        session,
        action="commercial.license_assigned",
        entity_type="commercial_license",
        entity_id=identifier,
        actor_user_id=actor_id,
        payload={
            "offer_code": period.offer_code,
            "offer_version": period.offer_version,
            "kind": period.kind.value,
            "starts_on": period.starts_on.isoformat(),
            "ends_on": period.ends_on.isoformat(),
            "suspended": period.suspended,
        },
    )
    return identifier
