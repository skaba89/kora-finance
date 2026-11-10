"""Tableau des flux de trésorerie (TFT), méthode directe, calculé depuis les écritures validées.

Arbitrage de l'expert-comptable : `docs/ARBITRAGE_COMPTABLE.md` (KF-15). En résumé :

- la trésorerie est l'ensemble des comptes de classe 5, comme au bilan (BQ/BS côté
  actif, DQ/DR côté passif) ; les virements internes ne génèrent aucun flux ;
- le flux d'une écriture validée est le mouvement net de ses lignes de classe 5,
  réparti entre les lignes du TFT d'après la contrepartie (ligne à ligne : une
  écriture « remboursement + intérêts » est ventilée automatiquement) ;
- deux référentiels versionnés dans `data/` :
  - `tft_syscohada_2017.csv` : les lignes (codes OA…FE), les sections et les totaux ;
  - `tft_affectations_2017.csv` : à quelle ligne va la contrepartie d'un compte, selon
    le sens de cette ligne (préfixe le plus long) ;
- la trésorerie d'ouverture vient des écritures d'origine `CLOSING` (à-nouveaux et
  contre-passations) datées du premier jour de l'exercice — même convention que le
  bilan, qui ne voit que l'exercice en cours ;
- contrôle indépendant : trésorerie de clôture = solde réel de la classe 5 à la date
  de coupure. Toute divergence (`coherent = false`) ou contrepartie sans affectation
  (`unmapped_accounts`) est signalée, jamais ignorée.

À valider par un expert-comptable guinéen : le classement des charges financières
payées (retenues en flux opérationnels) et la ventilation encaissements/remboursements
des emprunts (voir le mémoire d'arbitrage §1.5).
"""

import csv
import uuid
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from importlib import resources
from itertools import groupby
from operator import itemgetter

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.accounting import statements
from kora.models.accounting import Account
from kora.models.ledger import EntryOrigin, EntryStatus, JournalEntry, JournalLine
from kora.models.organization import FiscalYear

REFERENCE = "SYSCOHADA_REVISE_2017_TFT_V1"

# La trésorerie au sens du TFT : tous les comptes de classe 5 (cf. §1.2 du mémoire).
TREASURY_ROOT = "5"

LineKind = ["section", "ouverture", "ligne", "total"]


@dataclass(frozen=True)
class TftLine:
    code: str
    label: str
    kind: str
    formula: tuple[tuple[int, str], ...]  # (signe, code) pour un total


def _rows(name: str) -> list[dict[str, str]]:
    data = resources.files("kora.accounting.data").joinpath(name)
    with data.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


@lru_cache
def template() -> tuple[TftLine, ...]:
    lines = tuple(
        TftLine(
            code=row["code"],
            label=row["libelle"],
            kind=row["type"],
            formula=statements._parse_formula(row["formule"]) if row["type"] == "total" else (),
        )
        for row in _rows("tft_syscohada_2017.csv")
    )
    if len({line.code for line in lines}) != len(lines):
        raise ValueError("Code de ligne en double dans le référentiel du TFT.")
    by_kind = {line.code: line.kind for line in lines}
    seen: set[str] = set()
    for line in lines:
        if line.kind not in LineKind:
            raise ValueError(f"Type de ligne inconnu dans le référentiel du TFT : {line.kind}")
        for _, code in line.formula:
            # Un total référence des lignes, l'ouverture ou des totaux déjà définis —
            # jamais une section (simple en-tête d'affichage).
            if code not in seen or by_kind[code] == "section":
                raise ValueError(f"Le total {line.code} référence {code}, inconnu ou défini après.")
        seen.add(line.code)
    return lines


@lru_cache
def mappings() -> tuple[statements.Mapping, ...]:
    codes = {line.code: line for line in template()}
    result = []
    for row in _rows("tft_affectations_2017.csv"):
        mapping = statements.Mapping(
            row["prefixe"],
            statements._target(row["si_debiteur"]),
            statements._target(row["si_crediteur"]),
        )
        for target in (mapping.if_debit, mapping.if_credit):
            line = codes.get(target.code)
            if line is None or line.kind != "ligne":
                raise ValueError(
                    f"Affectation {mapping.prefix} vers une ligne TFT invalide : {target.code}"
                )
        result.append(mapping)
    # Le préfixe le plus long l'emporte.
    return tuple(sorted(result, key=lambda m: len(m.prefix), reverse=True))


def mapping_for(number: str) -> statements.Mapping | None:
    return next((m for m in mappings() if number.startswith(m.prefix)), None)


@dataclass
class CashFlows:
    fiscal_year: FiscalYear
    date_to: date
    values: dict[str, int] = field(default_factory=dict)
    opening: int = 0
    treasury_at_end: int = 0
    unmapped: list[str] = field(default_factory=list)

    def amount(self, code: str) -> int:
        return self.values[code]

    @property
    def variation(self) -> int:
        return self.values["XV"]

    @property
    def closing(self) -> int:
        return self.values["TC"]

    @property
    def coherent(self) -> bool:
        """Ouverture + variation = solde réel de la trésorerie, et rien d'ignoré."""
        return self.closing == self.treasury_at_end and not self.unmapped


def _entry_lines(
    session: Session, company_id: uuid.UUID, year: FiscalYear, date_to: date
) -> list[tuple[uuid.UUID, str, date, str, int]]:
    """(id, origine, date, numéro de compte, débit moins crédit) des écritures validées."""
    rows = session.execute(
        select(
            JournalEntry.id,
            JournalEntry.origin,
            JournalEntry.entry_date,
            Account.number,
            (JournalLine.debit - JournalLine.credit).label("net"),
        )
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalEntry.fiscal_year_id == year.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date <= date_to,
        )
        .order_by(JournalEntry.id)
    ).all()
    return [
        (entry_id, origin, entry_date, number, int(net))
        for entry_id, origin, entry_date, number, net in rows
    ]


def compute(
    session: Session, company_id: uuid.UUID, year: FiscalYear, date_to: date | None = None
) -> CashFlows:
    end = date_to or year.end_date
    lines = template()
    result = CashFlows(year, end, {line.code: 0 for line in lines})

    def treasury(number: str) -> bool:
        return number.startswith(TREASURY_ROOT)

    rows = _entry_lines(session, company_id, year, end)
    for _, group in groupby(rows, key=itemgetter(0)):
        entry = list(group)
        origin = entry[0][1]
        entry_date = entry[0][2]
        movement = sum(net for _, _, _, number, net in entry if treasury(number))
        result.treasury_at_end += movement
        if origin == EntryOrigin.CLOSING and entry_date <= year.start_date:
            result.opening += movement
        if origin != EntryOrigin.MANUAL or movement == 0:
            continue
        for _, _, _, number, net in entry:
            if treasury(number) or net == 0:
                continue
            mapping = mapping_for(number)
            if mapping is None:
                if number not in result.unmapped:
                    result.unmapped.append(number)
                continue
            target = mapping.if_debit if net > 0 else mapping.if_credit
            result.values[target.code] += -net

    # Totaux, dans l'ordre du référentiel (chaque total ne référence que plus haut) ;
    # la trésorerie d'ouverture est injectée avant le calcul de la clôture.
    for line in lines:
        if line.kind == "ouverture":
            result.values[line.code] = result.opening
        elif line.kind == "total":
            result.values[line.code] = sum(
                sign * result.values[code] for sign, code in line.formula
            )
    return result


def previous_year(session: Session, company_id: uuid.UUID, year: FiscalYear) -> FiscalYear | None:
    return statements.previous_year(session, company_id, year)
