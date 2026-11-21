"""Précontrôle d'un profil FEC textuel, sans import ni certification réglementaire."""

import csv
import re
from collections.abc import Callable
from io import StringIO
from typing import Literal

from kora.accounting.import_validation import ImportIssue, ImportLine, ImportReport, validate_rows

MAX_FEC_BYTES = 32 * 1024 * 1024
FEC_COLUMNS = (
    "JournalCode",
    "JournalLib",
    "EcritureNum",
    "EcritureDate",
    "CompteNum",
    "CompteLib",
    "CompAuxNum",
    "CompAuxLib",
    "PieceRef",
    "PieceDate",
    "EcritureLib",
    "Debit",
    "Credit",
    "EcritureLet",
    "DateLet",
    "ValidDate",
    "Montantdevise",
    "Idevise",
)


def _minor_units(raw: str, scale: Literal[0, 2]) -> str:
    match = re.fullmatch(r"([0-9]{1,14})(?:[,.]([0-9]{1,2}))?", raw)
    if match is None:
        return ""
    integer, fraction = match.groups()
    fraction = fraction or ""
    if scale == 0:
        return "" if fraction.strip("0") else integer
    return str(int(integer) * 100 + int(fraction.ljust(2, "0")))


def _normalize(row: list[str], scale: Literal[0, 2]) -> list[str]:
    day = row[3]
    day = f"{day[:4]}-{day[4:6]}-{day[6:]}" if re.fullmatch(r"[0-9]{8}", day) else ""
    return [
        row[0],
        row[2],
        day,
        row[4],
        row[10],
        _minor_units(row[11], scale),
        _minor_units(row[12], scale),
    ]


def validate_fec(
    content: bytes,
    *,
    scale: Literal[0, 2],
    delimiter: Literal["\t", "|"],
    on_line: Callable[[ImportLine], None] | None = None,
) -> ImportReport:
    """Profil strict UTF-8 (BOM accepté), 18 colonnes, séparateur explicite.

    Seules les sept colonnes du précontrôle sont interprétées. Les métadonnées
    FEC ne sont ni importées ni déclarées valides. La devise est choisie par
    l'appelant (GNF : scale=0), jamais déduite du fichier. Aucun arrondi.
    """
    if len(content) > MAX_FEC_BYTES:
        return ImportReport(issues=[ImportIssue(1, "file_size_limit")])
    if scale not in (0, 2) or delimiter not in ("\t", "|"):
        return ImportReport(issues=[ImportIssue(1, "invalid_format_options")])
    try:
        stream = StringIO(content.decode("utf-8-sig"), newline="")
    except UnicodeError:
        return ImportReport(issues=[ImportIssue(1, "invalid_encoding")])
    reader = csv.reader(stream, delimiter=delimiter, quoting=csv.QUOTE_NONE, strict=True)
    return validate_rows(reader, FEC_COLUMNS, lambda row: _normalize(row, scale), on_line=on_line)
