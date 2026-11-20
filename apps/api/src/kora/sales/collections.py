"""Indicateurs de recouvrement (lot B-4) : encours, DSO, taux de recouvrement.

Tout est **calculé en lecture** au jour demandé, à partir des seules sources de
vérité existantes (factures émises 4B, affectations de règlements 4C, avoirs
partiels, remboursements B-3) : aucune table, aucun statut dérivé, aucun
flottant — les taux sont en points de base (10 000 = 100 %), les durées en
jours entiers.

Définitions (affichées telles quelles dans l'interface fr/en) :

- **Encours** : somme des soldes restants dus des factures émises (TTC -
  affectations - avoirs partiels émis), exactement la balance âgée 4C.
- **Encours échu** : part de l'encours dont l'échéance est passée au jour
  demandé ; le retard moyen est pondéré par les soldes.
- **DSO (Days Sales Outstanding)** en jours de ventes : proportion de l'encours
  couverte par les ventes facturées des N derniers jours —
  `encours × N ÷ facturé(N)`, borné à N (au-delà, l'encours date d'avant la
  fenêtre : le DSO ne peut pas dépasser la fenêtre de mesure). Arithmétique
  entièrement entière, arrondie au plus proche.
- **Taux de recouvrement** sur la fenêtre : encaissements **nets des
  remboursements** (B-3) rapportés aux factures émises sur la même fenêtre —
  `net × 10 000 ÷ facturé`, en points de base.
- **Top débiteurs** : les cinq tiers au plus fort solde restant dû, avec leur
  retard maximum (priorité de relance).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.models.partners import Partner
from kora.models.sales import DocKind, DocStatus, SalesDocument, SalesPayment, SalesRefund
from kora.sales import payments

TOP_DEBTORS = 5
DEFAULT_LOOKBACK_DAYS = 90


@dataclass(frozen=True)
class Debtor:
    """Un tiers au solde restant dû significatif, pour la priorité de relance."""

    partner_id: uuid.UUID
    partner_name: str
    outstanding_ttc: int
    max_days_late: int


@dataclass(frozen=True)
class CollectionKpis:
    """Les indicateurs de recouvrement au jour demandé."""

    as_of: date
    lookback_days: int
    outstanding_ttc: int
    overdue_ttc: int
    overdue_share_bp: int  # part échue en points de base (10 000 = 100 %)
    weighted_days_late: int  # retard moyen pondéré des factures échues
    dso_days: int  # jours de ventes, borné à la fenêtre
    billed_ttc: int  # factures émises sur la fenêtre
    collected_ttc: int  # encaissements nets des remboursements sur la fenêtre
    recovery_rate_bp: int  # taux de recouvrement en points de base
    top_debtors: list[Debtor]


def _bp(numerateur: int, denominateur: int) -> int:
    """Part entière en points de base, arrondie au plus proche : jamais de
    flottant (10 000 = 100 %)."""
    if denominateur <= 0:
        return 0
    return (numerateur * 10_000 + denominateur // 2) // denominateur


def receivables_kpis(
    session: Session,
    company_id: uuid.UUID,
    as_of: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> CollectionKpis:
    """Les indicateurs au {as_of}, fenêtre de mesure {lookback_days} jours.

    Réutilise le calcul exact de la balance âgée 4C (soldes et buckets) : les
    indicateurs ne peuvent jamais diverger de la balance affichée à côté."""
    invoices = list(
        session.execute(
            select(SalesDocument).where(
                SalesDocument.tenant_id == company_id,
                SalesDocument.doc_kind == DocKind.INVOICE.value,
                SalesDocument.status == DocStatus.ISSUED.value,
            )
        ).scalars()
    )
    lettres = payments.outstanding_for_documents(session, company_id, [i.id for i in invoices])

    encours = 0
    echue = 0
    retard_pondere = 0
    par_tier: dict[uuid.UUID, list[int]] = {}
    for invoice in invoices:
        solde = invoice.total_ttc - lettres.get(invoice.id, 0)
        if solde <= 0:
            continue
        encours += solde
        retard = 0 if invoice.due_on is None else max((as_of - invoice.due_on).days, 0)
        if retard > 0:
            echue += solde
            retard_pondere += retard * solde
        par_tier.setdefault(invoice.partner_id, [0, 0])
        par_tier[invoice.partner_id][0] += solde
        par_tier[invoice.partner_id][1] = max(par_tier[invoice.partner_id][1], retard)

    # DSO en jours de ventes : proportion de l'encours couverte par les ventes
    # de la fenêtre, bornée à la fenêtre (un encours antérieur à la fenêtre ne
    # gonfle pas artificiellement le DSO au-delà de la période mesurée).
    depuis = as_of - timedelta(days=lookback_days)
    facture = int(
        session.execute(
            select(func.coalesce(func.sum(SalesDocument.total_ttc), 0)).where(
                SalesDocument.tenant_id == company_id,
                SalesDocument.doc_kind == DocKind.INVOICE.value,
                SalesDocument.status == DocStatus.ISSUED.value,
                SalesDocument.issued_on >= depuis,
                SalesDocument.issued_on <= as_of,
            )
        ).scalar_one()
    )
    encaisse = int(
        session.execute(
            select(func.coalesce(func.sum(SalesPayment.amount), 0)).where(
                SalesPayment.tenant_id == company_id,
                SalesPayment.paid_on >= depuis,
                SalesPayment.paid_on <= as_of,
            )
        ).scalar_one()
    )
    rembourse = int(
        session.execute(
            select(func.coalesce(func.sum(SalesRefund.amount), 0)).where(
                SalesRefund.tenant_id == company_id,
                SalesRefund.refunded_on >= depuis,
                SalesRefund.refunded_on <= as_of,
            )
        ).scalar_one()
    )
    net = max(encaisse - rembourse, 0)
    # DSO entier exact, arrondi au plus proche : encours ÷ facturé × fenêtre.
    dso = (
        min((encours * lookback_days + facture // 2) // facture, lookback_days)
        if facture > 0
        else 0
    )

    noms = {
        p.id: p.name
        for p in session.execute(select(Partner).where(Partner.tenant_id == company_id)).scalars()
        if p.id in par_tier
    }
    debiteurs = sorted(
        (
            Debtor(
                partner_id=tier,
                partner_name=noms.get(tier, "?"),
                outstanding_ttc=solde_et_retard[0],
                max_days_late=solde_et_retard[1],
            )
            for tier, solde_et_retard in par_tier.items()
        ),
        key=lambda d: d.outstanding_ttc,
        reverse=True,
    )[:TOP_DEBTORS]

    return CollectionKpis(
        as_of=as_of,
        lookback_days=lookback_days,
        outstanding_ttc=encours,
        overdue_ttc=echue,
        overdue_share_bp=_bp(echue, encours),
        weighted_days_late=(retard_pondere // echue) if echue > 0 else 0,
        dso_days=dso,
        billed_ttc=facture,
        collected_ttc=net,
        recovery_rate_bp=_bp(net, facture),
        top_debtors=debiteurs,
    )
