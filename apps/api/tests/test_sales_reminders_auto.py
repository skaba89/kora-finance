"""Relances automatiques configurables (Phase B, lot 2).

Recette : une politique par dossier (upsert audité), un échéancier d'escalade
(offsets en jours de retard, strictement croissants) et une exécution
périodique côté worker qui réutilise TOUTES les règles 4D — facture ÉMISE,
ÉCHUE et non soldée ; niveau compté sous verrou ; unicité (dossier, facture,
jour) en base : un balayage doublé ou une relance manuelle du même jour ne
crée jamais de doublon, et le rattrapage d'une facture déjà profondément en
retard progresse d'un niveau par jour jusqu'au dernier seuil. L'origine est
système (`created_by_user_id` NULL, audit `origine=automatique`) ; l'email part
du worker après le commit ; aucune écriture comptable (garde-fou retesté).

Convention temporelle (héritée de 4D) : une facture est créée ÉMISE avec une
échéance à J+10 ; les exécutions passent `as_of` explicite au worker (J+30 par
défaut) — le retard est de 20 jours, quel que soit le jour d'exécution de la
suite. Seul le test de la chaîne complète (balayage sans `as_of`) déplace
l'horloge par time-machine.
"""

from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx2 import Response

from kora.worker.tasks import run_reminder_policy, scan_automatic_reminders
from tests.conftest import CompanyFixture, Mailbox
from tests.test_sales import Sales, _dossier
from tests.test_sales_reminders import (
    JOURS_RAPPEL,
    Reminders,
    _au_jour,
    _facture_echue,
    _jour_iso,
    _tier_avec_email,
)

MakeCompany = Callable[..., CompanyFixture]
ECHEANCIER = [1, 7, 15]


class Policies:
    """Raccourcis d'appel à l'API politique de relance automatique."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def get(self, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/reminders/policy", headers=headers)

    def put(self, body: dict[str, object], company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.put(f"{self.base}/reminders/policy", headers=headers, json=body)


def _politique(
    policies: Policies,
    company: CompanyFixture,
    *,
    enabled: bool = True,
    offsets: list[int] | None = None,
) -> None:
    """Politique active par défaut (échéancier d'escalade standard)."""
    response = policies.put({"enabled": enabled, "offsets_days": offsets or ECHEANCIER})
    assert response.status_code == 200, response.text


def _execute(mailbox: Mailbox, company: CompanyFixture, as_of_iso: str | None = None) -> None:
    """Enfile puis traite l'exécution de politique du dossier (chemin réel du
    worker : session avec tenant lié, RLS active, emails en file)."""
    if as_of_iso is None:
        run_reminder_policy.send(str(company.id))
    else:
        run_reminder_policy.send(str(company.id), as_of_iso)
    mailbox.deliver()


# --- Politique : réglage (GET/PUT) ---------------------------------------------


def test_defauts_effectifs_sans_reglage(client: TestClient, make_company: MakeCompany) -> None:
    """Sans politique enregistrée : GET renvoie les défauts d'affichage
    (désactivée, échéancier suggéré) — jamais appliqués sans PUT explicite."""
    company = _dossier(make_company)
    body = Policies(client, company).get().json()
    assert body == {"enabled": False, "offsets_days": [1, 7, 15], "updated_at": None}


def test_put_cree_la_politique_get_la_renvoie_audit(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    policies = Policies(client, company)
    _politique(policies, company, offsets=[1, 10])

    body = policies.get().json()
    assert body["enabled"] is True
    assert body["offsets_days"] == [1, 10]
    assert body["updated_at"] is not None

    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    actions = [e["action"] for e in (journal["items"] if isinstance(journal, dict) else journal)]
    assert "sales_reminder_policy.updated" in actions


def test_put_met_a_jour_la_meme_politique(client: TestClient, make_company: MakeCompany) -> None:
    """Upsert : un second PUT corrige l'échéancier sur la même ligne (une
    politique au plus par dossier) et reste audité."""
    company = _dossier(make_company)
    policies = Policies(client, company)
    _politique(policies, company, offsets=[1, 10])
    _politique(policies, company, enabled=False, offsets=[2, 14, 30])

    body = policies.get().json()
    assert body["enabled"] is False
    assert body["offsets_days"] == [2, 14, 30]

    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    items = journal["items"] if isinstance(journal, dict) else journal
    # Journal trié seq DESC : le plus récent d'abord.
    reglages = [e for e in items if e["action"] == "sales_reminder_policy.updated"]
    assert len(reglages) == 2
    assert reglages[0]["payload"]["active"] is False
    assert reglages[0]["payload"]["échéancier"] == [2, 14, 30]
    assert reglages[1]["payload"]["active"] is True


def test_refus_echeancier_invalide(client: TestClient, make_company: MakeCompany) -> None:
    """L'échéancier : 1 à 6 seuils, entiers 1..365, strictement croissants —
    tout écart est refusé (422 : erreur métier BusinessRuleError ou typage)."""
    company = _dossier(make_company)
    policies = Policies(client, company)
    refus = {
        "vide": [],
        "decroissant": [7, 1],
        "doublon": [7, 7],
        "zero": [0, 7],
        "hors_borne": [1, 366],
        "trop_seuils": [1, 2, 3, 4, 5, 6, 7],
        "non_entier": ["a", 7],
    }
    for nom, offsets in refus.items():
        assert policies.put({"enabled": True, "offsets_days": offsets}).status_code == 422, nom
    # Un échéancier valide en bornes supérieures est accepté (365 jours).
    assert policies.put({"enabled": True, "offsets_days": [365]}).status_code == 200


def test_lecteur_lit_mais_ne_regle_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    """Permission : le lecteur consulte la politique mais ne peut ni l'activer
    ni la modifier (sales:manage exigé)."""
    company = _dossier(make_company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    entetes = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(f"/api/v1/companies/{company.id}/reminders/policy", headers=entetes).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/companies/{company.id}/reminders/policy",
            headers=entetes,
            json={"enabled": True, "offsets_days": ECHEANCIER},
        ).status_code
        == 403
    )


def test_isolation_rls_politique(client: TestClient, make_company: MakeCompany) -> None:
    """La politique d'un dossier n'est visible d'aucun autre : le GET du
    dossier B renvoie ses défauts, jamais les seuils du dossier A (la RLS
    force le filtre côté base)."""
    a = _dossier(make_company)
    b = _dossier(make_company)
    _politique(Policies(client, a), a, offsets=[3, 20])
    body = Policies(client, b).get().json()
    assert body["offsets_days"] == [1, 7, 15]
    assert body["updated_at"] is None


# --- Exécution : le worker crée les relances dues ------------------------------


def _facture_echue_auto(
    client: TestClient, company: CompanyFixture, *, email: str | None = "auto-client@exemple.gn"
) -> str:
    """Facture ÉMISE échue à J+10 avec tier client (email par défaut) — même
    protocole que 4D : échéance future à la création, `as_of` la rend échue."""
    sales = Sales(client, company)
    tier = _tier_avec_email(client, company, email=email)
    return _facture_echue(sales, client, company, partner_id=tier)


def test_run_cree_la_relance_due_niveau_1(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Facture échue de 20 jours, politique [1, 7, 15] : le worker crée la
    relance de niveau 1, origine système, et enfile son email."""
    company = _dossier(make_company)
    _facture_echue_auto(client, company)
    _politique(Policies(client, company), company)

    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))

    historique = client.get(
        f"/api/v1/companies/{company.id}/reminders", headers=company.headers
    ).json()
    assert historique["total"] == 1
    relance = historique["items"][0]
    assert relance["level"] == 1
    assert relance["email_to"] == "auto-client@exemple.gn"
    assert relance["reminded_on"] == _jour_iso(JOURS_RAPPEL)

    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    items = journal["items"] if isinstance(journal, dict) else journal
    auto = [e for e in items if e["action"] == "sales_reminder.auto_created"]
    assert len(auto) == 1
    assert auto[0]["payload"]["origine"] == "automatique"
    assert auto[0]["payload"]["niveau"] == 1


def test_run_rattrapage_un_niveau_par_jour_jusquau_dernier_seuil(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Facture découverte à J+30 (3 seuils franchis) : le rattrapage progresse
    d'un niveau par jour — jamais plusieurs relances le même jour — et
    l'escalade s'arrête au dernier seuil."""
    company = _dossier(make_company)
    _facture_echue_auto(client, company)
    _politique(Policies(client, company), company)
    reminders = Reminders(client, company)

    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))
    assert reminders.list().json()["total"] == 1

    # Même jour : le balayage redoublé ne crée rien (unicité quotidienne).
    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))
    assert reminders.list().json()["total"] == 1

    # Jours suivants : niveau 2 puis 3 (un par jour), puis plus rien.
    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL + 1))
    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL + 8))
    assert reminders.list().json()["total"] == 3

    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL + 9))
    assert reminders.list().json()["total"] == 3

    niveaux = [r["level"] for r in reminders.list().json()["items"]]
    assert sorted(niveaux) == [1, 2, 3]


def test_run_relance_manuelle_du_jour_bloque_la_auto(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Une relance manuelle déjà enregistrée le jour du balayage (4D) bloque
    la création automatique : même unicité (dossier, facture, jour) — le
    client ne reçoit jamais deux rappels le même jour."""
    company = _dossier(make_company)
    invoice_id = _facture_echue_auto(client, company)
    _politique(Policies(client, company), company)
    relances = Reminders(client, company)

    with _au_jour(client, company) as jour:
        assert relances.create({"document_id": invoice_id, "reminded_on": jour}).status_code == 201
        _execute(mailbox, company, jour)
        historique = relances.list().json()["items"]
    assert len(historique) == 1, "le balayage a doublé la relance manuelle du jour"
    # Le journal d'audit distingue les origines : la relance enregistrée est
    # celle de l'utilisateur (created), le balayage n'a rien créé (aucune
    # auto_created) — même unicité (dossier, facture, jour) pour les deux voies.
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    items = journal["items"] if isinstance(journal, dict) else journal
    actions = [e["action"] for e in items]
    assert "sales_reminder.created" in actions
    assert "sales_reminder.auto_created" not in actions


def test_run_ignore_facture_soldee(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Une facture soldée (règlement intégralement affecté) n'est pas une
    candidate : rien n'est créé, aucun email ne part."""
    company = _dossier(make_company)
    invoice_id = _facture_echue_auto(client, company)
    _politique(Policies(client, company), company)

    paiement = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": _jour_iso(JOURS_RAPPEL - 1),
            "method": "CASH",
            "allocations": [{"document_id": invoice_id, "amount": 3_540_000}],
        },
    )
    assert paiement.status_code == 201, paiement.text

    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))
    assert (
        client.get(f"/api/v1/companies/{company.id}/reminders", headers=company.headers).json()[
            "total"
        ]
        == 0
    )


def test_run_compte_les_tiers_sans_email(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Un tier sans adresse email est compté « sans_email » (fiche à
    compléter) : ni crash ni relance fantôme."""
    company = _dossier(make_company)
    _facture_echue_auto(client, company, email=None)
    _politique(Policies(client, company), company)

    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))
    assert (
        client.get(f"/api/v1/companies/{company.id}/reminders", headers=company.headers).json()[
            "total"
        ]
        == 0
    )


def test_politique_absente_ou_desactivee_ne_renvoie_rien(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Sans politique (ou politique désactivée) : l'exécution ne crée rien —
    le balayage quotidien traverse le dossier sans effet."""
    company = _dossier(make_company)
    _facture_echue_auto(client, company)

    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))
    _politique(Policies(client, company), company, enabled=False)
    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))

    assert (
        client.get(f"/api/v1/companies/{company.id}/reminders", headers=company.headers).json()[
            "total"
        ]
        == 0
    )


def test_chaine_complete_balayage_worker_email(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Chaîne complète en production : le balayage (sans as_of) traverse tous
    les dossiers, le worker exécute la politique du jour et l'email de relance
    part au client — testé à J+30 (horloge déplacée : le balayage réel court à
    la date du jour)."""
    company = _dossier(make_company)
    _facture_echue_auto(client, company)
    with _au_jour(client, company):
        _politique(Policies(client, company), company)
        scan_automatic_reminders.send()
        sent = mailbox.deliver()

    assert [e.to for e in sent] == ["auto-client@exemple.gn"], sent
    sujet = sent[0].subject
    assert "Relance n°1" in sujet, sujet
    assert (
        client.get(f"/api/v1/companies/{company.id}/reminders", headers=company.headers).json()[
            "total"
        ]
        == 1
    )


def test_les_relances_auto_necrivent_jamais_en_comptabilite(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Pré-requis 4E : aucun chemin des relances automatiques ne génère
    d'écriture (le réglage non plus)."""
    company = _dossier(make_company)
    _facture_echue_auto(client, company)
    _politique(Policies(client, company), company)
    _execute(mailbox, company, _jour_iso(JOURS_RAPPEL))

    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    assert entries.json()["items"] == [], (
        "des écritures sont apparues : relances auto → comptabilité"
    )


def test_contrat_immuable_pas_de_suppression() -> None:
    """Une relance envoyée ne se « désend » pas : le contrat n'expose aucune
    route DELETE ni modification — ni sur les relances ni sur la politique
    (la désactivation passe par `enabled=False`)."""
    from kora.main import create_app  # noqa: PLC0415

    chemins_relance = {
        path: set(methods)
        for path, methods in create_app().openapi()["paths"].items()
        if "/reminders" in path
    }
    assert chemins_relance, "routes relances absentes du contrat"
    for path, methods in chemins_relance.items():
        assert "delete" not in methods, f"DELETE exposé sur {path}"
        assert "patch" not in methods, f"PATCH exposé sur {path}"
        assert methods <= {"get", "post", "put"}, f"méthodes inattendues sur {path}: {methods}"
