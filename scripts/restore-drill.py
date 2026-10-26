"""Exercice de restauration synthétique, sans paramètre de connexion à la production.

Crée son propre projet Compose, ses secrets et ses volumes. Seul un rapport de
contrôle sans secrets est conservé ; l'archive et les clés temporaires sont effacées.
"""

import base64
import json
import os
import secrets
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project = "kora-drill-" + uuid.uuid4().hex[:16]
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="kora-drill-") as directory:
        archive = Path(directory)
        values = {
            "KORA_DRILL_ID": project,
            "KORA_DRILL_UID": str(os.getuid()),
            "KORA_DRILL_GID": str(os.getgid()),
            "KORA_DRILL_ARCHIVE_DIR": str(archive),
            "KORA_DRILL_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            "KORA_DRILL_S3_KEY_ID": "GK" + secrets.token_hex(12),
            **{
                "KORA_DRILL_" + name: secrets.token_hex(32)
                for name in (
                    "ADMIN_PASSWORD",
                    "OWNER_PASSWORD",
                    "APP_PASSWORD",
                    "JWT_SECRET",
                    "RPC_SECRET",
                    "ADMIN_TOKEN",
                    "S3_SECRET",
                )
            },
        }
        escrow = archive / "synthetic-keys.env"
        escrow.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        escrow.chmod(0o600)
        # Aucun héritage des paramètres Compose ou KORA du poste appelant.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("KORA_", "COMPOSE_"))
        }
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(escrow),
            "-f",
            str(ROOT / "compose.restore-drill.yml"),
        ]

        def run(
            args: list[str], *, output: BinaryIO | None = None, source: BinaryIO | None = None
        ) -> None:
            result = subprocess.run(  # noqa: S603 (commandes internes fixes, projet aléatoire)
                args,
                cwd=ROOT,
                env=env,
                stdin=source,
                stdout=output if output is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode:
                error = result.stderr.decode(errors="replace")
                for value in values.values():
                    error = error.replace(value, "[REDACTED]")
                raise RuntimeError(f"Étape de restauration en échec : {error[-6000:]}")

        def tools(side: str, phase: str) -> None:
            run(
                [
                    *compose,
                    "run",
                    "--rm",
                    "--no-deps",
                    f"{side}-tools",
                    "python",
                    "-m",
                    "tests.restore_drill_support",
                    phase,
                ]
            )

        try:
            print("Construction de l'outillage synthétique…", flush=True)
            run([*compose, "build", "source-tools"])
            run([*compose, "up", "-d", "--wait", "postgres-source", "storage-source", "redis"])
            run([*compose, "run", "--rm", "--no-deps", "init-source"])
            run(
                [*compose, "run", "--rm", "--no-deps", "source-tools", "alembic", "upgrade", "head"]
            )
            tools("source", "seed")
            with (archive / "source.dump").open("wb") as dump:
                run(
                    [
                        *compose,
                        "exec",
                        "-T",
                        "postgres-source",
                        "pg_dump",
                        "-U",
                        "kora_admin",
                        "-d",
                        "kora_drill",
                        "-Fc",
                    ],
                    output=dump,
                )
            tools("source", "archive")
            print("Sauvegarde chiffrée créée ; suppression de la source synthétique…", flush=True)
            recovery_start = time.monotonic()
            run([*compose, "rm", "--force", "--stop", "postgres-source", "storage-source", "redis"])
            for name in ("postgres_source", "storage_source"):
                run(["docker", "volume", "rm", f"{project}_{name}"])
            run([*compose, "up", "-d", "--wait", "postgres-target", "storage-target", "redis"])
            run([*compose, "run", "--rm", "--no-deps", "init-target"])
            tools("target", "recover")
            with (archive / "restored.dump").open("rb") as dump:
                run(
                    [
                        *compose,
                        "exec",
                        "-T",
                        "postgres-target",
                        "pg_restore",
                        "-U",
                        "kora_admin",
                        "-d",
                        "kora_drill",
                        "--clean",
                        "--if-exists",
                        "--single-transaction",
                    ],
                    source=dump,
                )
            tools("target", "verify")
            report = json.loads((archive / "report.json").read_text())
            report.update(
                {
                    "source_volumes_destroyed": True,
                    "recovery_seconds_synthetic": round(time.monotonic() - recovery_start, 2),
                    "total_seconds": round(time.monotonic() - start, 2),
                    "created_at": datetime.now(UTC).isoformat(),
                    "code_ref": os.environ.get("GITHUB_SHA", "local"),
                    "production_pra_validated": False,
                }
            )
            destination = ROOT / "artifacts" / "restore-drill.json"
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(json.dumps(report, indent=2) + "\n")
            print(
                "Restauration synthétique vérifiée ; rapport : artifacts/restore-drill.json",
                flush=True,
            )
        finally:
            # Les seuls volumes supprimés appartiennent au projet créé ci-dessus.
            run([*compose, "down", "--volumes", "--remove-orphans"])


if __name__ == "__main__":
    main()
