"""Devis, factures et avoirs (Phase 4B) : numérotation sans trou et cycle de vie.

Cœur de la recette : la numérotation chronologique sans trou exigée par le cahier
des charges — 100 émissions concurrentes = 100 numéros consécutifs — et sa
propriété transactionnelle (un échec APRÈS l'incrément restaure le compteur au
ROLLBACK). Vérifie aussi les calculs HT/TVA/TTC tabulés, le cycle devis → facture,
l'avoir annulateur (facture CANCELLED dans la même transaction), l'isolation par
dossier (RLS), les permissions (le lecteur lit, ne numérote pas) et le garde-fou
comptable : aucune écriture n'est générée par la ventes (Phase 4E le fera avec
validation humaine).

Depuis 4B-bis, les émissions portent la règle dure des mentions fiscales : les
helpers de ce module créent des dossiers et des tiers conformes (NIF/adresse
de l'émetteur, NIU/NCC/adresse du client) — les refus d'émission pour mentions
manquantes sont testés dans test_sales_pdf.py.
"""

import threading
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select, text

import kora.sales.service as sales_service
from kora.accounting.entries import Actor
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.sales import DocumentSequence
from tests.conftest import CompanyFixture

MakeCompany = Callable[..., CompanyFixture]


class Sales:
    """Raccourcis d'appel à l'API ventes pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/sales", headers=headers, json=body)

    def list(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query: dict[str, str] = {k: str(v) for k, v in params.items()}
        return self.client.get(f"{self.base}/sales", headers=headers, params=query)

    def get(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/sales/{document_id}", headers=headers)

    def patch(
        self, document_id: str, body: dict[str, object], company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.patch(f"{self.base}/sales/{document_id}", headers=headers, json=body)

    def delete(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.delete(f"{self.base}/sales/{document_id}", headers=headers)

    def issue(self, document_id: str, issued_on: str | None = None) -> Response:
        body = {"issued_on": issued_on} if issued_on else {}
        return self.client.post(
            f"{self.base}/sales/{document_id}/issue", headers=self.company.headers, json=body
        )

    def send(self, document_id: str) -> Response:
        return self.client.post(
            f"{self.base}/sales/{document_id}/send", headers=self.company.headers
        )

    def decision(self, document_id: str, accepted: bool) -> Response:
        return self.client.post(
            f"{self.base}/sales/{document_id}/decision",
            headers=self.company.headers,
            json={"accepted": accepted},
        )

    def convert(self, document_id: str) -> Response:
        return self.client.post(
            f"{self.base}/sales/{document_id}/convert", headers=self.company.headers
        )

    def cancel(self, document_id: str) -> Response:
        return self.client.post(
            f"{self.base}/sales/{document_id}/cancel", headers=self.company.headers
        )


def _dossier(make_company: MakeCompany) -> CompanyFixture:
    """Dossier émetteur conforme (4B-bis) : NIF et adresse de l'émetteur exigés à
    l'émission d'une facture ou d'un avoir (règle dure des mentions fiscales)."""
    return make_company(
        rccm=f"RCCM-KN-2026-B-{uuid.uuid4().hex[:4].upper()}",
        nif=f"NIF{uuid.uuid4().hex[:10].upper()}",
        address="Ratoma, Conakry",
        phone="+224 600 00 00 00",
    )


def _creer_tier(client: TestClient, company: CompanyFixture, nom: str = "Solar Shop Guinée") -> str:
    """Tier conforme (4B-bis) : NIU/NCC, adresse et RCCM — toutes les mentions
    d'une fiche client commerciale complète (avertissements d'émission vides)."""
    response = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={
            "name": f"{nom}-{uuid.uuid4().hex[:6]}",
            "is_client": True,
            "tax_id": f"NIU{uuid.uuid4().hex[:10].upper()}",
            "rccm": f"RCCM-KN-2026-B-{uuid.uuid4().hex[:4].upper()}",
            "address": "Kaloum, Conakry",
        },
    )
    assert response.status_code == 201, response.text
    partner_id: str = response.json()["id"]
    return partner_id


def _creer_tva(client: TestClient, company: CompanyFixture, bp: int = 1800) -> str:
    response = client.post(
        f"/api/v1/companies/{company.id}/tax-rates",
        headers=company.headers,
        json={
            "code": f"TVA{bp // 100}_{uuid.uuid4().hex[:4].upper()}",
            "label": f"TVA {bp / 100:.0f} %",
            "kind": "TVA",
            "rate_basis_points": bp,
            "valid_from": "2026-01-01",
        },
    )
    assert response.status_code == 201, response.text
    rate_id: str = response.json()["id"]
    return rate_id


def _lignes(tva_id: str | None = None) -> list[dict[str, object]]:
    ligne: dict[str, object] = {
        "label": "Panneau solaire 300 W",
        "quantity": 2500,  # 2,5 en millièmes
        "unit_price_ht": 1_200_000,  # GNF, unités mineures (0 décimale)
    }
    if tva_id:
        ligne["tax_rate_id"] = tva_id
    else:
        ligne["tax_exempt_reason"] = "Vente exonérée (article du CGI à documenter)"
    return [ligne]


def _facture_brouillon(sales: Sales, tva_id: str | None = None, **overrides: object) -> str:
    company = sales.company
    body: dict[str, object] = {
        "doc_kind": "invoice",
        "partner_id": _creer_tier(sales.client, company),
        "lines": _lignes(tva_id),
    }
    body.update(overrides)
    response = sales.create(body)
    assert response.status_code == 201, response.text
    doc_id: str = response.json()["id"]
    return doc_id


def _devis_brouillon(sales: Sales, **overrides: object) -> str:
    """Brouillon de devis (type quote) : numéroté à l'envoi, pas à l'émission."""
    body: dict[str, object] = {"doc_kind": "quote"}
    body.update(overrides)
    return _facture_brouillon(sales, **body)  # type: ignore[arg-type]


def test_brouillon_jamais_numerote(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    document_id = _facture_brouillon(sales, _creer_tva(client, company))
    document = sales.get(document_id).json()
    assert document["status"] == "DRAFT"
    assert document["number"] is None
    assert document["issued_on"] is None
    # Les montants dérivent des lignes : HT 3 000 000, TVA 540 000, TTC 3 540 000.
    assert document["total_ht"] == 3_000_000
    assert document["total_tax"] == 540_000
    assert document["total_ttc"] == 3_540_000


def test_emission_numerote_et_fige_les_mentions(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    document_id = _facture_brouillon(sales, _creer_tva(client, company))
    response = sales.issue(document_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"]["status"] == "ISSUED"
    assert body["document"]["number"] == 1
    assert body["document"]["issued_on"] is not None
    snapshot = body["document"]["partner_snapshot"]
    assert snapshot["nom"].startswith("Solar Shop")
    assert body["document"]["issuer_snapshot"]["nom"].startswith("Société ")


def test_numeros_consecutifs_sequentiels(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    for attendu in (1, 2, 3):
        document_id = _facture_brouillon(sales, _creer_tva(client, company))
        body = sales.issue(document_id).json()
        assert body["document"]["number"] == attendu


def test_compteurs_independants_par_type(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    quote_id = _devis_brouillon(sales)
    # Un devis n'est pas « émis » : il est envoyé, et c'est l'envoi qui le numérote.
    assert sales.issue(quote_id).status_code == 422
    body = sales.send(quote_id).json()
    assert body["document"]["status"] == "SENT"
    assert body["document"]["number"] == 1
    invoice_id = _facture_brouillon(sales, _creer_tva(client, company))
    assert sales.issue(invoice_id).json()["document"]["number"] == 1


def test_brouillons_abandonnes_ne_cree_pas_de_trou(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    a = _facture_brouillon(sales, tva)
    b = _facture_brouillon(sales, tva)
    c = _facture_brouillon(sales, tva)
    d = _facture_brouillon(sales, tva)
    assert sales.delete(b).status_code == 204
    numeros = [sales.issue(x).json()["document"]["number"] for x in (a, c, d)]
    assert numeros == [1, 2, 3]


def test_echec_apres_increment_restaure_le_compteur(
    client: TestClient, make_company: MakeCompany, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Propriété transactionnelle du sans-trou : une erreur déclenchée APRÈS
    l'incrément du compteur (ici, par le journal d'audit) laisse la transaction
    en échec ; son ROLLBACK restaure le compteur — le numéro n'est pas consommé."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    premier = _facture_brouillon(sales, tva)
    en_echec = _facture_brouillon(sales, tva)
    suivant = _facture_brouillon(sales, tva)
    assert sales.issue(premier).json()["document"]["number"] == 1

    def audit_en_feu(*args: object, **kwargs: object) -> None:
        raise RuntimeError("échec simulé après l'incrément")

    monkeypatch.setattr(sales_service, "record_event", audit_en_feu)
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        with pytest.raises(RuntimeError):
            sales_service.issue_document(
                session, Actor(company.id, company.owner.id), uuid.UUID(en_echec)
            )
    # La fermeture du contexte a annulé la transaction : le compteur est restauré.
    monkeypatch.undo()

    assert sales.issue(suivant).json()["document"]["number"] == 2


def test_cent_emissions_concurrentes_sans_trou(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Critère d'acceptation du PLAN : 100 créations concurrentes = 100 numéros
    consécutifs. Les brouillons sont pré-créés (hors course), puis émis par des
    fils sur des connexions PostgreSQL réelles : le verrou FOR UPDATE du compteur
    sérialise les attributions, et l'ensemble exact {1..100} est vérifié."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    ids = [_facture_brouillon(sales, tva) for _ in range(100)]

    erreurs: list[str] = []
    verrou = threading.Lock()

    def emettre(document_id: str) -> None:
        try:
            with get_sessionmaker()() as session:
                bind_tenant(session, company.id)
                session.execute(text("SET LOCAL lock_timeout = '30s'"))
                actor = Actor(company.id, company.owner.id)
                document, _ = sales_service.issue_document(session, actor, uuid.UUID(document_id))
                assert document.number is not None
        except BaseException as exc:
            with verrou:
                erreurs.append(f"{document_id}: {exc!r}")

    pas = 20
    for debut in range(0, len(ids), pas):
        lot = ids[debut : debut + pas]
        fils = [threading.Thread(target=emettre, args=(x,)) for x in lot]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(30)
            assert not fil.is_alive(), "émission bloquée > 30 s"

    assert erreurs == []
    numeros = [sales.get(x).json()["number"] for x in ids]
    assert set(numeros) == set(range(1, 101)), f"trous ou doublons : {sorted(numeros)[:5]}…"
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        compteur = session.execute(
            select(DocumentSequence).where(
                DocumentSequence.tenant_id == company.id,
                DocumentSequence.doc_kind == "invoice",
            )
        ).scalar_one()
        assert compteur.last_number == 100


def test_cycle_devis_conversion_facture(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    _creer_tva(client, company)
    quote_id = _devis_brouillon(sales)
    assert sales.decision(quote_id, True).status_code == 409  # pas encore envoyé
    assert sales.send(quote_id).status_code == 200
    assert sales.decision(quote_id, True).status_code == 200
    response = sales.convert(quote_id)
    assert response.status_code == 201, response.text
    facture = response.json()
    assert facture["status"] == "DRAFT"
    assert facture["number"] is None
    assert facture["origin_document_id"] == quote_id
    assert facture["total_ht"] == 3_000_000
    assert sales.issue(facture["id"]).json()["document"]["number"] == 1


def test_devis_refuse_conserve_son_numero(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    quote_id = _devis_brouillon(sales)
    sales.send(quote_id)
    body = sales.decision(quote_id, False).json()
    assert body["status"] == "REJECTED"
    assert body["number"] == 1
    # Un second devis envoyé prend le numéro suivant : jamais de réutilisation.
    assert sales.send(_devis_brouillon(sales)).json()["document"]["number"] == 2


def test_avoir_partiel_sur_facture_emise(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    tier = _creer_tier(client, company)
    invoice_id = _facture_brouillon(sales, tva, partner_id=tier)
    sales.issue(invoice_id)
    avoir_id = _facture_brouillon(
        sales,
        tva,
        doc_kind="credit_note",
        partner_id=tier,
        origin_document_id=invoice_id,
        lines=[
            {
                "label": "Retour d'un panneau",
                "quantity": 500,
                "unit_price_ht": 1_200_000,
                "tax_rate_id": tva,
            }
        ],
    )
    body = sales.issue(avoir_id).json()
    assert body["document"]["doc_kind"] == "credit_note"
    assert body["document"]["number"] == 1  # séquence propre aux avoirs
    assert body["document"]["total_ht"] == 600_000
    assert body["document"]["total_tax"] == 108_000
    # La facture reste émise : l'avoir est partiel.
    assert sales.get(invoice_id).json()["status"] == "ISSUED"


def test_avoir_annulateur_cloture_la_facture(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    tier = _creer_tier(client, company)
    invoice_id = _facture_brouillon(sales, tva, partner_id=tier)
    sales.issue(invoice_id)
    numero = sales.get(invoice_id).json()["number"]
    avoir_id = _facture_brouillon(
        sales,
        tva,
        doc_kind="credit_note",
        partner_id=tier,
        origin_document_id=invoice_id,
        reverses_document_id=invoice_id,
    )
    sales.issue(avoir_id)
    facture = sales.get(invoice_id).json()
    assert facture["status"] == "CANCELLED"
    assert facture["number"] == numero  # conservé, jamais réutilisé
    # Une seconde annulation totale est refusée dès la création (unicité du reverses).
    second = _facture_brouillon_ou_erreur(
        sales,
        tva,
        doc_kind="credit_note",
        partner_id=tier,
        origin_document_id=invoice_id,
        reverses_document_id=invoice_id,
    )
    assert second in (409, 422)


def _facture_brouillon_ou_erreur(
    sales: Sales, tva_id: str | None = None, **overrides: object
) -> int:
    company = sales.company
    body: dict[str, object] = {
        "doc_kind": "invoice",
        "partner_id": _creer_tier(sales.client, company),
        "lines": _lignes(tva_id),
    }
    body.update(overrides)
    return sales.create(body).status_code


def test_facture_annulee_directement_conserve_le_numero(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    invoice_id = _facture_brouillon(sales, tva)
    sales.issue(invoice_id)
    assert sales.cancel(invoice_id).json()["status"] == "CANCELLED"
    suivant = sales.issue(_facture_brouillon(sales, tva)).json()["document"]["number"]
    assert suivant == 2


def test_patch_brouillon_et_refus_apres_emission(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    patched = sales.patch(
        document_id,
        {
            "notes": "Paiement à 30 jours",
            "lines": [
                {
                    "label": "Installation",
                    "quantity": 1000,
                    "unit_price_ht": 500_000,
                    "tax_rate_id": tva,
                }
            ],
        },
    ).json()
    assert patched["total_ht"] == 500_000
    assert patched["total_tax"] == 90_000
    assert len(patched["lines"]) == 1
    sales.issue(document_id)
    assert sales.patch(document_id, {"notes": "x"}).status_code == 409
    assert sales.delete(document_id).status_code == 409


def test_calculs_arrondis_tabules(client: TestClient, make_company: MakeCompany) -> None:
    """Cas exacts : 3,333 × 1 999 - 15 % → HT 5 663 ; TVA 18 % → 1 019 (arrondi
    comptable demi-point vers +∞), TTC 6 682."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(
        sales,
        tva,
        lines=[
            {
                "label": "Heures de maintenance",
                "quantity": 3333,
                "unit_price_ht": 1999,
                "discount_bp": 1500,
                "tax_rate_id": tva,
            }
        ],
    )
    document = sales.get(document_id).json()
    assert document["total_ht"] == 5663
    assert document["total_tax"] == 1019
    assert document["total_ttc"] == 6682


def test_taux_ou_exoneration_exigee(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    ni_taux_ni_motif = {"lines": [{"label": "x", "quantity": 1000, "unit_price_ht": 100}]}
    response = sales.create(
        {"doc_kind": "invoice", "partner_id": _creer_tier(client, company), **ni_taux_ni_motif}
    )
    assert response.status_code == 422
    taux_futur = client.post(
        f"/api/v1/companies/{company.id}/tax-rates",
        headers=company.headers,
        json={
            "code": f"TVAFUT_{uuid.uuid4().hex[:4].upper()}",
            "label": "TVA future",
            "kind": "TVA",
            "rate_basis_points": 1800,
            "valid_from": "2027-01-01",
        },
    ).json()["id"]
    response = sales.create(
        {
            "doc_kind": "invoice",
            "partner_id": _creer_tier(client, company),
            "lines": [
                {"label": "x", "quantity": 1000, "unit_price_ht": 100, "tax_rate_id": taux_futur}
            ],
        }
    )
    assert response.status_code == 422


def test_avoir_sans_origine_ou_tier_different_refuse(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    response = sales.create(
        {
            "doc_kind": "credit_note",
            "partner_id": _creer_tier(client, company),
            "lines": _lignes(tva),
        }
    )
    assert response.status_code == 422
    invoice_id = _facture_brouillon(sales, tva)
    tier_autre = _creer_tier(client, company, nom="Autre client")
    response = sales.create(
        {
            "doc_kind": "credit_note",
            "partner_id": tier_autre,
            "origin_document_id": invoice_id,
            "lines": _lignes(tva),
        }
    )
    assert response.status_code == 422


def test_echeance_avant_emission_refusee(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    assert sales.patch(document_id, {"due_on": "2026-01-01"}).status_code == 200
    # L'échéance (1er janvier) est antérieure à l'émission du jour : refusée.
    response = sales.issue(document_id)
    assert response.status_code == 422
    assert "échéance" in response.json()["detail"].lower()


def test_emission_hors_exercice_refusee(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    response = sales.issue(document_id, issued_on="2025-12-31")
    assert response.status_code == 422


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    mine = Sales(client, _dossier(make_company))
    theirs = Sales(client, _dossier(make_company))
    tva = _creer_tva(mine.client, mine.company)
    document_id = _facture_brouillon(mine, tva)
    assert theirs.list().json()["items"] == []
    assert theirs.get(document_id).status_code == 404
    assert theirs.patch(document_id, {"notes": "x"}).status_code == 404


def test_lecteur_lit_mais_ne_numerote_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert client.get(f"/api/v1/companies/{company.id}/sales", headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/sales/{document_id}/issue",
            headers=headers,
            json={},
        ).status_code
        == 403
    )
    tier_id = _creer_tier(client, company)
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/sales",
            headers=headers,
            json={
                "doc_kind": "invoice",
                "partner_id": tier_id,
                "lines": [{"label": "x", "quantity": 1000, "unit_price_ht": 100}],
            },
        ).status_code
        == 403
    )


def test_le_module_ventes_necrit_jamais_en_comptabilite(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Pré-requis 4E : aucun chemin du module ventes ne génère d'écriture."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    tier = _creer_tier(client, company)
    quote_id = _devis_brouillon(sales, partner_id=tier)
    sales.send(quote_id)
    sales.decision(quote_id, True)
    invoice_id = sales.convert(quote_id).json()["id"]
    sales.issue(invoice_id)
    avoir_id = _facture_brouillon(
        sales, tva, doc_kind="credit_note", partner_id=tier, origin_document_id=invoice_id
    )
    sales.issue(avoir_id)
    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    assert entries.json()["items"] == [], "des écritures sont apparues : ventes → comptabilité"


def test_audit_trace_les_transitions(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    document_id = _facture_brouillon(sales, tva)
    sales.issue(document_id)
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    events = journal["items"] if isinstance(journal, dict) else journal
    actions = [event["action"] for event in events]
    assert "sales_document.created" in actions
    assert "sales_document.issued" in actions


def test_liste_filtree_par_type_et_statut(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    tva = _creer_tva(client, company)
    invoice_id = _facture_brouillon(sales, tva)
    sales.issue(invoice_id)
    quote_id = _devis_brouillon(sales)
    sales.send(quote_id)
    brouillon_id = _facture_brouillon(sales, tva)
    factures = sales.list(kind="invoice").json()
    assert factures["total"] == 2  # l'émise + le brouillon ; le devis n'est pas une facture
    emis = sales.list(status="ISSUED").json()
    assert [i["id"] for i in emis["items"]] == [invoice_id]
    tous = sales.list().json()
    assert tous["total"] == 3
    assert brouillon_id in {i["id"] for i in tous["items"]}
