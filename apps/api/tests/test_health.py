from collections.abc import Iterator

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from kora.core.redis import get_redis
from kora.db.session import get_db


def test_live_repond_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_ok_quand_base_et_redis_joignables(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


def test_ready_503_quand_base_injoignable(client: TestClient) -> None:
    # Port fermé : la connexion échoue immédiatement.
    engine = create_engine(
        "postgresql+psycopg://nobody:x@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )

    def broken_db() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    client.app.dependency_overrides[get_db] = broken_db  # type: ignore[attr-defined]
    response = client.get("/health/ready")
    engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "erreur", "database": "erreur", "redis": "ok"}


def test_ready_503_quand_redis_injoignable(client: TestClient) -> None:
    broken = Redis(host="127.0.0.1", port=1, socket_connect_timeout=1)
    client.app.dependency_overrides[get_redis] = lambda: broken  # type: ignore[attr-defined]
    response = client.get("/health/ready")
    broken.close()

    assert response.status_code == 503
    assert response.json() == {"status": "erreur", "database": "ok", "redis": "erreur"}
