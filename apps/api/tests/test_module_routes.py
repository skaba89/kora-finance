from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.models.identity import User
from tests.conftest import CompanyFixture, UserFixture


def test_api_modules_par_client(
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
    directory = "/api/v1/platform/module-clients"
    config = f"{directory}/{first.id}/modules"
    capabilities = f"/api/v1/companies/{first.id}/module-capabilities"
    change = {"enabled": False, "expected_revision": 0}
    assert client.get(directory).status_code == 401
    assert client.get(directory, headers=first.headers).status_code == 403
    assert client.get(config, headers=first.headers).status_code == 403
    assert client.put(f"{config}/treasury", headers=first.headers, json=change).status_code == 403
    response = client.get(directory, headers=headers, params={"limit": 1})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert set(response.json()["items"][0]) == {"id", "legal_name"}
    assert client.get(capabilities, headers=headers).status_code == 404
    assert client.get(capabilities, headers=second.headers).status_code == 404
    initial = client.get(config, headers=headers)
    assert initial.status_code == 200
    assert len(initial.json()) == 19
    invalid = client.put(f"{config}/ocr", headers=headers, json={**change, "enabled": True})
    assert invalid.status_code == 422
    invalid = client.put(f"{config}/treasury", headers=headers, json={**change, "enabled": "false"})
    assert invalid.status_code == 422
    updated = client.put(f"{config}/treasury", headers=headers, json=change)
    assert updated.status_code == 200
    rows = {row["module"]: row for row in updated.json()}
    assert rows["treasury"]["revision"] == 1
    assert rows["forecast"]["configured_status"] == "dependency_disabled"
    assert client.put(f"{config}/treasury", headers=headers, json=change).status_code == 409
    effective = client.get(capabilities, headers=first.headers)
    assert effective.status_code == 200
    statuses = {row["module"]: row["configured_status"] for row in effective.json()}
    assert statuses["treasury"] == "disabled"
    assert set(effective.json()[0]) == {"module", "configured_status"}
    other = client.get(f"{directory}/{second.id}/modules", headers=headers)
    assert other.status_code == 200
    assert other.json() == initial.json()
    # M3 expose les choix, sans encore modifier les autorisations métier.
    assert client.get(f"/api/v1/companies/{first.id}", headers=first.headers).status_code == 200
