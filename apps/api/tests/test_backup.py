"""Sauvegardes chiffrées, contre le Garage de test (préfixe propre à chaque test)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kora.core.config import get_settings
from kora.scripts import backup
from kora.storage import objects


@pytest.fixture(autouse=True)
def _prefixe_isole(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup, "PREFIX", f"backups-test-{uuid.uuid4().hex}/")


def _dump(tmp_path: Path, name: str = "kora-20261025T023000Z.dump") -> tuple[Path, bytes]:
    content = b"PGDMP" + os.urandom(200_000)
    path = tmp_path / name
    path.write_bytes(content)
    return path, content


def test_envoi_verifie_et_restauration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path, content = _dump(tmp_path)
    key = backup.upload(path)
    assert key == f"{backup.PREFIX}kora-20261025T023000Z.dump.enc"
    raw = objects.get(key)
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
    data = bytearray(objects.get(key))
    data[-10] ^= 0xFF
    objects._client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=bytes(data))
    with pytest.raises(objects.CorruptedObjectError):
        backup.download_bytes(key)


def test_sauvegarde_vide_refusee(tmp_path: Path) -> None:
    empty = tmp_path / "vide.dump"
    empty.write_bytes(b"")
    with pytest.raises(SystemExit, match="vide"):
        backup.upload(empty)


def test_purge_garde_toujours_les_sept_plus_recentes(tmp_path: Path) -> None:
    keys = [backup.upload(_dump(tmp_path, f"kora-{n:02d}.dump")[0]) for n in range(9)]
    # Dans 10 jours : rien n'est assez ancien.
    assert backup.prune(30, now=datetime.now(UTC) + timedelta(days=10)) == []
    # Dans 60 jours : toutes sont anciennes, mais les sept plus récentes restent.
    removed = backup.prune(30, now=datetime.now(UTC) + timedelta(days=60))
    assert sorted(removed) == sorted(keys[:2])
    assert [k for k, _, _ in backup.list_backups()] == keys[2:]
