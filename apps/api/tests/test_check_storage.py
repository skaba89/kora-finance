"""Commande de vérification du stockage, contre le Garage de test."""

import pytest
from botocore.exceptions import ClientError

from kora.core.config import get_settings
from kora.scripts import check_storage
from kora.storage import objects


def _run() -> tuple[bool, list[str]]:
    lines: list[str] = []
    return check_storage.run(lines.append), lines


def test_verification_complete_sans_trace() -> None:
    ok, lines = _run()
    assert [line for line in lines if line.startswith("OK")] == [
        "OK  bucket accessible",
        "OK  écriture d'un objet chiffré",
        "OK  relecture et déchiffrement identiques",
        "OK  suppression",
    ]
    # La clé locale voit aussi le bucket « kora » de la pile : signalé, comme une clé
    # de production trop large le serait.
    assert not ok
    assert any("autre(s) bucket(s)" in line for line in lines)
    assert not any(get_settings().s3_secret_access_key.get_secret_value() in line for line in lines)
    remaining = objects._client().list_objects_v2(
        Bucket=get_settings().s3_bucket, Prefix=check_storage._PREFIX
    )
    assert remaining.get("KeyCount", 0) == 0


def test_bucket_inaccessible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "s3_bucket", "bucket-inexistant-kora")
    ok, lines = _run()
    assert not ok
    assert lines[-2].startswith("ÉCHEC : bucket inaccessible")


def test_cle_restreinte_et_https_sans_avertissement(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_: object, **__: object) -> None:
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListBuckets")

    monkeypatch.setattr(objects._client(), "list_buckets", denied)
    ok, lines = _run()
    # Seul reste l'avertissement http:// du Garage local.
    assert [line for line in lines if line.startswith("ATTENTION")] == [
        "ATTENTION : le point d'accès n'est pas en https:// (refusé en production)"
    ]
    assert not ok
