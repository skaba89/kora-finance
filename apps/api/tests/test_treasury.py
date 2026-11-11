"""Trésorerie 3A : comptes financiers et mouvements, via l'API.

Chaque mouvement crée, dans une même transaction, une écriture validée du journal de
trésorerie et sa trace immuable ; le solde d'un compte financier est toujours la
somme des lignes validées de son compte comptable lié — la trésorerie ne peut pas
diverger du grand livre. Les tests vérifient les contraintes métier, l'immutabilité
portée par la base (migration 0011), l'isolation par dossier, les permissions, le
journal d'audit et la sérialisation réelle des mouvements concurrents.
"""

import threading
from collections.abc import Callable
from queue import Queue

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import text

from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from tests.conftest import CompanyFixture
from tests.ledger_helpers import account_id as gl_account_id_of

MakeCompany = Callable[..., CompanyFixture]


class Treasury:
    """Raccourcis d'appel à l'API trésorerie pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def create_account(
        self, body: dict[str, object], company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/treasury/accounts", headers=headers, json=body)

    def accounts(self, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/treasury/accounts", headers=headers)

    def movements(self, account_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(
            f"{self.base}/treasury/accounts/{account_id}/movements", headers=headers
        )

    def movement(
        self, account_id: str, body: dict[str, object], company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/treasury/accounts/{account_id}/movements", headers=headers, json=body
        )

    def transfer(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/treasury/transfers", headers=headers, json=body)


def _banque_body(
    client: TestClient, company: CompanyFixture, **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "BCRG principal",
        "kind": "BANQUE",
        "gl_account_id": gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "521"
        ),
        "account_number_masked": "****-1234",
    }
    body.update(overrides)
    return body


def _caisse_body(
    client: TestClient, company: CompanyFixture, **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Caisse du siège",
        "kind": "CAISSE",
        "gl_account_id": gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "571"
        ),
    }
    body.update(overrides)
    return body


def _mm_body(client: TestClient, company: CompanyFixture, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Orange Money ventes",
        "kind": "MOBILE_MONEY",
        "operator": "ORANGE_MONEY_GN",
        "gl_account_id": gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "521"
        ),
        "account_number_masked": "+224 6** *** 456",
    }
    body.update(overrides)
    return body


def _movement_body(
    client: TestClient, company: CompanyFixture, **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "kind": "DEPOT",
        "amount": "1500000",
        "movement_date": "2026-03-15",
        "label": "Dépôt du capital initial",
        "counterpart_account_id": gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "101"
        ),
    }
    body.update(overrides)
    return body


# --- Création de comptes


def test_creation_compte_banque(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    response = treasury.create_account(_banque_body(client, company))
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["kind"] == "BANQUE"
    assert data["gl_account_number"] == "521"
    assert data["balance"] == "0"
    assert data["is_active"] is True


def test_compte_mobile_money_exige_operateur(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    sans_operateur = _mm_body(client, company, operator=None)
    assert treasury.create_account(sans_operateur).status_code == 422
    mauvais = _mm_body(client, company, operator="orange money")  # minuscules et espaces
    assert treasury.create_account(mauvais).status_code == 422


def test_banque_exige_classe_52_et_caisse_classe_57(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    mauvaise_caisse = _caisse_body(
        client,
        company,
        gl_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "521"
        ),
    )
    assert treasury.create_account(mauvaise_caisse).status_code == 422
    mauvaise_banque = _banque_body(
        client,
        company,
        gl_account_id=gl_account_id_of(
            client, f"/api/v1/companies/{company.id}", company.headers, "571"
        ),
    )
    assert treasury.create_account(mauvaise_banque).status_code == 422


def test_nom_duplique_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    assert treasury.create_account(_banque_body(client, company)).status_code == 201
    assert treasury.create_account(_banque_body(client, company)).status_code == 409


# --- Dépôts, retraits, frais


def test_depot_cree_ecriture_validee_et_solde(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    account = treasury.create_account(_banque_body(client, company)).json()
    response = treasury.movement(account["id"], _movement_body(client, company))
    assert response.status_code == 201, response.text
    listed = treasury.movements(account["id"]).json()
    assert listed["total"] == 1
    assert listed["balance"] == "1500000"
    row = listed["items"][0]
    assert row["direction"] == "DEBIT"
    assert row["counterpart_number"] == "101"
    assert row["entry_number"] == 1  # première écriture validée du journal BQ
    # La contrepartie du dépôt de capital apparaît dans le grand livre : l'écriture
    # est bien une écriture comptable ordinaire, contrôlée par les tests du module
    # entries (équilibre, comptes actifs, exercice ouvert).


def test_retrait_et_frais_diminuent_le_solde(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    account = treasury.create_account(_banque_body(client, company)).json()
    assert treasury.movement(account["id"], _movement_body(client, company)).status_code == 201
    retrait = treasury.movement(
        account["id"],
        _movement_body(
            client,
            company,
            kind="RETRAIT",
            amount="200000",
            label="Retrait pour payer un fournisseur",
            counterpart_account_id=gl_account_id_of(
                client, f"/api/v1/companies/{company.id}", company.headers, "401"
            ),
        ),
    )
    assert retrait.status_code == 201, retrait.text
    frais = treasury.movement(
        account["id"],
        _movement_body(
            client,
            company,
            kind="FRAIS",
            amount="25000",
            label="Frais de tenue de compte",
            counterpart_account_id=gl_account_id_of(
                client, f"/api/v1/companies/{company.id}", company.headers, "631"
            ),
        ),
    )
    assert frais.status_code == 201, frais.text
    listed = treasury.movements(account["id"]).json()
    assert listed["balance"] == str(1500000 - 200000 - 25000)
    assert listed["total"] == 3
    assert [row["direction"] for row in listed["items"]] == ["DEBIT", "CREDIT", "CREDIT"]


def test_virement_interne_relie_deux_mouvements(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    banque = treasury.create_account(_banque_body(client, company)).json()
    caisse = treasury.create_account(_caisse_body(client, company)).json()
    assert treasury.movement(banque["id"], _movement_body(client, company)).status_code == 201
    response = treasury.transfer(
        {
            "source_account_id": banque["id"],
            "target_account_id": caisse["id"],
            "amount": "300000",
            "movement_date": "2026-03-20",
            "label": "Approvisionnement caisse",
        }
    )
    assert response.status_code == 201, response.text
    data = response.json()
    source = treasury.movements(banque["id"]).json()
    cible = treasury.movements(caisse["id"]).json()
    assert source["balance"] == "1200000"
    assert cible["balance"] == "300000"
    assert [row["direction"] for row in source["items"]] == ["DEBIT", "CREDIT"]
    assert [row["direction"] for row in cible["items"]] == ["DEBIT"]
    # Les deux mouvements portent la même écriture et se référencent l'un l'autre.
    entries = {row["entry_id"] for row in source["items"]} | {
        row["entry_id"] for row in cible["items"]
    }
    assert len(entries) == 2  # dépôt du capital + virement
    assert source["items"][-1]["entry_id"] == data["entry_id"]


def test_virement_sur_meme_compte_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    banque = treasury.create_account(_banque_body(client, company)).json()
    response = treasury.transfer(
        {
            "source_account_id": banque["id"],
            "target_account_id": banque["id"],
            "amount": "100000",
            "movement_date": "2026-03-20",
            "label": "Virement vers soi-même",
        }
    )
    assert response.status_code == 422


# --- Contrôles portés par la base (migration 0011)


def test_mouvements_immuables(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    account = treasury.create_account(_banque_body(client, company)).json()
    assert treasury.movement(account["id"], _movement_body(client, company)).status_code == 201
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        mouvement_id = session.execute(
            text("SELECT id FROM financial_movements LIMIT 1")
        ).scalar_one()
        for sql in (
            "UPDATE financial_movements SET amount = 999999 WHERE id = :id",
            "DELETE FROM financial_movements WHERE id = :id",
        ):
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            with pytest.raises(Exception, match="interdit"):
                session.execute(text(sql), {"id": str(mouvement_id)})
            session.rollback()


def test_periode_verrouillee_refuse_mouvement(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    account = treasury.create_account(_banque_body(client, company)).json()
    # Verrouillage de la période jusqu'à fin avril.
    lock = client.post(
        f"/api/v1/companies/{company.id}/fiscal-years/{_year_id(client, company)}/lock",
        headers=company.headers,
        json={"locked_until": "2026-04-30"},
    )
    assert lock.status_code == 200, lock.text
    response = treasury.movement(account["id"], _movement_body(client, company))
    assert response.status_code == 422
    assert "verrouill" in response.json()["detail"]


def _year_id(client: TestClient, company: CompanyFixture) -> str:
    years = client.get(
        f"/api/v1/companies/{company.id}/fiscal-years", headers=company.headers
    ).json()
    result: str = years[0]["id"]
    return result


# --- Isolation et permissions


def test_isolation_tenant(client: TestClient, make_company: MakeCompany) -> None:
    mine = Treasury(client, make_company())
    theirs = Treasury(client, make_company())
    account = mine.create_account(_banque_body(client, mine.company)).json()
    # Le compte d'un autre dossier n'est ni visible ni utilisable.
    assert theirs.accounts().json()["items"] == []
    assert theirs.movements(account["id"]).status_code == 404
    assert theirs.movement(account["id"], _movement_body(client, theirs.company)).status_code == 404


def test_lecteur_peut_lire_mais_pas_ecrire(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    account = treasury.create_account(_banque_body(client, company)).json()
    # Le lecteur voit les comptes et les mouvements…
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(f"/api/v1/companies/{company.id}/treasury/accounts", headers=headers).status_code
        == 200
    )
    # …mais ne peut rien écrire.
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/treasury/accounts",
            headers=headers,
            json=_banque_body(client, company),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/treasury/accounts/{account['id']}/movements",
            headers=headers,
            json=_movement_body(client, company),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/companies/{company.id}/treasury/transfers",
            headers=headers,
            json={
                "source_account_id": account["id"],
                "target_account_id": account["id"],
                "amount": "1",
                "movement_date": "2026-03-15",
                "label": "Refusé",
            },
        ).status_code
        == 403
    )


# --- Journal d'audit


def test_mouvements_traces_dans_le_journal_audit(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    treasury = Treasury(client, company)
    banque = treasury.create_account(_banque_body(client, company)).json()
    caisse = treasury.create_account(_caisse_body(client, company)).json()
    treasury.movement(banque["id"], _movement_body(client, company))
    treasury.transfer(
        {
            "source_account_id": banque["id"],
            "target_account_id": caisse["id"],
            "amount": "100000",
            "movement_date": "2026-03-16",
            "label": "Retrait espèces",
        }
    )
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    events = journal["items"] if isinstance(journal, dict) else journal
    actions = [event["action"] for event in events]
    assert "treasury.account.created" in actions
    assert "treasury.movement.recorded" in actions
    assert "treasury.transfer.recorded" in actions


# --- Concurrence


def test_mouvements_concurrents_se_serialisent(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Deux dépôts simultanés sur le même compte : les deux aboutissent, sérialisés
    par le verrou de ligne du compte financier, et le solde final est exact."""
    company = make_company()
    treasury = Treasury(client, company)
    account = treasury.create_account(_banque_body(client, company)).json()
    results: Queue[object] = Queue()

    def depoter() -> None:
        results.put(treasury.movement(account["id"], _movement_body(client, company)))

    threads = [threading.Thread(target=depoter) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    statuses = []
    while not results.empty():
        statuses.append(results.get().status_code)  # type: ignore[attr-defined]
    assert sorted(statuses) == [201, 201]
    listed = treasury.movements(account["id"]).json()
    assert listed["balance"] == "3000000"
    assert listed["total"] == 2
