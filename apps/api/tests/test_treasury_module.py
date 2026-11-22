from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kora.models.identity import User
from tests.conftest import CompanyFixture, UserFixture
from tests.test_treasury import Treasury, _banque_body, _caisse_body, _movement_body
from tests.test_treasury_statements import OFX, Statements, _banque_id


def test_tresorerie_desactivee_preserve_historique(
    client: TestClient,
    db: Session,
    make_company: Callable[..., CompanyFixture],
    make_user: Callable[..., UserFixture],
) -> None:
    first, second = make_company(), make_company()
    treasury = Treasury(client, first)
    bank = _banque_id(client, first)
    cash = treasury.create_account(_caisse_body(client, first))
    assert cash.status_code == 201
    movement = _movement_body(client, first)
    assert treasury.movement(bank, movement).status_code == 201
    previous = treasury.movements(bank).json()
    statements = Statements(client, first)
    imported = statements.import_file(bank, OFX)
    assert imported.status_code == 201
    admin = make_user()
    db.get_one(User, admin.id).is_platform_admin = True
    db.commit()
    headers = admin.headers(client)
    config = f"/api/v1/platform/module-clients/{first.id}/modules/treasury"
    change = client.put(config, headers=headers, json={"enabled": False, "expected_revision": 0})
    assert change.status_code == 200
    denied = treasury.create_account(_banque_body(client, first, name="Autre banque"))
    assert denied.status_code == 403
    assert treasury.movement(bank, movement).status_code == 403
    transfer = {
        "source_account_id": bank,
        "target_account_id": cash.json()["id"],
        "amount": "300000",
        "movement_date": "2026-03-20",
        "label": "Approvisionnement caisse",
    }
    assert treasury.transfer(transfer).status_code == 403
    assert statements.import_file(bank, OFX).status_code == 403
    assert treasury.accounts().status_code == 200
    assert treasury.movements(bank).json() == previous
    assert statements.lines(imported.json()["id"]).status_code == 200
    assert Treasury(client, second).create_account(_banque_body(client, second)).status_code == 201
    change = client.put(config, headers=headers, json={"enabled": True, "expected_revision": 1})
    assert change.status_code == 200
    assert treasury.transfer(transfer).status_code == 201
