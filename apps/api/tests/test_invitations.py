"""Invitation d'une personne sans compte à rejoindre un dossier."""

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from kora.core.config import get_settings
from kora.models.common import utcnow
from kora.models.identity import Invitation, User
from tests.conftest import CompanyFixture, Mailbox, UserFixture

MakeUser = Callable[..., UserFixture]
MakeCompany = Callable[..., CompanyFixture]

PASSWORD = "Mot-de-passe-solide-2026"


@pytest.fixture
def company(make_company: MakeCompany, make_user: MakeUser) -> CompanyFixture:
    """Dossier dont le dirigeant a une adresse vérifiée (condition pour inviter)."""
    return make_company(owner=make_user(verified=True, full_name="Ibrahima Sow"))


def _invite(
    client: TestClient, company: CompanyFixture, email: str, role: str = "PME_COMPTABLE"
) -> Any:
    return client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": email, "role": role},
    )


def _token(mailbox: Mailbox, email: str) -> str:
    match = re.search(r"/(?:fr|en)/invitation\?jeton=([A-Za-z0-9_-]+)", mailbox.last_to(email).text)
    assert match
    return match[1]


def _preview(client: TestClient, token: str) -> Any:
    return client.post("/api/v1/invitations/preview", json={"token": token})


def _accept(client: TestClient, token: str) -> Any:
    return client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "full_name": "Kadiatou Barry", "password": PASSWORD},
    )


def test_invitation_de_bout_en_bout(
    client: TestClient, company: CompanyFixture, mailbox: Mailbox, db: Session
) -> None:
    response = _invite(client, company, "Nouvelle.Comptable@exemple.gn")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "invited"
    assert body["email_queued"] is True
    assert body["invitation"]["email"] == "nouvelle.comptable@exemple.gn"

    email = mailbox.last_to("nouvelle.comptable@exemple.gn")
    assert email.subject.startswith("Ibrahima Sow vous invite sur le dossier")
    assert "Comptable" in email.text
    token = _token(mailbox, "nouvelle.comptable@exemple.gn")

    listed = client.get(f"/api/v1/companies/{company.id}/invitations", headers=company.headers)
    assert [i["email"] for i in listed.json()] == ["nouvelle.comptable@exemple.gn"]
    assert listed.json()[0]["sent_at"] is not None

    preview = _preview(client, token).json()
    assert preview == {
        **preview,
        "email": "nouvelle.comptable@exemple.gn",
        "role": "PME_COMPTABLE",
        "inviter_name": "Ibrahima Sow",
        "account_exists": False,
    }

    accepted = _accept(client, token)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["company_id"] == str(company.id)
    headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["email_verified"] is True
    access = client.get("/api/v1/companies", headers=headers).json()
    assert [(c["company"]["id"], c["role"]) for c in access] == [(str(company.id), "PME_COMPTABLE")]

    # Invitation consommée : lien inutilisable, plus dans la liste.
    assert _preview(client, token).status_code == 400
    assert _accept(client, token).status_code == 400
    assert (
        client.get(f"/api/v1/companies/{company.id}/invitations", headers=company.headers).json()
        == []
    )
    assert db.query(User).filter_by(email="nouvelle.comptable@exemple.gn").count() == 1


def test_un_compte_existant_est_rattache_directement(
    client: TestClient, company: CompanyFixture, make_user: MakeUser, mailbox: Mailbox
) -> None:
    existing = make_user()
    mailbox.deliver()
    response = _invite(client, company, existing.email)
    assert response.json()["status"] == "member"
    assert all("invite" not in m.subject for m in mailbox.deliver())


def test_inviter_exige_une_adresse_verifiee(client: TestClient, make_company: MakeCompany) -> None:
    unverified = make_company()
    response = _invite(client, unverified, "quelqu-un@exemple.gn")
    assert response.status_code == 403
    assert response.json()["code"] == "email_non_verifie"


def test_invitation_deja_en_attente_puis_renvoi(
    client: TestClient, company: CompanyFixture, mailbox: Mailbox
) -> None:
    invitation = _invite(client, company, "attente@exemple.gn").json()["invitation"]
    first = _token(mailbox, "attente@exemple.gn")
    assert _invite(client, company, "attente@exemple.gn").status_code == 409

    resent = client.post(
        f"/api/v1/companies/{company.id}/invitations/{invitation['id']}/resend",
        headers=company.headers,
    )
    assert resent.status_code == 200
    second = _token(mailbox, "attente@exemple.gn")
    assert first != second
    assert _preview(client, first).status_code == 400
    assert _preview(client, second).status_code == 200


def test_annulation(client: TestClient, company: CompanyFixture, mailbox: Mailbox) -> None:
    invitation = _invite(client, company, "annulee@exemple.gn").json()["invitation"]
    token = _token(mailbox, "annulee@exemple.gn")
    revoked = client.delete(
        f"/api/v1/companies/{company.id}/invitations/{invitation['id']}", headers=company.headers
    )
    assert revoked.status_code == 204
    assert _preview(client, token).status_code == 400
    # Une nouvelle invitation reste possible après annulation.
    assert _invite(client, company, "annulee@exemple.gn").status_code == 201


def test_invitation_expiree_renouvelee(
    client: TestClient, company: CompanyFixture, mailbox: Mailbox, db: Session
) -> None:
    first = _invite(client, company, "expiree@exemple.gn").json()["invitation"]
    token = _token(mailbox, "expiree@exemple.gn")
    db.execute(
        update(Invitation)
        .where(Invitation.email == "expiree@exemple.gn")
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    assert _preview(client, token).status_code == 400
    listed = client.get(f"/api/v1/companies/{company.id}/invitations", headers=company.headers)
    assert listed.json()[0]["expired"] is True

    renewed = _invite(client, company, "expiree@exemple.gn", role="PME_LECTEUR")
    assert renewed.status_code == 201
    assert renewed.json()["invitation"]["id"] == first["id"]
    assert renewed.json()["invitation"]["role"] == "PME_LECTEUR"
    assert _preview(client, _token(mailbox, "expiree@exemple.gn")).status_code == 200


def test_compte_cree_entre_temps_doit_se_connecter(
    client: TestClient, company: CompanyFixture, make_user: MakeUser, mailbox: Mailbox
) -> None:
    _invite(client, company, "tardif@exemple.gn", role="PME_LECTEUR")
    token = _token(mailbox, "tardif@exemple.gn")
    invited = make_user(email="tardif@exemple.gn")

    assert _preview(client, token).json()["account_exists"] is True
    conflict = _accept(client, token)
    assert conflict.status_code == 409

    # Un autre utilisateur connecté ne peut pas s'approprier l'invitation.
    intruder = make_user()
    stolen = client.post(
        "/api/v1/invitations/join", headers=intruder.headers(client), json={"token": token}
    )
    assert stolen.status_code == 400

    joined = client.post(
        "/api/v1/invitations/join", headers=invited.headers(client), json={"token": token}
    )
    assert joined.status_code == 200
    assert joined.json() == {"company_id": str(company.id)}
    access = client.get("/api/v1/companies", headers=invited.headers(client)).json()
    assert access[0]["role"] == "PME_LECTEUR"


def test_quota_d_invitations_par_dossier(
    client: TestClient, company: CompanyFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "invitations_per_company_per_day", 2)
    assert _invite(client, company, "a@exemple.gn").status_code == 201
    assert _invite(client, company, "b@exemple.gn").status_code == 201
    blocked = _invite(client, company, "c@exemple.gn")
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "trop_de_demandes"


def test_le_contenu_de_l_email_est_echappe(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser, mailbox: Mailbox
) -> None:
    company = make_company(
        owner=make_user(verified=True, full_name="<img src=x onerror=alert(1)>"),
        trade_name="<b>Société</b>\r\nBcc: victime@exemple.gn",
    )
    _invite(client, company, "cible@exemple.gn")
    email = mailbox.last_to("cible@exemple.gn")
    assert "<img" not in email.html
    assert "&lt;img src=x onerror=alert(1)&gt;" in email.html
    assert "<b>Société</b>" not in email.html
    assert "\n" not in email.subject
    assert "\r" not in email.subject


def test_idor_invitation_d_un_autre_dossier(
    client: TestClient, company: CompanyFixture, make_company: MakeCompany, make_user: MakeUser
) -> None:
    other = make_company(owner=make_user(verified=True))
    theirs = _invite(client, other, "autre@exemple.gn").json()["invitation"]["id"]
    for method, suffix in (("POST", "/resend"), ("DELETE", "")):
        response = client.request(
            method,
            f"/api/v1/companies/{company.id}/invitations/{theirs}{suffix}",
            headers=company.headers,
        )
        assert response.status_code == 404


def test_le_lecteur_ne_peut_pas_inviter(
    client: TestClient, company: CompanyFixture, make_user: MakeUser
) -> None:
    reader = make_user(verified=True)
    _invite(client, company, reader.email, role="PME_LECTEUR")
    response = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=reader.headers(client),
        json={"email": "x@exemple.gn", "role": "PME_LECTEUR"},
    )
    assert response.status_code == 403
