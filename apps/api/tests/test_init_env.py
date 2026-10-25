"""scripts/init-env.sh : génération et complétion des fichiers .env (local et production)."""

import re
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "init-env.sh"


def _run(root: Path) -> str:
    result = subprocess.run(  # noqa: S603  (script du dépôt, arguments fixes)
        ["bash", str(root / "scripts" / "init-env.sh"), "modele", "cible"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def _root(tmp_path: Path, template: str) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "init-env.sh")
    (tmp_path / "modele").write_text(template)
    return tmp_path


def test_creation_avec_secrets(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        "# commentaire\nA=1\nS=__GENERATE__\nF=__GENERATE_FERNET__\nK=__GENERATE_GARAGE_KEY_ID__\n",
    )
    _run(root)
    content = (root / "cible").read_text()
    assert content.startswith("# commentaire\nA=1\n")
    assert re.search(r"^S=[0-9a-f]{64}$", content, re.M)
    assert re.search(r"^F=[A-Za-z0-9_-]{43}=$", content, re.M)
    assert re.search(r"^K=GK[0-9a-f]{24}$", content, re.M)
    assert (root / "cible").stat().st_mode & 0o077 == 0


def test_completion_sans_toucher_l_existant_ni_les_choix_commentes(tmp_path: Path) -> None:
    root = _root(tmp_path, "A=1\nCOMPOSE_PROFILES=caddy\n# COMPOSE_FILE=x\nNOUVEAU=__GENERATE__\n")
    (root / "cible").write_text("A=9\n# COMPOSE_PROFILES=caddy\nCOMPOSE_FILE=x\n")
    output = _run(root)
    lines = (root / "cible").read_text().splitlines()
    assert lines[:3] == ["A=9", "# COMPOSE_PROFILES=caddy", "COMPOSE_FILE=x"]
    assert len(lines) == 4
    assert re.fullmatch(r"NOUVEAU=[0-9a-f]{64}", lines[3])
    assert "complété : NOUVEAU" in output
