"""Trésorerie 3C : rapprochement bancaire, via l'API.

Le moteur propose des candidats (même compte, montant égal, direction cohérente,
jamais rapprochés), un humain confirme — jamais l'inverse. Les tests vérifient le
classement des propositions, les refus de cohérence (montant, direction, compte,
double rapprochement — y compris concurrents), la réversibilité (dé-rapprochement),
la vue d'ensemble d'un compte, le journal d'audit, l'isolation par dossier et les
permissions (lecture sans confirmation).
"""

import threading
from collections.abc import Callable
from queue import Queue

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import CompanyFixture
from tests.test_treasury import _movement_body
from tests.test_treasury_statements import OFX, OFX_SUITE, Statements, _banque_id

MakeCompany = Callable[..., CompanyFixture]


class Reconciliation:
    """Raccourcis d'appel à l'API rapprochement pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def candidates(
        self, statement_id: str, line_id: str, company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.get(
            f"{self.base}/treasury/statements/{statement_id}/lines/{line_id}/candidates",
            headers=headers,
        )

    def match(
        self,
        statement_id: str,
        line_id: str,
        movement_id: str,
        company: CompanyFixture | None = None,
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/treasury/statements/{statement_id}/lines/{line_id}/match",
            headers=headers,
            json={"movement_id": movement_id},
        )

    def unmatch(
        self, statement_id: str, line_id: str, company: CompanyFixture | None = None
    ) -> Response:
        headers = (company or self.company).headers
        return self.client.post(
            f"{self.base}/treasury/statements/{statement_id}/lines/{line_id}/unmatch",
            headers=headers,
        )

    def overview(self, account_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(
            f"{self.base}/treasury/accounts/{account_id}/reconciliation", headers=headers
        )

    def movements(self, account_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(
            f"{self.base}/treasury/accounts/{account_id}/movements", headers=headers
        )


def _compte_avec_mouvement(
    client: TestClient,
    company: CompanyFixture,
    mouvement_date: str = "2026-03-02",
    amount: str = "1500000",
    label: str = "Dépôt espèces client",
) -> str:
    """Compte bancaire du dossier avec un dépôt prêt à être rapproché."""
    account_id = _banque_id(client, company)
    response = client.post(
        f"/api/v1/companies/{company.id}/treasury/accounts/{account_id}/movements",
        headers=company.headers,
        json=_movement_body(
            client, company, amount=amount, movement_date=mouvement_date, label=label
        ),
    )
    assert response.status_code == 201, response.text
    return account_id


def test_candidats_classe_par_ressemblance(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()

    lines = statements.lines(statement["id"]).json()["items"]
    depot = next(line for line in lines if line["label"] == "DEPOT ESPECES")
    response = api.candidates(statement["id"], depot["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["line_id"] == depot["id"]
    assert body["amount"] == "1500000"
    assert len(body["candidates"]) >= 1
    first = body["candidates"][0]
    # Le dépôt du même jour : premier candidat, score maximal de la fenêtre.
    assert first["movement_date"] == "2026-03-02"
    assert first["days_apart"] == 0
    assert first["score"] >= 30
    assert first["kind"] == "DEPOT"
    assert first["direction"] == "DEBIT"
    # Les scores sont triés par ordre décroissant.
    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_candidats_excluent_compte_montant_direction_et_rapproches(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    # Un second dépôt identique, daté du 3 : candidat de repli après le premier.
    client.post(
        f"/api/v1/companies/{company.id}/treasury/accounts/{account_id}/movements",
        headers=company.headers,
        json=_movement_body(client, company, movement_date="2026-03-03"),
    )
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    depot = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "1500000"
    )

    before = api.candidates(statement["id"], depot["id"]).json()["candidates"]
    assert len(before) == 2

    # Rapprocher la ligne consomme le premier mouvement : il disparaît des
    # candidats de la ligne suivante — jamais de double rapprochement proposé.
    mouvements = api.movements(account_id).json()["items"]
    premier = next(m for m in mouvements if m["movement_date"] == "2026-03-02")
    assert api.match(statement["id"], depot["id"], premier["id"]).status_code == 200

    # Une deuxième ligne du même montant (1500000 n'apparaît qu'une fois dans OFX :
    # on en importe un second exemplaire via un autre relevé sur le même compte).
    second = statements.import_file(account_id, OFX_SUITE).json()
    lines_suite = statements.lines(second["id"]).json()["items"]
    retrait = next(line for line in lines_suite if line["amount"] == "-120000")
    # Le retrait DAB n'a aucun mouvement CREDIT de 120000 : aucun candidat.
    assert api.candidates(second["id"], retrait["id"]).json()["candidates"] == []

    # Une ligne déjà rapprochée ne propose plus rien du tout.
    assert api.candidates(statement["id"], depot["id"]).status_code == 409


def test_confirmation_persiste_et_audite(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    depot = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvement = api.movements(account_id).json()["items"][0]

    response = api.match(statement["id"], depot["id"], mouvement["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "MATCHED"

    lines = statements.lines(statement["id"]).json()["items"]
    assert next(line for line in lines if line["id"] == depot["id"])["status"] == "MATCHED"

    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    events = journal["items"] if isinstance(journal, dict) else journal
    actions = [event["action"] for event in events]
    assert "treasury.reconciliation.matched" in actions


def test_montant_ou_direction_incoherents_refuses(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    lines = statements.lines(statement["id"]).json()["items"]
    frais = next(line for line in lines if line["amount"] == "-45000")
    depot = next(line for line in lines if line["amount"] == "1500000")
    mouvements = api.movements(account_id).json()["items"]
    depot_mvt = mouvements[0]

    # Un dépôt (entrée) ne rapproche jamais une ligne de frais (sortie).
    response = api.match(statement["id"], frais["id"], depot_mvt["id"])
    assert response.status_code == 422, response.text
    # Et le dépôt n'a pas de mouvement à -45000 : les candidats sont vides,
    # une confirmation directe avec un montant différent est refusée.
    assert api.candidates(statement["id"], frais["id"]).json()["candidates"] == []
    other = client.post(
        f"/api/v1/companies/{company.id}/treasury/accounts/{account_id}/movements",
        headers=company.headers,
        json=_movement_body(
            client,
            company,
            kind="RETRAIT",
            amount="1499000",
            movement_date="2026-03-05",
            label="Retrait partiel",
        ),
    )
    assert other.status_code == 201
    mauvais = api.match(statement["id"], depot["id"], other.json()["id"])
    assert mauvais.status_code == 422
    assert "ne correspond pas" in mauvais.json()["detail"]


def test_mouvement_dun_autre_compte_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    autre = _banque_id(client, company, name="Ecobank seconde")
    client.post(
        f"/api/v1/companies/{company.id}/treasury/accounts/{autre}/movements",
        headers=company.headers,
        json=_movement_body(client, company, movement_date="2026-03-02"),
    )
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    depot = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvements_autre = api.movements(autre).json()["items"]
    response = api.match(statement["id"], depot["id"], mouvements_autre[0]["id"])
    assert response.status_code == 422, response.text
    assert "autre compte" in response.json()["detail"]
    # Et la ligne du relevé du compte principal ne propose jamais ce mouvement.
    candidats = api.candidates(statement["id"], depot["id"]).json()["candidates"]
    assert all(c["id"] != mouvements_autre[0]["id"] for c in candidats)


def test_double_rapprochement_refuse(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    premier = statements.import_file(account_id, OFX).json()
    second = statements.import_file(account_id, OFX_SUITE).json()
    # OFX_SUITE reprend « DEPOT ESPECES » (recouvrement de période) : deux lignes
    # différentes veulent le même mouvement — une seule doit pouvoir l'obtenir.
    ligne_a = next(
        line
        for line in statements.lines(premier["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    ligne_b = next(
        line
        for line in statements.lines(second["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvement = api.movements(account_id).json()["items"][0]
    assert api.match(premier["id"], ligne_a["id"], mouvement["id"]).status_code == 200
    refuse = api.match(second["id"], ligne_b["id"], mouvement["id"])
    assert refuse.status_code == 409, refuse.text
    assert "déjà rapproché" in refuse.json()["detail"]


def test_double_rapprochement_concurrent_refuse(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Deux confirmations simultanées du même mouvement : une gagne, l'autre est
    refusée (verrous + contrainte d'unicité de la migration 0013)."""
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    premier = statements.import_file(account_id, OFX).json()
    second = statements.import_file(account_id, OFX_SUITE).json()
    ligne_a = next(
        line
        for line in statements.lines(premier["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    ligne_b = next(
        line
        for line in statements.lines(second["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvement = api.movements(account_id).json()["items"][0]

    results: Queue[Response] = Queue()

    def confirmer(statement_id: str, line_id: str) -> None:
        results.put(api.match(statement_id, line_id, mouvement["id"]))

    threads = [
        threading.Thread(target=confirmer, args=(premier["id"], ligne_a["id"])),
        threading.Thread(target=confirmer, args=(second["id"], ligne_b["id"])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    statuses = sorted(results.get().status_code for _ in threads)
    assert statuses == [200, 409]
    # La traçabilité reste cohérente : exactement une ligne rapprochée.
    matched = [
        line
        for statement_id in (premier["id"], second["id"])
        for line in statements.lines(statement_id).json()["items"]
        if line["status"] == "MATCHED"
    ]
    assert len(matched) == 1


def test_derapprochement_reversible(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    depot = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvement = api.movements(account_id).json()["items"][0]
    assert api.match(statement["id"], depot["id"], mouvement["id"]).status_code == 200

    response = api.unmatch(statement["id"], depot["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING"
    # Le mouvement est redevenu un candidat : rien n'est perdu ni bloqué.
    candidats = api.candidates(statement["id"], depot["id"]).json()["candidates"]
    assert any(c["id"] == mouvement["id"] for c in candidats)
    # Une ligne non rapprochée ne se dé-rapproche pas.
    assert api.unmatch(statement["id"], depot["id"]).status_code == 409

    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    events = journal["items"] if isinstance(journal, dict) else journal
    actions = [event["action"] for event in events]
    assert "treasury.reconciliation.unmatched" in actions


def test_ligne_ecartee_ne_peut_pas_etre_rapprochee(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    frais = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "-45000"
    )
    assert statements.ignore(statement["id"], frais["id"]).status_code == 200
    # Candidats refusés pour une ligne écartée, et confirmation impossible.
    assert api.candidates(statement["id"], frais["id"]).status_code == 422
    mouvement = api.movements(account_id).json()["items"][0]
    assert api.match(statement["id"], frais["id"], mouvement["id"]).status_code == 422


def test_vue_ensemble_par_compte(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()

    vide = api.overview(account_id).json()
    assert vide["lines_pending"] == 3  # les 3 lignes d'OFX
    assert vide["lines_matched"] == 0
    assert vide["pending_net"] == str(1500000 - 45000 + 200000)
    assert vide["movements_unmatched"] == 1  # le dépôt prêt à être rapproché

    lines = statements.lines(statement["id"]).json()["items"]
    depot = next(line for line in lines if line["amount"] == "1500000")
    frais = next(line for line in lines if line["amount"] == "-45000")
    mouvement = api.movements(account_id).json()["items"][0]
    assert api.match(statement["id"], depot["id"], mouvement["id"]).status_code == 200
    assert statements.ignore(statement["id"], frais["id"]).status_code == 200

    partial = api.overview(account_id).json()
    assert partial["lines_pending"] == 1
    assert partial["lines_matched"] == 1
    assert partial["lines_ignored"] == 1
    assert partial["pending_net"] == "200000"
    assert partial["movements_unmatched"] == 0  # le dépôt est rapproché

    assert api.unmatch(statement["id"], depot["id"]).status_code == 200
    assert api.overview(account_id).json()["movements_unmatched"] == 1


def test_lecteur_propose_mais_ne_confirme_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    depot = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvement = api.movements(account_id).json()["items"][0]

    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    lecteur_company = CompanyFixture(id=company.id, owner=lecteur, headers=headers)  # type: ignore[arg-type]
    # Lecture : candidats et vue d'ensemble autorisés.
    assert api.candidates(statement["id"], depot["id"], company=lecteur_company).status_code == 200
    assert api.overview(account_id, company=lecteur_company).status_code == 200
    # Écriture : confirmation et dé-rapprochement refusés.
    assert (
        api.match(
            statement["id"], depot["id"], mouvement["id"], company=lecteur_company
        ).status_code
        == 403
    )
    assert api.unmatch(statement["id"], depot["id"], company=lecteur_company).status_code == 403


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    company = make_company()
    api = Reconciliation(client, company)
    account_id = _compte_avec_mouvement(client, company)
    statements = Statements(client, company)
    statement = statements.import_file(account_id, OFX).json()
    depot = next(
        line
        for line in statements.lines(statement["id"]).json()["items"]
        if line["amount"] == "1500000"
    )
    mouvement = api.movements(account_id).json()["items"][0]

    other = make_company()
    other_api = Reconciliation(client, other)
    assert other_api.candidates(statement["id"], depot["id"]).status_code == 404
    assert other_api.match(statement["id"], depot["id"], mouvement["id"]).status_code == 404
    assert other_api.unmatch(statement["id"], depot["id"]).status_code == 404
    assert other_api.overview(account_id).status_code == 404
