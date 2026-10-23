"""Écriture et vérification du journal d'audit chaîné (SHA-256).

`record_event` s'exécute dans la transaction de l'action auditée : si l'action est
annulée, l'événement l'est aussi, et inversement. Les ajouts sont sérialisés par chaîne
grâce au verrou `FOR UPDATE` sur la tête de chaîne.

Limite connue : un attaquant disposant des droits propriétaire sur la base pourrait
réécrire toute la fin d'une chaîne *et* sa tête. Pour s'en prémunir, les têtes de
chaîne doivent être exportées régulièrement hors de la base (ancrage) — prévu avec
les sauvegardes.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from kora.db.tenant import current_tenant
from kora.models.audit import GENESIS_HASH, AuditChainHead, AuditEvent
from kora.models.common import utcnow

JsonValue = str | int | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class AuditPayloadError(ValueError):
    pass


def _check_payload(value: object, path: str = "payload") -> None:
    """Seuls les types JSON exacts sont admis : pas de float (montants en entiers)."""
    if isinstance(value, bool | int | str) or value is None:
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_payload(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditPayloadError(f"{path} : clé non textuelle {key!r}")
            _check_payload(item, f"{path}.{key}")
        return
    raise AuditPayloadError(f"{path} : type {type(value).__name__} non admis dans l'audit")


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def compute_hash(
    *,
    prev_hash: str,
    tenant_id: uuid.UUID | None,
    seq: int,
    occurred_at: datetime,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    payload: dict[str, Any],
    ip_address: str | None,
) -> str:
    canonical = json.dumps(
        {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "seq": seq,
            "occurred_at": _canonical_timestamp(occurred_at),
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
            "ip_address": ip_address,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(f"{prev_hash}\n{canonical}".encode()).hexdigest()


def _lock_head(session: Session, tenant_id: uuid.UUID | None) -> AuditChainHead:
    # Création idempotente de la tête au premier événement, puis verrou exclusif.
    session.execute(
        insert(AuditChainHead)
        .values(tenant_id=tenant_id, last_seq=0, last_hash=GENESIS_HASH)
        .on_conflict_do_nothing()
    )
    condition = (
        AuditChainHead.tenant_id.is_(None)
        if tenant_id is None
        else AuditChainHead.tenant_id == tenant_id
    )
    return session.execute(select(AuditChainHead).where(condition).with_for_update()).scalar_one()


def record_event(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Ajoute un événement à la chaîne du tenant courant (ou à la chaîne plateforme)."""
    payload = payload or {}
    _check_payload(payload)
    tenant_id = current_tenant(session)
    head = _lock_head(session, tenant_id)

    seq = head.last_seq + 1
    occurred_at = utcnow()
    entity = str(entity_id) if entity_id is not None else None
    digest = compute_hash(
        prev_hash=head.last_hash,
        tenant_id=tenant_id,
        seq=seq,
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity,
        payload=payload,
        ip_address=ip_address,
    )
    event = AuditEvent(
        tenant_id=tenant_id,
        seq=seq,
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity,
        payload=payload,
        ip_address=ip_address,
        prev_hash=head.last_hash,
        hash=digest,
    )
    session.add(event)
    head.last_seq = seq
    head.last_hash = digest
    session.flush()
    return event


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    events_checked: int
    broken_at_seq: int | None = None
    reason: str | None = None


def _walk(events: Iterable[AuditEvent]) -> ChainVerification | tuple[int, str]:
    """Parcourt la chaîne ; renvoie le premier défaut, ou (nombre vérifié, dernier hash)."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for event in events:
        if event.seq != expected_seq:
            return ChainVerification(False, checked, expected_seq, "séquence interrompue")
        if event.prev_hash != expected_prev:
            return ChainVerification(False, checked, event.seq, "lien vers le précédent rompu")
        recomputed = compute_hash(
            prev_hash=event.prev_hash,
            tenant_id=event.tenant_id,
            seq=event.seq,
            occurred_at=event.occurred_at,
            actor_user_id=event.actor_user_id,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
            ip_address=event.ip_address,
        )
        if recomputed != event.hash:
            return ChainVerification(False, checked, event.seq, "contenu altéré")
        expected_prev = event.hash
        expected_seq += 1
        checked += 1
    return checked, expected_prev


def verify_chain(session: Session) -> ChainVerification:
    """Recalcule toute la chaîne du tenant courant (ou plateforme) et la compare à sa tête."""
    tenant_id = current_tenant(session)
    result = session.execute(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id.is_(None)
            if tenant_id is None
            else AuditEvent.tenant_id == tenant_id
        )
        .order_by(AuditEvent.seq)
        .execution_options(yield_per=1000)
    ).scalars()
    try:
        outcome = _walk(result)
    finally:
        # Curseur serveur : à fermer même si la vérification s'arrête au premier défaut.
        result.close()
    if isinstance(outcome, ChainVerification):
        return outcome
    checked, expected_prev = outcome

    head = session.execute(
        select(AuditChainHead).where(
            AuditChainHead.tenant_id.is_(None)
            if tenant_id is None
            else AuditChainHead.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    head_seq, head_hash = (head.last_seq, head.last_hash) if head else (0, GENESIS_HASH)
    if head_seq != checked or head_hash != expected_prev:
        return ChainVerification(
            False, checked, checked + 1, "fin de chaîne supprimée ou tête altérée"
        )
    return ChainVerification(True, checked)
