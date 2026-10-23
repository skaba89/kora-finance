import pytest
from starlette.requests import Request

from kora.core.client_ip import client_ip
from kora.core.config import get_settings


def _request(host: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (host, 1234), "headers": headers})


def test_sans_proxy_l_en_tete_forwarded_est_ignore() -> None:
    assert client_ip(_request("10.0.0.5", "1.2.3.4")) == "10.0.0.5"


def test_hote_non_ip_ignore() -> None:
    assert client_ip(_request("testclient")) is None


@pytest.mark.parametrize(
    ("forwarded", "expected"),
    [
        ("41.79.1.2", "41.79.1.2"),
        # L'entrée de gauche est contrôlée par le client : seule la dernière fait foi.
        ("6.6.6.6, 41.79.1.2", "41.79.1.2"),
        ("pas-une-ip", None),
        ("2c0f:f0f8::1", "2c0f:f0f8::1"),
    ],
)
def test_derriere_un_proxy_de_confiance(
    monkeypatch: pytest.MonkeyPatch, forwarded: str, expected: str | None
) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 1)
    assert client_ip(_request("10.0.0.1", forwarded)) == expected
