"""Intégration comptable des ventes (Phase 4E).

Recette : la comptabilisation est un acte explicite du comptable (permission
`entries:post`) — jamais automatique. Une facture émise se comptabilise en une
écriture validée du journal des ventes (débit 411x au TTC, crédit 701 au HT,
crédit 4431 à la TVA — inversée pour un avoir) ; un règlement en une écriture
du journal de trésorerie (débit 571 caisse ou 521 banque, crédit 411x). Le
verrou du document/règlement sérialise les courses concurrentes : vingt
comptabilisations simultanées = une seule écriture, dix-neuf refus 409. Les
interlocks protègent le grand livre : un règlement ou une facture comptabilisé
ne se supprime (resp. ne s'annule) qu'après contre-passation de son écriture.
Un exercice clôturé ou verrouillé refuse la comptabilisation, comme toute
saisie. Le garde-fou des phases 4A-4D reste vrai : sans l'action explicite,
aucune écriture n'apparaît.
"""

import threading
import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import CompanyFixture, UserFixture
from tests.test_sales import (
    Sales,
    _creer_tier,
    _creer_tva,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]
TTC = 3_540_000  # facture type : 3 000 000 HT + 540 000 TVA (18 %)
HT = 3_000_000
TVA = 540_000


class Entries:
    """Raccourcis d'appel à l'API comptabilisation et grand livre."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def post_document(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/sales/{document_id}/entry", headers=headers, json={})

    def post_document_with_account(self, document_id: str, sales_account_id: str) -> Response:
        return self.client.post(
            f"{self.base}/sales/{document_id}/entry",
            headers=self.company.headers,
            json={"sales_account_id": sales_account_id},
        )

    def post_payment(self, payment_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/payments/{payment_id}/entry", headers=headers, json={}
        )

    def entry(self, entry_id: str) -> Response:
        return self.client.get(f"{self.base}/entries/{entry_id}", headers=self.company.headers)

    def list_entries(self) -> Response:
        return self.client.get(f"{self.base}/entries", headers=self.company.headers)

    def reverse(self, entry_id: str) -> Response:
        return self.client.post(
            f"{self.base}/entries/{entry_id}/reversal",
            headers=self.company.headers,
            json={"entry_date": "2026-12-31"},
        )


def _tva_avec_compte(client: TestClient, company: CompanyFixture) -> str:
    """Taux 18 % dont le compte collecté est le 4431 du plan SYSCOHADA du dossier
    (les taux par défaut de la pile de tests n'en portent pas)."""
    response = client.post(
        f"/api/v1/companies/{company.id}/tax-rates",
        headers=company.headers,
        json={
            "code": f"TVA18_{uuid.uuid4().hex[:4].upper()}",
            "label": "TVA 18 %",
            "kind": "TVA",
            "rate_basis_points": 1800,
            "valid_from": "2026-01-01",
            "collected_account_number": "4431",
        },
    )
    assert response.status_code == 201, response.text
    rate_id: str = response.json()["id"]
    return rate_id


def _facture_emise_avec_tva(sales: Sales, client: TestClient, company: CompanyFixture) -> str:
    """Facture émise avec TVA 18 % comptabilisable (compte collecté 4431)."""
    invoice_id = _facture_brouillon(sales, _tva_avec_compte(client, company))
    body = sales.issue(invoice_id).json()
    assert body["document"]["status"] == "ISSUED", body
    return invoice_id


def _facture_exoneree_emise(sales: Sales) -> str:
    invoice_id = _facture_brouillon(sales, None)
    body = sales.issue(invoice_id).json()
    assert body["document"]["status"] == "ISSUED", body
    return invoice_id


def _lignes_avec_comptes(entry_body: dict[str, object]) -> dict[str, tuple[int, int]]:
    """(débit, crédit) par numéro de compte d'une écriture renvoyée par l'API."""
    lignes = entry_body["lines"]
    assert isinstance(lignes, list)
    return {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in lignes
    }


def test_comptabilisation_facture_ecriture_ventes(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    facture_avant = sales.get(invoice_id).json()
    assert facture_avant["entry_id"] is None
    response = api.post_document(invoice_id)
    assert response.status_code == 200, response.text
    facture = response.json()
    entry_id = facture["entry_id"]
    assert entry_id is not None
    assert facture["status"] == "ISSUED"
    ecriture = api.entry(entry_id).json()
    assert ecriture["status"] == "POSTED"
    assert ecriture["journal_code"] == "VT"
    assert int(ecriture["total_debit"]) == TTC
    assert int(ecriture["total_credit"]) == TTC
    assert ecriture["reference"].startswith("FAC-2026-"), ecriture["reference"]
    lignes = _lignes_avec_comptes(ecriture)
    assert lignes["411"] == (TTC, 0), lignes
    assert lignes["701"] == (0, HT), lignes
    assert lignes["4431"] == (0, TVA), lignes


def test_comptabilisation_facture_exoneree_deux_lignes(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_exoneree_emise(sales)
    response = api.post_document(invoice_id)
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry_id"]
    assert entry_id is not None
    ecriture = api.entry(entry_id).json()
    lignes = _lignes_avec_comptes(ecriture)
    assert sorted(lignes) == ["411", "701"], lignes
    assert lignes["701"] == (0, HT)
    assert int(ecriture["total_debit"]) == HT
    assert int(ecriture["total_credit"]) == HT


def test_comptabilisation_avoir_ecriture_inverse(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    credit_note_id = sales.create(
        {
            "doc_kind": "credit_note",
            "partner_id": sales.get(invoice_id).json()["partner_id"],
            "origin_document_id": invoice_id,
            "lines": [
                {
                    "label": "Retour matériel",
                    "quantity": 1000,
                    "unit_price_ht": 500_000,
                    "tax_rate_id": _tva_avec_compte(client, company),
                }
            ],
        }
    ).json()["id"]
    body = sales.issue(credit_note_id).json()
    assert body["document"]["status"] == "ISSUED", body
    avoir_ht = body["document"]["total_ht"]
    avoir_tva = body["document"]["total_tax"]
    avoir_ttc = body["document"]["total_ttc"]
    response = api.post_document(credit_note_id)
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry_id"]
    assert entry_id is not None
    ecriture = api.entry(entry_id).json()
    assert ecriture["journal_code"] == "VT"
    assert int(ecriture["total_debit"]) == avoir_ttc
    assert int(ecriture["total_credit"]) == avoir_ttc
    lignes = _lignes_avec_comptes(ecriture)
    assert lignes["411"] == (0, avoir_ttc), lignes
    assert lignes["701"] == (avoir_ht, 0), lignes
    assert lignes["4431"] == (avoir_tva, 0), lignes


def test_devis_ne_se_comptabilise_pas(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    quote_id = sales.create(
        {
            "doc_kind": "quote",
            "partner_id": _creer_tier(client, company),
            "lines": [
                {
                    "label": "Étude",
                    "quantity": 1000,
                    "unit_price_ht": 1_000_000,
                    "tax_exempt_reason": "Vente exonérée (article du CGI à documenter)",
                }
            ],
        }
    ).json()["id"]
    sent = sales.send(quote_id)
    assert sent.status_code == 200, sent.text
    response = api.post_document(quote_id)
    assert response.status_code == 422, response.text
    assert "devis" in response.json()["detail"].lower()


def test_brouillon_et_annulee_ne_se_comptabilisent_pas(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    draft_id = _facture_brouillon(sales, _tva_avec_compte(client, company))
    assert api.post_document(draft_id).status_code == 409
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    cancelled = sales.cancel(invoice_id)
    assert cancelled.status_code == 200, cancelled.text
    assert api.post_document(invoice_id).status_code == 409


def test_double_comptabilisation_409(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    assert api.post_document(invoice_id).status_code == 200
    entry_id = sales.get(invoice_id).json()["entry_id"]
    again = api.post_document(invoice_id)
    assert again.status_code == 409, again.text
    assert sales.get(invoice_id).json()["entry_id"] == entry_id


def test_course_20_comptabilisations_simultanees(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Vingt comptabilisations concurrentes de la même facture : le verrou du
    document sérialise ; une seule écriture est créée, les dix-neuf autres
    voient l'entry_id rempli et répondent 409. Chaque fil opère sur une vraie
    connexion PostgreSQL (même protocole que la course des règlements 4C)."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)

    resultats: list[str] = []
    verrou = threading.Lock()

    def tenter() -> None:
        try:
            reponse = api.post_document(invoice_id)
            with verrou:
                resultats.append(str(reponse.status_code))
        except BaseException as exc:  # pragma: no cover - diagnostic de course
            with verrou:
                resultats.append(f"EXC {exc!r}")

    fils = [threading.Thread(target=tenter) for _ in range(20)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(30)
        assert not fil.is_alive(), "comptabilisation bloquée > 30 s"

    assert resultats.count("200") == 1, sorted(resultats)
    assert resultats.count("409") == 19, sorted(resultats)
    entries = api.list_entries().json()
    assert entries["total"] == 1, entries


def test_comptabilisation_reglement_caisse_et_mobile_money(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    payment_id = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": TTC}],
        },
    ).json()["id"]
    response = api.post_payment(payment_id)
    assert response.status_code == 200, response.text
    payment = response.json()
    entry_id = payment["entry_id"]
    assert entry_id is not None
    ecriture = api.entry(entry_id).json()
    assert ecriture["journal_code"] == "CA", ecriture
    lignes = _lignes_avec_comptes(ecriture)
    assert lignes["571"] == (TTC, 0), lignes
    assert lignes["411"] == (0, TTC), lignes
    # Un deuxième règlement en Mobile Money part au journal MM (compte 521).
    invoice_2 = _facture_emise_avec_tva(sales, client, company)
    payment_2 = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-16",
            "method": "MOBILE_MONEY",
            "allocations": [{"document_id": invoice_2, "amount": TTC}],
        },
    ).json()["id"]
    ecriture_2 = api.entry(api.post_payment(payment_2).json()["entry_id"]).json()
    assert ecriture_2["journal_code"] == "MM", ecriture_2
    assert "521" in _lignes_avec_comptes(ecriture_2)


def test_double_comptabilisation_reglement_409(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    payment_id = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "BANK_TRANSFER",
            "allocations": [{"document_id": invoice_id, "amount": TTC}],
        },
    ).json()["id"]
    assert api.post_payment(payment_id).status_code == 200
    assert api.post_payment(payment_id).status_code == 409


def test_suppression_reglement_comptabilise_refusee_puis_liberee_apres_contrepassation(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    payment_id = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": TTC}],
        },
    ).json()["id"]
    assert api.post_payment(payment_id).status_code == 200
    refusal = client.delete(
        f"/api/v1/companies/{company.id}/payments/{payment_id}", headers=company.headers
    )
    assert refusal.status_code == 409, refusal.text
    entry_id = client.get(
        f"/api/v1/companies/{company.id}/payments/{payment_id}", headers=company.headers
    ).json()["entry_id"]
    reversal = api.reverse(entry_id)
    assert reversal.status_code == 201, reversal.text
    assert (
        client.delete(
            f"/api/v1/companies/{company.id}/payments/{payment_id}", headers=company.headers
        ).status_code
        == 204
    )


def test_annulation_facture_comptabilisee_exige_contrepassation(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    assert api.post_document(invoice_id).status_code == 200
    refusal = sales.cancel(invoice_id)
    assert refusal.status_code == 409, refusal.text
    entry_id = sales.get(invoice_id).json()["entry_id"]
    assert entry_id is not None
    reversal = api.reverse(entry_id)
    assert reversal.status_code == 201, reversal.text
    assert sales.cancel(invoice_id).status_code == 200


def test_exercice_verrouille_refuse_la_comptabilisation(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    fiscal_year_id = client.get(
        f"/api/v1/companies/{company.id}/fiscal-years", headers=company.headers
    ).json()[0]["id"]
    locked = client.post(
        f"/api/v1/companies/{company.id}/fiscal-years/{fiscal_year_id}/lock",
        headers=company.headers,
        json={"locked_until": "2026-12-31"},
    )
    assert locked.status_code == 200, locked.text
    response = api.post_document(invoice_id)
    assert response.status_code == 422, response.text
    assert "verrouill" in response.json()["detail"].lower()


def test_compte_produit_choisi_et_regroupement_refuse(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    # Le compte 70 est un regroupement (sous-comptes) : le grand livre refuse.
    accounts = client.get(
        f"/api/v1/companies/{company.id}/accounts", headers=company.headers, params={"q": "70"}
    ).json()
    parent_70 = next(a["id"] for a in accounts["items"] if a["number"] == "70")
    response = api.post_document_with_account(invoice_id, parent_70)
    assert response.status_code == 422, response.text
    assert "sous-compte" in response.json()["detail"].lower()
    # Le sous-compte 701 choisi explicitement est accepté.
    account_701 = next(a["id"] for a in accounts["items"] if a["number"] == "701")
    ok = api.post_document_with_account(invoice_id, account_701)
    assert ok.status_code == 200, ok.text
    lignes = _lignes_avec_comptes(api.entry(ok.json()["entry_id"]).json())
    assert lignes["701"] == (0, HT)


def test_compte_produit_inconnu_400(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    response = api.post_document_with_account(invoice_id, str(uuid.uuid4()))
    assert response.status_code == 422, response.text
    assert "introuvable" in response.json()["detail"].lower()


def test_taux_sans_compte_collecte_400(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    api = Entries(client, company)
    invoice_id = _facture_brouillon(sales, _creer_tva(client, company))
    assert sales.issue(invoice_id).status_code == 200
    response = api.post_document(invoice_id)
    assert response.status_code == 422, response.text
    assert "collect" in response.json()["detail"].lower()


def test_garde_fou_sans_action_aucune_ecriture(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Cycle complet de ventes (émission, règlement, suppression du règlement,
    devis envoyé) sans comptabilisation explicite : le grand livre reste vide —
    l'intégration n'est jamais automatique."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    payment_id = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": TTC}],
        },
    ).json()["id"]
    deleted = client.delete(
        f"/api/v1/companies/{company.id}/payments/{payment_id}", headers=company.headers
    )
    assert deleted.status_code == 204, deleted.text
    quote_id = sales.create(
        {
            "doc_kind": "quote",
            "partner_id": _creer_tier(client, company),
            "lines": [
                {
                    "label": "Étude",
                    "quantity": 1000,
                    "unit_price_ht": 1_000_000,
                    "tax_exempt_reason": "Vente exonérée (article du CGI à documenter)",
                }
            ],
        }
    ).json()["id"]
    assert sales.send(quote_id).status_code == 200
    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    assert entries.json()["items"] == [], "des écritures sont apparues sans comptabilisation"


def test_isolation_comptabilisation_entre_dossiers(
    client: TestClient, make_company: MakeCompany
) -> None:
    mine = Sales(client, _dossier(make_company))
    theirs = Sales(client, _dossier(make_company))
    leurs_entries = Entries(client, theirs.company)
    invoice_id = _facture_emise_avec_tva(mine, client, mine.company)
    # Un autre dossier ne voit pas la facture (404, jamais 403).
    assert leurs_entries.post_document(invoice_id).status_code == 404


def test_lecteur_ne_comptabilise_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., UserFixture]
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    invoice_id = _facture_emise_avec_tva(sales, client, company)
    lecteur = make_user()
    invited = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},
    )
    assert invited.status_code in (200, 201), invited.text
    response = client.post(
        f"/api/v1/companies/{company.id}/sales/{invoice_id}/entry",
        headers=lecteur.headers(client),
        json={},
    )
    assert response.status_code == 403, response.text
