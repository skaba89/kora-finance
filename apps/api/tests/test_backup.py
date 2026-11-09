"""Sauvegardes chiffrées dans un bucket dédié (KF-09), contre le Garage de test.

Les tests pointent KORA_BACKUP_S3_* vers le bucket « kora » de la pile — distinct du
bucket des pièces (KORA_S3_BUCKET=kora-test) — avec un préfixe propre à chaque
exécution. Le test d'isolation prouve qu'une suppression par le chemin applicatif
(pièces) n'atteint pas une sauvegarde.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kora.core.config import get_settings
from kora.scripts import backup
from kora.storage import backups_store, objects

# Bucket des sauvegardes : DISTINCT du bucket des pièces (kora-test) utilisé par l'API.
BUCKET_SAUVEGARDES = "kora"


@pytest.fixture(autouse=True)
def _prefixe_isole(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = get_settings()
    monkeypatch.setattr(backup, "PREFIX", f"backups-test-{uuid.uuid4().hex}/")
    monkeypatch.setenv("KORA_BACKUP_S3_ENDPOINT_URL", settings.s3_endpoint_url)
    monkeypatch.setenv("KORA_BACKUP_S3_BUCKET", BUCKET_SAUVEGARDES)
    # En test, la même clé Garage couvre les deux buckets ; en production, la clé de
    # sauvegarde est distincte et sans droit de suppression (KF-09, cf. env.example).
    monkeypatch.setenv("KORA_BACKUP_S3_ACCESS_KEY_ID", settings.s3_access_key_id)
    monkeypatch.setenv(
        "KORA_BACKUP_S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key.get_secret_value()
    )
    # Pas de clé d'administration : la purge doit être refusée par défaut.
    monkeypatch.delenv("KORA_BACKUP_ADMIN_S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("KORA_BACKUP_ADMIN_S3_SECRET_ACCESS_KEY", raising=False)
    backups_store._client.cache_clear()
    yield
    backups_store._client.cache_clear()


def _dump(tmp_path: Path, name: str = "kora-20261025T023000Z.dump") -> tuple[Path, bytes]:
    content = b"PGDMP" + os.urandom(200_000)
    path = tmp_path / name
    path.write_bytes(content)
    return path, content


def test_envoi_verifie_et_restauration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, content = _dump(tmp_path)
    key = backup.upload(path)
    assert key == f"{backup.PREFIX}kora-20261025T023000Z.dump.enc"
    raw = backups_store.get(key)
    assert raw.startswith(b"KORA-BKP1")
    assert b"PGDMP" not in raw
    assert content[100:164] not in raw

    target = tmp_path / "restaure.dump"
    with pytest.raises(SystemExit) as exit_code:
        backup.main(["download", key, str(target)])
    assert exit_code.value.code == 0
    assert target.read_bytes() == content
    with pytest.raises(SystemExit):
        backup.main(["list"])
    assert "kora-20261025T023000Z.dump.enc" in capsys.readouterr().out


def test_sauvegarde_alteree_refusee(tmp_path: Path) -> None:
    path, _ = _dump(tmp_path)
    key = backup.upload(path)
    data = bytearray(backups_store.get(key))
    data[-10] ^= 0xFF
    backups_store._client().put_object(Bucket=backups_store.bucket(), Key=key, Body=bytes(data))
    with pytest.raises(objects.CorruptedObjectError):
        backup.download_bytes(key)


def test_sauvegarde_vide_refusee(tmp_path: Path) -> None:
    empty = tmp_path / "vide.dump"
    empty.write_bytes(b"")
    with pytest.raises(SystemExit, match="vide"):
        backup.upload(empty)


def test_purge_refusee_sans_cle_administration(tmp_path: Path) -> None:
    path, _ = _dump(tmp_path)
    backup.upload(path)
    with pytest.raises(SystemExit, match="Purge refusée"):
        backup.prune(30, now=datetime.now(UTC) + timedelta(days=60))
    # Rien n'a été supprimé.
    assert [k for k, _, _ in backup.list_backups()] == [backup.object_key(path.name)]


def test_purge_admin_garde_toujours_les_sept_plus_recentes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setenv("KORA_BACKUP_ADMIN_S3_ACCESS_KEY_ID", settings.s3_access_key_id)
    monkeypatch.setenv(
        "KORA_BACKUP_ADMIN_S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key.get_secret_value()
    )
    keys = [backup.upload(_dump(tmp_path, f"kora-{n:02d}.dump")[0]) for n in range(9)]
    # Dans 10 jours : rien n'est assez ancien.
    assert backup.prune(30, now=datetime.now(UTC) + timedelta(days=10)) == []
    # Dans 60 jours : toutes sont anciennes, mais les sept plus récentes restent.
    removed = backup.prune(30, now=datetime.now(UTC) + timedelta(days=60))
    assert sorted(removed) == sorted(keys[:2])
    assert [k for k, _, _ in backup.list_backups()] == keys[2:]


def test_client_sauvegardes_distinct_du_client_pieces() -> None:
    """Deux clients boto3 distincts : bucket et identifiants séparés (KF-09)."""
    assert backups_store.bucket() != get_settings().s3_bucket
    assert backups_store._client() is not objects._client()


def test_suppression_cote_pieces_natteint_pas_les_sauvegardes(tmp_path: Path) -> None:
    """Test d'acceptation KF-09 : avec les identifiants de l'application (pièces),
    tenter de supprimer une sauvegarde — même sous la même clé d'objet — la laisse
    intacte : elle vit dans un autre bucket, invisible de la clé applicative."""
    path, content = _dump(tmp_path)
    key = backup.upload(path)
    objects.delete(key)  # chemin applicatif : bucket des pièces uniquement
    assert backup.download_bytes(key) == content
