"""Lecture des relevés bancaires : formats OFX et CSV.

Le parseur est écrit sur mesure, sans dépendance nouvelle : les banques de la
sous-région exportent des OFX 1.x (SGML aux balises souvent non fermées), parfois
des OFX 2.x (XML), et des CSV aux colonnes variées (dates JJ/MM/AAAA, montants
« 1 234 567 » avec espaces insécables et virgule décimale, débit et crédit en deux
colonnes). Un parseur tiers ne suivrait pas ces variations.

Le montant d'une ligne est **signé, du point de vue du titulaire du compte** :
positif = entrée de fonds (la banque crédite), négatif = sortie. C'est la convention
OFX (TRNAMT) ; les CSV à colonnes débit/crédit séparées sont combinées dans ce sens.

Chaque montant est arrondi à l'unité (le GNF n'a pas de sous-unité) : un export qui
ferait apparaître des décimales n'est jamais tronqué — il est arrondi au plus près,
et le détail brut reste disponible dans le fichier original conservé au stockage.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from kora.core.errors import BusinessRuleError

# Longueurs maximales d'une ligne de relevé (alignées sur la migration 0012).
LABEL_MAX = 200
REFERENCE_MAX = 60

_LABEL_CLEAN = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedLine:
    """Une opération lue dans un relevé : date, montant signé, libellé, référence."""

    value_date: date
    # Signé, du point de vue du titulaire : positif = entrée, négatif = sortie.
    amount: int
    label: str
    reference: str | None = None
    # Solde après opération si le relevé le porte (colonne « solde » des CSV, absent
    # de la plupart des OFX).
    balance_after: int | None = None


@dataclass(frozen=True)
class ParsedStatement:
    """Résultat de la lecture d'un relevé : format reconnu et lignes en ordre du fichier."""

    format: str
    lines: list[ParsedLine]


def detect_format(content: bytes) -> str | None:
    """Format du relevé d'après le contenu (jamais l'extension fournie par le client).

    Reconnu : OFX (en-tête OFXHEADER ou document XML) et CSV (texte à délimiteur).
    Renvoie None pour tout le reste (PDF, image, binaire) : le service précise alors
    les formats acceptés.
    """
    head = content[:2048].lstrip()
    if re.match(rb"(OFXHEADER\s*:|<\?xml|OFX)", head, re.IGNORECASE):
        return "OFX"
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    first_line = text.splitlines()[:1]
    if not first_line or not first_line[0].strip():
        return None
    if any(sep in first_line[0] for sep in (";", ",", "\t", "|")):
        return "CSV"
    return None


def parse_statement(content: bytes) -> ParsedStatement:
    """Lit un relevé OFX ou CSV. Lève BusinessRuleError si rien n'est exploitable."""
    fmt = detect_format(content)
    if fmt == "OFX":
        lines = parse_ofx(content)
        if lines:
            return ParsedStatement("OFX", lines)
        raise BusinessRuleError(
            "Aucune opération lue dans ce fichier OFX (balises STMTTRN introuvables)."
        )
    if fmt == "CSV":
        lines = parse_csv(content)
        if lines:
            return ParsedStatement("CSV", lines)
        raise BusinessRuleError(
            "Aucune opération lue dans ce fichier CSV : colonnes date et montant "
            "introuvables ou vides."
        )
    raise BusinessRuleError("Format non reconnu : exportez le relevé au format OFX ou CSV.")


# --- OFX

_OFX_TAG = re.compile(r"<([A-Za-z0-9.]+)>([^<]*)")


def _ofx_blocks(content: str) -> list[dict[str, str]]:
    """Découpe les blocs STMTTRN. Les balises OFX 1.x (SGML) sont souvent non fermées :
    on lit chaque balise comme « nom + texte jusqu'à la suivante », ce qui traite
    correctement les deux variantes (fermées et non fermées)."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for match in _OFX_TAG.finditer(content):
        tag = match.group(1).upper()
        value = match.group(2).strip()
        if tag == "STMTTRN":
            current = {}
            blocks.append(current)
        elif tag == "/STMTTRN":
            current = None
        elif current is not None and value:
            current.setdefault(tag, value)
    return [b for b in blocks if b]


def _ofx_date(raw: str) -> date | None:
    """DTPOSTED : AAAAMMJJ[HHMMSS][.xxx][:TZ] — seule la date est retenue."""
    digits = re.match(r"(\d{8})", raw.strip())
    if digits is None:
        return None
    value = digits.group(1)
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _ofx_amount(raw: str) -> int | None:
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        return None
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_ofx(content: bytes) -> list[ParsedLine]:
    """Opérations d'un OFX 1.x (SGML) ou 2.x (XML), dans l'ordre du fichier.

    Une opération sans date exploitable ou de montant nul est ignorée : une ligne de
    relevé n'est jamais inventée à partir d'une donnée incomplète.
    """
    # OFX 1.x n'est pas du XML bien formé : une lecture par balises vaut pour les deux.
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    lines: list[ParsedLine] = []
    for block in _ofx_blocks(text):
        value_date = _ofx_date(block.get("DTPOSTED", ""))
        amount = _ofx_amount(block.get("TRNAMT", ""))
        if value_date is None or amount is None or amount == 0:
            continue
        # PAYEE est un conteneur : son propre texte est vide, le nom est dans NAME.
        label = _clean_label(
            block.get("NAME") or block.get("MEMO") or block.get("TRNTYPE", "") or ""
        )
        # Le mémo bancaire complète le nom quand il apporte un détail distinct.
        memo = _clean_label(block.get("MEMO") or "")
        if block.get("NAME") and memo and memo != label:
            label = f"{label} {memo}"[:LABEL_MAX]
        if not label:
            label = "opération de relevé"
        lines.append(
            ParsedLine(
                value_date=value_date,
                amount=amount,
                label=label[:LABEL_MAX],
                reference=_clean_reference(block.get("FITID") or block.get("CHECKNUM")),
            )
        )
    return lines


# --- CSV

# Mots-clés d'en-tête par rôle, par priorité de reconnaissance : une colonne « Date
# d'opération » ne doit pas être prise pour un libellé (« opération »).
_ROLE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("date", ("date", "valeur")),
    ("balance", ("solde",)),
    ("debit", ("débit", "debit")),
    ("credit", ("crédit", "credit")),
    ("amount", ("montant", "amount")),
    ("label", ("libellé", "libelle", "label", "description", "opération", "operation", "memo")),
    ("reference", ("référence", "reference", "réf", "ref", "pièce", "piece", "numéro", "numero")),
]

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y")

# Espace insécable, espace insécable étroit et espace simple : séparateurs de milliers
# des exports bancaires francophones.
_THOUSANDS = re.compile(r"[\u00a0\u202f ]")
_TRAILING_MINUS = re.compile(r"^([0-9.,\u00a0\u202f ]+)-$")


def _parse_number(raw: str) -> int | None:
    """Montant d'un CSV : « 1 234 567 », « 1.234.567,89 », « -12 500 », « (12 500) »,
    « 12 500- ». Renvoie None si rien d'exploitable (colonne non numérique)."""
    text = raw.strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    match = _TRAILING_MINUS.match(text)
    if match:
        negative, text = True, match.group(1)
    if text.startswith("-"):
        negative, text = True, text[1:]
    elif text.startswith("+"):
        text = text[1:]
    text = _THOUSANDS.sub("", text).replace("-", "")
    # Décimale : la dernière virgule ou le dernier point sépare les unités.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if len(tail) in (1, 2) and (head.replace(".", "").isdigit()):
            text = f"{head.replace('.', '')}.{tail}"
        else:
            text = text.replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    result = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -result if negative else result


def _parse_date(raw: str) -> date | None:
    """Date d'un CSV : JJ/MM/AAAA (exports francophones), AAAA-MM-JJ, JJ-MM-AAAA,
    JJ/MM/AA, JJ.MM.AAAA."""
    text = raw.strip().strip('"')
    for pattern, fmt in (
        (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), "dmy"),
        (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"), "dmy"),
        (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), "ymd"),
        (re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$"), "dmy"),
        (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$"), "dm2y"),
    ):
        match = pattern.match(text)
        if match is None:
            continue
        try:
            if fmt == "ymd":
                return date(int(match[1]), int(match[2]), int(match[3]))
            year = int(match[3])
            if fmt == "dm2y":
                year += 2000
            return date(year, int(match[2]), int(match[1]))
        except ValueError:
            continue
    return None


def _clean_label(raw: str) -> str:
    """Libellé affichable : caractères de contrôle supprimés, espaces réduits."""
    label = "".join(ch for ch in raw if unicodedata.category(ch)[0] != "C")
    return _LABEL_CLEAN.sub(" ", label).strip()


def _clean_reference(raw: str | None) -> str | None:
    if not raw:
        return None
    reference = _clean_label(raw)[:REFERENCE_MAX]
    return reference or None


def _decode_csv(content: bytes) -> str:
    """Les exports bancaires sont en UTF-8 (parfois avec BOM) ou en cp1252/latin-1."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        return dialect.delimiter
    except csv.Error:
        # Exports francophones : point-virgule plus probable que virgule.
        for candidate in (";", ",", "\t", "|"):
            if candidate in sample:
                return candidate
        return ";"


def _resolve_role(cell: str) -> str | None:
    lowered = cell.strip().lower()
    for role, hints in _ROLE_HINTS:
        if any(hint in lowered for hint in hints):
            return role
    return None


def _header_columns(header: list[str]) -> dict[str, int]:
    """Positions des colonnes reconnues dans la ligne d'en-tête (une colonne par rôle)."""
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        role = _resolve_role(cell)
        if role is not None and role not in columns:
            columns[role] = index
    return columns


def _infer_columns(data_rows: list[list[str]]) -> dict[str, int] | None:
    """Sans en-tête : la colonne date est celle qui lit le plus de dates, la colonne
    montant celle qui lit le plus de nombres ; le libellé est la colonne texte
    restante la plus longue."""
    width = max(len(row) for row in data_rows)
    date_scores = [0] * width
    number_scores = [0] * width
    text_lengths = [0] * width
    for row in data_rows[:200]:
        for index, cell in enumerate(row):
            if _parse_date(cell) is not None:
                date_scores[index] += 1
            elif _parse_number(cell) is not None:
                number_scores[index] += 1
            else:
                text_lengths[index] += len(cell.strip())
    date_index = max(range(width), key=lambda i: date_scores[i])
    if date_scores[date_index] == 0:
        return None
    amount_index = max(
        (i for i in range(width) if i != date_index),
        key=lambda i: number_scores[i],
        default=None,
    )
    if amount_index is None or number_scores[amount_index] == 0:
        return None
    label_index = max(
        (i for i in range(width) if i not in (date_index, amount_index)),
        key=lambda i: text_lengths[i],
        default=None,
    )
    columns = {"date": date_index, "amount": amount_index}
    if label_index is not None and text_lengths[label_index] > 0:
        columns["label"] = label_index
    return columns


def _row_amount(row: list[str], columns: dict[str, int]) -> int | None:
    """Montant signé de la ligne : colonne « montant » unique, ou débit/crédit séparés
    (le débit est une sortie, le crédit une entrée), ou une seule des deux colonnes."""

    def at(index: int) -> int | None:
        return _parse_number(row[index]) if index < len(row) else None

    if "debit" in columns and "credit" in columns:
        debit, credit = at(columns["debit"]), at(columns["credit"])
        if debit is None and credit is None:
            return None
        # Débit bancaire = sortie du compte (négatif), crédit = entrée (positif).
        return (credit or 0) - (debit or 0)
    if "debit" in columns:
        debit = at(columns["debit"])
        return None if debit is None else -debit
    if "credit" in columns:
        return at(columns["credit"])
    if "amount" in columns:
        return at(columns["amount"])
    return None


def parse_csv(content: bytes) -> list[ParsedLine]:
    """Opérations d'un CSV d'export bancaire. Colonnes détectées par en-tête si
    possible, sinon par la nature des données (dates lisibles, montants numériques)."""
    text = _decode_csv(content)
    delimiter = _sniff_delimiter(text[:4096])
    rows = [
        row
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if len(rows) < 2:
        return []
    header_columns = _header_columns(rows[0])
    complete_header = {"date", "amount"} <= header_columns.keys() or {
        "date",
        "debit",
        "credit",
    } <= header_columns.keys()
    columns: dict[str, int] | None
    if complete_header:
        columns = header_columns
        data_rows = rows[1:]
    else:
        columns = _infer_columns(rows)
        data_rows = rows
    if columns is None or "date" not in columns:
        return []

    lines: list[ParsedLine] = []
    for row in data_rows:
        if len(row) <= max(columns.values()):
            continue
        value_date = _parse_date(row[columns["date"]])
        if value_date is None:
            continue
        amount = _row_amount(row, columns)
        if amount is None or amount == 0:
            continue
        label = _clean_label(row[columns["label"]]) if "label" in columns else ""
        if not label:
            label = "opération de relevé"
        reference = (
            _clean_reference(row[columns["reference"]])
            if "reference" in columns and columns["reference"] < len(row)
            else None
        )
        balance_after = (
            _parse_number(row[columns["balance"]])
            if "balance" in columns and columns["balance"] < len(row)
            else None
        )
        lines.append(
            ParsedLine(
                value_date=value_date,
                amount=amount,
                label=label[:LABEL_MAX],
                reference=reference,
                balance_after=balance_after,
            )
        )
    return lines


# Empreinte métier d'une ligne : utilisée par le service pour signaler les doublons
# entre relevés successifs d'un même compte (même date, montant, libellé, référence).
def line_content_hash(line: ParsedLine) -> str:
    components = (
        f"{line.value_date.isoformat()}|{line.amount}|{line.label.lower()}|{line.reference or ''}"
    )
    return hashlib.sha256(components.encode()).hexdigest()
