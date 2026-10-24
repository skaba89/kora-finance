"""Bilan et compte de résultat SYSCOHADA révisé, calculés depuis les écritures validées.

Deux référentiels versionnés, dans `data/` :
- `etats_syscohada_2017.csv` : les postes (codes AD…BZ, CA…DZ, TA…XI) et les formules
  des totaux ;
- `etats_affectations_2017.csv` : à quel poste va le solde d'un compte, selon le sens
  de ce solde (préfixe le plus long). Ex. : une banque débitrice va en trésorerie-actif
  (BS), créditrice en trésorerie-passif (DR).

Le résultat de la période (classes 6, 7, 8) est ajouté au poste CJ : le bilan
s'équilibre avant comme après la clôture. Tout compte sans affectation est signalé,
jamais ignoré.

À valider par un expert-comptable guinéen : l'ensemble des affectations et la
présentation (voir la colonne `note` du fichier d'affectations).
"""

import csv
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from importlib import resources
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kora.models.accounting import Account
from kora.models.ledger import EntryStatus, JournalEntry, JournalLine
from kora.models.organization import FiscalYear

REFERENCE = "SYSCOHADA_REVISE_2017_ETATS_V1"

Statement = Literal["ACTIF", "PASSIF", "RESULTAT"]
LineKind = Literal["ligne", "total", "produit", "charge"]


@dataclass(frozen=True)
class TemplateLine:
    statement: Statement
    code: str
    label: str
    kind: LineKind
    formula: tuple[tuple[int, str], ...]  # (signe, code) pour un total


@dataclass(frozen=True)
class Target:
    code: str
    depreciation: bool  # colonne « amortissements et dépréciations » de l'actif


@dataclass(frozen=True)
class Mapping:
    prefix: str
    if_debit: Target
    if_credit: Target


def _parse_formula(text: str) -> tuple[tuple[int, str], ...]:
    terms = re.findall(r"([+-]?)([A-Z]{2})", text)
    if not terms or "".join(s + c for s, c in terms) != text.replace(" ", ""):
        raise ValueError(f"Formule invalide : {text!r}")
    return tuple((-1 if sign == "-" else 1, code) for sign, code in terms)


def _target(text: str) -> Target:
    code, _, column = text.partition("#")
    if column not in ("", "amort"):
        raise ValueError(f"Cible invalide : {text!r}")
    return Target(code, column == "amort")


def _rows(name: str) -> list[dict[str, str]]:
    data = resources.files("kora.accounting.data").joinpath(name)
    with data.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


@lru_cache
def template() -> tuple[TemplateLine, ...]:
    lines = tuple(
        TemplateLine(
            statement=row["etat"],  # type: ignore[arg-type]
            code=row["code"],
            label=row["libelle"],
            kind=row["type"],  # type: ignore[arg-type]
            formula=_parse_formula(row["formule"]) if row["type"] == "total" else (),
        )
        for row in _rows("etats_syscohada_2017.csv")
    )
    if len({line.code for line in lines}) != len(lines):
        raise ValueError("Code de poste en double dans le référentiel des états.")
    # Les totaux sont calculés dans l'ordre du fichier : chacun ne référence que des
    # postes du même état définis plus haut.
    seen: dict[str, Statement] = {}
    for line in lines:
        for _, code in line.formula:
            if seen.get(code) != line.statement:
                raise ValueError(f"Le total {line.code} référence {code}, inconnu ou défini après.")
        seen[line.code] = line.statement
    return lines


@lru_cache
def mappings() -> tuple[Mapping, ...]:
    codes = {line.code: line for line in template()}
    result = []
    for row in _rows("etats_affectations_2017.csv"):
        mapping = Mapping(row["prefixe"], _target(row["si_debiteur"]), _target(row["si_crediteur"]))
        for target in (mapping.if_debit, mapping.if_credit):
            line = codes.get(target.code)
            if line is None or line.kind == "total":
                raise ValueError(
                    f"Affectation {mapping.prefix} vers un poste invalide : {target.code}"
                )
            if target.depreciation and line.statement != "ACTIF":
                raise ValueError(f"Dépréciation hors de l'actif : {mapping.prefix}")
        result.append(mapping)
    # Le préfixe le plus long l'emporte.
    return tuple(sorted(result, key=lambda m: len(m.prefix), reverse=True))


def mapping_for(number: str) -> Mapping | None:
    return next((m for m in mappings() if number.startswith(m.prefix)), None)


# --- Calcul


@dataclass
class Amounts:
    gross: int = 0
    depreciation: int = 0

    @property
    def net(self) -> int:
        return self.gross - self.depreciation


@dataclass
class Statements:
    fiscal_year: FiscalYear
    date_to: date
    values: dict[str, Amounts] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)

    def amount(self, code: str) -> int:
        return self.values[code].net

    @property
    def net_result(self) -> int:
        return self.amount("XI")

    @property
    def balanced(self) -> bool:
        return self.amount("BZ") == self.amount("DZ") and not self.unmapped


def _balances(
    session: Session, company_id: uuid.UUID, year: FiscalYear, date_to: date
) -> list[tuple[str, int]]:
    rows = session.execute(
        select(Account.number, func.sum(JournalLine.debit - JournalLine.credit))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.tenant_id == company_id,
            JournalEntry.fiscal_year_id == year.id,
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date <= date_to,
        )
        .group_by(Account.number)
    ).all()
    return [(number, int(net)) for number, net in rows if int(net) != 0]


def compute(
    session: Session, company_id: uuid.UUID, year: FiscalYear, date_to: date | None = None
) -> Statements:
    end = date_to or year.end_date
    lines = template()
    by_code = {line.code: line for line in lines}
    result = Statements(year, end, {line.code: Amounts() for line in lines})

    for number, net in _balances(session, company_id, year, end):  # net : débit - crédit
        mapping = mapping_for(number)
        if mapping is None:
            result.unmapped.append(number)
            continue
        target = mapping.if_debit if net > 0 else mapping.if_credit
        amounts = result.values[target.code]
        statement = by_code[target.code].statement
        if target.depreciation:
            amounts.depreciation += -net
        elif statement == "ACTIF" or by_code[target.code].kind == "charge":
            amounts.gross += net
        else:  # passif et produits : montant créditeur positif
            amounts.gross += -net

    # Totaux du compte de résultat, puis report du résultat au bilan (CJ).
    def total(code: str) -> Amounts:
        computed = Amounts()
        for sign, part in by_code[code].formula:
            computed.gross += sign * result.values[part].gross
            computed.depreciation += sign * result.values[part].depreciation
        return computed

    for line in lines:
        if line.statement == "RESULTAT" and line.kind == "total":
            result.values[line.code] = total(line.code)
    result.values["CJ"].gross += result.values["XI"].net
    for line in lines:
        if line.statement != "RESULTAT" and line.kind == "total":
            result.values[line.code] = total(line.code)
    return result


def previous_year(session: Session, company_id: uuid.UUID, year: FiscalYear) -> FiscalYear | None:
    return session.execute(
        select(FiscalYear)
        .where(FiscalYear.tenant_id == company_id, FiscalYear.end_date < year.start_date)
        .order_by(FiscalYear.end_date.desc())
        .limit(1)
    ).scalar_one_or_none()
