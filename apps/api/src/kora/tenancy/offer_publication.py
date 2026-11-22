"""Publication commerciale auditée, indépendante des droits métier."""

import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, ForbiddenError
from kora.db.tenant import current_tenant
from kora.models.offers import CommercialOfferVersion
from kora.tenancy.module_config import require_platform_admin
from kora.tenancy.offers import OfferVersion


def publish_offer(session: Session, *, actor_id: uuid.UUID, offer: OfferVersion) -> None:
    """Publie une version immuable ; le commit appartient à l'appelant."""
    if current_tenant(session) is not None:
        raise ForbiddenError("Contexte plateforme obligatoire.")
    require_platform_admin(session, actor_id)
    if len(offer.code) > 64 or "\x00" in offer.code or offer.version > 2_147_483_647:
        raise BusinessRuleError("Identifiant de version invalide.")
    modules = sorted(module.value for module in offer.modules)
    published = session.scalar(
        insert(CommercialOfferVersion)
        .values(code=offer.code, version=offer.version, modules=modules)
        .on_conflict_do_nothing(index_elements=["code", "version"])
        .returning(CommercialOfferVersion.code)
    )
    if published is None:
        raise ConflictError("Cette version d'offre existe déjà.")
    record_event(
        session,
        action="commercial.offer_published",
        entity_type="commercial_offer",
        entity_id=f"{offer.code}:{offer.version}",
        actor_user_id=actor_id,
        payload={"code": offer.code, "version": offer.version, "modules": modules},
    )
