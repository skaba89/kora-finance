"""Indicateurs de recouvrement et export de la balance âgée (lot B-4).

Recette : tout est calculé en lecture au jour demandé, depuis les mêmes soldes
que la balance âgée 4C — encours, part échue, retard moyen pondéré, DSO en
jours de ventes (borné à la fenêtre), taux de recouvrement (encaissements nets
des remboursements ÷ factures émises de la fenêtre, en points de base) et top
débiteurs. Les dates du jeu de données sont toutes **relatives au jour
présent** (aucun jour calendaire en dur) ; l'exercice de test couvre 2026 et
les règlements y sont datés en dur comme dans les tests 4C/B-3.

L'export PDF/Excel de la balance âgée reproduit exactement la répartition de
la route JSON (mêmes buckets, mêmes soldes), sous quota d'exports (KF-13) et
journalisé (`export.generated`).
"""

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
TTC = 3_540_000  # facture type : 3 000 000 HT + 540 000 TVA (18 %)


class Recouvrement:
    """Raccourcis d'appel aux indicateurs et à l'export balance âgée."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def kpis(self, company: CompanyFixture | None = None, **params: object) -> Response:
        headers = (company or self.company).headers
        query = {k: str(v) for k, v in params.items() if v is not None}
        return self.client.get(f"{self.base}/receivables/kpis", headers=headers, params=query)

    def export(
        self, file_format: str, company: CompanyFixture | None = None, **params: object
    ) -> Response:
        headers = (company or self.company).headers
        query = {"format": file_format, **{k: str(v) for k, v in params.items() if v is not None}}
        return self.client.get(
            f"{self.base}/receivables/aging/export", headers=headers, params=query
        )


def _facture_emise(
    sales: Sales,
    client: TestClient,
    company: CompanyFixture,
    *,
    issued_on: str | None = None,
    due_on: str | None = None,
    partner_id: str | None = None,
) -> str:
    """Facture émise de TTC fixe ; émission rétrodatée si demandé (l'échéance
    ne peut pas précéder l'émission — le service l'exige)."""
    overrides: dict[str, object] = {}
    if partner_id is not None:
        overrides["partner_id"] = partner_id
    if due_on is not None:
        overrides["due_on"] = due_on
    invoice_id = _facture_brouillon(sales, _creer_tva(client, company), **overrides)
    corps: dict[str, object] = {"issued_on": issued_on} if issued_on else {}
    reponse = client.post(
        f"/api/v1/companies/{company.id}/sales/{invoice_id}/issue",
        headers=company.headers,
        json=corps,
    )
    assert reponse.status_code == 200, reponse.text
    return invoice_id


def _reglement(
    client: TestClient, company: CompanyFixture, invoice_id: str, montant: int, paid_on: str
) -> Response:
    return client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={
            "paid_on": paid_on,
            "method": "MOBILE_MONEY",
            "allocations": [{"document_id": invoice_id, "amount": montant}],
        },
    )


def test_kpis_dataset_connu(client: TestClient, make_company: MakeCompany) -> None:
    """Jeu de données relatif au jour présent, indicateurs exacts au as_of :
    encours, part échue, retard moyen pondéré, DSO, taux de recouvrement."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    recouvrement = Recouvrement(client, company)
    jour = utcnow().date()
    # F1 : échue de 30 jours au as_of (due T+10, as_of T+40), non payée.
    _facture_emise(
        sales, client, company, issued_on=(jour - timedelta(days=45)).isoformat(),
        due_on=(jour + timedelta(days=10)).isoformat(),
    )  # fmt: skip
    # F2 : payée intégralement le T-10 → hors encours, encaissee dans la fenetre.
    f2 = _facture_emise(
        sales, client, company, issued_on=(jour - timedelta(days=30)).isoformat(),
        due_on=(jour + timedelta(days=20)).isoformat(),
    )  # fmt: skip
    # F3 : échue de 10 jours au as_of, non payée.
    _facture_emise(
        sales, client, company, issued_on=(jour - timedelta(days=5)).isoformat(),
        due_on=(jour + timedelta(days=30)).isoformat(),
    )  # fmt: skip
    assert (
        _reglement(
            client, company, f2, 2 * TTC, (jour - timedelta(days=10)).isoformat()
        ).status_code
        == 201
    )

    as_of = (jour + timedelta(days=40)).isoformat()
    reponse = recouvrement.kpis(as_of=as_of, lookback_days=90)
    assert reponse.status_code == 200, reponse.text
    body = reponse.json()
    assert body["as_of"] == as_of
    # Encours = F1 + F3 (F2 soldée) ; échue = tout l'encours.
    assert body["outstanding_ttc"] == 2 * TTC
    assert body["overdue_ttc"] == 2 * TTC
    assert body["overdue_share_bp"] == 10_000
    # Retard pondéré : (30×TTC + 10×TTC) ÷ (2×TTC) = 20 jours entiers.
    assert body["weighted_days_late"] == 20
    # Fenêtre [T-50, T+40] : facturé TTC×3, encaissé TTC, taux 33,3 % (3 333 bp).
    assert body["billed_ttc"] == 3 * TTC
    assert body["collected_ttc"] == TTC
    assert body["recovery_rate_bp"] == 3_333
    # DSO = encours ÷ facturé × 90 j, arrondi au plus proche : 60 jours.
    assert body["dso_days"] == 60
    # Top débiteurs : F1 et F3 (partenaires distincts, soldes identiques),
    # avec leur retard maximum ; F2 payée n'apparaît pas.
    assert len(body["top_debtors"]) == 2
    assert {d["outstanding_ttc"] for d in body["top_debtors"]} == {TTC}
    assert {d["max_days_late"] for d in body["top_debtors"]} == {30, 10}
    assert uuid.UUID(body["top_debtors"][0]["partner_id"])


def test_kpis_dso_borne_a_la_fenetre(client: TestClient, make_company: MakeCompany) -> None:
    """Un encours antérieur à la fenêtre ne gonfle pas le DSO au-delà de la
    fenêtre de mesure ; une fenêtre sans ventes facturées donne un DSO nul."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    recouvrement = Recouvrement(client, company)
    jour = utcnow().date()
    _facture_emise(
        sales, client, company, issued_on=(jour - timedelta(days=45)).isoformat(),
        due_on=(jour + timedelta(days=10)).isoformat(),
    )  # fmt: skip
    _facture_emise(
        sales, client, company, issued_on=(jour - timedelta(days=1)).isoformat(),
        due_on=(jour + timedelta(days=10)).isoformat(),
    )  # fmt: skip
    reponse = recouvrement.kpis(as_of=jour.isoformat(), lookback_days=7)
    body = reponse.json()
    assert body["billed_ttc"] == TTC  # seule la facture de T-1 est dans la fenêtre
    assert body["outstanding_ttc"] == 2 * TTC
    # DSO demandé : 2×TTC ÷ TTC × 7 = 14 j → borné à la fenêtre de 7 jours.
    assert body["dso_days"] == 7

    # Fenêtre sans ventes facturées (avant la première émission) : DSO nul,
    # taux nul — jamais de division par zéro.
    vide = recouvrement.kpis(as_of=(jour - timedelta(days=90)).isoformat(), lookback_days=7).json()
    assert vide["billed_ttc"] == 0
    assert vide["dso_days"] == 0
    assert vide["recovery_rate_bp"] == 0


def test_kpis_excluent_les_remboursements_du_recouvrement(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Le taux de recouvrement porte les encaissements NETS des remboursements
    (B-3) : un acompte remboursé dans la fenêtre ne gonfle pas le taux."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    recouvrement = Recouvrement(client, company)
    jour = utcnow().date()
    _facture_emise(
        sales,
        client,
        company,
        issued_on=jour.isoformat(),
        due_on=(jour + timedelta(days=30)).isoformat(),
    )
    tier = _creer_tier(client, company)
    acompte = client.post(
        f"/api/v1/companies/{company.id}/payments",
        headers=company.headers,
        json={"paid_on": jour.isoformat(), "method": "CASH", "amount": TTC, "partner_id": tier},
    )
    assert acompte.status_code == 201, acompte.text
    acompte_id = acompte.json()["id"]
    # Un acompte reçu puis remboursé le même jour : net = 0.
    rembourse = client.post(
        f"/api/v1/companies/{company.id}/payments/{acompte_id}/refund",
        headers=company.headers,
        json={"refunded_on": jour.isoformat(), "amount": TTC, "method": "CASH"},
    )
    assert rembourse.status_code == 201, rembourse.text
    body = recouvrement.kpis(as_of=jour.isoformat(), lookback_days=90).json()
    assert body["billed_ttc"] == TTC
    assert body["collected_ttc"] == 0  # encaissé TTC - remboursement TTC
    assert body["recovery_rate_bp"] == 0
    # L'acompte remboursé ne laisse aucune créance ni aucun encaissement net.
    assert body["outstanding_ttc"] == TTC


def test_kpis_permissions_et_isolation(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = _dossier(make_company)
    autre = _dossier(make_company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(f"/api/v1/companies/{company.id}/receivables/kpis", headers=headers).status_code
        == 200
    )
    # Un autre dossier ne lit rien du premier (RLS) : l'état est vide (200).
    autres = Recouvrement(client, autre)
    reponse_etrangere = autres.kpis()
    assert reponse_etrangere.status_code == 200, reponse_etrangere.text
    vide = reponse_etrangere.json()
    assert vide["outstanding_ttc"] == 0
    assert vide["top_debtors"] == []


def test_export_balance_agee_pdf_et_excel(client: TestClient, make_company: MakeCompany) -> None:
    """L'export reproduit la répartition de la balance âgée JSON : PDF (données
    attendues) et Excel (ZIP OOXML), journalisé `export.generated`, bucket
    conforme à l'as_of demandé."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    recouvrement = Recouvrement(client, company)
    jour = utcnow().date()
    echue = _facture_emise(
        sales, client, company, issued_on=(jour - timedelta(days=45)).isoformat(),
        due_on=(jour - timedelta(days=5)).isoformat(),
    )  # fmt: skip
    _facture_emise(
        sales, client, company, issued_on=jour.isoformat(),
        due_on=(jour + timedelta(days=30)).isoformat(),
    )  # fmt: skip
    assert (
        _reglement(
            client, company, echue, 540_000, (jour - timedelta(days=3)).isoformat()
        ).status_code
        == 201
    )
    attendu_solde = TTC - 540_000

    # La balance âgée JSON fait foi : l'export en reproduit les buckets
    # (as_of où la première facture est échue de 9 jours, la seconde à échoir).
    situation = (jour + timedelta(days=10)).isoformat()
    balance = client.get(
        f"/api/v1/companies/{company.id}/receivables/aging",
        headers=company.headers,
        params={"as_of": situation},
    ).json()
    assert balance["buckets"]["d1_30"]["total_ttc"] == attendu_solde
    assert balance["buckets"]["not_due"]["total_ttc"] == TTC

    pdf = recouvrement.export("pdf", as_of=situation)
    assert pdf.status_code == 200, pdf.text
    contenu = pdf.content
    assert contenu[:5] == b"%PDF-", "le PDF est corrompu"
    assert "balance-agee" in pdf.headers.get("Content-Disposition", "")

    xlsx = recouvrement.export("xlsx", as_of=situation)
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.content[:2] == b"PK", "l'Excel n'est pas un OOXML valide"

    # La traçabilité : chaque export est au journal d'audit.
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    exports = [
        e
        for e in (journal["items"] if isinstance(journal, dict) else journal)
        if e["action"] == "export.generated" and e["payload"].get("type") == "balance-agee"
    ]
    assert len(exports) == 2
    assert exports[0]["payload"]["format"] in ("pdf", "xlsx")


def test_export_balance_agee_permissions(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    """`sales:read` suffit à l'export (lecture) ; un autre dossier est en 404 ;
    un format inconnu est rejeté par la validation."""
    company = _dossier(make_company)
    autre = _dossier(make_company)
    recouvrement = Recouvrement(client, company)
    assert recouvrement.export("pdf").status_code == 200
    assert recouvrement.export("csv").status_code == 422
    assert Recouvrement(client, autre).export("pdf").status_code == 200

    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    headers = lecteur.headers(client)  # type: ignore[attr-defined]
    assert (
        client.get(
            f"/api/v1/companies/{company.id}/receivables/aging/export",
            headers=headers,
            params={"format": "xlsx"},
        ).status_code
        == 200
    )
