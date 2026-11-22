from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.models.identity import User
from tests.conftest import CompanyFixture, UserFixture


def test_prevision_desactivee_historique_conserve(
    client: TestClient,
    db: Session,
    make_user: Callable[..., UserFixture],
    make_company: Callable[..., CompanyFixture],
) -> None:
    first, second = make_company(), make_company()
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    headers = admin.headers(client)
    base = f"/api/v1/companies/{first.id}/cashflow"
    config = f"/api/v1/platform/module-clients/{first.id}/modules"
    snapshot = client.post(f"{base}/snapshots", headers=first.headers)
    assert snapshot.status_code == 201
    snapshot_id = snapshot.json()["id"]
    response = client.put(
        f"{config}/forecast", headers=headers, json={"enabled": False, "expected_revision": 0}
    )
    assert response.status_code == 200
    for method, path, payload in (
        ("GET", "forecast", None),
        ("GET", "forecast/export?format=pdf", None),
        ("GET", "forecast/export?format=xlsx", None),
        ("GET", "settings", None),
        ("PUT", "settings", {"critical_floor_minor": 0}),
        ("POST", "snapshots", None),
    ):
        denied = client.request(method, f"{base}/{path}", headers=first.headers, json=payload)
        assert denied.status_code == 403, denied.text
    listed = client.get(f"{base}/snapshots", headers=first.headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [snapshot_id]
    assert client.get(f"{base}/snapshots/{snapshot_id}", headers=first.headers).status_code == 200
    assert (
        client.get(f"{base}/snapshots/{snapshot_id}/vs-actual", headers=first.headers).status_code
        == 200
    )
    assert client.get(f"{base}/snapshots/{snapshot_id}", headers=second.headers).status_code == 404
    other = f"/api/v1/companies/{second.id}/cashflow/forecast"
    assert client.get(other, headers=second.headers).status_code == 200
    response = client.put(
        f"{config}/forecast", headers=headers, json={"enabled": True, "expected_revision": 1}
    )
    assert response.status_code == 200
    assert client.get(f"{base}/forecast", headers=first.headers).status_code == 200
    response = client.put(
        f"{config}/treasury", headers=headers, json={"enabled": False, "expected_revision": 0}
    )
    assert response.status_code == 200
    assert client.get(f"{base}/forecast", headers=first.headers).status_code == 403
