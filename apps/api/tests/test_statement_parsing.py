"""Lecture des relevés OFX et CSV (3B) : formats réels des banques de la sous-région.

Les échantillons reproduisent les exports observés : OFX 1.x SGML aux balises non
fermées (BCRG, Ecobank), montants « 2 500 000 » avec espaces insécables, virgule
décimale, débit/crédit en colonnes séparées, dates JJ/MM/AAAA. Chaque cas de
corruption est refusé avec un message exploitable, jamais interprété à l'aveugle.
"""

import io
import zipfile
from datetime import date

import openpyxl
import pytest

from kora.core.errors import BusinessRuleError
from kora.treasury import parsing
from kora.treasury.parsing import ParsedLine, parse_csv, parse_statement, parse_xlsx

# OFX 1.x SGML : balises non fermées, en-tête à deux-points, fuseau sur DTPOSTED.
OFX_1 = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:UTF-8
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>0</TRNUID>
<STATUS><CODE>0<SEVERITY>INFO
<STMTRS>
<CURDEF>GNF
<BANKACCTFROM><BANKID>BCRG<ACCTID>0012345678-01<ACCTTYPE>CHECKING
<BANKTRANLIST>
<DTSTART>20260101000000
<DTEND>20260131120000
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260105100000[+0:GMT]<TRNAMT>-2500000.00
<FITID>TX0001<NAME>VIREMENT SALAIRE<MEMO>MOIS JANVIER 2026
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260112<TRNAMT>1180000.00
<FITID>TX0002<NAME>REMISE CHEQUE 123456
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260118<TRNAMT>-75000
<FITID>TX0003<NAME>FRAIS BANCAIRES<MEMO>TENUE DE COMPTE
</BANKTRANLIST>
<LEDGERBAL><BALAMT>3605000.00<DTASOF>20260131120000
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""

# OFX 2.x : XML bien formé, déclarations d'espacement, encodage UTF-8 explicite.
OFX_2 = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<?OFX OFXHEADER="200" VERSION="2.1.1" ?>\n'
    "<OFX>\n<BANKTRANLIST>\n"
    "<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260203</DTPOSTED>"
    "<TRNAMT>500000</TRNAMT><FITID>2X0007</FITID><NAME>DÉPÔT ESPÈCES AGENCE KALOUM</NAME>"
    "</STMTTRN>\n"
    "<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260210</DTPOSTED>"
    "<TRNAMT>-12500</TRNAMT><FITID>2X0008</FITID><NAME>FRAIS MOBILE MONEY</NAME></STMTTRN>\n"
    "</BANKTRANLIST>\n</OFX>\n"
).encode()


def test_ofx_sgml_balises_non_fermees() -> None:
    parsed = parse_statement(OFX_1)
    assert parsed.format == "OFX"
    assert [line.amount for line in parsed.lines] == [-2500000, 1180000, -75000]
    assert [line.value_date for line in parsed.lines] == [
        date(2026, 1, 5),
        date(2026, 1, 12),
        date(2026, 1, 18),
    ]
    assert parsed.lines[0].label == "VIREMENT SALAIRE MOIS JANVIER 2026"
    assert parsed.lines[0].reference == "TX0001"
    # Seule la date est retenue, jamais l'heure du fuseau bancaire.
    assert parsed.lines[1].reference == "TX0002"


def test_ofx2_xml() -> None:
    parsed = parse_statement(OFX_2)
    assert parsed.format == "OFX"
    assert len(parsed.lines) == 2
    assert parsed.lines[0].label == "DÉPÔT ESPÈCES AGENCE KALOUM"
    assert parsed.lines[1].amount == -12500


def test_ofx_sans_operation_refuse() -> None:
    sans_operation = OFX_1.split(b"<BANKTRANLIST>")[0] + b"</OFX>"
    with pytest.raises(BusinessRuleError, match="Aucune opération"):
        parse_statement(sans_operation)


def test_pdf_refuse() -> None:
    with pytest.raises(BusinessRuleError, match="Format non reconnu"):
        parse_statement(b"%PDF-1.7 fakerelevant content")


# --- CSV


CSV_HEADER_FR = (
    "Date opération;Libellé;Référence;Débit;Crédit;Solde\r\n"
    "05/01/2026;Virement salaire janvier;VIR20260105;;2\u00a0500\u00a0000;2\u00a0500\u00a0000\r\n"
    "18/01/2026;Frais de tenue de compte;AGIO0118;75\u00a0000;;2\u00a0425\u00a0000\r\n"
    "22/01/2026;Retrait DAB;RET2201;250\u00a0000;;2\u00a0175\u00a0000\r\n"
).encode()


def test_csv_entetes_fr_debit_credit() -> None:
    lines = parse_csv(CSV_HEADER_FR)
    assert [line.amount for line in lines] == [2500000, -75000, -250000]
    # Le débit est une sortie (négatif), le crédit une entrée (positif) ;
    # la colonne solde est portée telle quelle.
    assert lines[0].balance_after == 2500000
    assert lines[1].reference == "AGIO0118"


CSV_SEMIS = (
    "Date;Libellé;Montant\r\n2026-02-03;Dépôt espèces;500 000\r\n2026-02-10;Frais MM;12 500-\r\n"
).encode()


def test_csv_montants_speciaux() -> None:
    lines = parse_csv(CSV_SEMIS)
    assert [line.amount for line in lines] == [500000, -12500]


def test_csv_moins_parenthetique() -> None:
    contenu = (
        "date;libellé;montant\n"
        "01/03/2026;Retrait guichet;(75 000)\n"
        "02/03/2026;Remise chèque;150000\n"
    ).encode()
    lines = parse_csv(contenu)
    assert [line.amount for line in lines] == [-75000, 150000]


def test_csv_decimales_arrondies_au_gnf() -> None:
    # « 1.234.567,89 » : le GNF n'a pas de sous-unité — arrondi au plus près.
    # Une ligne qui s'arrondit à 0 (0,40) est ignorée : aucune opération nulle.
    contenu = (
        "date;libellé;montant\n03/03/2026;Vente;1.234.567,89\n04/03/2026;Achat;0,40\n"
    ).encode()
    lines = parse_csv(contenu)
    assert [line.amount for line in lines] == [1234568]


def test_csv_sans_entete_inference() -> None:
    # Sans en-tête, les colonnes sont déduites des données ; le signe du fichier est
    # conservé tel quel (aucune direction n'est inventée : le tri des lignes
    # ambiguës reste à l'utilisateur, le rapprochement 3C tranche).
    contenu = (
        b"05/01/2026;Vente client KOFFI;1250000\n"
        b"06/01/2026;Achat carburant;-85000\n"
        b"07/01/2026;Loyer janvier;700000\n"
    )
    lines = parse_csv(contenu)
    assert [line.amount for line in lines] == [1250000, -85000, 700000]
    assert lines[0].label == "Vente client KOFFI"


def test_csv_cp1252_accents() -> None:
    contenu = "Date;Libellé;Montant\r\n01/02/2026;Prélèvement EEE;10000\r\n".encode("cp1252")
    lines = parse_csv(contenu)
    assert lines[0].label == "Prélèvement EEE"


def test_csv_colonnes_larges_ignorees() -> None:
    contenu = (
        "Date;Libellé;Montant;Devise;Note\r\n"
        "01/04/2026;Vente;300000;GNF;sans note\r\n"
        "02/04/2026;;400000;GNF;x\r\n"
    ).encode()
    lines = parse_csv(contenu)
    assert [line.amount for line in lines] == [300000, 400000]
    assert lines[1].label == "opération de relevé"


def test_csv_aucune_operation_reconnaissance() -> None:
    # Colonnes sans dates lisibles ni montants : refus net, jamais d'invention.
    contenu = b"texte;texte2\nbonjour;monde\n"
    with pytest.raises(BusinessRuleError, match="Aucune opération"):
        parse_statement(contenu)


def test_format_detection_inchanges_par_extension() -> None:
    # Un PDF renommé « .ofx » reste un PDF : la détection ne lit que le contenu.
    assert parsing.detect_format(b"%PDF-1.7 ...") is None
    assert parsing.detect_format(OFX_1) == "OFX"
    assert parsing.detect_format(CSV_HEADER_FR) == "CSV"


def test_libelle_controle_purifie() -> None:
    line = ParsedLine(value_date=date(2026, 1, 5), amount=100, label="A\x00B\n  C  D\tE")
    assert parsing.line_content_hash(line) != ""
    # L'empreinte est stable et insensible à la casse du libellé.
    autre = ParsedLine(value_date=date(2026, 1, 5), amount=100, label="a\x00b\n  c  d\te")
    assert parsing.line_content_hash(line) == parsing.line_content_hash(autre)


# --- Frais Mobile Money (3D) : la commission devient une ligne distincte [FRAIS]


CSV_MOMO = (
    "Date;Libellé;Montant;Frais;Référence\r\n"
    "01/04/2026;Transfert reçu de Mariama S.;300000;0;OM-GN-25040101\r\n"
    "02/04/2026;Paiement boutique Kaloum;-45000;250;OM-GN-25040202\r\n"
    "03/04/2026;Retrait agent Matam;-200000;500;OM-GN-25040303\r\n"
).encode()


def test_csv_momo_frais_ligne_distincte() -> None:
    lines = parse_csv(CSV_MOMO)
    # Chaque opération à frais non nuls est suivie de sa ligne [FRAIS].
    assert [(line.label, line.amount) for line in lines] == [
        ("Transfert reçu de Mariama S.", 300000),
        ("Paiement boutique Kaloum", -45000),
        ("[FRAIS] Paiement boutique Kaloum", -250),
        ("Retrait agent Matam", -200000),
        ("[FRAIS] Retrait agent Matam", -500),
    ]
    # La ligne de frais partage la date et la référence de son opération :
    # le rapprochement peut ainsi les lier, la commission reste comptabilisable
    # séparément (nature « frais bancaires et Mobile Money » de la saisie guidée).
    frais = lines[2]
    assert frais.value_date == date(2026, 4, 2)
    assert frais.reference == "OM-GN-25040202"
    # Aucune ligne de frais n'invente un solde : la colonne n'existe pas pour elle.
    assert frais.balance_after is None


def test_csv_frais_zero_ou_vide_sans_ligne() -> None:
    contenu = (
        "Date;Libellé;Montant;Frais\n"
        "10/04/2026;Transfert reçu;100000;0\n"
        "11/04/2026;Transfert reçu;200000;\n"
    ).encode()
    lines = parse_csv(contenu)
    assert [line.amount for line in lines] == [100000, 200000]
    assert all(not line.label.startswith("[FRAIS]") for line in lines)


def test_csv_frais_signes_variants_toujours_negatifs() -> None:
    # Commission écrite négative, parenthétique ou avec signe à droite : une
    # commission est une sortie du point de vue du titulaire, quel que soit
    # l'export. Le sens n'est jamais inversé à l'aveugle.
    contenu = (
        "Date;Libellé;Montant;Frais\n"
        "10/04/2026;Paiement A;50000;-100\n"
        "11/04/2026;Paiement B;60000;(200)\n"
        "12/04/2026;Paiement C;70000;300-\n"
    ).encode()
    lines = parse_csv(contenu)
    assert [line.amount for line in lines if line.label.startswith("[FRAIS]")] == [-100, -200, -300]


def test_csv_frais_avant_debit_et_montant() -> None:
    # « Frais débités » ne doit pas être pris pour la colonne débit, ni
    # « Montant des frais » pour la colonne montant : le rôle frais passe avant.
    contenu = (
        "Date;Libellé;Montant;Frais débités\n05/04/2026;Retrait agent;200000;250\n"
        "Date;Libellé;Montant;Montant des frais\n06/04/2026;Paiement;100000;300\n"
    ).encode()
    lines = parse_csv(contenu)
    assert [(line.label, line.amount) for line in lines] == [
        ("Retrait agent", 200000),
        ("[FRAIS] Retrait agent", -250),
        ("Paiement", 100000),
        ("[FRAIS] Paiement", -300),
    ]


def test_csv_bancaire_classique_sans_ligne_frais() -> None:
    # Le format bancaire (3B) ne porte pas de colonne frais : aucun changement
    # de comportement, aucune ligne [FRAIS] inventée.
    lines = parse_csv(CSV_HEADER_FR)
    assert [line.amount for line in lines] == [2500000, -75000, -250000]


# --- Excel (.xlsx) : le même contrat de lecture que le CSV


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


XLSX_MOMO = _xlsx(
    [
        ["Date", "Libellé", "Montant", "Frais", "Référence"],
        [date(2026, 4, 1), "Transfert reçu de Mariama S.", 300000, 0, "OM-GN-25040101"],
        [date(2026, 4, 2), "Paiement boutique Kaloum", -45000, 250, "OM-GN-25040202"],
        [date(2026, 4, 3), "Retrait agent Matam", -200000, 500, "OM-GN-25040303"],
    ]
)


def test_xlsx_momo_entetes_fr() -> None:
    lines = parse_xlsx(XLSX_MOMO)
    assert [(line.label, line.amount) for line in lines] == [
        ("Transfert reçu de Mariama S.", 300000),
        ("Paiement boutique Kaloum", -45000),
        ("[FRAIS] Paiement boutique Kaloum", -250),
        ("Retrait agent Matam", -200000),
        ("[FRAIS] Retrait agent Matam", -500),
    ]
    # Les cellules date réelles d'Excel (datetime interne) donnent la bonne journée.
    assert lines[0].value_date == date(2026, 4, 1)
    assert lines[3].reference == "OM-GN-25040303"


def test_xlsx_inference_sans_entete() -> None:
    classeur = _xlsx(
        [
            [date(2026, 5, 2), "Dépôt espèces", 850000],
            [date(2026, 5, 9), "Achat carburant", -45000],
        ]
    )
    lines = parse_xlsx(classeur)
    assert [line.amount for line in lines] == [850000, -45000]
    assert lines[0].label == "Dépôt espèces"


def test_xlsx_debit_credit_separes() -> None:
    classeur = _xlsx(
        [
            ["Date", "Libellé", "Débit", "Crédit", "Solde"],
            ["01/06/2026", "Virement salaire", "", 2500000, 2500000],
            ["05/06/2026", "Loyer boutique", 450000, "", 2050000],
        ]
    )
    lines = parse_xlsx(classeur)
    assert [line.amount for line in lines] == [2500000, -450000]
    assert lines[1].balance_after == 2050000


def test_xlsx_detection_et_format() -> None:
    assert parsing.detect_format(XLSX_MOMO) == "XLSX"
    statement = parse_statement(XLSX_MOMO)
    assert statement.format == "XLSX"
    assert len(statement.lines) == 5


def test_xlsx_macros_refusees() -> None:
    # Un classeur à macros (xlsm) contient aussi xl/workbook.xml : il est reconnu
    # comme Excel mais refusé explicitement — l'application ne lit jamais du code.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/vbaProject.bin", b"\x00\x01vba")
    buffer.seek(0)
    with pytest.raises(BusinessRuleError, match="macros"):
        parse_statement(buffer.getvalue())


def test_xlsx_corrompu_ou_zip_etranger_refuse() -> None:
    # Archive invalide : ni OFX ni CSV ni Excel — refus net et exploitable.
    with pytest.raises(BusinessRuleError, match="Format non reconnu"):
        parse_statement(b"PK\x03\x04" + b"garbage" * 10)
    # ZIP valide mais sans classeur (docx, odt…) : ce n'est pas un relevé.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<doc/>")
    buffer.seek(0)
    with pytest.raises(BusinessRuleError, match="Format non reconnu"):
        parse_statement(buffer.getvalue())


def test_xlsx_classeur_vide_refuse() -> None:
    classeur = _xlsx([["Date", "Libellé", "Montant"]])
    with pytest.raises(BusinessRuleError, match="Aucune opération lue dans ce fichier Excel"):
        parse_statement(classeur)
