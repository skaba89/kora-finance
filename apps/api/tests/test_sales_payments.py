"""Règlements clients et lettrage commercial (Phase 4C).

Recette : un règlement est un encaissement réel, affecté à des factures émises
du même tier — jamais au-delà de leur solde restant dû. La course critique est
testée sur PostgreSQL réel : vingt règlements concurrents de 1 000 sur une
facture de TTC 10 000 → exactement dix succès, solde à zéro, jamais d'excédent
(le verrou FOR UPDATE de la facture sérialise les contrôles). Vérifie aussi les
refus (brouillon, annulée, devis, avoir, tier mixte, hors exercice), l'avoir qui
réduit le solde, l'interlock d'annulation (une facture lettrée ne s'annule pas),
la suppression qui libère le solde, l'isolation RLS, les permissions, la balance
âgée et le garde-fou comptable : aucune écriture n'est générée par les
règlements (Phase 4E le fera avec validation humaine).
"""

import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from httpx2 import Response

from kora.models.common import utcnow
from tests.conftest import CompanyFixture
from tests.test_sales import (
    Sales,
    _creer_tier,
    _creer_tva,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]


class Payments:
    """Raccourcis d'appel à l'API règlements pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/payments", headers=headers, json=body)

    def list(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query = {k: str(v) for k, v in params.items() if v is not None}
        return self.client.get(f"{self.base}/payments", headers=headers, params=query)

    def get(self, payment_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/payments/{payment_id}", headers=headers)

    def delete(self, payment_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.delete(f"{self.base}/payments/{payment_id}", headers=headers)

    def aging(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query = {k: str(v) for k, v in params.items() if v is not None}
        return self.client.get(f"{self.base}/receivables/aging", headers=headers, params=query)


def _facture_emise(
    sales: Sales,
    client: TestClient,
    company: CompanyFixture,
    *,
    due_on: str | None = None,
    partner_id: str | None = None,
) -> str:
    """Facture émise de TTC 3 540 000 (lignes 4B : 3 000 000 HT + 540 000 TVA),
    échéance passée ou future selon les besoins de la balance âgée."""
    overrides: dict[str, object] = {"due_on": due_on}
    if partner_id is not None:
        overrides["partner_id"] = partner_id
    invoice_id = _facture_brouillon(sales, _creer_tva(client, company), **overrides)
    body = sales.issue(invoice_id).json()
    assert body["document"]["status"] == "ISSUED", body
    return invoice_id


def _reglement(
    payments_api: Payments,
    invoice_id: str,
    montant: int,
    *,
    paid_on: str = "2026-06-15",
    method: str = "MOBILE_MONEY",
) -> Response:
    return payments_api.create(
        {
            "paid_on": paid_on,
            "method": method,
            "allocations": [{"document_id": invoice_id, "amount": montant}],
        }
    )


def test_reglement_integral_solde_zero(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    invoice_id = _facture_emise(sales, client, company)
    response = _reglement(reglements, invoice_id, 3_540_000)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == 3_540_000
    assert body["currency"] == "GNF"
    assert [a["amount"] for a in body["allocations"]] == [3_540_000]
    assert body["method"] == "MOBILE_MONEY"
    facture = sales.get(invoice_id).json()
    assert facture["outstanding_ttc"] == 0
    assert facture["payment_status"] == "paid"


def test_reglement_partiel_et_multi_factures(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    tier = _creer_tier(client, company)
    a = _facture_emise(sales, client, company, partner_id=tier)  # TTC 3 540 000
    b = _facture_brouillon(sales, _creer_tva(client, company), partner_id=tier)
    assert sales.issue(b).status_code == 200
    response = reglements.create(
        {
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [
                {"document_id": a, "amount": 1_000_000},
                {"document_id": b, "amount": 3_540_000},
            ],
        }
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == 4_540_000  # somme des affectations, jamais saisie
    assert len(body["allocations"]) == 2
    assert sales.get(a).json()["payment_status"] == "partial"
    assert sales.get(a).json()["outstanding_ttc"] == 2_540_000
    assert sales.get(b).json()["payment_status"] == "paid"
    # Un règlement ne s'affecte qu'une fois à une même facture.
    doublon = reglements.create(
        {
            "paid_on": "2026-06-16",
            "method": "CASH",
            "allocations": [
                {"document_id": a, "amount": 100},
                {"document_id": a, "amount": 200},
            ],
        }
    )
    assert doublon.status_code == 422


def test_avoir_reduit_le_solde(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    tier = _creer_tier(client, company)
    tva = _creer_tva(client, company)
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    avoir_id = _facture_brouillon(
        sales, tva, doc_kind="credit_note", partner_id=tier, origin_document_id=invoice_id
    )
    assert sales.issue(avoir_id).status_code == 200
    # Avoir TTC 3 540 000 (mêmes lignes) : solde nul sans aucun règlement.
    facture = sales.get(invoice_id).json()
    assert facture["outstanding_ttc"] == 0
    assert facture["payment_status"] == "paid"
    # Le règlement au TTC intégral est refusé : le solde est déjà couvert.
    refus = _reglement(reglements, invoice_id, 3_540_000)
    assert refus.status_code == 422


def test_refus_hors_solde_et_statuts_interdits(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    tva = _creer_tva(client, company)
    tier = _creer_tier(client, company)
    emise = _facture_emise(sales, client, company, partner_id=tier)
    # Au-delà du solde : 422 (contrôle métier, pas un conflit d'état).
    assert _reglement(reglements, emise, 3_540_001).status_code == 422
    # Brouillon : conflit d'état 409 (le brouillon n'est pas une facture réelle).
    brouillon = _facture_brouillon(sales, tva)
    assert _reglement(reglements, brouillon, 100).status_code == 409
    # Devis et avoir : 422 (un règlement ne s'affecte qu'à une facture).
    devis = _facture_brouillon(sales, doc_kind="quote", partner_id=tier)
    assert _reglement(reglements, devis, 100).status_code == 422
    avoir = _facture_brouillon(
        sales, tva, doc_kind="credit_note", partner_id=tier, origin_document_id=emise
    )
    assert _reglement(reglements, avoir, 100).status_code == 422


def test_facture_annulee_refuse_le_reglement(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    invoice_id = _facture_emise(sales, client, company)
    assert sales.cancel(invoice_id).status_code == 200
    assert _reglement(reglements, invoice_id, 100).status_code == 409


def test_tier_mixte_et_methode_inconnue_refuses(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    a = _facture_emise(sales, client, company)  # tier A
    b = _facture_emise(sales, client, company)  # tier B (helpers créent à chaque fois)
    reponse = reglements.create(
        {
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [
                {"document_id": a, "amount": 100},
                {"document_id": b, "amount": 100},
            ],
        }
    )
    assert reponse.status_code == 422
    assert _reglement(reglements, a, 100, method="BITCOIN").status_code == 422


def test_date_hors_exercice_refusee(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    invoice_id = _facture_emise(sales, client, company)
    reponse = _reglement(reglements, invoice_id, 100, paid_on="2025-12-31")
    assert reponse.status_code == 422


def test_suppression_libere_le_solde_et_journalise(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    invoice_id = _facture_emise(sales, client, company)
    payment_id = _reglement(reglements, invoice_id, 3_540_000).json()["id"]
    assert sales.get(invoice_id).json()["payment_status"] == "paid"
    assert reglements.delete(payment_id).status_code == 204
    assert reglements.get(payment_id).status_code == 404
    facture = sales.get(invoice_id).json()
    assert facture["outstanding_ttc"] == 3_540_000
    assert facture["payment_status"] == "none"
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    actions = [e["action"] for e in (journal["items"] if isinstance(journal, dict) else journal)]
    assert "sales_payment.created" in actions
    assert "sales_payment.deleted" in actions


def test_facture_lettree_ne_s_annule_pas(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    tva = _creer_tva(client, company)
    tier = _creer_tier(client, company)
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    payment_id = _reglement(reglements, invoice_id, 1_000_000).json()["id"]
    # Annulation sans avoir : refusée tant que le règlement existe.
    assert sales.cancel(invoice_id).status_code == 409
    # Avoir annulateur : même interlock.
    avoir_id = _facture_brouillon(
        sales,
        tva,
        doc_kind="credit_note",
        partner_id=tier,
        origin_document_id=invoice_id,
        reverses_document_id=invoice_id,
    )
    assert sales.issue(avoir_id).status_code == 409
    # Après suppression du règlement, les deux chemins redeviennent possibles.
    assert reglements.delete(payment_id).status_code == 204
    assert sales.cancel(invoice_id).status_code == 200


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    mine = Sales(client, _dossier(make_company))
    theirs = Sales(client, _dossier(make_company))
    mes_reglements = Payments(client, mine.company)
    leurs_reglements = Payments(client, theirs.company)
    invoice_id = _facture_emise(mine, client, mine.company)
    payment_id = _reglement(mes_reglements, invoice_id, 100).json()["id"]
    assert theirs.list().json()["items"] == []
    # Le règlement d'un autre dossier est invisible (404, jamais 403).
    assert leurs_reglements.get(payment_id).status_code == 404
    assert leurs_reglements.delete(payment_id).status_code == 404
    # Affecter une facture d'un autre dossier est un 404 : la RLS ne la voit pas.
    assert _reglement(leurs_reglements, invoice_id, 100).status_code == 404
    assert leurs_reglements.aging().json()["grand_total_ttc"] == 0


def test_lecteur_lit_mais_ne_reglemente_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    invoice_id = _facture_emise(sales, client, company)
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(f"/api/v1/companies/{company.id}/payments", headers=headers).status_code == 200
    )
    assert (
        client.get(f"/api/v1/companies/{company.id}/receivables/aging", headers=headers).status_code
        == 200
    )
    reponse = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=headers,
        json={
            "paid_on": "2026-06-15",
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": 100}],
        },
    )
    assert reponse.status_code == 403
    payment_id = _reglement(reglements, invoice_id, 100).json()["id"]
    assert (
        client.delete(
            f"/api/v1/companies/{company.id}/payments/{payment_id}", headers=headers
        ).status_code
        == 403
    )


def test_les_reglements_necrivent_jamais_en_comptabilite(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Pré-requis 4E : aucun chemin des règlements ne génère d'écriture."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    invoice_id = _facture_emise(sales, client, company)
    payment_id = _reglement(reglements, invoice_id, 3_540_000).json()["id"]
    reglements.delete(payment_id)
    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    assert entries.json()["items"] == [], "des écritures sont apparues : règlements → comptabilité"


def test_balance_agee_buckets(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    # Échéances **dynamiques** (demain) : la création refuse une échéance passée,
    # la balance âgée se lit à des `as_of` arbitraires pour placer les buckets —
    # aucun jour calendaire en dur dans ce test (il restait vert jusqu'à la date
    # écrite en dur, puis cassait chaque jour suivant).
    echeance = utcnow().date() + timedelta(days=1)
    echue_1_30 = _facture_emise(sales, client, company, due_on=echeance.isoformat())
    echue_31_60 = _facture_emise(sales, client, company, due_on=echeance.isoformat())
    echue_61_90 = _facture_emise(sales, client, company, due_on=echeance.isoformat())
    echue_90_plus = _facture_emise(sales, client, company, due_on=echeance.isoformat())
    payee = _facture_emise(sales, client, company, due_on=echeance.isoformat())
    _sans_echeance = _facture_emise(sales, client, company)  # due_on NULL : à-échoir
    _reglement(reglements, payee, 3_540_000)
    ttc = 3_540_000
    # as_of arbitraire : chaque facture tombe dans son bucket (la balance âgée
    # se calcule à la date demandée, jamais à la date du jour seulement).
    response = reglements.aging(as_of=(echeance + timedelta(days=93)).isoformat())
    assert response.status_code == 200, response.text
    body = response.json()
    buckets = body["buckets"]
    assert buckets["not_due"] == {"count": 1, "total_ttc": ttc}  # sans échéance
    assert buckets["d1_30"]["count"] == 0
    assert buckets["d31_60"]["count"] == 0
    assert buckets["d61_90"]["count"] == 0
    assert buckets["d90_plus"] == {"count": 4, "total_ttc": 4 * ttc}
    assert body["grand_total_ttc"] == 5 * ttc
    # Règlement partiel : seul le solde restant entre dans le bucket.
    _reglement(reglements, echue_1_30, 540_000)
    _reglement(reglements, echue_31_60, 540_000)
    _reglement(reglements, echue_61_90, 540_000)
    _reglement(reglements, echue_90_plus, 540_000)
    # 31 jours après l'échéance : les quatre soldes partiels tombent en d31_60.
    body = reglements.aging(as_of=(echeance + timedelta(days=31)).isoformat()).json()
    buckets = body["buckets"]
    assert buckets["not_due"] == {"count": 1, "total_ttc": ttc}
    assert buckets["d1_30"] == {"count": 0, "total_ttc": 0}
    assert buckets["d31_60"] == {"count": 4, "total_ttc": 4 * 3_000_000}
    assert body["grand_total_ttc"] == ttc + 4 * 3_000_000


def test_liste_reglements_filtree(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    a = _facture_emise(sales, client, company)
    b = _facture_emise(sales, client, company)
    _reglement(reglements, a, 100, paid_on="2026-06-15")
    _reglement(reglements, b, 200, paid_on="2026-07-15")
    assert reglements.list().json()["total"] == 2
    assert reglements.list(document_id=a).json()["total"] == 1
    assert reglements.list(date_from="2026-07-01").json()["total"] == 1
    assert reglements.list(date_to="2026-06-30").json()["total"] == 1
    assert reglements.list(partner_id=uuid.uuid4()).json()["total"] == 0


def test_reglements_concurrents_sans_excedent(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Course critique du lettrage : vingt règlements concurrents de 1 000 sur
    une facture de TTC 10 000 → exactement dix succès, aucun excédent, solde
    zéro. Chaque fil opère sur une vraie connexion PostgreSQL : le verrou FOR
    UPDATE de la facture sérialise les contrôles de solde."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    reglements = Payments(client, company)
    # Petite facture (exonérée) : TTC exactement 10 000 — la course n'a de sens
    # que si le solde est fini.
    petite = _facture_brouillon(
        sales,
        doc_kind="invoice",
        lines=[
            {
                "label": "Panneau de démonstration",
                "quantity": 1000,
                "unit_price_ht": 10_000,
                "tax_exempt_reason": "Vente exonérée (article du CGI à documenter)",
            }
        ],
    )
    assert sales.issue(petite).status_code == 200
    invoice_id = petite

    resultats: list[str] = []
    verrou = threading.Lock()

    def regler() -> None:
        try:
            reponse = _reglement(reglements, invoice_id, 1_000, paid_on="2026-06-15", method="CASH")
            with verrou:
                resultats.append(str(reponse.status_code))
        except BaseException as exc:  # pragma: no cover - diagnostic de course
            with verrou:
                resultats.append(f"EXC {exc!r}")

    fils = [threading.Thread(target=regler) for _ in range(20)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(30)
        assert not fil.is_alive(), "règlement bloqué > 30 s"

    assert resultats.count("201") == 10, sorted(resultats)
    assert resultats.count("422") == 10, sorted(resultats)
    facture = sales.get(invoice_id).json()
    assert facture["outstanding_ttc"] == 0
    assert facture["payment_status"] == "paid"
    total = sum(
        a["amount"] for p in reglements.list(limit=100).json()["items"] for a in p["allocations"]
    )
    assert total == 10_000, "la somme lettrée dépasse le TTC : fuite de contrôle"
