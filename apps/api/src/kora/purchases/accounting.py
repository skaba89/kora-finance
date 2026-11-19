"""Intégration comptable des achats (Phase 4F).

La comptabilisation est un **acte explicite du comptable** (permission
`entries:post`) : aucune émission, aucun décaissement ne génère d'écriture —
le garde-fou testé depuis la 4A. Une fois comptabilisée, l'opération porte son
écriture validée (POSTED, numérotée sans trou, immuable) dans la colonne
`entry_id` ; une erreur se corrige par contre-passation.

Écritures générées (SYSCOHADA révisé) :
- **facture fournisseur émise** (journal des achats) : débit du compte de charge
  choisi au HT par groupe de lignes, débit du compte de TVA récupérable de chaque
  taux (4452 pour la TVA normale sur achats), crédit du compte de tiers au TTC ;
- **avoir fournisseur émis** : l'écriture inverse dans le même journal ;
- **décaissement** (journal de trésorerie selon le mode de paiement) : débit du
  compte de tiers, crédit du compte de trésorerie.

Comptes par défaut résolus dans le plan du dossier, sans jamais contourner un
choix explicite : tiers = compte fournisseur par défaut de la fiche (401x),
sinon le numéro 401 ; charge = 601 ; trésorerie = 571 pour la caisse, 521 pour
les autres modes. La TVA suit le compte récupérable configuré sur chaque taux
daté.

La date de l'écriture est le fait générateur : date du document fournisseur,
date de décaissement — jamais la date de la décision. L'exercice qui couvre
cette date doit rester ouvert et non verrouillé : comptabiliser dans un
exercice clôturé est refusé (même règle que toute saisie).
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting.entries import (
    Actor,
    EntryData,
    LineData,
    apply_generated,
    check_entry_date,
    post_pending,
    reversal_id_of,
)
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account, TaxRate
from kora.models.common import utcnow
from kora.models.ledger import Journal, JournalEntry
from kora.models.organization import FiscalYear
from kora.models.partners import Partner
from kora.models.purchases import (
    PurchaseDocKind,
    PurchaseDocStatus,
    PurchaseDocument,
    PurchaseDocumentLine,
    PurchasePayment,
    PurchasePaymentAllocation,
    PurchaseRefund,
)
from kora.models.sales import PaymentMethod
from kora.purchases.service import _lock_document, format_document_number

# Numéros SYSCOHADA des comptes par défaut, résolus dans le plan du dossier.
SUPPLIER_ACCOUNT_NUMBER = "401"
# Avances et acomptes versés (lot B-3) : le reste non affecté d'un décaissement
# (avance versée sans facture ou trop-versé) se porte au 4091 — jamais au 401,
# où il masquerait une dette réelle dans le bilan.
ADVANCES_PAID_ACCOUNT_NUMBER = "4091"
# Parent du référentiel préchargé : utilisé quand le dossier n'a pas créé le 4091.
ADVANCES_PARENT_ACCOUNT_NUMBER = "409"
PURCHASE_ACCOUNT_NUMBER = "601"
CASH_ACCOUNT_NUMBER = "571"
BANK_ACCOUNT_NUMBER = "521"
# Journaux par défaut créés à l'initialisation du dossier : achats, trésorerie
# et opérations diverses (transfert d'avance — aucun mouvement de trésorerie).
ACHATS_JOURNAL_CODE = "AC"
CASH_JOURNAL_CODE = "CA"
MOBILE_MONEY_JOURNAL_CODE = "MM"
BANK_JOURNAL_CODE = "BQ"
OD_JOURNAL_CODE = "OD"


def _resolve_account(session: Session, company_id: uuid.UUID, number: str, role: str) -> Account:
    """Compte du plan par numéro : il doit exister et être actif."""
    account = session.execute(
        select(Account).where(Account.tenant_id == company_id, Account.number == number)
    ).scalar_one_or_none()
    if account is None:
        raise BusinessRuleError(
            f"Compte {number} introuvable dans le plan comptable du dossier "
            f"(attendu pour {role}) : créez-le ou choisissez un autre compte."
        )
    if not account.is_active:
        raise BusinessRuleError(f"Le compte {number} ({role}) est désactivé.")
    return account


def _resolve_given_account(
    session: Session, company_id: uuid.UUID, account_id: uuid.UUID, role: str
) -> Account:
    """Compte explicitement choisi : il appartient au plan du dossier et est actif."""
    account = session.execute(
        select(Account).where(Account.tenant_id == company_id, Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise BusinessRuleError(f"Le compte {role} choisi est introuvable dans ce dossier.")
    if not account.is_active:
        raise BusinessRuleError(f"Le compte {role} choisi est désactivé.")
    return account


def _supplier_account(
    session: Session, company_id: uuid.UUID, partner_default_account_id: uuid.UUID | None
) -> Account:
    """Compte de tiers fournisseur : le choix par défaut de la fiche, sinon le 401."""
    if partner_default_account_id is not None:
        return _resolve_given_account(
            session, company_id, partner_default_account_id, "compte de tiers fournisseur"
        )
    return _resolve_account(
        session, company_id, SUPPLIER_ACCOUNT_NUMBER, "compte de tiers fournisseur"
    )


def _advances_account(session: Session, company_id: uuid.UUID) -> Account:
    """Compte d'avances et acomptes versés : le 4091 précis du plan quand le
    dossier l'a créé, sinon le parent 409 « Fournisseurs débiteurs » du
    référentiel préchargé — l'avance reste portée hors du 401 (dettes réelles)
    dans tous les cas, sans exiger une personnalisation du plan."""
    precise = session.execute(
        select(Account).where(
            Account.tenant_id == company_id, Account.number == ADVANCES_PAID_ACCOUNT_NUMBER
        )
    ).scalar_one_or_none()
    if precise is not None:
        if not precise.is_active:
            raise BusinessRuleError(
                f"Le compte {ADVANCES_PAID_ACCOUNT_NUMBER} (avances versées) est désactivé."
            )
        return precise
    return _resolve_account(
        session,
        company_id,
        ADVANCES_PARENT_ACCOUNT_NUMBER,
        "compte d'avances et acomptes versés (409)",
    )


def _journal_by_code(session: Session, company_id: uuid.UUID, code: str) -> Journal:
    journal = session.execute(
        select(Journal).where(Journal.tenant_id == company_id, Journal.code == code)
    ).scalar_one_or_none()
    if journal is None:
        raise BusinessRuleError(f"Le journal {code} est introuvable : créez-le (Paramètres).")
    if not journal.is_active:
        raise BusinessRuleError(f"Le journal {code} est désactivé.")
    return journal


def _document_entry_lines(
    session: Session,
    company_id: uuid.UUID,
    document: PurchaseDocument,
    *,
    partner_name: str,
    supplier: Account,
    expense: Account,
    lines: list[PurchaseDocumentLine],
) -> list[LineData]:
    """Lignes d'écriture d'un document d'achat : débit du compte de charge au HT
    par groupe de taux (crédit pour un avoir), débit du compte de TVA récupérable
    de chaque taux (crédit pour un avoir), crédit du tiers au TTC (débit pour un
    avoir). Les montants viennent des instantanés de l'émission — jamais
    recalculés ici. L'exonération (sans taux) entre au HT du compte de charge,
    sans ligne de TVA."""
    # Regroupement des lignes par taux figé : (HT, TVA, taux).
    groupes: dict[uuid.UUID | None, tuple[int, int, TaxRate | None]] = {}
    for line in lines:
        ht, taxe, rate = groupes.get(line.tax_rate_id, (0, 0, None))
        if rate is None and line.tax_rate_id is not None:
            rate = session.get_one(TaxRate, line.tax_rate_id)
            if not rate.deductible_account_number:
                raise BusinessRuleError(
                    f"Le taux « {rate.label} » n'a pas de compte de TVA récupérable : "
                    "définissez-le (Paramètres > Taxes) avant de comptabiliser."
                )
        groupes[line.tax_rate_id] = (ht + line.line_ht, taxe + line.line_tax, rate)
    deductible_by_rate: dict[uuid.UUID, Account] = {}
    for tax_rate_id, (_, _, rate) in groupes.items():
        if tax_rate_id is not None and rate is not None:
            if not rate.deductible_account_number:  # pragma: no cover — déjà vérifié
                raise BusinessRuleError(
                    f"Le taux « {rate.label} » n'a pas de compte de TVA récupérable."
                )
            deductible_by_rate[tax_rate_id] = _resolve_account(
                session,
                company_id,
                rate.deductible_account_number,
                f"compte de TVA récupérable du taux « {rate.label} »",
            )
    is_invoice = PurchaseDocKind(document.doc_kind) is PurchaseDocKind.SUPPLIER_INVOICE
    ttc = document.total_ttc
    entry_lines: list[LineData] = [
        LineData(
            account_id=supplier.id,
            debit=0 if is_invoice else ttc,
            credit=ttc if is_invoice else 0,
            label=partner_name[:200],
        )
    ]
    for tax_rate_id in sorted(groupes, key=lambda k: (k is not None, str(k) if k else "")):
        ht, taxe, rate = groupes[tax_rate_id]
        if ht <= 0 and taxe <= 0:
            continue
        if ht > 0:
            entry_lines.append(
                LineData(
                    account_id=expense.id,
                    debit=ht if is_invoice else 0,
                    credit=0 if is_invoice else ht,
                    label="Achats",
                )
            )
        if taxe > 0 and tax_rate_id is not None:
            deductible = deductible_by_rate[tax_rate_id]
            entry_lines.append(
                LineData(
                    account_id=deductible.id,
                    debit=taxe if is_invoice else 0,
                    credit=0 if is_invoice else taxe,
                    label=rate.label[:200] if rate else "TVA",
                )
            )
    return entry_lines


def post_document(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    *,
    expense_account_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Comptabilise une facture ou un avoir fournisseur émis : écriture validée du
    journal des achats, liée au document. Idempotence refusée : une opération
    déjà comptabilisée ne l'est pas deux fois (409) — la course concurrente se
    sérialise sur le verrou du document, la seconde voit `entry_id` rempli."""
    document = _lock_document(session, actor.company_id, document_id)
    if document.status != PurchaseDocStatus.ISSUED.value:
        raise ConflictError("Seule une facture ou un avoir fournisseur émis se comptabilise.")
    if document.entry_id is not None:
        raise ConflictError("Ce document est déjà comptabilisé : l'écriture est liée au document.")
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == document.partner_id
        )
    ).scalar_one()
    lines = list(
        session.execute(
            select(PurchaseDocumentLine)
            .where(PurchaseDocumentLine.document_id == document.id)
            .order_by(PurchaseDocumentLine.line_no)
        ).scalars()
    )
    if not lines:
        raise BusinessRuleError("Ce document n'a aucune ligne : rien à comptabiliser.")
    assert document.issued_on is not None  # noqa: S101 — garanti par la base dès l'émission
    day = document.issued_on
    check_entry_date(session, actor.company_id, day)
    fiscal_year = session.execute(
        select(FiscalYear).where(
            FiscalYear.tenant_id == actor.company_id, FiscalYear.id == document.fiscal_year_id
        )
    ).scalar_one()
    supplier = _supplier_account(session, actor.company_id, partner.default_supplier_account_id)
    expense = (
        _resolve_given_account(session, actor.company_id, expense_account_id, "compte de charge")
        if expense_account_id is not None
        else _resolve_account(
            session, actor.company_id, PURCHASE_ACCOUNT_NUMBER, "compte de charge"
        )
    )
    entry_lines = _document_entry_lines(
        session,
        actor.company_id,
        document,
        partner_name=partner.name,
        supplier=supplier,
        expense=expense,
        lines=lines,
    )
    is_invoice = PurchaseDocKind(document.doc_kind) is PurchaseDocKind.SUPPLIER_INVOICE
    numero_affichage = format_document_number(
        document.doc_kind, fiscal_year.start_date, document.number or 0
    )
    label = (
        f"{'Facture fournisseur' if is_invoice else 'Avoir fournisseur'} "
        f"{numero_affichage} — {partner.name}"
    )
    entry = JournalEntry(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        label=label[:200],
        created_by_user_id=actor.user_id,
    )
    apply_generated(
        session,
        actor,
        entry,
        EntryData(
            journal_id=_journal_by_code(session, actor.company_id, ACHATS_JOURNAL_CODE).id,
            entry_date=day,
            label=label[:200],
            reference=numero_affichage,
            lines=entry_lines,
        ),
    )
    post_pending(session, actor, entry)
    document.entry_id = entry.id
    record_event(
        session,
        action="purchase_document.posted",
        entity_type="purchase_document",
        entity_id=document.id,
        payload={
            "type": document.doc_kind,
            "numero": numero_affichage,
            "total_ttc": document.total_ttc,
            "journal": ACHATS_JOURNAL_CODE,
            "ecriture": entry.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return entry


def post_payment(
    session: Session,
    actor: Actor,
    payment_id: uuid.UUID,
    *,
    cash_account_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Comptabilise un décaissement : écriture validée du journal de trésorerie
    (caisse, banque ou Mobile Money selon le mode de paiement), liée au
    règlement. La course concurrente se sérialise sur le verrou du règlement.

    La partie **affectée** au débit du compte de tiers fournisseur (le lettrage
    commercial correspond à la comptabilité) ; le **reste non affecté** (avance
    ou trop-versé, lot B-3) au débit du 4091 « Fournisseurs, avances et
    acomptes versés » — jamais au 401, où il masquerait une dette dans le
    bilan. Les affectations présentes à la comptabilisation sont couvertes par
    cette écriture (`entry_id` posé) ; une affectation ultérieure restera non
    couverte jusqu'au transfert d'avance explicite."""
    payment = session.execute(
        select(PurchasePayment)
        .where(PurchasePayment.tenant_id == actor.company_id, PurchasePayment.id == payment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Règlement introuvable dans ce dossier.")
    if payment.entry_id is not None:
        raise ConflictError(
            "Ce règlement est déjà comptabilisé : l'écriture est liée au règlement."
        )
    allocations = sorted(
        session.execute(
            select(PurchasePaymentAllocation).where(
                PurchasePaymentAllocation.payment_id == payment.id
            )
        ).scalars(),
        key=lambda row: row.document_id,
    )
    check_entry_date(session, actor.company_id, payment.paid_on)
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == payment.partner_id
        )
    ).scalar_one()
    supplier = _supplier_account(session, actor.company_id, partner.default_supplier_account_id)
    if cash_account_id is not None:
        treasury = _resolve_given_account(
            session, actor.company_id, cash_account_id, "compte de trésorerie"
        )
    else:
        number = (
            CASH_ACCOUNT_NUMBER
            if payment.method == PaymentMethod.CASH.value
            else BANK_ACCOUNT_NUMBER
        )
        treasury = _resolve_account(session, actor.company_id, number, "compte de trésorerie")
    journal_code = (
        CASH_JOURNAL_CODE
        if payment.method == PaymentMethod.CASH.value
        else (
            MOBILE_MONEY_JOURNAL_CODE
            if payment.method == PaymentMethod.MOBILE_MONEY.value
            else BANK_JOURNAL_CODE
        )
    )
    journal = _journal_by_code(session, actor.company_id, journal_code)
    lettres = sum(allocation.amount for allocation in allocations)
    reste = payment.amount - lettres
    lines = [
        LineData(account_id=treasury.id, credit=payment.amount, label=partner.name[:200]),
    ]
    if lettres > 0:
        lines.append(LineData(account_id=supplier.id, debit=lettres, label=partner.name[:200]))
    if reste > 0:
        advances = _advances_account(session, actor.company_id)
        lines.append(
            LineData(
                account_id=advances.id,
                debit=reste,
                label=f"Avance {partner.name}"[:200],
            )
        )
    label = f"Décaissement fournisseur {partner.name}"[:200]
    entry = JournalEntry(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        label=label,
        created_by_user_id=actor.user_id,
    )
    apply_generated(
        session,
        actor,
        entry,
        EntryData(
            journal_id=journal.id,
            entry_date=payment.paid_on,
            label=label,
            reference=payment.reference,
            lines=lines,
        ),
    )
    post_pending(session, actor, entry)
    payment.entry_id = entry.id
    for allocation in allocations:
        allocation.entry_id = entry.id
    record_event(
        session,
        action="purchase_payment.posted",
        entity_type="purchase_payment",
        entity_id=payment.id,
        payload={
            "montant": payment.amount,
            "mode": payment.method,
            "journal": journal.code,
            "ecriture": entry.number,
            "affecte": lettres,
            "non_affecte": reste,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return entry


def post_allocation_entry(
    session: Session,
    actor: Actor,
    payment_id: uuid.UUID,
    *,
    entry_date: date | None = None,
) -> JournalEntry:
    """Transfert d'avance (lot B-3) : couvre en comptabilité les affectations
    ajoutées **après** la comptabilisation du règlement — débit du compte de
    tiers fournisseur, crédit du 4091 « Fournisseurs, avances et acomptes
    versés », au journal des opérations diverses (aucun mouvement de
    trésorerie : le 4091 se reporte sur le 401x, l'avance devient un règlement
    de factures). La date d'écriture est le jour du transfert (défaut :
    aujourd'hui) — le reclassement s'inscrit dans l'exercice courant, ouvert.
    Idempotence refusée : une affectation déjà couverte ne se transfère pas
    deux fois (409) — la course concurrente se sérialise sur le verrou du
    règlement."""
    payment = session.execute(
        select(PurchasePayment)
        .where(PurchasePayment.tenant_id == actor.company_id, PurchasePayment.id == payment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Règlement introuvable dans ce dossier.")
    if payment.entry_id is None:
        raise ConflictError(
            "Ce règlement n'est pas comptabilisé : ses affectations seront "
            "couvertes par l'écriture du règlement — rien à transférer."
        )
    if reversal_id_of(session, actor.company_id, payment.entry_id) is not None:
        raise ConflictError(
            "L'écriture du règlement est contre-passée : rétablissez le "
            "règlement avant de transférer ses avances."
        )
    non_couvertes = sorted(
        session.execute(
            select(PurchasePaymentAllocation).where(
                PurchasePaymentAllocation.payment_id == payment.id,
                PurchasePaymentAllocation.entry_id.is_(None),
            )
        ).scalars(),
        key=lambda row: row.document_id,
    )
    if not non_couvertes:
        raise ConflictError(
            "Aucune affectation à transférer : les affectations de ce règlement "
            "sont déjà couvertes en comptabilité."
        )
    jour = entry_date if entry_date is not None else utcnow().date()
    check_entry_date(session, actor.company_id, jour)
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == payment.partner_id
        )
    ).scalar_one()
    supplier = _supplier_account(session, actor.company_id, partner.default_supplier_account_id)
    advances = _advances_account(session, actor.company_id)
    transfert = sum(allocation.amount for allocation in non_couvertes)
    lines = [
        LineData(account_id=supplier.id, debit=transfert, label=partner.name[:200]),
    ]
    for allocation in non_couvertes:
        lines.append(
            LineData(
                account_id=advances.id,
                credit=allocation.amount,
                label=f"Transfert avance {partner.name}"[:200],
            )
        )
    label = f"Transfert d'avance fournisseur {partner.name}"[:200]
    entry = JournalEntry(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        label=label,
        created_by_user_id=actor.user_id,
    )
    apply_generated(
        session,
        actor,
        entry,
        EntryData(
            journal_id=_journal_by_code(session, actor.company_id, OD_JOURNAL_CODE).id,
            entry_date=jour,
            label=label,
            reference=payment.reference,
            lines=lines,
        ),
    )
    post_pending(session, actor, entry)
    for allocation in non_couvertes:
        allocation.entry_id = entry.id
    record_event(
        session,
        action="purchase_payment.allocation_entry_posted",
        entity_type="purchase_payment",
        entity_id=payment.id,
        payload={
            "transfert": transfert,
            "affectations": len(non_couvertes),
            "journal": OD_JOURNAL_CODE,
            "ecriture": entry.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return entry


def post_refund_entry(
    session: Session,
    actor: Actor,
    refund_id: uuid.UUID,
    *,
    cash_account_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Comptabilise un remboursement reçu d'un fournisseur (lot B-3) : écriture
    validée du journal de trésorerie selon le mode — débit du compte de
    trésorerie (l'argent revient), crédit du 4091 « Fournisseurs, avances et
    acomptes versés » (l'avance remboursée sort du bilan). Le règlement porteur
    doit être comptabilisé et son écriture vivante : le remboursement ne fait
    que sortir une part du débit d'avance déjà inscrit — sinon le 4091
    partirait en crédit sans origine."""
    refund = session.execute(
        select(PurchaseRefund)
        .where(PurchaseRefund.tenant_id == actor.company_id, PurchaseRefund.id == refund_id)
        .with_for_update()
    ).scalar_one_or_none()
    if refund is None:
        raise NotFoundError("Remboursement introuvable dans ce dossier.")
    if refund.entry_id is not None:
        raise ConflictError(
            "Ce remboursement est déjà comptabilisé : l'écriture est liée au remboursement."
        )
    payment = session.execute(
        select(PurchasePayment)
        .where(
            PurchasePayment.tenant_id == actor.company_id, PurchasePayment.id == refund.payment_id
        )
        .with_for_update()
    ).scalar_one()
    if payment.entry_id is None:
        raise ConflictError(
            "Le règlement porteur n'est pas comptabilisé : comptabilisez-le "
            "d'abord (le 4091 doit exister avant d'être remboursé)."
        )
    if reversal_id_of(session, actor.company_id, payment.entry_id) is not None:
        raise ConflictError(
            "L'écriture du règlement porteur est contre-passée : son avance "
            "n'existe plus au 4091 — le remboursement ne se comptabilise pas."
        )
    check_entry_date(session, actor.company_id, refund.refunded_on)
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == payment.partner_id
        )
    ).scalar_one()
    advances = _advances_account(session, actor.company_id)
    if cash_account_id is not None:
        treasury = _resolve_given_account(
            session, actor.company_id, cash_account_id, "compte de trésorerie"
        )
    else:
        number = (
            CASH_ACCOUNT_NUMBER
            if refund.method == PaymentMethod.CASH.value
            else BANK_ACCOUNT_NUMBER
        )
        treasury = _resolve_account(session, actor.company_id, number, "compte de trésorerie")
    journal_code = (
        CASH_JOURNAL_CODE
        if refund.method == PaymentMethod.CASH.value
        else (
            MOBILE_MONEY_JOURNAL_CODE
            if refund.method == PaymentMethod.MOBILE_MONEY.value
            else BANK_JOURNAL_CODE
        )
    )
    journal = _journal_by_code(session, actor.company_id, journal_code)
    label = f"Remboursement fournisseur {partner.name}"[:200]
    entry = JournalEntry(
        id=uuid.uuid4(),
        tenant_id=actor.company_id,
        label=label,
        created_by_user_id=actor.user_id,
    )
    apply_generated(
        session,
        actor,
        entry,
        EntryData(
            journal_id=journal.id,
            entry_date=refund.refunded_on,
            label=label,
            reference=refund.reference,
            lines=[
                LineData(
                    account_id=treasury.id,
                    debit=refund.amount,
                    label=partner.name[:200],
                ),
                LineData(
                    account_id=advances.id,
                    credit=refund.amount,
                    label=f"Avance remboursée {partner.name}"[:200],
                ),
            ],
        ),
    )
    post_pending(session, actor, entry)
    refund.entry_id = entry.id
    record_event(
        session,
        action="purchase_refund.posted",
        entity_type="purchase_refund",
        entity_id=refund.id,
        payload={
            "montant": refund.amount,
            "mode": refund.method,
            "journal": journal.code,
            "ecriture": entry.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return entry
