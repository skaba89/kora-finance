"""Échéanciers clients (lot B-4) : tranches de règlement prévues d'une facture.

Un échéancier est un **outil de planification du recouvrement** : les tranches
convenues avec le client (date attendue, montant attendu), remplacées en bloc à
chaque mise à jour (sémantique PUT). Il n'écrit jamais en comptabilité, ne
modifie jamais le solde (calculé en lecture depuis les affectations et les
avoirs partiels, comme partout) et ne déclenche rien d'automatique : les
relances restent un acte explicite (4D) ou pilotées par la politique (B2).

Le statut d'une ligne est calculé en lecture au jour demandé : les encaissements
lettrés couvrent les lignes dans l'ordre (1..N) — une ligne est réglée quand le
cumul encaissé atteint le cumul attendu qui la inclut, en retard quand sa date
attendue est passée sans être couverte, à venir sinon. Aucun statut dérivé
n'est stocké : les règlements (4C) et les avoirs partiels restent la seule
source de vérité du solde.

Le remplacement du plan est contrôlé sous verrou FOR UPDATE du document — le
même verrou que les règlements (4C) : une affectation concurrente qui réduit le
solde restant dû se sérialise avec la validation du plan, jamais d'excédent
planifié.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.common import utcnow
from kora.models.partners import Partner
from kora.models.sales import DocKind, DocStatus, SalesDocument, SalesPaymentScheduleLine
from kora.sales import payments
from kora.sales.service import _lock_document

# Au-delà de 24 tranches, un échéancier devient un plan de financement :
# refusé explicitement (limite du formulaire et de la lisibilité).
MAX_SCHEDULE_LINES = 24


@dataclass(frozen=True)
class ScheduleLineIn:
    """Une tranche demandée : date attendue, montant attendu (unités mineures),
    note facultative."""

    expected_on: date
    expected_amount: int
    note: str | None = None


@dataclass(frozen=True)
class ScheduleLine:
    """Une ligne du plan en lecture : statut calculé, jamais stocké."""

    line_no: int
    expected_on: date
    expected_amount: int
    note: str | None
    status: str  # "settled" | "late" | "upcoming"


@dataclass(frozen=True)
class ScheduleView:
    """Le plan complet d'une facture : lignes statuées et agrégats de lecture."""

    document_id: uuid.UUID
    document_number: int | None
    currency: str
    total_ttc: int
    paid_ttc: int
    outstanding_ttc: int
    planned_total: int
    planned_remaining: int  # somme des lignes non réglées
    lines: list[ScheduleLine]


def _load_lines(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID
) -> list[SalesPaymentScheduleLine]:
    return list(
        session.execute(
            select(SalesPaymentScheduleLine)
            .where(
                SalesPaymentScheduleLine.tenant_id == company_id,
                SalesPaymentScheduleLine.document_id == document_id,
            )
            .order_by(SalesPaymentScheduleLine.line_no)
        ).scalars()
    )


def _statuses(
    lines: list[SalesPaymentScheduleLine], paid_ttc: int, as_of: date
) -> list[ScheduleLine]:
    """Statut de chaque ligne : le cumul encaissé couvre les lignes dans
    l'ordre. Une ligne est réglée dès que le cumul encaissé atteint le cumul
    attendu qui l'inclut ; sinon en retard si sa date est passée, à venir sinon.
    Aucun flottant : les montants restent des entiers en unités mineures."""
    result: list[ScheduleLine] = []
    cumul_attendu = 0
    for line in lines:
        cumul_attendu += line.expected_amount
        if paid_ttc >= cumul_attendu:
            statut = "settled"
        elif line.expected_on < as_of:
            statut = "late"
        else:
            statut = "upcoming"
        result.append(
            ScheduleLine(
                line_no=line.line_no,
                expected_on=line.expected_on,
                expected_amount=line.expected_amount,
                note=line.note,
                status=statut,
            )
        )
    return result


def get_schedule(
    session: Session, company_id: uuid.UUID, document_id: uuid.UUID, as_of: date | None = None
) -> ScheduleView:
    """Le plan d'une facture, statué au jour demandé (aujourd'hui par défaut).
    Les règlements 4C couvrent les lignes dans l'ordre : la lecture n'écrit
    rien."""
    document = session.execute(
        select(SalesDocument).where(
            SalesDocument.id == document_id, SalesDocument.tenant_id == company_id
        )
    ).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document introuvable dans ce dossier.")
    lines = _load_lines(session, company_id, document_id)
    lettres = payments.outstanding_for_documents(session, company_id, [document_id])
    paid_ttc = lettres.get(document_id, 0)
    outstanding = max(document.total_ttc - paid_ttc, 0)
    lines_with_status = _statuses(lines, paid_ttc, as_of or utcnow().date())
    planned_total = sum(line.expected_amount for line in lines)
    planned_remaining = sum(
        vue.expected_amount for vue in lines_with_status if vue.status != "settled"
    )
    return ScheduleView(
        document_id=document.id,
        document_number=document.number,
        currency=document.currency,
        total_ttc=document.total_ttc,
        paid_ttc=paid_ttc,
        outstanding_ttc=outstanding,
        planned_total=planned_total,
        planned_remaining=planned_remaining,
        lines=lines_with_status,
    )


def replace_schedule(
    session: Session, actor: Actor, document_id: uuid.UUID, lines: list[ScheduleLineIn]
) -> ScheduleView:
    """Remplace le plan d'une facture ÉMISE en bloc (PUT idempotent : répéter le
    même plan laisse la facture dans le même état). Refusé pour un brouillon
    (pas encore d'échéance réelle), un devis, un avoir ou une facture annulée ;
    refusé si la somme du plan dépasse le solde restant dû (contrôlé sous verrou
    FOR UPDATE du document — sérialisé avec les règlements 4C).

    Journalisé `sales_schedule.updated` ; aucune écriture comptable."""
    document = _lock_document(session, actor.company_id, document_id)
    if document.doc_kind != DocKind.INVOICE.value or document.status != DocStatus.ISSUED.value:
        raise ConflictError(
            "L'échéancier concerne une facture émise : brouillons, devis, avoirs et "
            "factures annulées n'ont pas d'échéancier."
        )
    if not lines:
        raise BusinessRuleError("Un échéancier vide se supprime : au moins une tranche attendue.")
    if len(lines) > MAX_SCHEDULE_LINES:
        raise BusinessRuleError(
            f"Au maximum {MAX_SCHEDULE_LINES} tranches par échéancier (reçu {len(lines)})."
        )
    lettres = payments.outstanding_for_documents(session, actor.company_id, [document_id])
    outstanding = max(document.total_ttc - lettres.get(document_id, 0), 0)
    planned_total = sum(line.expected_amount for line in lines)
    if planned_total > outstanding:
        raise BusinessRuleError(
            f"Le plan ({planned_total}) dépasse le solde restant dû ({outstanding}) : "
            "une tranche ne peut pas être attendue au-delà de la dette."
        )
    # Remplacement en bloc : delete + insert renumérotés 1..N (idempotent).
    session.query(SalesPaymentScheduleLine).filter(
        SalesPaymentScheduleLine.tenant_id == actor.company_id,
        SalesPaymentScheduleLine.document_id == document_id,
    ).delete(synchronize_session=False)
    for numero, line in enumerate(lines, start=1):
        session.add(
            SalesPaymentScheduleLine(
                tenant_id=actor.company_id,
                document_id=document_id,
                line_no=numero,
                expected_on=line.expected_on,
                expected_amount=line.expected_amount,
                note=line.note,
                created_by_user_id=actor.user_id,
            )
        )
    record_event(
        session,
        action="sales_schedule.updated",
        entity_type="sales_document",
        entity_id=document_id,
        payload={
            "tranches": len(lines),
            "total_planifie": planned_total,
            "solde_restant_du": outstanding,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return get_schedule(session, actor.company_id, document_id)


@dataclass(frozen=True)
class ScheduleSummary:
    """Le plan d'une facture, avec le contexte du document : pour la liste des
    échéanciers du dossier (page Ventes)."""

    document_id: uuid.UUID
    document_number: int
    partner_id: uuid.UUID
    partner_name: str
    currency: str
    total_ttc: int
    paid_ttc: int
    outstanding_ttc: int
    planned_total: int
    planned_remaining: int
    lines: list[ScheduleLine]


def list_schedules(
    session: Session, company_id: uuid.UUID, as_of: date | None = None
) -> list[ScheduleSummary]:
    """Tous les échéanciers du dossier, statués au jour demandé — une lecture
    groupée (lignes, factures, soldes, noms de tiers), jamais N+1 requêtes."""
    lignes = list(
        session.execute(
            select(SalesPaymentScheduleLine)
            .where(SalesPaymentScheduleLine.tenant_id == company_id)
            .order_by(SalesPaymentScheduleLine.document_id, SalesPaymentScheduleLine.line_no)
        ).scalars()
    )
    if not lignes:
        return []
    par_document: dict[uuid.UUID, list[SalesPaymentScheduleLine]] = {}
    for line in lignes:
        par_document.setdefault(line.document_id, []).append(line)
    invoices = list(
        session.execute(
            select(SalesDocument).where(
                SalesDocument.tenant_id == company_id,
                SalesDocument.id.in_(par_document.keys()),
                SalesDocument.doc_kind == DocKind.INVOICE.value,
                SalesDocument.status == DocStatus.ISSUED.value,
            )
        ).scalars()
    )
    lettres = payments.outstanding_for_documents(session, company_id, list(par_document.keys()))
    noms = {
        p.id: p.name
        for p in session.execute(
            select(Partner).where(
                Partner.tenant_id == company_id, Partner.id.in_({i.partner_id for i in invoices})
            )
        ).scalars()
    }
    jour = as_of or utcnow().date()
    summaries: list[ScheduleSummary] = []
    for invoice in sorted(invoices, key=lambda i: i.number or 0):
        lines = par_document[invoice.id]
        paid = lettres.get(invoice.id, 0)
        lines_statued = _statuses(lines, paid, jour)
        summaries.append(
            ScheduleSummary(
                document_id=invoice.id,
                document_number=invoice.number or 0,
                partner_id=invoice.partner_id,
                partner_name=noms.get(invoice.partner_id, "?"),
                currency=invoice.currency,
                total_ttc=invoice.total_ttc,
                paid_ttc=paid,
                outstanding_ttc=max(invoice.total_ttc - paid, 0),
                planned_total=sum(line.expected_amount for line in lines),
                planned_remaining=sum(
                    v.expected_amount for v in lines_statued if v.status != "settled"
                ),
                lines=lines_statued,
            )
        )
    return summaries
