"""Suspension et réactivation auditées des licences commerciales."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.licenses import CommercialLicensePeriod
from kora.tenancy.module_admin import bind_module_client


def change_license_suspension(
    session: Session,
    *,
    actor_id: uuid.UUID,
    company_id: uuid.UUID,
    license_id: uuid.UUID,
    suspended: bool,
    expected_suspended: bool,
) -> bool:
    """Change seulement le drapeau, sous RLS, verrou et audit atomique.

    L'appelant possède la transaction et utilise une session dédiée.
    L'état attendu protège des demandes concurrentes sur un état obsolète.
    Aucun changement de période, paiement, module ou droit comptable.
    """
    if type(suspended) is not bool or type(expected_suspended) is not bool:
        raise BusinessRuleError("État de suspension booléen requis.")
    bind_module_client(session, actor_id, company_id)
    row = session.scalar(
        select(CommercialLicensePeriod)
        .where(
            CommercialLicensePeriod.id == license_id,
            CommercialLicensePeriod.tenant_id == company_id,
        )
        .with_for_update(of=CommercialLicensePeriod)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFoundError("Licence introuvable dans ce dossier.")
    if row.suspended != expected_suspended:
        raise ConflictError("État de licence modifié ; actualisez avant de réessayer.")
    if row.suspended == suspended:
        return False
    previous = row.suspended
    row.suspended = suspended
    session.flush()
    record_event(
        session,
        action="commercial.license_suspended" if suspended else "commercial.license_reactivated",
        entity_type="commercial_license",
        entity_id=license_id,
        actor_user_id=actor_id,
        payload={"previous_suspended": previous, "suspended": suspended},
    )
    return True
