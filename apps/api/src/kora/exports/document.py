"""Document tabulaire neutre, rendu ensuite en Excel (`xlsx.py`) ou en PDF (`pdf.py`).

Les montants restent des entiers en unités mineures jusqu'au rendu : aucun flottant.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from kora.core.errors import BusinessRuleError

ColumnKind = Literal["text", "date", "amount", "number"]
RowStyle = Literal["normal", "subtotal", "total", "heading"]
Cell = str | int | date | None

# Décimales des devises (ISO 4217) acceptées par les exports.
_CURRENCY_DECIMALS = {"GNF": 0, "XOF": 0, "XAF": 0, "EUR": 2, "USD": 2}


def currency_decimals(currency: str) -> int:
    if currency not in _CURRENCY_DECIMALS:
        raise BusinessRuleError(f"Devise {currency} non prise en charge par les exports.")
    return _CURRENCY_DECIMALS[currency]


@dataclass(frozen=True)
class Column:
    label: str
    kind: ColumnKind = "text"
    width: int = 12  # largeur indicative (caractères)


@dataclass(frozen=True)
class Row:
    cells: tuple[Cell, ...]
    style: RowStyle = "normal"


@dataclass
class Section:
    title: str | None
    columns: list[Column]
    rows: list[Row] = field(default_factory=list)

    def add(self, *cells: Cell, style: RowStyle = "normal") -> None:
        if len(cells) != len(self.columns):
            raise ValueError("Nombre de cellules incohérent avec les colonnes.")
        self.rows.append(Row(cells, style))


@dataclass
class Document:
    title: str
    company_name: str
    identifiers: str  # RCCM, NIF
    period: str
    currency: str
    generated_at: datetime
    sections: list[Section] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    landscape: bool = False

    @property
    def decimals(self) -> int:
        return currency_decimals(self.currency)


def format_amount(minor_units: int, decimals: int) -> str:
    """Montant au format français : 1 234 567 (espace fine insécable) ou 1 234,50."""
    sign = "-" if minor_units < 0 else ""
    absolute = abs(minor_units)
    whole, fraction = divmod(absolute, 10**decimals) if decimals else (absolute, 0)
    grouped = f"{whole:,}".replace(",", "\u202f")
    return f"{sign}{grouped},{fraction:0{decimals}d}" if decimals else f"{sign}{grouped}"


def format_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")
