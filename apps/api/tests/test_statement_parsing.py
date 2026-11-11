"""Lecture des relevés OFX et CSV (3B) : formats réels des banques de la sous-région.

Les échantillons reproduisent les exports observés : OFX 1.x SGML aux balises non
fermées (BCRG, Ecobank), montants « 2 500 000 » avec espaces insécables, virgule
décimale, débit/crédit en colonnes séparées, dates JJ/MM/AAAA. Chaque cas de
corruption est refusé avec un message exploitable, jamais interprété à l'aveugle.
"""

from datetime import date

import pytest

from kora.core.errors import BusinessRuleError
from kora.treasury import parsing
from kora.treasury.parsing import ParsedLine, parse_csv, parse_statement

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
