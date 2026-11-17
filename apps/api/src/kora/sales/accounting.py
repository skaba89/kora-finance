"""Intégration comptable des ventes (Phase 4E).

La comptabilisation est un **acte explicite du comptable** (permission
`entries:post`) : aucune émission, aucun règlement, aucune relance ne génère
d'écriture — le garde-fou testé depuis la 4A. Une fois comptabilisée,
l'opération porte son écriture validée (POSTED, numérotée sans trou, immuable)
dans la colonne `entry_id` ; une erreur se corrige par contre-passation.

Écritures générées (SYSCOHADA révisé) :
- **facture émise** (journal des ventes) : débit 411x du tier au TTC, crédit du
  compte de produits choisi par le HT par groupe de lignes, crédit du compte
  collecté de chaque taux (4431 pour la TVA normale) ;
- **avoir émis** : l'écriture inverse dans le même journal ;
- **règlement** (journal de trésorerie selon le mode d'encaissement) : débit du
  compte de trésorerie, crédit du compte de tiers.

Comptes par défaut résolus dans le plan du dossier, sans jamais contourner un
choix explicite : tiers = compte client par défaut de la fiche (411x), sinon
le numéro 411 ; produits = 701 ; trésorerie = 571 pour la caisse, 521 pour les
autres modes. La TVA suit le compte collecté configuré sur chaque taux daté.

La date de l'écriture est le fait générateur : date d'émission du document,
date d'encaissement du règlement — jamais la date de la décision. L'exercice
qui couvre cette date doit rester ouvert et non verrouillé : comptabiliser
dans un exercice clôturé est refusé (même règle que toute saisie).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting.entries import (
    Actor,
    EntryData,
    LineData,
    apply_generated,
    check_entry_date,
    post_pending,
)
from kora.audit.service import record_event
from kora.core.errors import BusinessRuleError, ConflictError, NotFoundError
from kora.models.accounting import Account, TaxRate
from kora.models.ledger import Journal, JournalEntry
from kora.models.organization import FiscalYear
from kora.models.partners import Partner
from kora.models.sales import (
    DocKind,
    DocStatus,
    PaymentMethod,
    SalesDocument,
    SalesDocumentLine,
    SalesPayment,
)
from kora.sales.pdf import format_document_number
from kora.sales.service import _lock_document

# Numéros SYSCOHADA des comptes par défaut, résolus dans le plan du dossier.
CLIENT_ACCOUNT_NUMBER = "411"
SALES_ACCOUNT_NUMBER = "701"
CASH_ACCOUNT_NUMBER = "571"
BANK_ACCOUNT_NUMBER = "521"
# Journaux par défaut créés à l'initialisation du dossier : ventes et trésorerie.
VENTES_JOURNAL_CODE = "VT"
CASH_JOURNAL_CODE = "CA"
MOBILE_MONEY_JOURNAL_CODE = "MM"
BANK_JOURNAL_CODE = "BQ"

_BANK_LIKE_METHODS = frozenset(
    {
        PaymentMethod.BANK_TRANSFER.value,
        PaymentMethod.CHECK.value,
        PaymentMethod.CARD.value,
        PaymentMethod.OTHER.value,
    }
)


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


def _client_account(
    session: Session, company_id: uuid.UUID, partner_default_account_id: uuid.UUID | None
) -> Account:
    """Compte de tiers client : le choix par défaut de la fiche, sinon le 411."""
    if partner_default_account_id is not None:
        return _resolve_given_account(
            session, company_id, partner_default_account_id, "compte de tiers client"
        )
    return _resolve_account(session, company_id, CLIENT_ACCOUNT_NUMBER, "compte de tiers client")


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
    document: SalesDocument,
    *,
    partner_name: str,
    client: Account,
    product: Account,
    lines: list[SalesDocumentLine],
) -> list[LineData]:
    """Lignes d'écriture d'un document de vente : débit du tiers au TTC (crédit
    pour un avoir), crédit du compte de produits au HT par groupe de taux
    (débit pour un avoir), crédit du compte collecté de chaque taux (débit pour
    un avoir). Les montants viennent des instantanés de l'émission — jamais
    recalculés ici. L'exonération (sans taux) entre au HT du compte de produits,
    sans ligne de TVA."""
    # Regroupement des lignes par taux figé : (HT, TVA, taux).
    groupes: dict[uuid.UUID | None, tuple[int, int, TaxRate | None]] = {}
    for line in lines:
        ht, taxe, rate = groupes.get(line.tax_rate_id, (0, 0, None))
        if rate is None and line.tax_rate_id is not None:
            rate = session.get_one(TaxRate, line.tax_rate_id)
            if not rate.collected_account_number:
                raise BusinessRuleError(
                    f"Le taux « {rate.label} » n'a pas de compte de TVA collectée : "
                    "définissez-le (Paramètres > Taxes) avant de comptabiliser."
                )
        groupes[line.tax_rate_id] = (ht + line.line_ht, taxe + line.line_tax, rate)
    collected_by_rate: dict[uuid.UUID, Account] = {}
    for tax_rate_id, (_, _, rate) in groupes.items():
        if tax_rate_id is not None and rate is not None:
            if not rate.collected_account_number:  # pragma: no cover — déjà vérifié
                raise BusinessRuleError(
                    f"Le taux « {rate.label} » n'a pas de compte de TVA collectée."
                )
            collected_by_rate[tax_rate_id] = _resolve_account(
                session,
                company_id,
                rate.collected_account_number,
                f"compte de TVA collectée du taux « {rate.label} »",
            )
    is_invoice = DocKind(document.doc_kind) is DocKind.INVOICE
    ttc = document.total_ttc
    entry_lines: list[LineData] = [
        LineData(
            account_id=client.id,
            debit=ttc if is_invoice else 0,
            credit=0 if is_invoice else ttc,
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
                    account_id=product.id,
                    debit=0 if is_invoice else ht,
                    credit=ht if is_invoice else 0,
                    label="Ventes",
                )
            )
        if taxe > 0 and tax_rate_id is not None:
            collected = collected_by_rate[tax_rate_id]
            entry_lines.append(
                LineData(
                    account_id=collected.id,
                    debit=0 if is_invoice else taxe,
                    credit=taxe if is_invoice else 0,
                    label=rate.label[:200] if rate else "TVA",
                )
            )
    return entry_lines


def post_document(
    session: Session,
    actor: Actor,
    document_id: uuid.UUID,
    *,
    sales_account_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Comptabilise une facture ou un avoir émis : écriture validée du journal des
    ventes, liée au document. Le devis n'est jamais un fait financier ; un
    document annulé non plus. Idempotence refusée : une opération déjà
    comptabilisée ne l'est pas deux fois (409) — la course concurrente se
    sérialise sur le verrou du document, la seconde voit `entry_id` rempli."""
    document = _lock_document(session, actor.company_id, document_id)
    doc_kind = DocKind(document.doc_kind)
    if doc_kind is DocKind.QUOTE:
        raise BusinessRuleError("Un devis n'est pas comptabilisé : il n'est pas un fait financier.")
    if document.status != DocStatus.ISSUED.value:
        raise ConflictError("Seule une facture ou un avoir émis se comptabilise.")
    if document.entry_id is not None:
        raise ConflictError("Ce document est déjà comptabilisé : l'écriture est liée au document.")
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == document.partner_id
        )
    ).scalar_one()
    lines = list(
        session.execute(
            select(SalesDocumentLine)
            .where(SalesDocumentLine.document_id == document.id)
            .order_by(SalesDocumentLine.line_no)
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
    client = _client_account(session, actor.company_id, partner.default_client_account_id)
    product = (
        _resolve_given_account(session, actor.company_id, sales_account_id, "compte de produits")
        if sales_account_id is not None
        else _resolve_account(session, actor.company_id, SALES_ACCOUNT_NUMBER, "compte de produits")
    )
    entry_lines = _document_entry_lines(
        session,
        actor.company_id,
        document,
        partner_name=partner.name,
        client=client,
        product=product,
        lines=lines,
    )
    is_invoice = doc_kind is DocKind.INVOICE
    numero_affichage = format_document_number(
        document.doc_kind, fiscal_year.start_date, document.number or 0
    )
    label = f"{'Facture' if is_invoice else 'Avoir'} {numero_affichage} — {partner.name}"
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
            journal_id=_journal_by_code(session, actor.company_id, VENTES_JOURNAL_CODE).id,
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
        action="sales_document.posted",
        entity_type="sales_document",
        entity_id=document.id,
        payload={
            "type": document.doc_kind,
            "numero": numero_affichage,
            "total_ttc": document.total_ttc,
            "journal": VENTES_JOURNAL_CODE,
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
    """Comptabilise un règlement : écriture validée du journal de trésorerie
    (caisse, banque ou Mobile Money selon le mode d'encaissement), liée au
    règlement. La course concurrente se sérialise sur le verrou du règlement."""
    payment = session.execute(
        select(SalesPayment)
        .where(SalesPayment.tenant_id == actor.company_id, SalesPayment.id == payment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Règlement introuvable dans ce dossier.")
    if payment.entry_id is not None:
        raise ConflictError(
            "Ce règlement est déjà comptabilisé : l'écriture est liée au règlement."
        )
    check_entry_date(session, actor.company_id, payment.paid_on)
    partner = session.execute(
        select(Partner).where(
            Partner.tenant_id == actor.company_id, Partner.id == payment.partner_id
        )
    ).scalar_one()
    client = _client_account(session, actor.company_id, partner.default_client_account_id)
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
    label = f"Encaissement client {partner.name}"[:200]
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
            lines=[
                LineData(account_id=treasury.id, debit=payment.amount, label=partner.name[:200]),
                LineData(account_id=client.id, credit=payment.amount, label=partner.name[:200]),
            ],
        ),
    )
    post_pending(session, actor, entry)
    payment.entry_id = entry.id
    record_event(
        session,
        action="sales_payment.posted",
        entity_type="sales_payment",
        entity_id=payment.id,
        payload={
            "montant": payment.amount,
            "mode": payment.method,
            "journal": journal.code,
            "ecriture": entry.number,
        },
        actor_user_id=actor.user_id,
        ip_address=actor.ctx.ip_address,
    )
    session.commit()
    return entry
