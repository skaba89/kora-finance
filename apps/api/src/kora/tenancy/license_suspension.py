"""Suspension et réactivation auditées des licences commerciales."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.licenses import CommercialLicensePeriod
from kora.tenancy.module_admin import bind_module_client

REASON_MIN_LENGTH = 3
REASON_MAX_LENGTH = 500


def _clean_reason(reason: object) -> str:
    """Motif d'intervention obligatoire, conservé tel quel (sans espaces de bord) dans l'audit."""
    if type(reason) is not str:
        raise BusinessRuleError("Motif de l'intervention requis.")
    cleaned = reason.strip()
    if not REASON_MIN_LENGTH <= len(cleaned) <= REASON_MAX_LENGTH or "\0" in cleaned:
        raise BusinessRuleError(
            f"Motif de {REASON_MIN_LENGTH} à {REASON_MAX_LENGTH} caractères requis."
        )
    return cleaned


def change_license_suspension(
    session: Session,
    *,
    actor_id: uuid.UUID,
    company_id: uuid.UUID,
    license_id: uuid.UUID,
    suspended: bool,
    expected_suspended: bool,
    reason: str,
) -> bool:
    """Change seulement le drapeau, sous RLS, verrou et audit atomique.

    L'appelant possède la transaction et utilise une session dédiée.
    L'état attendu protège des demandes concurrentes sur un état obsolète.
    Aucun changement de période, paiement, module ou droit comptable.
    """
    if type(suspended) is not bool or type(expected_suspended) is not bool:
        raise BusinessRuleError("État de suspension booléen requis.")
    cleaned_reason = _clean_reason(reason)
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
        payload={
            "previous_suspended": previous,
            "suspended": suspended,
            "reason": cleaned_reason,
        },
    )
    return True
