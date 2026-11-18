"""Relances de factures échues (Phase 4D).

Recette : une relance est un rappel documenté et immuable adressé au client
d'une facture ÉMISE, ÉCHUE (échéance passée à la date du rappel) et non soldée.
Le niveau (1re, 2e relance…) est compté par le service sous verrou FOR UPDATE de
la facture — jamais saisi ; une même facture ne reçoit qu'une relance par jour
(unicité en base — deux courses concurrentes se sérialisent sur ce contraignant,
traduit en 409). Vérifie aussi les refus (brouillon, annulée, devis, avoir,
facture soldée, tier sans email, date future), les filtres de l'historique,
l'immutabilité (aucune suppression ni modification dans le contrat), l'isolation
RLS, les permissions, le journal d'audit, l'email réellement composé depuis
l'état persisté (adresse figée au moment de l'envoi) et le garde-fou comptable :
aucune écriture n'est générée par les relances (Phase 4E le fera).

Convention temporelle : une facture est créée ÉMISE avec une échéance à J+10
(pas de due_on passé à la création — règle 4B) ; les relances partent de J+30
(horloge déplacée par time-machine, jetons réémis au jour du rappel) — le retard
est donc de 20 jours, quel que soit le jour d'exécution de la suite.
"""

import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta

import time_machine
from fastapi.testclient import TestClient
from httpx2 import Response

from kora.models.common import utcnow
from tests.conftest import CompanyFixture, Mailbox
from tests.test_sales import (
    Sales,
    _creer_tva,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]

JOURS_ECHEANCE = 10  # échéance à J+10 (futur autorisé à la création)
JOURS_RAPPEL = 30  # rappel à J+30 : échéance passée de 20 jours
RETARD = JOURS_RAPPEL - JOURS_ECHEANCE


def _jour_iso(jours: int) -> str:
    """Date ISO à {jours} jours d'aujourd'hui (base des reminded_on)."""
    return (utcnow().date() + timedelta(days=jours)).isoformat()


@contextmanager
def _au_jour(
    client: TestClient, company: CompanyFixture, jours: int = JOURS_RAPPEL
) -> Iterator[str]:
    """Déplace l'horloge à J+{jours} (le jour d'un rappel) et réémet les jetons :
    l'accès de session ne survit pas à un saut de 30 jours (TTL 900 s). À la
    sortie, l'horloge étant revenue, les jetons sont de nouveau réémis : un jeton
    émis dans le futur (iat à J+30) est rejeté à l'heure réelle."""
    with time_machine.travel(utcnow() + timedelta(days=jours)):
        company.headers = company.owner.headers(client)
        yield _jour_iso(0)
    company.headers = company.owner.headers(client)


class Reminders:
    """Raccourcis d'appel à l'API relances pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def overdue(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query = {k: str(v) for k, v in params.items() if v is not None}
        return self.client.get(f"{self.base}/receivables/overdue", headers=headers, params=query)

    def list(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query = {k: str(v) for k, v in params.items() if v is not None}
        return self.client.get(f"{self.base}/reminders", headers=headers, params=query)

    def create(
        self,
        body: dict[str, object],
        company: CompanyFixture | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        entetes = headers if headers is not None else (company or self.company).headers
        return self.client.post(f"{self.base}/reminders", headers=entetes, json=body)

    def resend(self, reminder_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.post(f"{self.base}/reminders/{reminder_id}/resend", headers=headers)


def _tier_avec_email(
    client: TestClient, company: CompanyFixture, *, email: str | None = "client@exemple.gn"
) -> str:
    """Tier client avec (ou sans) adresse email : sans email, pas de relance."""
    response = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={
            "name": f"Client Relancé-{uuid.uuid4().hex[:6]}",
            "is_client": True,
            "tax_id": f"NIU{uuid.uuid4().hex[:10].upper()}",
            "rccm": f"RCCM-KN-2026-B-{uuid.uuid4().hex[:4].upper()}",
            "address": "Kaloum, Conakry",
            "email": email,
        },
    )
    assert response.status_code == 201, response.text
    partner_id: str = response.json()["id"]
    return partner_id


def _facture_echue(
    sales: Sales,
    client: TestClient,
    company: CompanyFixture,
    *,
    partner_id: str | None = None,
    jours_echeance: int = JOURS_ECHEANCE,
    total: int | None = None,
) -> str:
    """Facture ÉMISE avec échéance à J+{jours_echeance} (futur : la règle 4B
    interdit un due_on passé à la création — les tests déplacent l'horloge pour
    la rendre échue). TTC 3 540 000 (lignes 4B : 3 000 000 HT + 540 000 TVA) ou
    TTC imposé. Le tier client a une adresse email par défaut : relançable dès
    que l'échéance est passée."""
    tva = _creer_tva(client, company)
    overrides: dict[str, object] = {"due_on": _jour_iso(jours_echeance)}
    overrides["partner_id"] = partner_id or _tier_avec_email(client, company)
    if total is not None:
        overrides["lines"] = [
            {
                "label": "Panneau de démonstration",
                "quantity": 1000,
                "unit_price_ht": total,
                "tax_exempt_reason": "Vente exonérée (article du CGI à documenter)",
            }
        ]
    invoice_id = _facture_brouillon(sales, tva, **overrides)
    body = sales.issue(invoice_id).json()
    assert body["document"]["status"] == "ISSUED", body
    return invoice_id


def _relance(
    reminders_api: Reminders, invoice_id: str, jour: str, note: str | None = None
) -> Response:
    body: dict[str, object] = {"document_id": invoice_id, "reminded_on": jour}
    if note is not None:
        body["note"] = note
    return reminders_api.create(body)


def test_facture_echue_listee_puis_niveau_suivant(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    tier = _tier_avec_email(client, company)
    invoice_id = _facture_echue(sales, client, company, partner_id=tier)
    echue_2 = _facture_echue(sales, client, company, jours_echeance=JOURS_ECHEANCE + 5)

    # Candidates à J+30 : la facture à échéance J+10 (retard 20 jours) précède
    # celle à J+15 (retard 15 jours) — du retard le plus ancien au plus récent.
    body = relances.overdue(as_of=_jour_iso(JOURS_RAPPEL)).json()
    assert body["as_of"] == _jour_iso(JOURS_RAPPEL)
    items = {i["document_id"]: i for i in body["items"]}
    assert set(items) == {invoice_id, echue_2}
    item = items[invoice_id]
    assert item["number"] == 1
    assert item["partner_id"] == tier
    assert item["partner_email"] == "client@exemple.gn"
    assert item["outstanding_ttc"] == 3_540_000
    assert item["days_late"] == RETARD
    assert item["reminders_count"] == 0
    assert item["next_level"] == 1
    assert items[echue_2]["days_late"] == RETARD - 5

    with _au_jour(client, company) as jour:
        response = _relance(relances, invoice_id, jour)
        assert response.status_code == 201, response.text
        relance = response.json()["reminder"]
        assert response.json()["email_queued"] is True
        assert relance["level"] == 1
        assert relance["channel"] == "EMAIL"
        assert relance["email_to"] == "client@exemple.gn"
        assert relance["document_id"] == invoice_id

        # Historique visible : reminders_count et next_level avancent.
        body = relances.overdue(as_of=jour).json()
        item = {i["document_id"]: i for i in body["items"]}[invoice_id]
        assert item["reminders_count"] == 1
        assert item["next_level"] == 2
        facture = sales.get(invoice_id).json()
        assert facture["reminders_count"] == 1


def test_niveaux_1_puis_2_et_unicite_quotidienne(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    invoice_id = _facture_echue(sales, client, company)

    with _au_jour(client, company) as jour1:
        premiere = _relance(relances, invoice_id, jour1, note="Merci de régler sous 8 jours.")
        assert premiere.status_code == 201, premiere.text
        assert premiere.json()["reminder"]["level"] == 1
        assert premiere.json()["reminder"]["note"] == "Merci de régler sous 8 jours."

        # Même jour : refusé 409 (une relance par facture et par jour).
        doublon = _relance(relances, invoice_id, jour1)
        assert doublon.status_code == 409, doublon.text

    with _au_jour(client, company, JOURS_RAPPEL + 1) as jour2:
        # Jour suivant : niveau 2 — compté par le service, jamais saisi.
        seconde = _relance(relances, invoice_id, jour2)
        assert seconde.status_code == 201, seconde.text
        assert seconde.json()["reminder"]["level"] == 2

        total = relances.list().json()
        assert total["total"] == 2
        # La plus récente d'abord.
        assert [r["level"] for r in total["items"]] == [2, 1]


def test_refus_pas_echue_soldee_et_statuts_interdits(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    tva = _creer_tva(client, company)
    tier = _tier_avec_email(client, company)

    # Pas encore échue à la date du rappel : rappel avant l'échéance (J+5),
    # puis rappel le jour même de l'échéance (J+10) — les deux refusés.
    future = _facture_echue(sales, client, company, jours_echeance=JOURS_ECHEANCE + 40)
    with _au_jour(client, company, 5) as jour_avant:
        assert _relance(relances, future, jour_avant).status_code == 422
    with _au_jour(client, company, JOURS_ECHEANCE) as jour_echeance:
        assert _relance(relances, future, jour_echeance).status_code == 422

    # Facture soldée (avoir intégral) : pas de relance.
    soldee = _facture_echue(sales, client, company, partner_id=tier)
    avoir = _facture_brouillon(
        sales, tva, doc_kind="credit_note", partner_id=tier, origin_document_id=soldee
    )
    assert sales.issue(avoir).status_code == 200
    with _au_jour(client, company) as jour:
        assert _relance(relances, soldee, jour).status_code == 422

        # Brouillon : conflit d'état (jamais émise au client).
        brouillon = _facture_brouillon(sales, tva)
        assert _relance(relances, brouillon, jour).status_code == 409

        # Facture annulée : conflit d'état.
        annulee = _facture_echue(sales, client, company)
        assert sales.cancel(annulee).status_code == 200
        assert _relance(relances, annulee, jour).status_code == 409

        # Devis et avoir : une relance ne vise qu'une facture — le contrôle du
        # type précède celui du statut : brouillon ou émis, c'est 422.
        devis = _facture_brouillon(sales, doc_kind="quote", partner_id=tier)
        assert _relance(relances, devis, jour).status_code == 422
        avoir_seul = _facture_brouillon(
            sales, tva, doc_kind="credit_note", partner_id=tier, origin_document_id=soldee
        )
        assert _relance(relances, avoir_seul, jour).status_code == 422


def test_tier_sans_email_et_date_future_refuses(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    # Date du rappel dans le futur : refusée avant même de charger la facture.
    invoice_id = _facture_echue(sales, client, company)
    assert _relance(relances, invoice_id, _jour_iso(100)).status_code == 422

    # Pas d'adresse email sur le tier : compléter la fiche avant de relancer.
    sans_email = _tier_avec_email(client, company, email=None)
    echue = _facture_echue(sales, client, company, partner_id=sans_email)
    with _au_jour(client, company) as jour:
        assert _relance(relances, echue, jour).status_code == 422


def test_historique_filtre_et_immutabilite(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    tier_a = _tier_avec_email(client, company)
    tier_b = _tier_avec_email(client, company)
    a = _facture_echue(sales, client, company, partner_id=tier_a)
    b = _facture_echue(sales, client, company, partner_id=tier_b)
    with _au_jour(client, company) as jour:
        assert _relance(relances, a, jour).status_code == 201
        assert _relance(relances, b, jour).status_code == 201

    # Filtres : par facture, par tier, par fenêtre de dates, pagination.
    par_facture = relances.list(document_id=a).json()
    assert par_facture["total"] == 1
    assert par_facture["items"][0]["document_id"] == a
    par_tier = relances.list(partner_id=tier_b).json()
    assert par_tier["total"] == 1
    assert par_tier["items"][0]["partner_id"] == tier_b
    fenetre = relances.list(
        date_from=_jour_iso(JOURS_RAPPEL), date_to=_jour_iso(JOURS_RAPPEL)
    ).json()
    assert fenetre["total"] == 2
    page = relances.list(limit=1, offset=1).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1

    # Immuable : un email envoyé ne se « désend » pas — ni suppression ni
    # édition : le contrat lui-même n'expose aucune route DELETE ni PATCH.
    contract = client.get("/api/openapi.json").json()
    chemins_relances = {
        chemin: set(methods)
        for chemin, methods in contract["paths"].items()
        if "/reminders" in chemin and "/resend" not in chemin
    }
    assert chemins_relances, "aucune route relance dans le contrat"
    for chemin, methods in chemins_relances.items():
        # La politique de relance automatique (lot 2) est un réglage upsert :
        # PUT autorisé sur ce seul chemin — les relances elles-mêmes restent
        # en création seule, et DELETE/PATCH sont interdits partout.
        attendu = (
            {"get", "post", "put"} if chemin.endswith("/reminders/policy") else {"get", "post"}
        )
        assert methods <= attendu, (chemin, methods)
    # Une relance visée hors du dossier est un 404, jamais un 403.
    autres = Reminders(client, _dossier(make_company))
    assert autres.resend(par_facture["items"][0]["id"]).status_code == 404


def test_renvoi_journalise_et_email_recompose(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Après une file injoignable (ou un échec d'envoi), le renvoi re-programme
    l'email depuis l'état persisté : la relance reste inchangée."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    tier = _tier_avec_email(client, company, email="relance-client@exemple.gn")
    invoice_id = _facture_echue(sales, client, company, partner_id=tier)
    with _au_jour(client, company) as jour:
        created = _relance(relances, invoice_id, jour, note="Dernier rappel avant recouvrement.")
        assert created.status_code == 201, created.text
        assert created.json()["email_queued"] is True
        reminder_id = created.json()["reminder"]["id"]

        emails = mailbox.deliver()
        assert any(e.to == "relance-client@exemple.gn" for e in emails)

        resend = relances.resend(reminder_id)
        assert resend.status_code == 200, resend.text
        assert resend.json()["email_queued"] is True
        emails = mailbox.deliver()
        # Le renvoi repart vers l'adresse figée à la création (traçabilité).
        assert any(e.to == "relance-client@exemple.gn" for e in emails)
        # La relance elle-même n'a pas changé (immuable).
        historique = relances.list(document_id=invoice_id).json()
        assert historique["total"] == 1
        assert historique["items"][0]["level"] == 1
        assert historique["items"][0]["note"] == "Dernier rappel avant recouvrement."


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    mine = Sales(client, _dossier(make_company))
    theirs = Sales(client, _dossier(make_company))
    mes_relances = Reminders(client, mine.company)
    leurs_relances = Reminders(client, theirs.company)
    invoice_id = _facture_echue(mine, client, mine.company)
    with _au_jour(client, mine.company) as jour:
        # Le second dossier suit la même horloge : ses jetons aussi sont réémis.
        theirs.company.headers = theirs.company.owner.headers(client)
        reminder_id = _relance(mes_relances, invoice_id, jour).json()["reminder"]["id"]
        assert _relance(leurs_relances, invoice_id, jour).status_code == 404

    # Sortie du voyage : les jetons des deux dossiers sont réémis à l'heure réelle.
    theirs.company.headers = theirs.company.owner.headers(client)
    assert leurs_relances.list().json()["items"] == []
    assert leurs_relances.overdue(as_of=_jour_iso(JOURS_RAPPEL)).json()["items"] == []
    # Le rappel d'un autre dossier est invisible : 404 (la RLS ne le voit pas).
    assert leurs_relances.resend(reminder_id).status_code == 404


def test_lecteur_lit_mais_ne_relance_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    invoice_id = _facture_echue(sales, client, company)
    with _au_jour(client, company) as jour:
        headers = lecteur.headers(client)  # type: ignore[attr-defined]
        reponse = client.post(
            f"/api/v1/companies/{company.id}/reminders",
            headers=headers,
            json={"document_id": invoice_id, "reminded_on": jour},
        )
        assert reponse.status_code == 403
        reminder_id = _relance(relances, invoice_id, jour).json()["reminder"]["id"]
        assert (
            client.post(
                f"/api/v1/companies/{company.id}/reminders/{reminder_id}/resend", headers=headers
            ).status_code
            == 403
        )


def test_les_relances_necrivent_jamais_en_comptabilite(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Pré-requis 4E : aucun chemin des relances ne génère d'écriture."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    invoice_id = _facture_echue(sales, client, company)
    with _au_jour(client, company) as jour:
        reminder_id = _relance(relances, invoice_id, jour).json()["reminder"]["id"]
        relances.resend(reminder_id)
    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    assert entries.json()["items"] == [], "des écritures sont apparues : relances → comptabilité"


def test_journalise_creation_et_renvoi(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    invoice_id = _facture_echue(sales, client, company)
    with _au_jour(client, company) as jour:
        reminder_id = _relance(relances, invoice_id, jour).json()["reminder"]["id"]
        relances.resend(reminder_id)
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    actions = [e["action"] for e in (journal["items"] if isinstance(journal, dict) else journal)]
    assert "sales_reminder.created" in actions
    assert "sales_reminder.resent" in actions


def test_course_concurrente_une_seule_relance_par_jour(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Course critique : vingt relances concurrentes le même jour sur une même
    facture → exactement une création (201), dix-neuf conflits (409). L'unicité
    (dossier, facture, jour) en base est le juge de paix ; le verrou FOR UPDATE
    de la facture sérialise le comptage des niveaux."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    invoice_id = _facture_echue(sales, client, company, total=10_000)

    with _au_jour(client, company) as jour:
        resultats: list[str] = []
        verrou = threading.Lock()

        def relancer() -> None:
            try:
                reponse = _relance(relances, invoice_id, jour)
                with verrou:
                    resultats.append(str(reponse.status_code))
            except BaseException as exc:  # pragma: no cover - diagnostic de course
                with verrou:
                    resultats.append(f"EXC {exc!r}")

        fils = [threading.Thread(target=relancer) for _ in range(20)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(30)
            assert not fil.is_alive(), "relance bloquée > 30 s"

        assert resultats.count("201") == 1, sorted(resultats)
        assert resultats.count("409") == 19, sorted(resultats)
        historique = relances.list().json()
        assert historique["total"] == 1
        assert historique["items"][0]["level"] == 1
        assert historique["items"][0]["reminded_on"] == jour


def test_email_de_relance_compose_depuis_etat_persiste(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """L'email part dans le worker (jamais pendant la requête) : composé depuis
    l'état persisté — adresse du tier au moment de l'envoi, montant en unités
    d'affichage, message personnalisé inclus."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    relances = Reminders(client, company)
    tier = _tier_avec_email(client, company, email="awa@client.gn")
    invoice_id = _facture_echue(sales, client, company, partner_id=tier)
    echeance = _jour_iso(JOURS_ECHEANCE)  # figée avant le voyage temporel
    with _au_jour(client, company) as jour:
        response = _relance(
            relances,
            invoice_id,
            jour,
            note="Merci de régler par Orange Money au +224 600 00 00 00.",
        )
        assert response.status_code == 201, response.text
        assert response.json()["email_queued"] is True

        emails = mailbox.deliver()
        [email] = [e for e in emails if e.to == "awa@client.gn"]
        assert "Relance n°1" in email.subject
        assert "FAC-2026-00001" in email.subject
        texte = email.text
        assert "3 540 000" in texte
        assert "GNF" in texte
        assert f"{RETARD} jour(s)" in texte  # jours de retard
        assert echeance in texte  # échéance
        assert "Orange Money" in texte  # message personnalisé
        assert "Kora Finance" in texte
