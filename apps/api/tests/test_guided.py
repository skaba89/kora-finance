"""Saisie guidée : chaque opération produit l'écriture attendue, équilibrée et validable."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from kora.accounting import guided
from kora.accounting.guided import Operation, Sense
from kora.accounting.setup import reference_chart
from kora.models.accounting import Account
from kora.models.ledger import MAX_LINE_AMOUNT
from tests.conftest import CompanyFixture, UserFixture
from tests.ledger_helpers import Ledger

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]


class Guided:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.base = f"{ledger.base}/guided-entries"
        self.headers = ledger.company.headers
        self.options = self.client.get(f"{self.base}/options", headers=self.headers).json()

    @property
    def client(self) -> TestClient:
        return self.ledger.client

    def account(self, number: str) -> str:
        groups = [
            self.options["treasury_accounts"],
            *self.options["party_accounts"].values(),
            *([c["account"] for c in v] for v in self.options["natures"].values()),
        ]
        return next(str(a["id"]) for group in groups for a in group if a["number"] == number)

    def body(self, operation: str, amount: int, **fields: Any) -> dict[str, Any]:
        resolved = {
            k: self.account(v) if k.endswith("account_id") else v for k, v in fields.items()
        }
        return {
            "operation": operation,
            "entry_date": "2026-03-15",
            "amount": str(amount),
            **resolved,
        }

    def preview(self, operation: str, amount: int, **fields: Any) -> Any:
        return self.client.post(
            f"{self.base}/preview",
            headers=self.headers,
            json=self.body(operation, amount, **fields),
        )

    def create(self, operation: str, amount: int, **fields: Any) -> Any:
        return self.client.post(
            self.base, headers=self.headers, json=self.body(operation, amount, **fields)
        )


@pytest.fixture
def g(client: TestClient, make_company: MakeCompany) -> Guided:
    return Guided(Ledger(client, make_company()))


def _lines(preview: Any) -> list[tuple[str, int, int]]:
    assert preview.status_code == 200, preview.text
    return [
        (ln["account_number"], int(ln["debit"]), int(ln["credit"]))
        for ln in preview.json()["lines"]
    ]


# --- Référentiel


def test_natures_imputables_dans_le_plan_de_reference() -> None:
    chart = {number for number, _ in reference_chart()}
    for nature in guided.natures():
        assert nature.account_number in chart, nature
        # Compte d'imputation dans le référentiel : aucun sous-compte préchargé.
        assert not any(
            n != nature.account_number and n.startswith(nature.account_number) for n in chart
        )
        expected_class = "7" if nature.sense == Sense.PRODUIT else "6"
        assert nature.account_number.startswith(expected_class), nature
        assert nature.label
        assert nature.label_en
    numbers = [n.account_number for n in guided.natures()]
    assert len(numbers) == len(set(numbers))


@pytest.mark.parametrize(
    ("total", "rate", "expected"),
    [
        (1_180_000, 1800, (1_000_000, 180_000)),
        (100, 1800, (85, 15)),
        (1, 1800, (1, 0)),
        (5_900, 1800, (5_000, 900)),
    ],
)
def test_ventilation_de_la_tva(total: int, rate: int, expected: tuple[int, int]) -> None:
    assert guided.split_vat(total, rate) == expected


def _account(number: str) -> Account:
    return Account(id=uuid.uuid4(), number=number, label=number)


@given(
    total=st.integers(min_value=1, max_value=MAX_LINE_AMOUNT),
    rate=st.integers(min_value=1, max_value=10_000),
    operation=st.sampled_from(list(Operation)),
    with_vat=st.booleans(),
)
def test_toute_operation_est_equilibree(
    total: int, rate: int, operation: Operation, with_vat: bool
) -> None:
    net, vat_amount = guided.split_vat(total, rate)
    assert 0 <= vat_amount <= total
    accounts = guided._Accounts(
        nature_account=_account("601"),
        treasury=_account("571"),
        target=_account("521"),
        party=_account("401"),
    )
    vat = (
        guided._VatSplit(net, vat_amount, _account("4452")) if with_vat else guided._VatSplit(total)
    )
    lines = guided._lines(operation, total, accounts, vat)
    assert sum(ln.debit for ln in lines) == sum(ln.credit for ln in lines) == total
    assert all((ln.debit == 0) != (ln.credit == 0) for ln in lines)


# --- Options


def test_options_par_defaut(g: Guided) -> None:
    options = g.options
    assert options["reference"] == "SAISIE_GUIDEE_V1"
    banks = ["521", "522", "523", "524", "525", "526"]
    e_money = ["551", "552", "553", "554", "558"]
    cash = ["571", "572", "573"]
    assert [a["number"] for a in options["treasury_accounts"]] == [*banks, *e_money, *cash]
    assert [a["number"] for a in options["party_accounts"]["CLIENT"]] == ["411"]
    assert [a["number"] for a in options["party_accounts"]["FOURNISSEUR"]] == ["401"]
    assert {c["account"]["number"] for c in options["natures"]["PRODUIT"]} == {
        "701", "702", "705", "706", "707",
    }  # fmt: skip
    assert options["vat"] == {"rate_basis_points": 1800, "verified": False}


def test_sous_comptes_proposes_a_la_place_du_compte_parent(g: Guided) -> None:
    for number, label in [
        ("5521", "Orange Money"),
        ("5522", "MTN MoMo"),
        ("4111", "Clients Kaloum"),
    ]:
        created = g.client.post(
            f"{g.ledger.base}/accounts", headers=g.headers, json={"number": number, "label": label}
        )
        assert created.status_code == 201
    options = g.client.get(f"{g.base}/options", headers=g.headers).json()
    treasury = [a["number"] for a in options["treasury_accounts"]]
    assert "552" not in treasury
    assert {"5521", "5522"} <= set(treasury)
    assert [a["number"] for a in options["party_accounts"]["CLIENT"]] == ["4111"]
    # Le compte parent n'est plus accepté.
    g.options = options
    body = g.body("ENCAISSEMENT_CLIENT", 1000, treasury_account_id="5521")
    body["party_account_id"] = g.ledger.client.get(
        f"{g.ledger.base}/accounts", headers=g.headers, params={"q": "411"}
    ).json()["items"][0]["id"]
    response = g.client.post(g.base, headers=g.headers, json=body)
    assert response.status_code == 422
    assert "compte client" in response.json()["detail"]


# --- Opérations


def test_vente_encaissee_avec_tva(g: Guided) -> None:
    preview = g.preview(
        "VENTE_COMPTANT",
        1_180_000,
        nature_account_id="701",
        treasury_account_id="571",
        vat_included=True,
    )
    assert _lines(preview) == [("571", 1_180_000, 0), ("701", 0, 1_000_000), ("4431", 0, 180_000)]
    body = preview.json()
    assert body["journal_code"] == "CA"
    assert body["label"] == "Vente encaissée — Vente de marchandises"
    assert body["vat_amount"] == "180000"
    assert body["warnings"] == [
        "Le taux de TVA de 18 % n'a pas encore été vérifié auprès de la DGI (paramètres → taxes)."
    ]


def test_vente_sans_tva_en_mobile_money(g: Guided) -> None:
    preview = g.preview(
        "VENTE_COMPTANT", 250_000, nature_account_id="706", treasury_account_id="552"
    )
    assert _lines(preview) == [("552", 250_000, 0), ("706", 0, 250_000)]
    assert preview.json()["journal_code"] == "MM"
    assert preview.json()["warnings"] == []


def test_facture_client_puis_reglement(g: Guided) -> None:
    invoice = g.preview(
        "FACTURE_CLIENT", 590_000, nature_account_id="706", party_account_id="411",
        vat_included=True, reference="F-2026-014",
    )  # fmt: skip
    assert _lines(invoice) == [("411", 590_000, 0), ("706", 0, 500_000), ("4431", 0, 90_000)]
    assert invoice.json()["journal_code"] == "VT"
    assert invoice.json()["reference"] == "F-2026-014"
    payment = g.preview(
        "ENCAISSEMENT_CLIENT", 590_000, treasury_account_id="521", party_account_id="411"
    )
    assert _lines(payment) == [("521", 590_000, 0), ("411", 0, 590_000)]
    assert payment.json()["journal_code"] == "BQ"
    assert payment.json()["label"] == "Règlement client"


def test_depense_payee_avec_tva_deductible(g: Guided) -> None:
    preview = g.preview(
        "ACHAT_COMPTANT", 118_000, nature_account_id="628", treasury_account_id="571",
        vat_included=True, label="Recharge internet mars",
    )  # fmt: skip
    assert _lines(preview) == [("628", 100_000, 0), ("4452", 18_000, 0), ("571", 0, 118_000)]
    assert preview.json()["label"] == "Recharge internet mars"


def test_facture_fournisseur_puis_paiement(g: Guided) -> None:
    invoice = g.preview(
        "FACTURE_FOURNISSEUR", 3_000_000, nature_account_id="622", party_account_id="401"
    )
    assert _lines(invoice) == [("622", 3_000_000, 0), ("401", 0, 3_000_000)]
    assert invoice.json()["journal_code"] == "AC"
    payment = g.preview(
        "PAIEMENT_FOURNISSEUR", 3_000_000, treasury_account_id="521", party_account_id="401"
    )
    assert _lines(payment) == [("401", 3_000_000, 0), ("521", 0, 3_000_000)]


def test_virement_entre_comptes(g: Guided) -> None:
    preview = g.preview(
        "VIREMENT_INTERNE", 2_000_000, treasury_account_id="521", target_treasury_account_id="571"
    )
    assert _lines(preview) == [("571", 2_000_000, 0), ("521", 0, 2_000_000)]
    assert preview.json()["journal_code"] == "BQ"
    same = g.preview(
        "VIREMENT_INTERNE", 2_000_000, treasury_account_id="521", target_treasury_account_id="521"
    )
    assert same.status_code == 422
    assert "différents" in same.json()["detail"]


def test_enregistrement_en_brouillon_validable_et_idempotent(g: Guided) -> None:
    body = g.body(
        "ACHAT_COMPTANT",
        118_000,
        nature_account_id="605",
        treasury_account_id="571",
        vat_included=True,
    )
    body["id"] = str(uuid.uuid4())
    created = g.client.post(g.base, headers=g.headers, json=body)
    assert created.status_code == 201, created.text
    again = g.client.post(g.base, headers=g.headers, json=body)
    assert again.status_code == 200
    assert again.json()["id"] == created.json()["id"] == body["id"]

    entry = g.client.get(f"{g.ledger.base}/entries/{body['id']}", headers=g.headers).json()
    assert entry["status"] == "DRAFT"
    assert entry["journal_code"] == "CA"
    assert entry["total_debit"] == entry["total_credit"] == "118000"
    posted = g.ledger.post(body["id"])
    assert posted.status_code == 200, posted.text
    assert posted.json()["number"] == 1


# --- Refus


N, T, P, TVA = "nature_account_id", "treasury_account_id", "party_account_id", "vat_included"


@pytest.mark.parametrize(
    ("operation", "fields", "message"),
    [
        ("VENTE_COMPTANT", {N: "601", T: "571"}, "nature de la recette"),
        ("ACHAT_COMPTANT", {N: "701", T: "571"}, "nature de la dépense"),
        ("ACHAT_COMPTANT", {N: "622"}, "Choisissez compte de trésorerie"),
        ("FACTURE_CLIENT", {N: "701", P: "401"}, "compte client"),
        ("PAIEMENT_FOURNISSEUR", {T: "571", P: "411"}, "compte fournisseur"),
        ("ACHAT_COMPTANT", {N: "625", T: "571", TVA: True}, "pas de TVA"),
        ("VIREMENT_INTERNE", {T: "571", TVA: True}, "compte de destination"),
    ],
)
def test_choix_incoherents_refuses(
    g: Guided, operation: str, fields: dict[str, Any], message: str
) -> None:
    response = g.preview(operation, 10_000, **fields)
    assert response.status_code == 422
    assert message in response.json()["detail"]
    # Rien n'est enregistré.
    entries = g.client.get(f"{g.ledger.base}/entries", headers=g.headers).json()
    assert entries["total"] == 0


def test_date_hors_exercice_refusee(g: Guided) -> None:
    body = g.body("VENTE_COMPTANT", 1000, nature_account_id="701", treasury_account_id="571")
    body["entry_date"] = "2031-01-01"
    response = g.client.post(f"{g.base}/preview", headers=g.headers, json=body)
    assert response.status_code == 422
    assert "Aucun exercice" in response.json()["detail"]


def test_montant_nul_refuse(g: Guided) -> None:
    assert (
        g.preview(
            "VENTE_COMPTANT", 0, nature_account_id="701", treasury_account_id="571"
        ).status_code
        == 422
    )


def test_journal_desactive(g: Guided) -> None:
    journals = g.client.get(f"{g.ledger.base}/journals", headers=g.headers).json()
    caisse = next(j for j in journals if j["code"] == "CA")
    g.client.patch(
        f"{g.ledger.base}/journals/{caisse['id']}", headers=g.headers, json={"is_active": False}
    )
    response = g.preview("VENTE_COMPTANT", 1000, nature_account_id="701", treasury_account_id="571")
    assert response.status_code == 422
    assert "journal CA" in response.json()["detail"]


def test_lecteur_sans_saisie_guidee(client: TestClient, g: Guided, make_user: MakeUser) -> None:
    reader = make_user()
    client.post(
        f"{g.ledger.base}/members",
        headers=g.headers,
        json={"email": reader.email, "role": "PME_LECTEUR"},
    )
    headers = reader.headers(client)
    assert client.get(f"{g.base}/options", headers=headers).status_code == 403
    body = g.body("VENTE_COMPTANT", 1000, nature_account_id="701", treasury_account_id="571")
    assert client.post(g.base, headers=headers, json=body).status_code == 403
