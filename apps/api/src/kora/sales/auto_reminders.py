"""Relances automatiques configurables (Phase B, lot 2).

Une politique par dossier (upsert — même patron que les réglages de
trésorerie) porte l'échéancier d'escalade `offsets_days` : les retards, en
jours après l'échéance, auxquels une relance est due — ex. [1, 7, 15] = 1re
relance à J+1, 2e à J+7, 3e à J+15.

Règles portées par le service :
- le balayage est périodique (planificateur → worker) et idempotent : une
  relance automatique réutilise TOUTES les règles 4D — facture ÉMISE, ÉCHUE et
  non soldée ; niveau compté sous verrou FOR UPDATE de la facture ; unicité
  (dossier, facture, jour) en base : un tick doublé, un balayage concurrent ou
  une relance manuelle déjà faite le même jour ne crée jamais de doublon ;
- rattrapage un niveau par jour : une facture découverte déjà profondément en
  retard rejoint l'échéancier un niveau par jour (jamais plusieurs relances le
  même jour) et l'escalade s'arrête au dernier seuil de la politique ;
- l'origine est système : `created_by_user_id` est NULL (distinction
  structurelle des relances manuelles 4D) et l'audit porte `origine` ;
- l'envoi email part du worker (`send_sales_reminder`, 4D) après le commit —
  une panne de la file n'annule pas la relance enregistrée (renvoi possible
  depuis l'historique) ;
- aucune écriture comptable (garde-fou testé, comme en 4A/4B/4C/4D/4D-bis) :
  une relance est un acte commercial documenté, pas un fait financier.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError
from kora.models.sales import (
    DocStatus,
    ReminderChannel,
    SalesDocument,
    SalesReminder,
    SalesReminderPolicy,
)
from kora.sales import payments, reminders
from kora.tenancy.module_config import effective_modules, require_enabled_module
from kora.tenancy.modules import Module, ModuleStatus

# Bornes de l'échéancier : 1 à 6 seuils, chaque seuil entre 1 et 365 jours de retard.
OFFSETS_COUNT_MIN = 1
OFFSETS_COUNT_MAX = 6
OFFSET_DAYS_MAX = 365
# Échéancier suggéré à l'affichage (jamais appliqué sans PUT explicite).
DEFAULT_OFFSETS_DAYS = [1, 7, 15]


@dataclass(frozen=True)
class PolicyData:
    """Politique demandée : activation et échéancier d'escalade."""

    enabled: bool
    offsets_days: list[int]


@dataclass
class PolicyRun:
    """Résumé d'une exécution de politique : journalisable et testable."""

    enabled: bool
    created: list[uuid.UUID] = field(default_factory=list)  # relances créées
    factures: list[int | None] = field(default_factory=list)  # numéros visés
    emails_queued: int = 0
    a_jour: int = 0  # candidats déjà au niveau cible (rien à faire)
    sans_email: int = 0  # tiers sans adresse email (fiche à compléter)
    doublons: int = 0  # relance déjà faite aujourd'hui (unicité 4D)


def validate_offsets(values: list[int]) -> list[int]:
    """Valide l'échéancier : 1 à 6 seuils, entiers de 1 à 365 jours,
    strictement croissants (un seuil = un niveau de relance, jamais deux
    relances dues le même jour)."""
    if not OFFSETS_COUNT_MIN <= len(values) <= OFFSETS_COUNT_MAX:
        raise BusinessRuleError(
            f"L'échéancier doit compter entre {OFFSETS_COUNT_MIN} et "
            f"{OFFSETS_COUNT_MAX} seuils de relance."
        )
    for valeur in values:
        if not isinstance(valeur, int) or isinstance(valeur, bool):
            raise BusinessRuleError("L'échéancier doit être une liste d'entiers (jours).")
        if not 1 <= valeur <= OFFSET_DAYS_MAX:
            raise BusinessRuleError(
                f"Chaque seuil doit être entre 1 et {OFFSET_DAYS_MAX} jours de retard."
            )
    if any(a >= b for a, b in pairwise(values)):
        raise BusinessRuleError(
            "L'échéancier doit être strictement croissant : chaque seuil est un "
            "niveau de relance supplémentaire."
        )
    return list(values)


def get_policy(session: Session, company_id: uuid.UUID) -> SalesReminderPolicy | None:
    """Politique du dossier (RLS forcée côté base : une session d'un autre
    dossier ne voit rien)."""
    return session.execute(
        select(SalesReminderPolicy).where(SalesReminderPolicy.tenant_id == company_id)
    ).scalar_one_or_none()


def upsert_policy(session: Session, actor: Actor, data: PolicyData) -> SalesReminderPolicy:
    """Crée ou met à jour LA politique du dossier (une ligne au plus — le verrou
    de ligne sérialise deux PUT concurrents) et journalise le réglage. L'acte
    est audité : activer ou retendre des relances automatiques n'est pas
    anodin, le journal d'audit le porte."""
    if data.enabled:
        require_enabled_module(session, actor.company_id, Module.SALES)
    offsets = validate_offsets(data.offsets_days)
    policy = session.execute(
        select(SalesReminderPolicy)
        .where(SalesReminderPolicy.tenant_id == actor.company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if policy is None:
        policy = SalesReminderPolicy(
            id=uuid.uuid4(),
            tenant_id=actor.company_id,
            enabled=data.enabled,
            offsets_days=offsets,
            created_by_user_id=actor.user_id,
        )
        session.add(policy)
    else:
        policy.enabled = data.enabled
        policy.offsets_days = offsets
    record_event(
        session,
        action="sales_reminder_policy.updated",
        entity_type="sales_reminder_policy",
        entity_id=policy.id,
        payload={"active": data.enabled, "échéancier": offsets},
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return policy


def target_level(offsets: list[int], days_late: int) -> int:
    """Niveau de relance atteint au regard du retard : nombre de seuils
    franchis (0 si aucun — pas encore de relance due)."""
    return sum(1 for seuil in offsets if days_late >= seuil)


def run_policy(session: Session, company_id: uuid.UUID, as_of: date) -> PolicyRun:
    """Exécute la politique du dossier au {as_of} : crée (et enregistre) les
    relances dues ; l'envoi email est enfilé PAR LE WORKER après le commit —
    le service reste sans dépendance au broker. Une seule transaction pour tout
    le run ; chaque création est protégée par un point de sauvegarde : une
    course perdue (doublon du jour) n'annule pas les autres relances."""
    if effective_modules(session, company_id)[Module.SALES] != ModuleStatus.ENABLED:
        return PolicyRun(enabled=False)
    policy = get_policy(session, company_id)
    if policy is None or not policy.enabled:
        return PolicyRun(enabled=False)
    offsets = [int(v) for v in policy.offsets_days]
    candidates = reminders.overdue_invoices(session, company_id, as_of)
    run = PolicyRun(enabled=True)
    for candidate in candidates:
        cible = target_level(offsets, candidate.days_late)
        if candidate.reminders_count >= cible:
            run.a_jour += 1
            continue
        if not candidate.partner_email or not candidate.partner_email.strip():
            run.sans_email += 1
            continue
        created = _cree_relance(session, company_id, candidate, as_of, candidate.partner_email)
        if created is None:
            run.doublons += 1
            continue
        run.created.append(created)
        run.factures.append(candidate.document.number)
    session.commit()
    return run


def _cree_relance(
    session: Session,
    company_id: uuid.UUID,
    candidate: reminders.OverdueInvoice,
    as_of: date,
    email_to: str,
) -> uuid.UUID | None:
    """Crée UNE relance automatique sous verrou FOR UPDATE de la facture, avec
    re-contrôles à l'instant du verrou (statut, échéance, solde, email) —
    l'état peut avoir changé entre le balayage et le verrou (annulation,
    règlement reçu). Point de sauvegarde : un doublon du jour (course perdue
    contre une relance manuelle ou un balayage concurrent) est abandonné sans
    toucher aux autres. Renvoie l'id de la relance ou None (doublon)."""
    invoice = session.execute(
        select(SalesDocument)
        .where(
            SalesDocument.tenant_id == company_id,
            SalesDocument.id == candidate.document.id,
        )
        .with_for_update()
    ).scalar_one()
    if invoice.status != DocStatus.ISSUED.value:
        return None
    if invoice.due_on is None or invoice.due_on >= as_of:
        return None
    lettres = payments.outstanding_for_documents(session, company_id, [invoice.id])
    solde = invoice.total_ttc - lettres.get(invoice.id, 0)
    if solde <= 0:
        return None
    deja_faite = session.execute(
        select(SalesReminder.id).where(
            SalesReminder.tenant_id == company_id,
            SalesReminder.document_id == invoice.id,
            SalesReminder.reminded_on == as_of,
        )
    ).scalar_one_or_none()
    if deja_faite is not None:
        return None
    niveau = (
        reminders.reminders_count_for_documents(session, company_id, [invoice.id]).get(
            invoice.id, 0
        )
        + 1
    )
    reminder = SalesReminder(
        id=uuid.uuid4(),
        tenant_id=company_id,
        document_id=invoice.id,
        partner_id=invoice.partner_id,
        level=niveau,
        reminded_on=as_of,
        channel=ReminderChannel.EMAIL.value,
        email_to=email_to.strip(),
        note=None,
        created_by_user_id=None,  # origine système : le planificateur
    )
    # Point de sauvegarde : relance + audit partagent le même sort local. La
    # violation d'unicité (dossier, facture, jour) — course perdue contre une
    # relance manuelle ou un balayage concurrent — ne roule que ce bloc : le
    # gestionnaire de contexte restaure le savepoint et l'exception remonte,
    # capturée par l'appelant sans toucher aux autres relances du run.
    try:
        with session.begin_nested():
            session.add(reminder)
            session.flush()
            record_event(
                session,
                action="sales_reminder.auto_created",
                entity_type="sales_reminder",
                entity_id=reminder.id,
                payload={
                    "facture": invoice.number,
                    "niveau": niveau,
                    "canal": ReminderChannel.EMAIL.value,
                    "jours_retard": (as_of - (invoice.due_on or as_of)).days,
                    "origine": "automatique",
                },
                actor_user_id=None,
                ip_address=None,
            )
    except IntegrityError:
        return None
    return reminder.id
