"""Trésorerie 3B : relevés bancaires importés, via l'API.

Un relevé importé ne crée jamais d'écriture : il dépose des lignes en attente de
rapprochement (3C) sur un compte financier. Les tests vérifient la lecture OFX/CSV
de bout en bout, la déduplication (fichier et lignes), le tri des lignes (ignorer,
remettre), la suppression d'un relevé non rapproché, l'isolation par dossier et les
permissions (lecture sans écriture).
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from kora.core.config import get_settings
from tests.conftest import CompanyFixture
from tests.test_treasury import _banque_body

MakeCompany = Callable[..., CompanyFixture]

# OFX minimal à balises non fermées (format dominant des banques de la sous-région).
OFX = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260302<TRNAMT>1500000.00<FITID>A001<NAME>DEPOT ESPECES
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260310<TRNAMT>-45000.00
<FITID>A002<NAME>FRAIS BANCAIRES<MEMO>COMMISSION
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260321<TRNAMT>200000.00
<FITID>A003<NAME>REMISE CHEQUE 778899
</BANKTRANLIST>
</OFX>
"""

# Recouvrement volontaire : la première opération (DEPOT ESPECES) figure aussi sur
# OFX_SUITE pour vérifier le signalement des doublons entre relevés successifs.
OFX_SUITE = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260302<TRNAMT>1500000.00<FITID>A001<NAME>DEPOT ESPECES
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260402<TRNAMT>-120000.00<FITID>B001<NAME>RETRAIT DAB
</BANKTRANLIST>
</OFX>
"""

CSV = (
    "Date;Libellé;Débit;Crédit\r\n"
    "01/04/2026;Vente comptoir;;300000\r\n"
    "05/04/2026;Achat fournitures;85000;\r\n"
).encode()


class Statements:
    """Raccourcis d'appel à l'API relevés pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def import_file(
        self,
        account_id: str,
        content: bytes,
        filename: str = "releve.ofx",
        company: CompanyFixture | None = None,
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/treasury/accounts/{account_id}/statements?filename={filename}",
            headers=headers,
            content=content,
        )

    def list(self, account_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(
            f"{self.base}/treasury/accounts/{account_id}/statements", headers=headers
        )

    def lines(self, statement_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(
            f"{self.base}/treasury/statements/{statement_id}/lines", headers=headers
        )

    def ignore(
        self, statement_id: str, line_id: str, company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/treasury/statements/{statement_id}/lines/{line_id}/ignore",
            headers=headers,
        )

    def restore(
        self, statement_id: str, line_id: str, company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/treasury/statements/{statement_id}/lines/{line_id}/restore",
            headers=headers,
        )

    def delete(self, statement_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.delete(
            f"{self.base}/treasury/statements/{statement_id}", headers=headers
        )


def _banque_id(
    client: TestClient,
    company: CompanyFixture,
    name: str = "BCRG principal",
) -> str:
    body = _banque_body(client, company, name=name)
    response = client.post(
        f"/api/v1/companies/{company.id}/treasury/accounts", headers=company.headers, json=body
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_import_ofx_cree_lignes_en_attente(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    response = api.import_file(account_id, OFX)
    assert response.status_code == 201, response.text
    statement = response.json()
    assert statement["format"] == "OFX"
    assert statement["line_count"] == 3
    assert statement["period_start"] == "2026-03-02"
    assert statement["period_end"] == "2026-03-21"
    assert statement["sha256"] != ""

    lines = api.lines(statement["id"]).json()
    assert lines["total"] == 3
    # Montant signé du point de vue du titulaire : entrée positive, frais négatifs.
    assert [line["amount"] for line in lines["items"]] == ["1500000", "-45000", "200000"]
    assert all(line["status"] == "PENDING" for line in lines["items"])
    assert all(not line["duplicate"] for line in lines["items"])
    frais = lines["items"][1]
    assert frais["label"] == "FRAIS BANCAIRES COMMISSION"


def test_reimport_meme_fichier_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    assert api.import_file(account_id, OFX).status_code == 201
    again = api.import_file(account_id, OFX)
    assert again.status_code == 409
    assert "déjà été importé" in again.json()["detail"]


def test_meme_fichier_sur_deux_comptes_accepte(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    api = Statements(client, company)
    principal = _banque_id(client, company)
    secondaire = _banque_id(client, company, name="Ecobank seconde")
    assert api.import_file(principal, OFX).status_code == 201
    assert api.import_file(secondaire, OFX).status_code == 201


def test_import_csv_debit_credit(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    response = api.import_file(account_id, CSV, filename="releve.csv")
    assert response.status_code == 201, response.text
    assert response.json()["format"] == "CSV"
    lines = api.lines(response.json()["id"]).json()
    assert [line["amount"] for line in lines["items"]] == ["300000", "-85000"]


def test_fichier_vide_ou_illisible_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    vide = api.import_file(account_id, b"")
    assert vide.status_code == 422
    pdf = api.import_file(account_id, "%PDF-1.7 relevé scanné".encode(), filename="releve.pdf")
    assert pdf.status_code == 422
    assert "Format non reconnu" in pdf.json()["detail"]
    # Aucun relevé partiel n'a été créé : la liste reste vide.
    assert api.list(account_id).json()["total"] == 0


def test_doublons_signales_entre_releves_recouvrants(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    premier = api.import_file(account_id, OFX).json()
    second = api.import_file(account_id, OFX_SUITE).json()
    lines = api.lines(second["id"]).json()
    depot = next(line for line in lines["items"] if line["label"] == "DEPOT ESPECES")
    assert depot["duplicate"] is True
    retrait = next(line for line in lines["items"] if line["label"] == "RETRAIT DAB")
    assert retrait["duplicate"] is False
    # Le signalement est symétrique : les deux relevés montrent le recouvrement,
    # aucun des deux ne « cache » l'autre.
    premier_lines = api.lines(premier["id"]).json()["items"]
    depot_premier = next(line for line in premier_lines if line["label"] == "DEPOT ESPECES")
    assert depot_premier["duplicate"] is True
    assert all(not line["duplicate"] for line in premier_lines if line["label"] != "DEPOT ESPECES")


def test_ignorer_puis_remettre_une_ligne(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    statement = api.import_file(account_id, OFX).json()
    line = api.lines(statement["id"]).json()["items"][1]  # frais bancaires
    ignored = api.ignore(statement["id"], line["id"])
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["status"] == "IGNORED"
    # Idempotent : ignorer une ligne déjà ignorée ne change rien.
    assert api.ignore(statement["id"], line["id"]).json()["status"] == "IGNORED"
    restored = api.restore(statement["id"], line["id"])
    assert restored.status_code == 200
    assert restored.json()["status"] == "PENDING"


def test_suppression_releve_non_rapproche(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    statement = api.import_file(account_id, OFX).json()
    assert api.delete(statement["id"]).status_code == 204
    assert api.list(account_id).json()["total"] == 0
    assert api.lines(statement["id"]).status_code == 404


def test_lecteur_lit_mais_ne_peut_pas_importer(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    statement = api.import_file(account_id, OFX).json()
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    lecteur_company = CompanyFixture(id=company.id, owner=lecteur, headers=headers)  # type: ignore[arg-type]
    # Lecture autorisée…
    assert (
        client.get(
            f"/api/v1/companies/{company.id}/treasury/accounts/{account_id}/statements",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/companies/{company.id}/treasury/statements/{statement['id']}/lines",
            headers=headers,
        ).status_code
        == 200
    )
    # …écriture refusée : import, tri, suppression.
    assert api.import_file(account_id, OFX, company=lecteur_company).status_code == 403
    line = api.lines(statement["id"]).json()["items"][0]
    assert api.ignore(statement["id"], line["id"], company=lecteur_company).status_code == 403
    assert api.delete(statement["id"], company=lecteur_company).status_code == 403


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    statement = api.import_file(account_id, OFX).json()

    other = make_company()
    other_api = Statements(client, other)
    # Le dossier voisin ne voit ni la liste, ni les lignes du relevé.
    assert other_api.list(account_id).status_code == 404
    assert other_api.lines(statement["id"]).status_code == 404
    assert other_api.delete(statement["id"]).status_code == 404
    # Et ne peut pas importer sur un compte qui n'est pas le sien.
    assert other_api.import_file(account_id, OFX).status_code == 404


def test_releve_trop_volumineux(
    client: TestClient,
    make_company: MakeCompany,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    monkeypatch.setattr(get_settings(), "statement_max_bytes", 1024)
    gros = b"OFXHEADER:100\n" + b"<STMTTRN>" + b"A" * 4096
    response = api.import_file(account_id, gros)
    assert response.status_code == 413
    assert response.json()["code"] == "fichier_trop_volumineux"


def test_plafond_de_lignes_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Statements(client, company)
    account_id = _banque_id(client, company)
    max_lines = get_settings().statement_max_lines
    blocs = b"".join(
        b"<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>202603%02d<TRNAMT>1000.00<FITID>X%d<NAME>OP %d"
        % (jour % 28 + 1, no, no)
        for no, jour in enumerate(range(max_lines + 1))
    )
    content = b"OFXHEADER:100\n<OFX><BANKTRANLIST>" + blocs + b"</BANKTRANLIST></OFX>"
    response = api.import_file(account_id, content)
    assert response.status_code == 422
    assert "Trop d'opérations" in response.json()["detail"]
