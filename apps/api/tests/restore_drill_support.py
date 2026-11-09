"""Support de l'exercice synthétique : aucune utilisation sur une base réelle.

Exécution dans compose.restore-drill.yml, après le garde-fou d'environnement.
Les seuls fichiers conservés par la CI sont des résultats de contrôle, jamais les clés.
"""

import argparse
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from kora.core.config import Environment, Settings, get_settings

ARCHIVE = Path("/drill")
MANIFEST = ARCHIVE / "manifest.json"
PIECE = b"%PDF-1.4\nJustificatif synthetique de restauration Kora.\n%%EOF\n"


def assert_isolated(settings: Settings, phase: str) -> None:
    """Échec fermé avant tout appel aux services, SQL ou S3."""
    side = "source" if phase in {"seed", "archive"} else "target"
    hosts = settings.database_url.hosts()
    endpoint = urlsplit(settings.s3_endpoint_url)
    if (
        os.environ.get("KORA_RESTORE_DRILL") != "synthetic-v1"
        or settings.env != Environment.TEST
        or len(hosts) != 1
        or hosts[0]["host"] != f"postgres-{side}"
        or hosts[0]["username"] != "kora_app"
        or settings.database_url.path != "/kora_drill"
        or endpoint.scheme != "http"
        or endpoint.hostname != f"storage-{side}"
        or endpoint.port != 3900
        or settings.s3_bucket != "kora-drill"
    ):
        raise RuntimeError("Exercice refusé : environnement synthétique isolé requis.")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save(manifest: dict[str, Any]) -> None:
    MANIFEST.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def _load() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST.read_text(encoding="utf-8")))


def _json(response: Any, expected: int = 200) -> dict[str, Any]:
    assert response.status_code == expected, f"Statut HTTP inattendu : {response.status_code}"
    return cast(dict[str, Any], response.json())


def _snapshot(companies: list[str]) -> dict[str, str]:
    from sqlalchemy import select  # noqa: PLC0415 (après garde-fou)

    from kora.db import models  # noqa: PLC0415, F401 (registre SQLAlchemy)
    from kora.db.base import Base  # noqa: PLC0415
    from kora.db.session import get_sessionmaker  # noqa: PLC0415
    from kora.db.tenant import bind_tenant  # noqa: PLC0415

    result = {}
    for company in [None, *companies]:
        with get_sessionmaker()() as session:
            bind_tenant(session, uuid.UUID(company) if company else None)
            for table in Base.metadata.sorted_tables:
                rows = session.execute(select(table).order_by(*table.primary_key.columns))
                values = [dict(row) for row in rows.mappings()]
                encoded = json.dumps(values, sort_keys=True, default=str).encode()
                result[f"{company or 'platform'}:{table.name}"] = _digest(encoded)
    return result


def seed() -> None:
    import pyotp  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from kora.main import create_app  # noqa: PLC0415

    tenants = []
    with TestClient(create_app()) as client:
        for index in range(2):
            password = "Drill-" + secrets.token_urlsafe(32) + "-7aA!"
            email = f"drill-{uuid.uuid4().hex}@exemple.gn"
            user = _json(
                client.post(
                    "/api/v1/auth/register",
                    json={"email": email, "password": password, "full_name": "PME fictive"},
                ),
                201,
            )
            pair = _json(
                client.post("/api/v1/auth/login", json={"email": email, "password": password})
            )
            headers = {"Authorization": f"Bearer {pair['access_token']}"}
            company = _json(
                client.post(
                    "/api/v1/companies",
                    headers=headers,
                    json={
                        "legal_name": f"PME synthétique {index}",
                        "legal_form": "SARL",
                        "first_fiscal_year": {"start_date": "2026-01-01", "end_date": "2026-12-31"},
                    },
                ),
                201,
            )
            base = f"/api/v1/companies/{company['id']}"
            journals = client.get(f"{base}/journals", headers=headers).json()
            journal = next(j["id"] for j in journals if j["code"] == "OD")
            accounts = {}
            for number in ("571", "701"):
                rows = _json(client.get(f"{base}/accounts", headers=headers, params={"q": number}))
                accounts[number] = next(a["id"] for a in rows["items"] if a["number"] == number)
            entry = _json(
                client.post(
                    f"{base}/entries",
                    headers=headers,
                    json={
                        "journal_id": journal,
                        "entry_date": "2026-06-30",
                        "label": "Vente synthétique",
                        "lines": [
                            {"account_id": accounts["571"], "debit": "1000", "credit": "0"},
                            {"account_id": accounts["701"], "debit": "0", "credit": "1000"},
                        ],
                    },
                ),
                201,
            )
            attachment = _json(
                client.post(
                    f"{base}/entries/{entry['id']}/attachments",
                    headers=headers,
                    params={"filename": "piece-synthetique.pdf"},
                    content=PIECE,
                ),
                201,
            )
            _json(client.post(f"{base}/entries/{entry['id']}/post", headers=headers))
            # L'enrôlement du second facteur exige la réauthentification (KF-08).
            setup = _json(
                client.post("/api/v1/auth/mfa/setup", headers=headers, json={"password": password})
            )
            _json(
                client.post(
                    "/api/v1/auth/mfa/enable",
                    headers=headers,
                    json={"password": password, "code": pyotp.TOTP(setup["secret"]).now()},
                )
            )
            tenants.append(
                {
                    "user_id": user["id"],
                    "company_id": company["id"],
                    "entry_id": entry["id"],
                    "attachment_id": attachment["id"],
                    "totp_fingerprint": _digest(setup["secret"].encode()),
                }
            )
    _save({"tenants": tenants, "snapshot": _snapshot([t["company_id"] for t in tenants])})


def archive() -> None:
    from kora.scripts import backup  # noqa: PLC0415
    from kora.storage import backups_store, objects  # noqa: PLC0415

    manifest = _load()
    dump = ARCHIVE / "source.dump"
    manifest["dump_sha256"] = _digest(dump.read_bytes())
    manifest["backup_key"] = backup.upload(dump)
    saved = []

    def _archiver(bucket: str, stockage: str, client: Any) -> None:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                raw = (objects if stockage == "pieces" else backups_store).get(key)
                filename = _digest(key.encode()) + ".blob"
                (ARCHIVE / filename).write_bytes(raw)
                saved.append(
                    {"key": key, "stockage": stockage, "filename": filename, "sha256": _digest(raw)}
                )

    _archiver(get_settings().s3_bucket, "pieces", objects._client())
    # Les sauvegardes vivent dans un bucket dédié (KF-09) : l'archive doit couvrir
    # les deux buckets, sinon la seule copie de la sauvegarde chiffrée disparaît.
    _archiver(backups_store.bucket(), "sauvegardes", backups_store._client())
    assert len(saved) == 3  # deux pièces chiffrées et une sauvegarde chiffrée
    manifest["objects"] = saved
    _save(manifest)
    dump.unlink()  # seule la sauvegarde chiffrée reste disponible après le sinistre


def recover() -> None:
    from cryptography.fernet import Fernet, InvalidToken  # noqa: PLC0415
    from pydantic import SecretStr  # noqa: PLC0415

    from kora.core import crypto  # noqa: PLC0415
    from kora.scripts import backup  # noqa: PLC0415
    from kora.storage import backups_store, objects  # noqa: PLC0415

    manifest = _load()
    assert not (ARCHIVE / "source.dump").exists()
    for item in manifest["objects"]:
        raw = (ARCHIVE / item["filename"]).read_bytes()
        assert _digest(raw) == item["sha256"]
        if item.get("stockage") == "sauvegardes":
            backups_store._client().put_object(
                Bucket=backups_store.bucket(), Key=item["key"], Body=raw
            )
        else:
            objects._client().put_object(Bucket=get_settings().s3_bucket, Key=item["key"], Body=raw)
    settings = get_settings()
    escrowed_key = settings.encryption_keys
    try:
        settings.encryption_keys = SecretStr(Fernet.generate_key().decode())
        crypto._cipher.cache_clear()
        try:
            backup.download_bytes(manifest["backup_key"])
        except (InvalidToken, objects.CorruptedObjectError):
            manifest["wrong_key_rejected"] = True
        else:
            raise AssertionError("La sauvegarde a été déchiffrée sans la clé séquestrée.")
    finally:
        settings.encryption_keys = escrowed_key
        crypto._cipher.cache_clear()
    restored = backup.download_bytes(manifest["backup_key"])
    assert _digest(restored) == manifest["dump_sha256"]
    (ARCHIVE / "restored.dump").write_bytes(restored)
    _save(manifest)


def _verify_database_security() -> None:
    from alembic.config import Config  # noqa: PLC0415
    from alembic.script import ScriptDirectory  # noqa: PLC0415
    from sqlalchemy import select, text  # noqa: PLC0415

    from kora.audit.service import verify_chain  # noqa: PLC0415
    from kora.db.session import get_sessionmaker  # noqa: PLC0415
    from kora.models.ledger import JournalEntry  # noqa: PLC0415

    with get_sessionmaker()() as session:
        expected_revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        assert (
            session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == expected_revision
        )
        privileges = session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert not privileges.rolsuper
        assert not privileges.rolbypassrls
        assert not session.execute(
            text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        ).scalar_one()
        rls = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid='journal_entries'::regclass"
            )
        ).one()
        assert rls.relrowsecurity
        assert rls.relforcerowsecurity
        assert session.execute(select(JournalEntry.id)).first() is None
        assert verify_chain(session).ok


def verify() -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from sqlalchemy.exc import DBAPIError  # noqa: PLC0415

    from kora.audit.service import verify_chain  # noqa: PLC0415
    from kora.auth.tokens import create_access_token  # noqa: PLC0415
    from kora.core.crypto import decrypt  # noqa: PLC0415
    from kora.db.session import get_sessionmaker  # noqa: PLC0415
    from kora.db.tenant import bind_tenant  # noqa: PLC0415
    from kora.main import create_app  # noqa: PLC0415
    from kora.models.identity import User  # noqa: PLC0415
    from kora.models.ledger import JournalEntry  # noqa: PLC0415

    manifest = _load()
    tenants = manifest["tenants"]
    assert _snapshot([t["company_id"] for t in tenants]) == manifest["snapshot"]
    _verify_database_security()
    with TestClient(create_app()) as client:
        for index, tenant in enumerate(tenants):
            with get_sessionmaker()() as session:
                user = session.get_one(User, uuid.UUID(tenant["user_id"]))
                assert user.totp_enabled_at is not None
                assert user.totp_secret_encrypted is not None
                assert (
                    _digest(decrypt(user.totp_secret_encrypted).encode())
                    == tenant["totp_fingerprint"]
                )
                headers = {
                    "Authorization": "Bearer " + create_access_token(user.id, user.token_version)
                }
                bind_tenant(session, uuid.UUID(tenant["company_id"]))
                assert verify_chain(session).ok
                other = tenants[1 - index]
                assert session.get(JournalEntry, uuid.UUID(other["entry_id"])) is None
                try:
                    session.execute(
                        text("UPDATE journal_lines SET debit=999 WHERE entry_id=:id AND debit>0"),
                        {"id": uuid.UUID(tenant["entry_id"])},
                    )
                except DBAPIError:
                    session.rollback()
                else:
                    raise AssertionError("L'immuabilité n'a pas été restaurée.")
            base = f"/api/v1/companies/{tenant['company_id']}"
            entry = _json(client.get(f"{base}/entries/{tenant['entry_id']}", headers=headers))
            assert entry["status"] == "POSTED"
            assert entry["total_debit"] == entry["total_credit"] == "1000"
            piece = client.get(
                f"{base}/attachments/{tenant['attachment_id']}/content", headers=headers
            )
            assert piece.status_code == 200
            assert piece.content == PIECE
            denied = client.get(
                f"/api/v1/companies/{other['company_id']}/entries/{other['entry_id']}",
                headers=headers,
            )
            assert denied.status_code == 404
            denied_piece = client.get(
                f"{base}/attachments/{other['attachment_id']}/content", headers=headers
            )
            assert denied_piece.status_code == 404
    report = {
        "synthetic_only": True,
        "database_restored": True,
        "migration_revision_verified": True,
        "snapshots_equal": True,
        "tenants_verified": 2,
        "attachments_decrypted": 2,
        "audit_chains_verified": 3,
        "rls_verified": True,
        "rbac_verified": True,
        "immutability_verified": True,
        "totp_secrets_decrypted": 2,
        "wrong_key_rejected": manifest["wrong_key_rejected"],
    }
    (ARCHIVE / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["seed", "archive", "recover", "verify"])
    phase = parser.parse_args().phase
    assert_isolated(get_settings(), phase)
    {"seed": seed, "archive": archive, "recover": recover, "verify": verify}[phase]()
    print(f"Exercice synthétique : phase {phase} réussie.")


if __name__ == "__main__":
    main()
