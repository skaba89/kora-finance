"""Journal des requêtes lentes : gabarit de route, sans donnée personnelle."""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from kora.core.config import get_settings
from kora.db.session import get_engine


def test_requete_lente_journalisee_avec_gabarit_de_route(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "slow_request_ms", 0)
    company_id = uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger="kora.slow_requests"):
        response = client.get(f"/api/v1/companies/{company_id}/dashboard")
    assert response.status_code == 401
    records = [r for r in caplog.records if r.name == "kora.slow_requests"]
    assert len(records) == 1
    record = records[0]
    assert record.route == "/api/v1/companies/{company_id}/dashboard"  # type: ignore[attr-defined]
    assert record.method == "GET"  # type: ignore[attr-defined]
    assert record.status == 401  # type: ignore[attr-defined]
    assert record.duration_ms >= 0  # type: ignore[attr-defined]
    assert "pool" in vars(record)
    # Ni identifiant de dossier, ni chaîne de requête, ni en-tête dans l'événement.
    assert str(company_id) not in str(vars(record))


def test_requete_rapide_non_journalisee(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "slow_request_ms", 60_000)
    with caplog.at_level(logging.WARNING, logger="kora.slow_requests"):
        client.get("/health/live")
    assert not [r for r in caplog.records if r.name == "kora.slow_requests"]


def test_route_inconnue_sans_chemin_brut(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "slow_request_ms", 0)
    with caplog.at_level(logging.WARNING, logger="kora.slow_requests"):
        client.get("/api/v1/inexistant/secret-token-123")
    records = [r for r in caplog.records if r.name == "kora.slow_requests"]
    assert len(records) == 1
    assert records[0].route == "(route inconnue)"  # type: ignore[attr-defined]
    assert "secret-token-123" not in str(vars(records[0]))


def test_pool_postgres_dimensionne_par_la_configuration() -> None:
    settings = get_settings()
    pool = get_engine().pool
    assert pool.size() == settings.db_pool_size == 10  # type: ignore[attr-defined]
    assert pool._max_overflow == settings.db_max_overflow == 20  # type: ignore[attr-defined]
