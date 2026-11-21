"""Précontrôle métier à partir d'un référentiel fourni, sans accès à la base."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Literal

from kora.accounting.import_fec import validate_fec
from kora.accounting.import_validation import (
    ImportIssue,
    ImportLine,
    ImportReport,
    validate_normalized_csv,
)
from kora.accounting.import_xlsx import validate_xlsx

MAX_CSV_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class ImportPeriod:
    start: date
    end: date
    is_open: bool
    locked_until: date | None = None


class ImportCatalog:
    """Instantané des journaux, de tous les comptes et des exercices d'un dossier.

    Les dictionnaires associent les codes à leur état actif. Le futur service
    tenant devra charger ces référentiels côté serveur, jamais depuis le client.
    """

    def __init__(
        self,
        *,
        journals: Mapping[str, bool],
        accounts: Mapping[str, bool],
        periods: Sequence[ImportPeriod],
    ) -> None:
        self._journals = dict(journals)
        self._accounts = dict(accounts)
        self._parents = {
            number[:length]
            for number in accounts
            for length in range(1, len(number))
            if number[:length] in accounts
        }
        self._periods = sorted(periods, key=lambda period: period.start)
        self._starts = [period.start for period in self._periods]
        previous: ImportPeriod | None = None
        for period in self._periods:
            if period.start > period.end or (previous and previous.end >= period.start):
                raise ValueError("Exercices incohérents dans le catalogue d'import.")
            previous = period

    def _date_issue(self, day: date) -> str | None:
        position = bisect_right(self._starts, day) - 1
        if position < 0 or self._periods[position].end < day:
            return "missing_fiscal_year"
        period = self._periods[position]
        if not period.is_open:
            return "closed_fiscal_year"
        if period.locked_until is not None and day <= period.locked_until:
            return "locked_period"
        return None

    def check(self, line: ImportLine) -> list[ImportIssue]:
        codes = []
        if line.journal not in self._journals:
            codes.append("unknown_journal")
        elif not self._journals[line.journal]:
            codes.append("inactive_journal")
        if line.account not in self._accounts:
            codes.append("unknown_account")
        elif not self._accounts[line.account]:
            codes.append("inactive_account")
        elif line.account in self._parents:
            codes.append("grouping_account")
        date_issue = self._date_issue(line.day)
        if date_issue is not None:
            codes.append(date_issue)
        return [ImportIssue(line.row, code) for code in codes]


def validate_import(
    content: bytes,
    *,
    file_format: Literal["csv", "fec", "xlsx"],
    catalog: ImportCatalog,
    fec_scale: Literal[0, 2] = 0,
    fec_delimiter: Literal["\t", "|"] = "|",
) -> ImportReport:
    """Précontrôle sans écriture : un rapport valide ne vaut jamais autorisation d'import."""
    issues: list[ImportIssue] = []

    def check(line: ImportLine) -> None:
        issues.extend(catalog.check(line))

    if file_format == "csv":
        if len(content) > MAX_CSV_BYTES:
            return ImportReport(issues=[ImportIssue(1, "file_size_limit")])
        try:
            stream = StringIO(content.decode("utf-8-sig"), newline="")
        except UnicodeError:
            return ImportReport(issues=[ImportIssue(1, "invalid_encoding")])
        report = validate_normalized_csv(stream, on_line=check)
    elif file_format == "fec":
        report = validate_fec(content, scale=fec_scale, delimiter=fec_delimiter, on_line=check)
    elif file_format == "xlsx":
        report = validate_xlsx(content, on_line=check)
    else:
        return ImportReport(issues=[ImportIssue(1, "invalid_format_options")])
    report.issues.extend(issues)
    return report
