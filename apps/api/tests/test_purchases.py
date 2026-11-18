"""Achats fournisseurs (Phase 4F) : numérotation sans trou et cycle de vie.

Miroir du module ventes : 100 émissions concurrentes = 100 numéros consécutifs
sur la séquence 'supplier_invoice', propriété transactionnelle (un échec APRÈS
l'incrément restaure le compteur au ROLLBACK), cycle brouillon → émission →
annulation (numéro conservé), avoir annulateur (facture CANCELLED dans la même
transaction), règle dure des mentions fiscales (NIU/NCC et adresse du
fournisseur, NIF et adresse de l'émetteur), tier fournisseur exigé, isolation
par dossier (RLS) et permissions (le lecteur lit, ne numérote pas).

Le garde-fou comptable reste vrai : aucune écriture n'est générée par ce module
(la comptabilisation est testée dans test_purchases_accounting.py).
"""

import threading
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select, text

import kora.purchases.service as purchases_service
from kora.accounting.entries import Actor
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.sales import DocumentSequence
from tests.conftest import CompanyFixture, UserFixture
from tests.test_sales import _creer_tier, _creer_tva, _dossier, _lignes

MakeCompany = Callable[..., CompanyFixture]


class Purchases:
    """Raccourcis d'appel à l'API achats pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/purchases", headers=headers, json=body)

    def list(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query: dict[str, str] = {k: str(v) for k, v in params.items()}
        return self.client.get(f"{self.base}/purchases", headers=headers, params=query)

    def get(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/purchases/{document_id}", headers=headers)

    def patch(
        self, document_id: str, body: dict[str, object], company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.patch(f"{self.base}/purchases/{document_id}", headers=headers, json=body)

    def delete(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.delete(f"{self.base}/purchases/{document_id}", headers=headers)

    def issue(self, document_id: str, issued_on: str | None = None) -> Response:
        body = {"issued_on": issued_on} if issued_on else {}
        return self.client.post(
            f"{self.base}/purchases/{document_id}/issue", headers=self.company.headers, json=body
        )

    def cancel(self, document_id: str) -> Response:
        return self.client.post(
            f"{self.base}/purchases/{document_id}/cancel", headers=self.company.headers
        )


def _creer_fournisseur(
    client: TestClient,
    company: CompanyFixture,
    nom: str = "Fournisseur Électrique Guinée",
    *,
    sans_mentions: bool = False,
) -> str:
    """Tier fournisseur conforme : NIU/NCC et adresse (mentions fiscales exigées
    à l'émission d'une facture d'achat — règle dure 4B-bis étendue aux achats).
    sans_mentions=True crée une fiche défaillante (sans NIU) pour tester le
    refus d'émission."""
    payload: dict[str, object] = {
        "name": f"{nom}-{uuid.uuid4().hex[:6]}",
        "is_supplier": True,
        "rccm": f"RCCM-KN-2026-B-{uuid.uuid4().hex[:4].upper()}",
        "address": "Matam, Conakry",
    }
    if not sans_mentions:
        payload["tax_id"] = f"NIU{uuid.uuid4().hex[:10].upper()}"
    response = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    partner_id: str = response.json()["id"]
    return partner_id


def _facture_achat_brouillon(
    purchases: Purchases, tva_id: str | None = None, **overrides: object
) -> str:
    company = purchases.company
    body: dict[str, object] = {
        "doc_kind": "supplier_invoice",
        "partner_id": _creer_fournisseur(purchases.client, company),
        "lines": _lignes(tva_id),
    }
    body.update(overrides)
    response = purchases.create(body)
    assert response.status_code == 201, response.text
    doc_id: str = response.json()["id"]
    return doc_id


def test_brouillon_jamais_numerote(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    doc_id = _facture_achat_brouillon(purchases)
    document = purchases.get(doc_id).json()
    assert document["status"] == "DRAFT"
    assert document["number"] is None
    assert document["issued_on"] is None
    assert document["outstanding_ttc"] is None
    assert document["entry_id"] is None


def test_tier_client_simple_refuse(client: TestClient, make_company: MakeCompany) -> None:
    """Un tier qui n'est pas fournisseur ne peut pas porter une facture d'achat."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    response = purchases.create(
        {
            "doc_kind": "supplier_invoice",
            "partner_id": _creer_tier(client, company),  # client seulement
            "lines": _lignes(tva_id),
        }
    )
    assert response.status_code == 422, response.text
    assert "fournisseur" in response.json()["detail"].lower()


def test_mentions_obligatoires_bloquent_emission(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Règle dure (4B-bis étendue) : sans NIU/NCC du fournisseur, la facture
    d'achat refuse de naître (contrôle avant le compteur : aucune numérotation
    consommée)."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    doc_id = _facture_achat_brouillon(
        purchases, partner_id=_creer_fournisseur(client, company, sans_mentions=True)
    )
    response = purchases.issue(doc_id)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "NIU" in detail
    # Le compteur n'a pas été consommé : l'émission suivante reçoit le numéro 1.
    doc2 = _facture_achat_brouillon(purchases)
    issued = purchases.issue(doc2)
    assert issued.status_code == 200, issued.text
    assert issued.json()["document"]["number"] == 1


def test_cent_emissions_concurrentes_sans_trou(
    client: TestClient, make_company: MakeCompany
) -> None:
    """100 émissions concurrentes de factures fournisseurs distinctes = 100
    numéros consécutifs, de 1 à 100 ; la séquence 'supplier_invoice' est
    indépendante de celle des ventes."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    ids = [_facture_achat_brouillon(purchases, tva_id) for _ in range(100)]

    def emettre(document_id: str) -> None:
        with get_sessionmaker()() as session:
            bind_tenant(session, company.id)
            session.execute(text("SET LOCAL lock_timeout = '30s'"))
            purchases_service.issue_document(
                session, Actor(company.id, company.owner.id), uuid.UUID(document_id)
            )

    for lot in (ids[i : i + 20] for i in range(0, 100, 20)):
        fils = [threading.Thread(target=emettre, args=(x,)) for x in lot]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(30)
            assert not fil.is_alive(), "émission bloquée : la course s'est interbloquée"
    numeros = sorted(purchases.get(doc_id).json()["number"] for doc_id in ids)
    assert numeros == list(range(1, 101))
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        dernier = session.execute(
            select(DocumentSequence).where(
                DocumentSequence.tenant_id == company.id,
                DocumentSequence.doc_kind == "supplier_invoice",
            )
        ).scalar_one()
    assert dernier.last_number == 100


def test_echec_apres_increment_restaure_le_compteur(
    client: TestClient, make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Propriété transactionnelle du sans-trou : une erreur déclenchée APRÈS
    l'incrément du compteur (ici, par le journal d'audit) laisse la transaction
    en échec ; son ROLLBACK restaure le compteur — le numéro n'est pas consommé."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    premier = _facture_achat_brouillon(purchases)
    en_echec = _facture_achat_brouillon(purchases)
    suivant = _facture_achat_brouillon(purchases)
    assert purchases.issue(premier).json()["document"]["number"] == 1

    def audit_en_feu(*args: object, **kwargs: object) -> None:
        raise RuntimeError("échec simulé après l'incrément")

    monkeypatch.setattr(purchases_service, "record_event", audit_en_feu)
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        with pytest.raises(RuntimeError):
            purchases_service.issue_document(
                session, Actor(company.id, company.owner.id), uuid.UUID(en_echec)
            )
    # La fermeture du contexte a annulé la transaction : le compteur est restauré.
    monkeypatch.undo()

    assert purchases.issue(suivant).json()["document"]["number"] == 2


def test_annulation_conserve_le_numero(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    doc1 = _facture_achat_brouillon(purchases, tva_id)
    assert purchases.issue(doc1).status_code == 200
    cancelled = purchases.cancel(doc1)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["number"] == 1, "le numéro est conservé, jamais réutilisé"
    doc2 = _facture_achat_brouillon(purchases, tva_id)
    issued = purchases.issue(doc2)
    assert issued.status_code == 200
    assert issued.json()["document"]["number"] == 2


def test_avoir_annulateur_passe_la_facture_cancellee(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    invoice_id = _facture_achat_brouillon(purchases, tva_id)
    assert purchases.issue(invoice_id).status_code == 200
    invoice = purchases.get(invoice_id).json()
    response = purchases.create(
        {
            "doc_kind": "supplier_credit_note",
            "partner_id": invoice["partner_id"],
            "lines": _lignes(tva_id),
            "origin_document_id": invoice_id,
            "reverses_document_id": invoice_id,
        }
    )
    assert response.status_code == 201, response.text
    avoir_id = response.json()["id"]
    issued = purchases.issue(avoir_id)
    assert issued.status_code == 200, issued.text
    invoice = purchases.get(invoice_id).json()
    assert invoice["status"] == "CANCELLED", "l'avoir annulateur clôt la facture"
    # Un second avoir annulateur est refusé (une facture ne s'annule qu'une fois).
    second = purchases.create(
        {
            "doc_kind": "supplier_credit_note",
            "partner_id": invoice["partner_id"],
            "lines": _lignes(tva_id),
            "origin_document_id": invoice_id,
            "reverses_document_id": invoice_id,
        }
    )
    assert second.status_code in (409, 422), second.text


def test_lecteur_lit_mais_ne_numerote_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., UserFixture]
) -> None:
    company = _dossier(make_company)
    tva_id = _creer_tva(client, company)
    lecteur = make_user()
    invited = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},
    )
    assert invited.status_code in (200, 201), invited.text
    lecteur_headers = lecteur.headers(client)
    # Le lecteur lit.
    assert (
        client.get(f"/api/v1/companies/{company.id}/purchases", headers=lecteur_headers).status_code
        == 200
    )
    # Le lecteur ne crée pas.
    refused = client.post(
        f"/api/v1/companies/{company.id}/purchases",
        headers=lecteur_headers,
        json={
            "doc_kind": "supplier_invoice",
            "partner_id": _creer_tier(client, company),
            "lines": _lignes(tva_id),
        },
    )
    assert refused.status_code == 403, refused.text


def test_isolation_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    """RLS : une facture d'achat d'un dossier est invisible depuis un autre."""
    company_a = _dossier(make_company)
    company_b = _dossier(make_company)
    purchases_a = Purchases(client, company_a)
    purchases_b = Purchases(client, company_b)
    tva_a = _creer_tva(client, company_a)
    doc_id = _facture_achat_brouillon(purchases_a, tva_a)
    assert purchases_b.get(doc_id).status_code == 404
    assert purchases_b.list().json()["total"] == 0


def test_reference_fournisseur_figee_a_emission(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Le numéro imprimé du fournisseur (reference) est saisi sur le brouillon,
    modifiable tant que brouillon, figé à l'émission."""
    company = _dossier(make_company)
    purchases = Purchases(client, company)
    tva_id = _creer_tva(client, company)
    doc_id = _facture_achat_brouillon(purchases, tva_id, reference="FACT-FNS-2026-0017")
    patched = purchases.patch(doc_id, {"reference": "FACT-FNS-2026-0017-BIS"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["reference"] == "FACT-FNS-2026-0017-BIS"
    issued = purchases.issue(doc_id)
    assert issued.status_code == 200
    document = issued.json()["document"]
    assert document["reference"] == "FACT-FNS-2026-0017-BIS", "figée à l'émission"
    # Les instantanés portent les mentions fiscales exigées.
    assert document["partner_snapshot"]["niu"] is not None
    assert document["issuer_snapshot"]["nif"] is not None
