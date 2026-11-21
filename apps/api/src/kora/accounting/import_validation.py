"""Précontrôle structurel d'un CSV normalisé, sans écriture ni accès au tenant."""

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from typing import TextIO

from kora.accounting.limits import MAX_LINE_AMOUNT, MAX_LINES_PER_ENTRY

MAX_IMPORT_ROWS = 100_000
COLUMNS = ("journal", "ecriture", "date", "compte", "libelle", "debit", "credit")


@dataclass(frozen=True)
class ImportIssue:
    row: int
    code: str


@dataclass
class ImportReport:
    rows: int = 0
    entries: int = 0
    debit: int = 0
    credit: int = 0
    issues: list[ImportIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues and self.rows > 0


@dataclass
class _Group:
    first_row: int
    day: date
    label: str
    count: int = 0
    debit: int = 0
    credit: int = 0


def _amount(raw: str) -> int | None:
    # Unités mineures uniquement : pas de float, exposant, arrondi ni séparateur ambigu.
    if not re.fullmatch(r"[0-9]{1,14}", raw):
        return None
    value = int(raw)
    return value if value <= MAX_LINE_AMOUNT else None


def _day(raw: str) -> date | None:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _text(raw: str, limit: int) -> bool:
    return bool(raw.strip()) and len(raw) <= limit and all(char.isprintable() for char in raw)


def _validate_row(
    row: list[str], number: int, report: ImportReport, groups: dict[tuple[str, str], _Group]
) -> None:
    if len(row) != len(COLUMNS):
        report.issues.append(ImportIssue(number, "column_count"))
        return
    journal, entry, raw_day, account, label, raw_debit, raw_credit = row
    day = _day(raw_day)
    debit, credit = _amount(raw_debit), _amount(raw_credit)
    if not all((_text(journal, 8), _text(entry, 60), _text(account, 12), _text(label, 200))):
        report.issues.append(ImportIssue(number, "invalid_text"))
        return
    if day is None:
        report.issues.append(ImportIssue(number, "invalid_date"))
        return
    if debit is None or credit is None or (debit == 0) == (credit == 0):
        report.issues.append(ImportIssue(number, "invalid_amount"))
        return
    group = groups.setdefault((journal, entry), _Group(number, day, label))
    if (group.day, group.label) != (day, label):
        report.issues.append(ImportIssue(number, "inconsistent_entry"))
    group.count += 1
    group.debit += debit
    group.credit += credit
    report.debit += debit
    report.credit += credit


def validate_normalized_csv(stream: TextIO) -> ImportReport:
    """CSV UTF-8 décodé, séparateur ';', dates ISO et unités mineures entières.

    Le rapport ne contient aucun contenu source. Les écritures non contiguës sont
    regroupées par (journal, identifiant source). Les totaux couvrent uniquement
    les lignes structurellement valides. Rien ne garantit encore l'imputabilité
    des comptes ou l'ouverture des exercices : contrôle métier ultérieur obligatoire.
    """
    report = ImportReport()
    groups: dict[tuple[str, str], _Group] = {}
    reader = csv.reader(stream, delimiter=";", strict=True)
    try:
        if next(reader, None) != list(COLUMNS):
            report.issues.append(ImportIssue(1, "invalid_header"))
            return report
        for row in reader:
            if report.rows == MAX_IMPORT_ROWS:
                report.issues.append(ImportIssue(reader.line_num, "row_limit"))
                break
            report.rows += 1
            _validate_row(row, reader.line_num, report, groups)
    except (csv.Error, UnicodeError):
        report.issues.append(ImportIssue(reader.line_num, "invalid_csv"))
    report.entries = len(groups)
    if not report.rows:
        report.issues.append(ImportIssue(1, "empty_import"))
    for group in groups.values():
        if group.count > MAX_LINES_PER_ENTRY:
            report.issues.append(ImportIssue(group.first_row, "entry_line_limit"))
        if group.debit != group.credit or group.count < 2:
            report.issues.append(ImportIssue(group.first_row, "unbalanced_entry"))
    return report
