"""Tests du correctif C3 — `resolve_out_dir` (module `kora.scripts.seed_demo`).

Sans base de données : tests unitaires purs du choix de répertoire.
Le cas « lecture seule » s'appuie sur un vrai répertoire chmod 0o555 (Linux/CI) ;
sur Windows (Git Bash), chmod est sans effet sur les répertoires : le test est
marqué skipif — la voie heureuse reste couverte partout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kora.scripts.seed_demo import _CP_HINT, _FALLBACK, resolve_out_dir


def test_repertoire_inscriptible_utilise_le_demande(tmp_path: Path) -> None:
    """Chemin heureux : le répertoire demandé est créé et retourné sans message."""
    out, message = resolve_out_dir(tmp_path / "demo")
    assert out == tmp_path / "demo"
    assert message is None
    assert out.is_dir()


def test_probe_nettoyee_dans_repertoire_valide(tmp_path: Path) -> None:
    """Le fichier-sonde n'est jamais laissé derrière lui."""
    out, _ = resolve_out_dir(tmp_path / "demo")
    assert not (out / ".kora-seed-probe").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="chmod de répertoire sans effet sur Windows")
def test_repertoire_lecture_seule_replie_vers_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Répertoire demandé refusé → repli créé + consigne docker compose cp."""
    verrou = tmp_path / "verrou"
    verrou.mkdir()
    verrou.chmod(0o555)  # lecture seule : mkdir dedans échoue avec PermissionError
    monkeypatch.setattr("kora.scripts.seed_demo._FALLBACK", tmp_path / "repli")
    try:
        out, message = resolve_out_dir(verrou / "demo")
        assert out == tmp_path / "repli"
        assert out.is_dir()
        assert message is not None
        assert "docker compose cp" in message
    finally:
        verrou.chmod(0o755)  # permettre le nettoyage de tmp_path


@pytest.mark.skipif(sys.platform == "win32", reason="chmod de répertoire sans effet sur Windows")
def test_echec_honnete_si_repli_impossible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Si même le repli est refusé, l'erreur remonte : jamais de perte silencieuse."""
    verrou = tmp_path / "verrou"
    verrou.mkdir()
    verrou.chmod(0o555)
    repli_verrouille = tmp_path / "repli-verrouille"
    repli_verrouille.mkdir()
    repli_verrouille.chmod(0o555)
    monkeypatch.setattr("kora.scripts.seed_demo._FALLBACK", repli_verrouille)
    try:
        # Sur un répertoire chmod 0o555, mkdir lève précisément PermissionError
        # (sous-classe d'OSError) : le test vérifie que l'erreur D'ORIGINE remonte.
        with pytest.raises(PermissionError):
            resolve_out_dir(verrou / "demo")
    finally:
        verrou.chmod(0o755)
        repli_verrouille.chmod(0o755)


def test_message_consigne_mentionne_le_container_et_l_hote() -> None:
    """La consigne affichée est exécutable telle quelle (api: + copie hôte)."""
    rendu = _CP_HINT.format(fallback=_FALLBACK)
    assert "docker compose cp" in rendu
    assert "api:" in rendu
    assert "./demo-export/" in rendu
