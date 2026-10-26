"""Les textes métier exportés doivent rester du texte, même s'ils ressemblent à une formule."""

import io
from datetime import UTC, datetime

from openpyxl import load_workbook

from kora.exports.document import Column, Document, Section
from kora.exports.xlsx import render


def test_export_ne_transforme_pas_les_textes_en_formules() -> None:
    text = "=1+1"
    section = Section(text, [Column(text), Column("Montant", "amount")])
    section.add(text, 1234567)
    document = Document(
        title=text,
        company_name=text,
        identifiers=text,
        period=text,
        currency="GNF",
        generated_at=datetime(2026, 10, 26, tzinfo=UTC),
        sections=[section],
        notes=[text],
    )
    workbook = load_workbook(io.BytesIO(render(document)), data_only=False)
    cells = [cell for sheet in workbook for row in sheet for cell in row]
    texts = [cell for cell in cells if cell.value == text]
    assert len(texts) == 8
    assert all(cell.data_type == "s" for cell in texts)
    assert not any(cell.data_type == "f" for cell in cells)
    amount = next(cell for cell in cells if cell.value == 1234567)
    assert amount.data_type == "n"
