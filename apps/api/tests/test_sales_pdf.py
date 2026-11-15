"""PDF conforme des documents de vente et règle dure des mentions (Phase 4B-bis).

La recette porte deux garanties :
- le PDF d'un document numéroté ne consomme que les instantanés figés à la
  numérotation (émetteur, tier, taux, montants) et porte toutes les mentions
  exigées par l'arbitrage KF-16 (raison sociale, NIU/NCC, adresse, montants
  HT / TVA / TTC, référence de l'exercice) — vérifiées par extraction du texte ;
- la règle dure : une facture ou un avoir refuse de naître sans ses mentions
  fiscales (NIU/NCC et adresse du client, NIF et adresse de l'émetteur) — un
  devis, document commercial et non fiscal, reste averti sans être bloqué.
"""

import io
import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.conftest import CompanyFixture
from tests.test_sales import (
    Sales,
    _creer_tva,
    _devis_brouillon,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]


def _pdf(client: TestClient, company: CompanyFixture, document_id: str) -> str:
    """Télécharge le PDF et renvoie son texte extrait (espaces fines normalisées)."""
    response = client.get(
        f"/api/v1/companies/{company.id}/sales/{document_id}/pdf", headers=company.headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(response.content))
    texte = "\n".join(page.extract_text() for page in reader.pages)
    return texte.replace("\u202f", " ").replace("\xa0", " ")


def test_pdf_facture_contient_les_mentions_obligatoires(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    body = sales.issue(document_id).json()
    assert body["warnings"] == []  # dossier et tier conformes : plus aucun avertissement
    texte = _pdf(client, company, document_id)
    emetteur_nom: str = body["document"]["issuer_snapshot"]["nom"]
    assert "FACTURE" in texte
    assert "FAC-2026-00001" in texte  # exercice 2026 (first_fiscal_year du dossier)
    assert emetteur_nom in texte  # raison sociale de l'émetteur (instantané figé)
    assert "RCCM-KN-2026-B" in texte
    assert "NIF" in texte
    assert "Ratoma, Conakry" in texte  # adresse de l'émetteur
    assert "Solar Shop" in texte  # raison sociale du client
    assert "NIU" in texte  # NIU/NCC du client (mention KF-16)
    assert "Kaloum, Conakry" in texte  # adresse du client
    assert "Panneau solaire 300 W" in texte
    assert "2,5" in texte  # quantité en millièmes → affichage
    assert "TVA 18 %" in texte  # taux figé (points de base → pourcentage)
    assert "Total hors taxes" in texte
    assert "3 000 000" in texte
    assert "540 000" in texte
    assert "3 540 000" in texte
    assert "Total toutes taxes comprises" in texte
    assert "Référence de l'exercice : du 01/01/2026 au 31/12/2026" in texte
    assert "montants exprimés en GNF" in texte


def test_pdf_brouillon_refuse(client: TestClient, make_company: MakeCompany) -> None:
    """Un brouillon n'a ni numéro ni mentions figées : pas de PDF."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    response = client.get(
        f"/api/v1/companies/{company.id}/sales/{document_id}/pdf", headers=company.headers
    )
    assert response.status_code == 422
    assert "numérotation" in response.json()["detail"]


def test_pdf_devis_envoye_puis_timbre_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    quote_id = _devis_brouillon(sales)
    sent = sales.send(quote_id).json()
    assert sent["document"]["number"] == 1
    texte = _pdf(client, company, quote_id)
    assert "DEVIS DEV-2026-00001" in texte
    assert "Valable jusqu'au" not in texte  # validité non saisie : mention omise
    sales.decision(quote_id, False)
    texte = _pdf(client, company, quote_id)
    assert "DEVIS REFUSÉ" in texte
    # Un devis refusé conserve son numéro : le PDF reste téléchargeable.


def test_pdf_avoir_annulateur_et_facture_annulee(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    invoice_id = _facture_brouillon(sales, tva)
    sales.issue(invoice_id)
    avoir_id = _facture_brouillon(
        sales,
        tva,
        doc_kind="credit_note",
        partner_id=sales.get(invoice_id).json()["partner_id"],
        origin_document_id=invoice_id,
        reverses_document_id=invoice_id,
    )
    sales.issue(avoir_id)
    texte_avoir = _pdf(client, company, avoir_id)
    assert "AVOIR AV-2026-00001" in texte_avoir
    assert "Annule et remplace la facture FAC-2026-00001" in texte_avoir
    # La facture annulée porte son timbre : document sans valeur, numéro conservé.
    texte_facture = _pdf(client, company, invoice_id)
    assert "FACTURE ANNULÉE" in texte_facture
    assert "FAC-2026-00001" in texte_facture  # numéro conservé, jamais réutilisé


def test_pdf_facture_avec_devis_d_origine(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    _creer_tva(client, company)
    quote_id = _devis_brouillon(sales)
    sales.send(quote_id)
    sales.decision(quote_id, True)
    invoice_id = sales.convert(quote_id).json()["id"]
    sales.issue(invoice_id)
    texte = _pdf(client, company, invoice_id)
    assert "Devis d'origine : DEV-2026-00001" in texte


def test_pdf_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    mine = Sales(client, _dossier(make_company))
    other_company = _dossier(make_company)
    theirs = Sales(client, other_company)
    tva = _creer_tva(mine.client, mine.company)
    document_id = _facture_brouillon(mine, tva)
    mine.issue(document_id)
    response = theirs.client.get(
        f"/api/v1/companies/{other_company.id}/sales/{document_id}/pdf",
        headers=other_company.headers,
    )
    assert response.status_code == 404


def test_pdf_lecteur_peut_telecharger(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., Any]
) -> None:
    """sales:read (tous les rôles du dossier) suffit pour lire un PDF ; la
    numérotation reste réservée à sales:manage (testée en 4B)."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},
    )
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    sales.issue(document_id)
    headers = lecteur.headers(client)
    response = client.get(
        f"/api/v1/companies/{company.id}/sales/{document_id}/pdf", headers=headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_pdf_inscrit_au_journal_d_audit(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    sales.issue(document_id)
    _pdf(client, company, document_id)
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    events = journal["items"] if isinstance(journal, dict) else journal
    exports = [event for event in events if event["action"] == "sales_document.exported"]
    assert len(exports) == 1
    assert exports[0]["entity_type"] == "sales_document"
    assert exports[0]["entity_id"] == document_id
    assert exports[0]["payload"]["numero"] == "FAC-2026-00001"


def test_regles_dures_emission_mentions_manquantes(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Facture et avoir naissent conformes ou ne naissent pas : l'émission est
    refusée (422) avant tout compteur — le devis, document commercial, reste
    averti sans être bloqué."""
    company = make_company()  # dossier sans NIF ni adresse : non conforme
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    # Tier sans NIU/NCC ni adresse : deux mentions fiscales manquantes.
    response = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={"name": f"Client nu-{uuid.uuid4().hex[:6]}", "is_client": True},
    )
    assert response.status_code == 201, response.text
    tier_id: str = response.json()["id"]
    invoice_id = _facture_brouillon(sales, tva, partner_id=tier_id)
    refused = sales.issue(invoice_id)
    assert refused.status_code == 422
    detail: str = refused.json()["detail"]
    assert "NIU/NCC ou NIF du client" in detail
    assert "adresse du client" in detail
    assert "NIF de l'émetteur" in detail
    assert "adresse de l'émetteur" in detail
    # Le document reste un brouillon : corriger les fiches suffit à émettre.
    client.patch(
        f"/api/v1/companies/{company.id}/partners/{tier_id}",
        headers=company.headers,
        json={"tax_id": f"NIU{uuid.uuid4().hex[:10].upper()}", "address": "Dixinn, Conakry"},
    )
    client.patch(
        f"/api/v1/companies/{company.id}",
        headers=company.headers,
        json={"nif": f"NIF{uuid.uuid4().hex[:10].upper()}", "address": "Kaloum, Conakry"},
    )
    emitted = sales.issue(invoice_id)
    assert emitted.status_code == 200, emitted.text
    assert emitted.json()["document"]["number"] == 1
    # Un devis sans les mentions fiscales passe : avertissements, pas de blocage.
    quote_id = _devis_brouillon(sales)
    sent = sales.send(quote_id)
    assert sent.status_code == 200, sent.text
    assert sent.json()["warnings"], "le devis doit porter les avertissements non bloquants"


def test_regles_dures_sans_trou(client: TestClient, make_company: MakeCompany) -> None:
    """Un refus de règle dure ne consomme aucun numéro : la chronologie reste sans trou."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    # Tier conforme : première facture numérotée 1.
    premier = _facture_brouillon(sales, tva)
    assert sales.issue(premier).json()["document"]["number"] == 1
    # Tier sans NIU : l'émission est refusée (le compteur ne bouge pas).
    response = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={"name": f"Client nu-{uuid.uuid4().hex[:6]}", "is_client": True},
    )
    tier_id: str = response.json()["id"]
    refuse = _facture_brouillon(sales, tva, partner_id=tier_id)
    assert sales.issue(refuse).status_code == 422
    # Tier conforme : le numéro suivant est 2, pas 3.
    troisieme = _facture_brouillon(sales, tva)
    assert sales.issue(troisieme).json()["document"]["number"] == 2
