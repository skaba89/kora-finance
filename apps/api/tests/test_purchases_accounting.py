"""Intégration comptable des achats (Phase 4F).

Recette : la comptabilisation est un acte explicite du comptable (permission
`entries:post`) — jamais automatique. Une facture fournisseur émise se
comptabilise en une écriture validée du journal des achats (débit du compte de
charge au HT, débit 4452 de la TVA récupérable, crédit 401 au TTC — inversée
pour un avoir) ; un décaissement en une écriture du journal de trésorerie
(débit 401x, crédit 571 caisse ou 521 banque/Mobile Money). Le verrou du
document/règlement sérialise les courses concurrentes : vingt comptabilisations
simultanées = une seule écriture, dix-neuf refus 409. Les interlocks protègent
le grand livre : un décaissement ou une facture comptabilisé ne se supprime
(resp. ne s'annule) qu'après contre-passation de son écriture. Un exercice
clôturé ou verrouillé refuse la comptabilisation, comme toute saisie. Le
garde-fou des phases 4A-4E reste vrai : sans l'action explicite, aucune
écriture n'apparaît.
"""

import threading
import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import CompanyFixture, UserFixture
from tests.test_purchases import Purchases, _facture_achat_brouillon
from tests.test_sales import _creer_tva, _dossier

MakeCompany = Callable[..., CompanyFixture]
TTC = 3_540_000  # facture type : 3 000 000 HT + 540 000 TVA (18 %)
HT = 3_000_000
TVA = 540_000


class PEntries:
    """Raccourcis d'appel à l'API comptabilisation et grand livre."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def post_document(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/purchases/{document_id}/entry", headers=headers, json={}
        )

    def post_document_with_account(self, document_id: str, expense_account_id: str) -> Response:
        return self.client.post(
            f"{self.base}/purchases/{document_id}/entry",
            headers=self.company.headers,
            json={"expense_account_id": expense_account_id},
        )

    def post_payment(self, payment_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/purchase-payments/{payment_id}/entry", headers=headers, json={}
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


def _tva_avec_comptes(client: TestClient, company: CompanyFixture) -> str:
    """Taux 18 % dont les comptes sont les 4431 (collectée) et 4452 (récupérable)
    du plan SYSCOHADA du dossier (les taux par défaut de la pile n'en portent
    pas)."""
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
            "deductible_account_number": "4452",
        },
    )
    assert response.status_code == 201, response.text
    rate_id: str = response.json()["id"]
    return rate_id


def _facture_emise_avec_tva(
    purchases: Purchases, client: TestClient, company: CompanyFixture
) -> str:
    """Facture fournisseur émise avec TVA 18 % comptabilisable (compte
    récupérable 4452)."""
    invoice_id = _facture_achat_brouillon(purchases, _tva_avec_comptes(client, company))
    issued = purchases.issue(invoice_id)
    assert issued.status_code == 200, issued.text
    return invoice_id


def _lignes_avec_comptes(entry_body: dict[str, object]) -> dict[str, tuple[int, int]]:
    """(débit, crédit) par numéro de compte d'une écriture renvoyée par l'API."""
    lignes = entry_body["lines"]
    assert isinstance(lignes, list)
    return {
        str(ligne["account_number"]): (int(ligne["debit"]), int(ligne["credit"]))
        for ligne in lignes
    }


def test_comptabilisation_facture_ecriture_achats(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    facture_avant = purchases.get(invoice_id).json()
    assert facture_avant["entry_id"] is None
    response = api.post_document(invoice_id)
    assert response.status_code == 200, response.text
    facture = response.json()
    entry_id = facture["entry_id"]
    assert entry_id is not None
    assert facture["status"] == "ISSUED"
    ecriture = api.entry(entry_id).json()
    assert ecriture["status"] == "POSTED"
    assert ecriture["journal_code"] == "AC"
    assert int(ecriture["total_debit"]) == TTC
    assert int(ecriture["total_credit"]) == TTC
    assert ecriture["reference"].startswith("FACH-2026-"), ecriture["reference"]
    lignes = _lignes_avec_comptes(ecriture)
    assert lignes["601"] == (HT, 0), lignes
    assert lignes["4452"] == (TVA, 0), lignes
    assert lignes["401"] == (0, TTC), lignes


def test_comptabilisation_facture_exoneree_sans_ligne_tva(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_achat_brouillon(purchases, None)
    assert purchases.issue(invoice_id).status_code == 200
    response = api.post_document(invoice_id)
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry_id"]
    assert entry_id is not None
    ecriture = api.entry(entry_id).json()
    lignes = _lignes_avec_comptes(ecriture)
    assert sorted(lignes) == ["401", "601"], lignes
    assert lignes["601"] == (HT, 0)
    assert lignes["401"] == (0, HT)


def test_comptabilisation_avoir_ecriture_inverse(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    avoir = purchases.create(
        {
            "doc_kind": "supplier_credit_note",
            "partner_id": purchases.get(invoice_id).json()["partner_id"],
            "origin_document_id": invoice_id,
            "lines": [
                {
                    "label": "Retour marchandise",
                    "quantity": 1000,
                    "unit_price_ht": 500_000,
                    "tax_rate_id": _tva_avec_comptes(client, company),
                }
            ],
        }
    )
    assert avoir.status_code == 201, avoir.text
    avoir_id = avoir.json()["id"]
    assert purchases.issue(avoir_id).status_code == 200
    response = api.post_document(avoir_id)
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry_id"]
    assert entry_id is not None
    ecriture = api.entry(entry_id).json()
    assert ecriture["journal_code"] == "AC"
    assert ecriture["reference"].startswith("AVF-2026-"), ecriture["reference"]
    lignes = _lignes_avec_comptes(ecriture)
    assert lignes["401"] == (590_000, 0), lignes
    assert lignes["601"] == (0, 500_000), lignes
    assert lignes["4452"] == (0, 90_000), lignes


def test_compte_charge_choisi_explicitement(client: TestClient, make_company: MakeCompany) -> None:
    """Le comptable choisit le compte de charge (602 matières au lieu du défaut
    601 marchandises)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_achat_brouillon(purchases, None)
    assert purchases.issue(invoice_id).status_code == 200
    comptes = client.get(
        f"/api/v1/companies/{company.id}/accounts",
        headers=company.headers,
        params={"q": "602"},
    ).json()
    compte_602 = next(a for a in comptes["items"] if a["number"] == "602")
    response = api.post_document_with_account(invoice_id, compte_602["id"])
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry_id"]
    assert entry_id is not None
    lignes = _lignes_avec_comptes(api.entry(entry_id).json())
    assert "602" in lignes, lignes
    assert "601" not in lignes, lignes


def test_taux_sans_compte_recuperable_refuse(client: TestClient, make_company: MakeCompany) -> None:
    """Un taux sans compte de TVA récupérable refuse la comptabilisation avec un
    message clair (réglage manquant, Paramètres > Taxes)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_achat_brouillon(purchases, _creer_tva(client, company))
    assert purchases.issue(invoice_id).status_code == 200
    response = api.post_document(invoice_id)
    assert response.status_code == 422, response.text
    assert "récupérable" in response.json()["detail"].lower()


def test_garde_fou_aucune_ecriture_sans_action(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Garde-fou des phases 4A-4E maintenu : émissions, décaissements et
    attributions sans acte explicite → grand livre strictement vide."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    payment = client.post(
        f"/api/v1/companies/{company.id}/purchase-payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": 100_000}],
        },
    )
    assert payment.status_code == 201, payment.text
    assert api.list_entries().json()["total"] == 0, "le grand livre doit rester vide"


def test_double_comptabilisation_409(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    assert api.post_document(invoice_id).status_code == 200
    again = api.post_document(invoice_id)
    assert again.status_code == 409, again.text


def test_course_20_comptabilisations_simultanees(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Vingt comptabilisations concurrentes de la même facture = une écriture et
    dix-neuf refus 409 : le verrou du document sérialise, la seconde lecture voit
    entry_id rempli avant tout INSERT."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)

    resultats: list[str] = []
    verrou = threading.Lock()

    def comptabiliser() -> None:
        try:
            reponse = client.post(
                f"/api/v1/companies/{company.id}/purchases/{invoice_id}/entry",
                headers=company.headers,
                json={},
            )
            with verrou:
                resultats.append(str(reponse.status_code))
        except BaseException as exc:  # pragma: no cover - diagnostic de course
            with verrou:
                resultats.append(f"EXC {exc!r}")

    fils = [threading.Thread(target=comptabiliser) for _ in range(20)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(30)
        assert not fil.is_alive(), "comptabilisation bloquée > 30 s"

    assert resultats.count("200") == 1, sorted(resultats)
    assert resultats.count("409") == 19, sorted(resultats)
    facture = purchases.get(invoice_id).json()
    assert facture["entry_id"] is not None


def test_comptabilisation_reglement_caisse_banque_et_mobile_money(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Le décaissement passe au journal de trésorerie selon le mode : débit 401x,
    crédit 571 (caisse au journal CA), 521 (banque au journal BQ, Mobile Money au
    journal MM)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    for method, compte_tresorerie, journal in (
        ("CASH", "571", "CA"),
        ("BANK_TRANSFER", "521", "BQ"),
        ("MOBILE_MONEY", "521", "MM"),
    ):
        payment = client.post(
            f"/api/v1/companies/{company.id}/purchase-payments",
            headers=company.headers,
            json={
                "paid_on": "2026-06-15",
                "method": method,
                "allocations": [{"document_id": invoice_id, "amount": 10_000}],
            },
        )
        assert payment.status_code == 201, payment.text
        payment_id = payment.json()["id"]
        posted = api.post_payment(payment_id)
        assert posted.status_code == 200, posted.text
        entry_id = posted.json()["entry_id"]
        assert entry_id is not None
        ecriture = api.entry(entry_id).json()
        assert ecriture["journal_code"] == journal, ecriture
        lignes = _lignes_avec_comptes(ecriture)
        assert lignes["401"] == (10_000, 0), lignes
        assert lignes[compte_tresorerie] == (0, 10_000), lignes


def test_suppression_reglement_comptabilise_refusee_puis_liberee_apres_contrepassation(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Interlock : un décaissement comptabilisé ne se supprime qu'après la
    contre-passation de son écriture (et la facture redevient annulable)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    payment = client.post(
        f"/api/v1/companies/{company.id}/purchase-payments",
        headers=company.headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": 1_000}],
        },
    )
    assert payment.status_code == 201, payment.text
    payment_id = payment.json()["id"]
    assert api.post_payment(payment_id).status_code == 200
    # Suppression refusée tant que l'écriture est vivante.
    refused = client.delete(
        f"/api/v1/companies/{company.id}/purchase-payments/{payment_id}",
        headers=company.headers,
    )
    assert refused.status_code == 409, refused.text
    # Contre-passation, puis la suppression passe.
    payment_body = client.get(
        f"/api/v1/companies/{company.id}/purchase-payments/{payment_id}",
        headers=company.headers,
    ).json()
    reversal = api.reverse(payment_body["entry_id"])
    assert reversal.status_code == 201, reversal.text
    assert (
        client.delete(
            f"/api/v1/companies/{company.id}/purchase-payments/{payment_id}",
            headers=company.headers,
        ).status_code
        == 204
    )
    # La facture est redevenue annulable (plus de décaissement).
    assert purchases.cancel(invoice_id).status_code == 200


def test_annulation_facture_comptabilisee_exige_contrepassation(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    assert api.post_document(invoice_id).status_code == 200
    refused = purchases.cancel(invoice_id)
    assert refused.status_code == 409, refused.text
    entry_id = purchases.get(invoice_id).json()["entry_id"]
    assert api.reverse(entry_id).status_code == 201
    assert purchases.cancel(invoice_id).status_code == 200


def test_exercice_verrouille_refuse_la_comptabilisation(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    api = PEntries(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
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


def test_lecteur_ne_comptabilise_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., UserFixture]
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    invoice_id = _facture_emise_avec_tva(purchases, client, company)
    lecteur = make_user()
    invited = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},
    )
    assert invited.status_code in (200, 201), invited.text
    response = client.post(
        f"/api/v1/companies/{company.id}/purchases/{invoice_id}/entry",
        headers=lecteur.headers(client),
        json={},
    )
    assert response.status_code == 403, response.text
