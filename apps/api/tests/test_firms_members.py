"""Lecture des membres d'un cabinet : préalable de l'écran d'affectation (CAB-1).

L'administrateur retrouve ses collaborateurs (courriel, nom complet, identifiant
de membership) pour les affecter à des dossiers ; la lecture est réservée aux
administrateurs et l'existence d'un cabinet reste invisible des non-membres
(404, jamais 403, même logique que les autres routes cabinets).
"""

import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import UserFixture

MakeUser = Callable[..., UserFixture]


def test_admin_liste_son_cabinet_avec_courriel_et_nom(
    client: TestClient, make_user: MakeUser
) -> None:
    admin = make_user(full_name="Mamadou Camara")
    collaborateur = make_user(full_name="Fatoumata Sylla")
    headers = admin.headers(client)
    firm = client.post(
        "/api/v1/firms", headers=headers, json={"name": "Cabinet Camara & Associés"}
    ).json()
    added = client.post(
        f"/api/v1/firms/{firm['id']}/members",
        headers=headers,
        json={"email": collaborateur.email, "role": "CABINET_COLLABORATEUR"},
    )
    assert added.status_code == 201, added.text

    res = client.get(f"/api/v1/firms/{firm['id']}/members", headers=headers)
    assert res.status_code == 200, res.text
    members = res.json()
    assert len(members) == 2
    # Administrateur d'abord, puis collaborateur (tri par rôle puis nom).
    assert [m["role"] for m in members] == ["CABINET_ADMIN", "CABINET_COLLABORATEUR"]
    assert members[0]["email"] == admin.email
    assert members[0]["full_name"] == "Mamadou Camara"
    assert members[1]["email"] == collaborateur.email
    assert members[1]["full_name"] == "Fatoumata Sylla"
    # Contrat strict : l'écran d'affectation consomme exactement ces champs.
    assert set(members[1]) == {"id", "user_id", "role", "email", "full_name"}
    # L'identifiant de membership servi par la lecture est celui des affectations.
    assert members[1]["id"] == added.json()["id"]
    uuid.UUID(members[1]["user_id"])


def test_collaborateur_ne_peut_pas_lister_les_membres(
    client: TestClient, make_user: MakeUser
) -> None:
    admin = make_user()
    collaborateur = make_user()
    admin_headers = admin.headers(client)
    firm = client.post("/api/v1/firms", headers=admin_headers, json={"name": "Cabinet Fouta"}).json()
    added = client.post(
        f"/api/v1/firms/{firm['id']}/members",
        headers=admin_headers,
        json={"email": collaborateur.email, "role": "CABINET_COLLABORATEUR"},
    )
    assert added.status_code == 201, added.text

    res = client.get(f"/api/v1/firms/{firm['id']}/members", headers=collaborateur.headers(client))
    assert res.status_code == 403
    assert res.json()["detail"] == "Action réservée aux administrateurs du cabinet."


def test_non_membre_recoit_404_et_ne_devine_pas_lexistence(
    client: TestClient, make_user: MakeUser
) -> None:
    admin = make_user()
    outsider = make_user()
    firm = client.post(
        "/api/v1/firms", headers=admin.headers(client), json={"name": "Cabinet Fétof"}
    ).json()

    # Cabinet existant hors membership : même réponse qu'un cabinet inconnu.
    res = client.get(f"/api/v1/firms/{firm['id']}/members", headers=outsider.headers(client))
    assert res.status_code == 404
    assert res.json()["detail"] == "Cabinet introuvable."
    inconnu = client.get(f"/api/v1/firms/{uuid.uuid4()}/members", headers=outsider.headers(client))
    assert inconnu.status_code == 404
    assert inconnu.json()["detail"] == "Cabinet introuvable."


def test_isolation_entre_deux_cabinets(client: TestClient, make_user: MakeUser) -> None:
    admin_a = make_user()
    admin_b = make_user()
    collaborateur = make_user()
    headers_a = admin_a.headers(client)
    firm_a = client.post("/api/v1/firms", headers=headers_a, json={"name": "Cabinet A"}).json()
    headers_b = admin_b.headers(client)
    firm_b = client.post("/api/v1/firms", headers=headers_b, json={"name": "Cabinet B"}).json()
    client.post(
        f"/api/v1/firms/{firm_a['id']}/members",
        headers=headers_a,
        json={"email": collaborateur.email, "role": "CABINET_COLLABORATEUR"},
    )

    # Le cabinet A ne voit que ses propres membres…
    res_a = client.get(f"/api/v1/firms/{firm_a['id']}/members", headers=headers_a)
    assert res_a.status_code == 200, res_a.text
    emails = {m["email"] for m in res_a.json()}
    assert emails == {admin_a.email, collaborateur.email}
    # …et ne peut pas lire la composition du cabinet B (404, pas 403).
    res_b = client.get(f"/api/v1/firms/{firm_b['id']}/members", headers=headers_a)
    assert res_b.status_code == 404
