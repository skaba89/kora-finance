"""Saisie guidée : une opération décrite simplement (« j'ai payé une facture ») produit
une écriture en partie double, enregistrée en brouillon.

Les correspondances opération → comptes et la nature des recettes et des dépenses
(`data/saisie_guidee_v1.csv`) sont **à valider par un expert-comptable guinéen**. Les
comptes proposés sont toujours des comptes d'imputation du dossier : si un compte du
référentiel a des sous-comptes (ex. 5521 sous 552), ce sont eux qui sont proposés.

TVA : le montant saisi est le montant total payé ou facturé (TTC) ; la part de TVA est
calculée avec le taux TVA_NORMAL du dossier en vigueur à la date de l'opération
(arrondi au plus proche, la TVA est le complément exact pour que l'écriture s'équilibre).
"""

import csv
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import lru_cache
from importlib import resources

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kora.accounting import entries
from kora.accounting.entries import Actor, EntryData, LineData
from kora.core.errors import BusinessRuleError
from kora.models.accounting import Account, TaxRate
from kora.models.ledger import MAX_LINE_AMOUNT, Journal, JournalEntry

REFERENCE = "SAISIE_GUIDEE_V1"
_NATURES_FILE = "saisie_guidee_v1.csv"
VAT_CODE = "TVA_NORMAL"


class Operation(StrEnum):
    VENTE_COMPTANT = "VENTE_COMPTANT"
    FACTURE_CLIENT = "FACTURE_CLIENT"
    ENCAISSEMENT_CLIENT = "ENCAISSEMENT_CLIENT"
    ACHAT_COMPTANT = "ACHAT_COMPTANT"
    FACTURE_FOURNISSEUR = "FACTURE_FOURNISSEUR"
    PAIEMENT_FOURNISSEUR = "PAIEMENT_FOURNISSEUR"
    VIREMENT_INTERNE = "VIREMENT_INTERNE"


class Sense(StrEnum):
    PRODUIT = "PRODUIT"
    CHARGE = "CHARGE"


class Party(StrEnum):
    CLIENT = "CLIENT"
    FOURNISSEUR = "FOURNISSEUR"


@dataclass(frozen=True)
class OperationSpec:
    label: str
    nature: Sense | None = None
    treasury: bool = False
    target_treasury: bool = False
    party: Party | None = None
    # Journal fixe ; sinon celui du compte de trésorerie (banque, caisse, Mobile Money).
    journal: str | None = None


SPECS: dict[Operation, OperationSpec] = {
    Operation.VENTE_COMPTANT: OperationSpec("Vente encaissée", Sense.PRODUIT, treasury=True),
    Operation.FACTURE_CLIENT: OperationSpec(
        "Facture client", Sense.PRODUIT, party=Party.CLIENT, journal="VT"
    ),
    Operation.ENCAISSEMENT_CLIENT: OperationSpec(
        "Règlement client", treasury=True, party=Party.CLIENT
    ),
    Operation.ACHAT_COMPTANT: OperationSpec("Dépense payée", Sense.CHARGE, treasury=True),
    Operation.FACTURE_FOURNISSEUR: OperationSpec(
        "Facture fournisseur", Sense.CHARGE, party=Party.FOURNISSEUR, journal="AC"
    ),
    Operation.PAIEMENT_FOURNISSEUR: OperationSpec(
        "Règlement fournisseur", treasury=True, party=Party.FOURNISSEUR
    ),
    Operation.VIREMENT_INTERNE: OperationSpec(
        "Virement entre comptes", treasury=True, target_treasury=True
    ),
}

# Comptes de trésorerie proposés et journal correspondant. À valider : banques (52),
# monnaie électronique (55), caisses (57).
TREASURY_JOURNALS: dict[str, str] = {"52": "BQ", "55": "MM", "57": "CA"}
PARTY_PREFIXES: dict[Party, str] = {Party.CLIENT: "411", Party.FOURNISSEUR: "401"}


@dataclass(frozen=True)
class Nature:
    sense: Sense
    code: str
    label: str
    label_en: str
    account_number: str
    vat_possible: bool
    note: str


@lru_cache
def natures() -> tuple[Nature, ...]:
    data = resources.files("kora.accounting.data").joinpath(_NATURES_FILE)
    with data.open(encoding="utf-8") as handle:
        rows = tuple(
            Nature(
                sense=Sense(row["sens"]),
                code=row["code"],
                label=row["libelle"],
                label_en=row["libelle_en"],
                account_number=row["compte"],
                vat_possible=row["tva_possible"] == "oui",
                note=row["note"],
            )
            for row in csv.DictReader(handle, delimiter=";")
        )
    keys = [(n.sense, n.code) for n in rows]
    if len(set(keys)) != len(keys):
        raise RuntimeError(f"{_NATURES_FILE} : code de nature en double")
    return rows


# --- Comptes proposés


def _leaf_accounts(
    session: Session, company_id: uuid.UUID, prefixes: Iterable[str]
) -> list[Account]:
    """Comptes actifs sans sous-compte sous ces préfixes (préfixe compris), par numéro.
    Un sous-compte désactivé fait toujours du parent un compte de regroupement."""
    prefixes = sorted(set(prefixes))
    if not prefixes:
        return []
    accounts = list(
        session.execute(
            select(Account)
            .where(
                Account.tenant_id == company_id,
                or_(*(Account.number.startswith(p, autoescape=True) for p in prefixes)),
            )
            .order_by(Account.number)
        ).scalars()
    )
    numbers = [a.number for a in accounts]
    return [
        a
        for a in accounts
        if a.is_active and not any(n != a.number and n.startswith(a.number) for n in numbers)
    ]


@dataclass(frozen=True)
class NatureChoice:
    nature: Nature
    account: Account


def nature_choices(session: Session, company_id: uuid.UUID, sense: Sense) -> list[NatureChoice]:
    selected = [n for n in natures() if n.sense == sense]
    leaves = _leaf_accounts(session, company_id, [n.account_number for n in selected])
    choices = []
    for nature in selected:
        for account in leaves:
            if account.number.startswith(nature.account_number):
                choices.append(NatureChoice(nature, account))
    return choices


def treasury_accounts(session: Session, company_id: uuid.UUID) -> list[Account]:
    return _leaf_accounts(session, company_id, TREASURY_JOURNALS)


def party_accounts(session: Session, company_id: uuid.UUID, party: Party) -> list[Account]:
    return _leaf_accounts(session, company_id, [PARTY_PREFIXES[party]])


# --- TVA


@dataclass(frozen=True)
class Vat:
    rate_basis_points: int
    verified: bool
    collected_account_number: str | None
    deductible_account_number: str | None


def vat_rate(session: Session, company_id: uuid.UUID, day: date) -> Vat | None:
    rate = session.execute(
        select(TaxRate).where(
            TaxRate.tenant_id == company_id,
            TaxRate.code == VAT_CODE,
            TaxRate.valid_from <= day,
            or_(TaxRate.valid_to.is_(None), TaxRate.valid_to >= day),
        )
    ).scalar_one_or_none()
    if rate is None:
        return None
    return Vat(
        rate.rate_basis_points,
        rate.verified_at is not None,
        rate.collected_account_number,
        rate.deductible_account_number,
    )


def split_vat(total: int, rate_basis_points: int) -> tuple[int, int]:
    """(hors taxe, TVA) d'un montant TTC en unités mineures ; HT arrondi au plus proche."""
    divisor = 10_000 + rate_basis_points
    net = (total * 10_000 * 2 + divisor) // (2 * divisor)
    return net, total - net


# --- Construction de l'écriture


@dataclass(frozen=True)
class GuidedData:
    operation: Operation
    entry_date: date
    amount: int
    label: str | None = None
    reference: str | None = None
    nature_account_id: uuid.UUID | None = None
    treasury_account_id: uuid.UUID | None = None
    target_treasury_account_id: uuid.UUID | None = None
    party_account_id: uuid.UUID | None = None
    vat_included: bool = False


@dataclass(frozen=True)
class BuiltLine:
    account: Account
    debit: int = 0
    credit: int = 0


@dataclass(frozen=True)
class Built:
    journal: Journal
    label: str
    reference: str | None
    lines: list[BuiltLine]
    nature: Nature | None = None
    vat_amount: int = 0
    warnings: list[str] = field(default_factory=list)

    def entry_data(self, entry_date: date) -> EntryData:
        return EntryData(
            journal_id=self.journal.id,
            entry_date=entry_date,
            label=self.label,
            reference=self.reference,
            lines=[LineData(line.account.id, line.debit, line.credit) for line in self.lines],
        )


def _pick(accounts: list[Account], account_id: uuid.UUID | None, what: str) -> Account:
    if account_id is None:
        raise BusinessRuleError(f"Choisissez {what}.")
    for account in accounts:
        if account.id == account_id:
            return account
    raise BusinessRuleError(f"Ce compte ne peut pas être utilisé comme {what}.")


def _journal(session: Session, company_id: uuid.UUID, code: str) -> Journal:
    journal = session.execute(
        select(Journal).where(Journal.tenant_id == company_id, Journal.code == code)
    ).scalar_one_or_none()
    if journal is None or not journal.is_active:
        raise BusinessRuleError(
            f"Le journal {code} est introuvable ou désactivé : réactivez-le dans les "
            "paramètres ou utilisez la saisie classique."
        )
    return journal


def _treasury_journal_code(account: Account) -> str:
    return next(
        code for prefix, code in TREASURY_JOURNALS.items() if account.number.startswith(prefix)
    )


def _vat_account(session: Session, company_id: uuid.UUID, number: str | None) -> Account:
    leaves = _leaf_accounts(session, company_id, [number] if number else [])
    exact = [a for a in leaves if a.number == number]
    if not exact:
        raise BusinessRuleError(
            f"Le compte de TVA {number or '(non paramétré)'} du taux {VAT_CODE} n'est pas "
            "utilisable (absent, désactivé ou avec des sous-comptes) : vérifiez les taxes."
        )
    return exact[0]


def _req(account: Account | None) -> Account:
    """Compte imposé par la spécification de l'opération (toujours résolu plus haut)."""
    if account is None:
        raise RuntimeError("Spécification d'opération incohérente : compte non résolu")
    return account


@dataclass(frozen=True)
class _Accounts:
    nature: Nature | None = None
    nature_account: Account | None = None
    treasury: Account | None = None
    target: Account | None = None
    party: Account | None = None


def _resolve(session: Session, company_id: uuid.UUID, data: GuidedData) -> _Accounts:
    """Comptes choisis, chacun vérifié parmi ceux que l'opération autorise."""
    spec = SPECS[data.operation]
    nature = nature_account = treasury = target = party = None
    if spec.nature is not None:
        choices = nature_choices(session, company_id, spec.nature)
        kind = "nature de la recette" if spec.nature == Sense.PRODUIT else "nature de la dépense"
        nature_account = _pick([c.account for c in choices], data.nature_account_id, kind)
        nature = next(c.nature for c in choices if c.account.id == nature_account.id)
    if spec.treasury:
        accounts = treasury_accounts(session, company_id)
        treasury = _pick(accounts, data.treasury_account_id, "compte de trésorerie")
        if spec.target_treasury:
            target = _pick(accounts, data.target_treasury_account_id, "compte de destination")
            if target.id == treasury.id:
                raise BusinessRuleError(
                    "Les comptes de départ et d'arrivée doivent être différents."
                )
    if spec.party is not None:
        party = _pick(
            party_accounts(session, company_id, spec.party),
            data.party_account_id,
            "compte client" if spec.party == Party.CLIENT else "compte fournisseur",
        )
    return _Accounts(nature, nature_account, treasury, target, party)


@dataclass(frozen=True)
class _VatSplit:
    net: int
    amount: int = 0
    account: Account | None = None
    warning: str | None = None


def _vat(
    session: Session, company_id: uuid.UUID, data: GuidedData, nature: Nature | None
) -> _VatSplit:
    if not data.vat_included:
        return _VatSplit(net=data.amount)
    if nature is None or not nature.vat_possible:
        raise BusinessRuleError("Cette opération ne comporte pas de TVA.")
    vat = vat_rate(session, company_id, data.entry_date)
    if vat is None or vat.rate_basis_points == 0:
        raise BusinessRuleError(
            f"Aucun taux {VAT_CODE} en vigueur au {data.entry_date:%d/%m/%Y} : "
            "paramétrez-le dans les taxes."
        )
    number = (
        vat.collected_account_number
        if nature.sense == Sense.PRODUIT
        else vat.deductible_account_number
    )
    net, amount = split_vat(data.amount, vat.rate_basis_points)
    warning = None
    if not vat.verified:
        warning = (
            f"Le taux de TVA de {vat.rate_basis_points / 100:g} % n'a pas encore été "
            "vérifié auprès de la DGI (paramètres → taxes)."
        )
    return _VatSplit(net, amount, _vat_account(session, company_id, number), warning)


def _lines(operation: Operation, total: int, acc: _Accounts, vat: _VatSplit) -> list[BuiltLine]:
    vat_line = vat.account is not None and vat.amount > 0
    match operation:
        case Operation.VENTE_COMPTANT | Operation.FACTURE_CLIENT:
            debit = acc.treasury if operation == Operation.VENTE_COMPTANT else acc.party
            lines = [
                BuiltLine(_req(debit), debit=total),
                BuiltLine(_req(acc.nature_account), credit=vat.net),
            ]
            if vat_line:
                lines.append(BuiltLine(_req(vat.account), credit=vat.amount))
            return lines
        case Operation.ACHAT_COMPTANT | Operation.FACTURE_FOURNISSEUR:
            credit = acc.treasury if operation == Operation.ACHAT_COMPTANT else acc.party
            lines = [BuiltLine(_req(acc.nature_account), debit=vat.net)]
            if vat_line:
                lines.append(BuiltLine(_req(vat.account), debit=vat.amount))
            lines.append(BuiltLine(_req(credit), credit=total))
            return lines
        case Operation.ENCAISSEMENT_CLIENT:
            return [
                BuiltLine(_req(acc.treasury), debit=total),
                BuiltLine(_req(acc.party), credit=total),
            ]
        case Operation.PAIEMENT_FOURNISSEUR:
            return [
                BuiltLine(_req(acc.party), debit=total),
                BuiltLine(_req(acc.treasury), credit=total),
            ]
        case Operation.VIREMENT_INTERNE:
            return [
                BuiltLine(_req(acc.target), debit=total),
                BuiltLine(_req(acc.treasury), credit=total),
            ]


def build(session: Session, company_id: uuid.UUID, data: GuidedData) -> Built:
    spec = SPECS[data.operation]
    if data.amount <= 0:
        raise BusinessRuleError("Le montant doit être supérieur à zéro.")
    if data.amount > MAX_LINE_AMOUNT:
        raise BusinessRuleError("Montant trop élevé.")
    entries.check_entry_date(session, company_id, data.entry_date)
    accounts = _resolve(session, company_id, data)
    vat = _vat(session, company_id, data, accounts.nature)
    journal = _journal(
        session, company_id, spec.journal or _treasury_journal_code(_req(accounts.treasury))
    )
    nature = accounts.nature
    label = (data.label or "").strip() or (
        f"{spec.label} — {nature.label}" if nature else spec.label
    )
    return Built(
        journal=journal,
        label=label[:200],
        reference=(data.reference or "").strip() or None,
        lines=_lines(data.operation, data.amount, accounts, vat),
        nature=nature,
        vat_amount=vat.amount,
        warnings=[vat.warning] if vat.warning else [],
    )


def create(
    session: Session, actor: Actor, data: GuidedData, *, entry_id: uuid.UUID | None = None
) -> tuple[JournalEntry, bool]:
    """Enregistre l'opération en brouillon (idempotent avec `entry_id`)."""
    built = build(session, actor.company_id, data)
    return entries.create_draft(
        session, actor, built.entry_data(data.entry_date), entry_id=entry_id
    )
