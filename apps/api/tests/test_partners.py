"""Référentiel des tiers (Phase 4A) : fiches clients et fournisseurs, via l'API.

Vérifie les règles métier (au moins un sens client/fournisseur, unicité du nom
insensible à la casse, préfixes de comptes de tiers 411x/401x), l'isolation par
dossier (RLS), les permissions (le lecteur lit, n'écrit pas), le PATCH partiel,
les filtres de liste, la désactivation (jamais de suppression) et le journal
d'audit. Aucun postage comptable n'est déclenché par le référentiel : c'est le
pré-requis de la facturation (4B) et des règlements (4C).
"""

from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import CompanyFixture
from tests.ledger_helpers import account_id as gl_account_id_of

MakeCompany = Callable[..., CompanyFixture]


class Partners:
    """Raccourcis d'appel à l'API référentiel pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/partners", headers=headers, json=body)

    def list(
        self,
        company: CompanyFixture | None = None,
        **params: object,
    ) -> Response:
        headers = (company or self.company).headers
        query: dict[str, str | bool] = {
            k: v if isinstance(v, bool) else str(v) for k, v in params.items()
        }
        return self.client.get(f"{self.base}/partners", headers=headers, params=query)

    def get(self, partner_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/partners/{partner_id}", headers=headers)

    def patch(
        self, partner_id: str, body: dict[str, object], company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.patch(f"{self.base}/partners/{partner_id}", headers=headers, json=body)


def _client_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Solar Shop Guinée",
        "is_client": True,
        "tax_id": "NIU-2026-04512",
        "rccm": "RCCM/GN-KA-2026-B-04512",
        "address": "Kipé, Commune de Ratoma, Conakry",
        "email": "contact@solarshop.gn",
        "phone": "+224 622 00 00 00",
    }
    body.update(overrides)
    return body


def test_creation_client(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    response = partners.create(_client_body())
    assert response.status_code == 201, response.text
    tier = response.json()
    assert tier["name"] == "Solar Shop Guinée"
    assert tier["is_client"] is True
    assert tier["is_supplier"] is False
    assert tier["tax_id"] == "NIU-2026-04512"
    assert tier["is_active"] is True
    # La fiche est relisible individuellement.
    assert partners.get(tier["id"]).json()["name"] == "Solar Shop Guinée"


def test_client_et_fournisseur_simultanes(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    response = partners.create(
        {"name": "Marché Kaloum SARL", "is_client": True, "is_supplier": True}
    )
    assert response.status_code == 201
    tier = response.json()
    assert tier["is_client"] is True
    assert tier["is_supplier"] is True


def test_sens_obligatoire(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    response = partners.create({"name": "Ni client ni fournisseur"})
    assert response.status_code == 422, response.text


def test_nom_unique_insensible_casse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    assert partners.create(_client_body()).status_code == 201
    response = partners.create(_client_body(name="solar shop guinée"))
    assert response.status_code == 409, response.text
    # Deux dossiers distincts peuvent porter le même nom de tier.
    other = Partners(client, make_company())
    assert other.create(_client_body()).status_code == 201


def test_espaces_de_trimmed(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    response = partners.create(_client_body(name="  Solar Shop Guinée  "))
    assert response.status_code == 201
    assert response.json()["name"] == "Solar Shop Guinée"


def test_compte_client_411_accepte(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    body = _client_body(
        default_client_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "411"
        ),
        default_supplier_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "401"
        ),
    )
    assert partners.create(body).status_code == 201


def test_sous_compte_client_4111_accepte(client: TestClient, make_company: MakeCompany) -> None:
    """Les sous-comptes créés par le dossier (4111…) pré-remplissent aussi la fiche."""
    company = make_company()
    partners = Partners(client, company)
    # Un sous-compte 4111 créé par le dossier (le plan de référence n'a que 411).
    sub = client.post(
        f"/api/v1/companies/{company.id}/accounts",
        headers=company.headers,
        json={"number": "4111", "label": "Clients Guinée"},
    )
    assert sub.status_code == 201, sub.text
    body = _client_body(default_client_account_id=sub.json()["id"])
    assert partners.create(body).status_code == 201


def test_compte_client_mauvaise_classe_refuse(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Un compte 521 (banque) ne peut pas pré-remplir un compte client 411x."""
    company = make_company()
    partners = Partners(client, company)
    body = _client_body(
        default_client_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "521"
        )
    )
    response = partners.create(body)
    assert response.status_code == 422, response.text
    assert "411" in response.json()["detail"]


def test_compte_fournisseur_mauvais_prefixe_refuse(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    partners = Partners(client, company)
    body = _client_body(
        is_client=True,
        is_supplier=True,
        default_supplier_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "411"
        ),
    )
    response = partners.create(body)
    assert response.status_code == 422, response.text
    assert "401" in response.json()["detail"]


def test_compte_dun_autre_dossier_refuse(client: TestClient, make_company: MakeCompany) -> None:
    mine = Partners(client, make_company())
    theirs = Partners(client, make_company())
    body = _client_body(
        default_client_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{theirs.company.id}", theirs.company.headers, "411"
        )
    )
    assert mine.create(body).status_code == 404


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    mine = Partners(client, make_company())
    theirs = Partners(client, make_company())
    tier = mine.create(_client_body()).json()
    # Le tier d'un autre dossier n'est ni visible ni adressable.
    assert theirs.list().json()["items"] == []
    assert theirs.get(tier["id"]).status_code == 404
    assert theirs.patch(tier["id"], {"is_active": False}).status_code == 404


def test_lecteur_lit_mais_necrit_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = make_company()
    partners = Partners(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    tier = partners.create(_client_body()).json()
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(f"/api/v1/companies/{company.id}/partners", headers=headers).status_code == 200
    )
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/partners", headers=headers, json=_client_body()
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/companies/{company.id}/partners/{tier['id']}",
            headers=headers,
            json={"is_active": False},
        ).status_code
        == 403
    )


def test_patch_partiel_ne_touche_que_le_champ_fourni(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    partners = Partners(client, company)
    tier = partners.create(_client_body()).json()
    response = partners.patch(tier["id"], {"phone": "+224 664 11 22 33"})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["phone"] == "+224 664 11 22 33"
    # Tout le reste est intact.
    assert updated["name"] == "Solar Shop Guinée"
    assert updated["tax_id"] == "NIU-2026-04512"
    assert updated["is_active"] is True


def test_patch_vide_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    tier = partners.create(_client_body()).json()
    assert partners.patch(tier["id"], {}).status_code == 422


def test_patch_sens_vide_refuse(client: TestClient, make_company: MakeCompany) -> None:
    """Un tier client ne peut pas devenir « ni client ni fournisseur »."""
    company = make_company()
    partners = Partners(client, company)
    tier = partners.create(_client_body()).json()
    response = partners.patch(tier["id"], {"is_client": False})
    assert response.status_code == 422, response.text


def test_desactivation_et_filtre(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    actif = partners.create(_client_body()).json()
    inactif = partners.create(_client_body(name="Ancien client")).json()
    partners.patch(inactif["id"], {"is_active": False})
    # Jamais de suppression : la fiche reste lisible.
    assert partners.get(inactif["id"]).json()["is_active"] is False
    tous = partners.list().json()
    assert tous["total"] == 2
    actifs = partners.list(active=True).json()
    assert actifs["total"] == 1
    assert [i["id"] for i in actifs["items"]] == [actif["id"]]


def test_liste_filtres_et_recherche(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    partners.create(_client_body())
    partners.create({"name": "Fournisseur Kaloum", "is_supplier": True, "tax_id": "NIU-777"})
    partners.create(
        {"name": "Boutique Madina", "is_client": True, "is_supplier": True, "tax_id": "NIU-888"}
    )
    clients = partners.list(kind="CLIENT").json()
    assert clients["total"] == 2
    fournisseurs = partners.list(kind="FOURNISSEUR").json()
    assert fournisseurs["total"] == 2
    # Recherche par fragment du nom…
    par_nom = partners.list(q="kaloum").json()
    assert par_nom["total"] == 1
    assert par_nom["items"][0]["name"] == "Fournisseur Kaloum"
    # …ou par NIU.
    par_niu = partners.list(q="NIU-888").json()
    assert par_niu["total"] == 1
    assert par_niu["items"][0]["name"] == "Boutique Madina"
    # Pagination.
    page = partners.list(limit=2, offset=0).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    page2 = partners.list(limit=2, offset=2).json()
    assert len(page2["items"]) == 1


def test_tiers_traces_dans_le_journal_audit(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    partners = Partners(client, company)
    tier = partners.create(_client_body()).json()
    partners.patch(tier["id"], {"address": "Sandervalia, Conakry"})
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    events = journal["items"] if isinstance(journal, dict) else journal
    actions = [event["action"] for event in events]
    assert "partner.created" in actions
    assert "partner.updated" in actions


def test_le_referentiel_necrit_jamais_en_comptabilite(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Créer des tiers ne crée aucune écriture : le référentiel n'est qu'un
    paramétrage, la comptabilité ne bouge pas (pré-requis 4B/4E)."""
    company = make_company()
    partners = Partners(client, company)
    partners.create(_client_body())
    partners.create({"name": "Fournisseur Kaloum", "is_supplier": True})
    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    body = entries.json()
    assert body["items"] == [], f"des écritures sont apparues : {body['items'][:3]}"
