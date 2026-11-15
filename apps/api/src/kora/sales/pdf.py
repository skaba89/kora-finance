"""PDF conforme des documents de vente : factures, devis et avoirs (Phase 4B-bis).

Le PDF d'un document numéroté consomme exclusivement les données figées à la
numérotation : instantanés JSONB de l'émetteur et du tier, numéro définitif,
dates, lignes et montants recalculés à l'émission. Les fiches vivantes (tier,
dossier) ne sont jamais relues : le document émis reste fidèle même si les
fiches changent ensuite — c'est la garantie de conformité dans le temps.

Conformité (ARBITRAGE_COMPTABLE.md, KF-16) : raison sociale, NIU/NCC ou NIF,
adresse, montants HT / TVA / TTC, référence de l'exercice. La règle dure est
posée à l'émission (`kora.sales.service`) : une facture ou un avoir refuse de
naître sans les mentions fiscales — le PDF ne peut donc pas produire un document
fiscal incomplet. Un brouillon, jamais numéroté, n'a pas de PDF.

Documents en français, comme les exports comptables ; l'affichage convertit les
quantités (millièmes) et les taux (points de base) sans jamais utiliser de
flottants — mêmes conventions d'arrondi que le reste du dépôt.
"""

import io
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from kora.core.errors import BusinessRuleError
from kora.exports.document import currency_decimals, format_amount, format_date
from kora.exports.pdf import FONT, FONT_BOLD, _escape, _NumberedCanvas, _register_fonts
from kora.models.organization import FiscalYear
from kora.models.sales import QUANTITY_SCALE, SalesDocument, SalesDocumentLine

# Préfixe d'affichage du numéro : l'identifiant stocké reste un entier (sans trou),
# seul le rendu lui donne sa forme commerciale « FAC-2026-00042 ».
PREFIXES = {"quote": "DEV", "invoice": "FAC", "credit_note": "AV"}
# Préfixe des fichiers téléchargés (facture-FAC-2026-00042-acme.pdf).
FILE_PREFIXES = {"quote": "devis", "invoice": "facture", "credit_note": "avoir"}
# Titre du document dans le PDF.
KIND_TITLES = {"quote": "DEVIS", "invoice": "FACTURE", "credit_note": "AVOIR"}

# Timbre apposé sur un document hors usage : le numéro est conservé (jamais
# réutilisé) pour la continuité de la chronologie, le document n'a plus de valeur.
STAMPS = {
    ("invoice", "CANCELLED"): (
        "FACTURE ANNULÉE — document sans valeur commerciale ; le numéro est conservé "
        "et ne sera jamais réutilisé (chronologie sans trou)."
    ),
    ("quote", "REJECTED"): "DEVIS REFUSÉ — sans suite.",
}


def format_document_number(doc_kind: str, fiscal_year_start: date, number: int) -> str:
    """Numéro d'affichage « FAC-2026-00042 » : préfixe, année de l'exercice, cinq
    chiffres. L'exercice fait partie du numéro parce que la séquence est annuelle."""
    try:
        prefix = PREFIXES[doc_kind]
    except KeyError as exc:
        raise BusinessRuleError(f"Type de document inconnu : {doc_kind!r}.") from exc
    return f"{prefix}-{fiscal_year_start:%Y}-{number:05d}"


def format_quantity(milli: int) -> str:
    """Quantité en millièmes → affichage sans flottant (2500 → « 2,5 », 1000 → « 1 »)."""
    entier, reste = divmod(milli, QUANTITY_SCALE)
    grouped = f"{entier:,}".replace(",", "\u202f")
    if reste == 0:
        return grouped
    return f"{grouped},{reste:03d}".rstrip("0")


def format_bp(bp: int) -> str:
    """Points de base → pourcentage sans flottant (1800 → « 18 % », 1650 → « 16,5 % »)."""
    entier, reste = divmod(bp, 100)
    if reste == 0:
        return f"{entier} %"
    decimales = f"{reste:02d}".rstrip("0")
    return f"{entier},{decimales} %"


def slug(texte: str) -> str:
    """« Société Élégance » → « societe-elegance » (même convention que les exports)."""
    ascii_text = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower() or "dossier"


def filename_document(document: SalesDocument, fiscal_year: FiscalYear) -> str:
    """Nom de fichier commercial : facture-FAC-2026-00042-acme.pdf."""
    if document.number is None:  # le service refuse les brouillons avant le rendu
        raise BusinessRuleError("Un brouillon n'a pas de PDF : numérotez-le d'abord.")
    numero = format_document_number(document.doc_kind, fiscal_year.start_date, document.number)
    prefix = FILE_PREFIXES.get(document.doc_kind, "document")
    issuer_nom = (document.issuer_snapshot or {}).get("nom") or "dossier"
    return f"{prefix}-{numero}-{slug(issuer_nom)}.pdf"


def _styles() -> dict[str, ParagraphStyle]:
    """Styles du document commercial (polices partagées avec les exports comptables)."""
    return {
        "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=16, leading=20),
        "stamp": ParagraphStyle("stamp", fontName=FONT_BOLD, fontSize=10, leading=13),
        "bloc_titre": ParagraphStyle("bloc_titre", fontName=FONT_BOLD, fontSize=7.5, leading=10),
        "bloc_nom": ParagraphStyle("bloc_nom", fontName=FONT_BOLD, fontSize=10, leading=13),
        "bloc_ligne": ParagraphStyle("bloc_ligne", fontName=FONT, fontSize=8.5, leading=11),
        "meta": ParagraphStyle("meta", fontName=FONT, fontSize=9, leading=12),
        "note": ParagraphStyle("note", fontName=FONT, fontSize=7.5, leading=10),
        "cell": ParagraphStyle("cell", fontName=FONT, fontSize=7.5, leading=9),
        "cell_bold": ParagraphStyle("cell_bold", fontName=FONT_BOLD, fontSize=7.5, leading=9),
        "total": ParagraphStyle("total", fontName=FONT, fontSize=8, leading=10),
    }


def _bloc_partie(titre: str, champs: list[tuple[str, str | None]]) -> list[Any]:
    """Bloc « ÉMETTEUR » / « CLIENT » : les champs absents (None) sont omis —
    le PDF reflète exactement l'instantané figé à la numérotation."""
    styles = _styles()
    flowables: list[Any] = [Paragraph(_escape(titre), styles["bloc_titre"])]
    for index, (libelle, valeur) in enumerate(champs):
        if not valeur:
            continue
        if index == 0:
            flowables.append(Paragraph(_escape(valeur), styles["bloc_nom"]))
        else:
            flowables.append(Paragraph(_escape(f"{libelle} : {valeur}"), styles["bloc_ligne"]))
    return flowables


def _timbre(document: SalesDocument) -> Table | None:
    """Timbre d'état encadré pour un document hors usage (annulé, refusé)."""
    texte = STAMPS.get((document.doc_kind, document.status))
    if texte is None:
        return None
    styles = _styles()
    table = Table([[Paragraph(_escape(texte), styles["stamp"])]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.2, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _tableau_lignes(lines: list[SalesDocumentLine], decimals: int) -> Table:
    """Tableau des lignes : désignation, quantité, prix unitaire, remise, TVA,
    montants HT et TTC. Les lignes exonérées portent leur motif sous la désignation."""
    styles = _styles()
    head = [
        "N°",
        "Désignation",
        "Qté",
        "Prix unitaire HT",
        "Remise",
        "TVA",
        "Montant HT",
        "Montant TTC",
    ]
    col_widths = [10 * mm, 52 * mm, 16 * mm, 26 * mm, 16 * mm, 14 * mm, 22 * mm, 24 * mm]
    data: list[list[Any]] = [[Paragraph(_escape(h), styles["cell_bold"]) for h in head]]
    commands: list[Any] = [
        ("FONT", (0, 0), (-1, -1), FONT, 7.5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
    ]
    for line in lines:
        designation: list[Any] = [Paragraph(_escape(line.label), styles["cell"])]
        if line.tax_exempt_reason:
            designation.append(
                Paragraph(_escape(f"Exonéré : {line.tax_exempt_reason}"), styles["note"])
            )
        remise = format_bp(line.discount_bp) if line.discount_bp else "—"
        tva = format_bp(line.tax_bp_snapshot) if line.tax_bp_snapshot is not None else "Exonéré"
        data.append(
            [
                str(line.line_no),
                designation,
                format_quantity(line.quantity),
                format_amount(line.unit_price_ht, decimals),
                remise,
                tva,
                format_amount(line.line_ht, decimals),
                format_amount(line.line_ttc, decimals),
            ]
        )
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


def _tableau_totaux(
    document: SalesDocument, lines: list[SalesDocumentLine], decimals: int
) -> Table:
    """Totaux : HT, TVA décomposée par taux (le taux daté figé fait foi), TTC."""
    tva_par_taux: dict[int, int] = {}
    exonere = False
    for line in lines:
        if line.tax_bp_snapshot is None:
            exonere = True
        else:
            tva_par_taux[line.tax_bp_snapshot] = (
                tva_par_taux.get(line.tax_bp_snapshot, 0) + line.line_tax
            )
    rows: list[list[str]] = [["Total hors taxes", format_amount(document.total_ht, decimals)]]
    for bp in sorted(tva_par_taux, reverse=True):
        rows.append([f"dont TVA {format_bp(bp)}", format_amount(tva_par_taux[bp], decimals)])
    if exonere:
        rows.append(["dont TVA — ligne(s) exonérée(s)", "0"])
    rows.append(["Total toutes taxes comprises", format_amount(document.total_ttc, decimals)])
    table = Table(rows, colWidths=[70 * mm, 40 * mm], hAlign="RIGHT")
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), FONT, 8),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONT", (0, -1), (-1, -1), FONT_BOLD, 8.5),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEEEEE")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.4, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def render_document(
    document: SalesDocument,
    lines: list[SalesDocumentLine],
    fiscal_year: FiscalYear,
    *,
    origin_number: str | None = None,
    generated_at: datetime,
) -> bytes:
    """Rendu du PDF : données figées uniquement. `origin_number` porte le numéro
    formaté du document d'origine (devis d'une facture, facture d'un avoir)."""
    _register_fonts()
    styles = _styles()
    if document.number is None or document.issued_on is None:
        raise BusinessRuleError("Un brouillon n'a pas de PDF : numérotez-le d'abord.")
    numero = format_document_number(document.doc_kind, fiscal_year.start_date, document.number)
    titre = f"{KIND_TITLES.get(document.doc_kind, 'DOCUMENT')} {numero}"
    decimals = currency_decimals(document.currency)
    issuer: dict[str, Any] = document.issuer_snapshot or {}
    partner: dict[str, Any] = document.partner_snapshot or {}

    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=titre,
        author="Kora Finance",
    )
    story: list[Any] = [Paragraph(_escape(titre), styles["title"]), Spacer(1, 3 * mm)]
    timbre = _timbre(document)
    if timbre is not None:
        story += [timbre, Spacer(1, 3 * mm)]

    blocs = Table(
        [
            [
                _bloc_partie(
                    "ÉMETTEUR",
                    [
                        ("", issuer.get("nom")),
                        ("RCCM", issuer.get("rccm")),
                        ("NIF", issuer.get("nif")),
                        ("Adresse", issuer.get("adresse")),
                        ("Ville", issuer.get("ville")),
                        ("Téléphone", issuer.get("telephone")),
                    ],
                ),
                _bloc_partie(
                    "CLIENT",
                    [
                        ("", partner.get("nom")),
                        ("NIU/NCC", partner.get("niu")),
                        ("RCCM", partner.get("rccm")),
                        ("Adresse", partner.get("adresse")),
                    ],
                ),
            ]
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    blocs.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (0, 0), 0.5, colors.grey),
                ("BOX", (1, 0), (1, 0), 0.5, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(blocs)
    story.append(Spacer(1, 3 * mm))

    meta = [f"Émis le : {format_date(document.issued_on)}"]
    if document.due_on is not None:
        meta.append(f"Échéance : {format_date(document.due_on)}")
    if document.valid_until is not None:
        meta.append(f"Valable jusqu'au : {format_date(document.valid_until)}")
    story.append(Paragraph(_escape(" — ".join(meta)), styles["meta"]))
    if origin_number is not None:
        if document.doc_kind == "credit_note":
            origin = (
                f"Annule et remplace la facture {origin_number}"
                if document.reverses_document_id is not None
                else f"Facture d'origine : {origin_number}"
            )
        else:
            origin = f"Devis d'origine : {origin_number}"
        story.append(Paragraph(_escape(origin), styles["meta"]))
    story.append(Spacer(1, 3 * mm))

    story.append(_tableau_lignes(lines, decimals))
    story.append(Spacer(1, 3 * mm))
    story.append(_tableau_totaux(document, lines, decimals))
    if document.notes:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_escape(f"Notes : {document.notes}"), styles["note"]))
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            _escape(
                f"Référence de l'exercice : du {format_date(fiscal_year.start_date)} "
                f"au {format_date(fiscal_year.end_date)} — montants exprimés en "
                f"{document.currency}."
            ),
            styles["note"],
        )
    )

    footer = (
        f"{issuer.get('nom') or 'Kora Finance'} — {titre} — généré le "
        f"{format_date(generated_at.date())} à {generated_at:%H:%M} UTC"
    )
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer=footer, **k))
    return output.getvalue()
