"""Pièces justificatives : envoi, dédoublonnage, chiffrement, conservation, droits.

Le stockage est le vrai Garage de la pile (bucket « kora-test »), comme Mailpit pour
les emails : rien n'est simulé côté S3, sauf pour provoquer des pannes.
"""

import hashlib
import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from dramatiq.brokers.stub import StubBroker
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from kora.attachments import service
from kora.core.config import get_settings
from kora.core.errors import ServiceUnavailableError
from kora.db.session import get_sessionmaker
from kora.storage import objects
from kora.worker.broker import broker
from tests.conftest import CompanyFixture, UserFixture
from tests.ledger_helpers import Ledger

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]

SALE = [("571", 1_500_000, 0), ("701", 0, 1_500_000)]
PDF = b"%PDF-1.7\n" + os.urandom(4096) + b"\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(512)
JPEG = b"\xff\xd8\xff\xe0" + os.urandom(512)
WEBP = b"RIFF\x00\x10\x00\x00WEBPVP8 " + os.urandom(512)


@pytest.fixture
def ledger(client: TestClient, make_company: MakeCompany) -> Ledger:
    return Ledger(client, make_company())


def _draft(ledger: Ledger) -> str:
    created = ledger.create(SALE)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _upload(
    ledger: Ledger,
    entry_id: str,
    content: bytes,
    filename: str = "facture.pdf",
    headers: dict[str, str] | None = None,
) -> Any:
    return ledger.client.post(
        f"{ledger.base}/entries/{entry_id}/attachments",
        params={"filename": filename},
        content=content,
        headers={**(headers or ledger.company.headers), "Content-Type": "application/pdf"},
    )


def _list(ledger: Ledger, entry_id: str) -> list[dict[str, Any]]:
    response = ledger.client.get(
        f"{ledger.base}/entries/{entry_id}/attachments", headers=ledger.company.headers
    )
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()
    return result


def _object_exists(key: str) -> bool:
    try:
        objects._client().head_object(Bucket=get_settings().s3_bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise
    return True


def _key(ledger: Ledger, attachment_id: str) -> str:
    return service.storage_key(ledger.company.id, uuid.UUID(attachment_id))


# --- Envoi et lecture


def test_envoi_liste_et_telechargement(ledger: Ledger) -> None:
    entry_id = _draft(ledger)
    response = _upload(ledger, entry_id, PDF, "Facture n°12 – SOTELGUI.pdf")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["entry_id"] == entry_id
    assert body["filename"] == "Facture n°12 – SOTELGUI.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(PDF)
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert [a["id"] for a in _list(ledger, entry_id)] == [body["id"]]

    content = ledger.client.get(
        f"{ledger.base}/attachments/{body['id']}/content", headers=ledger.company.headers
    )
    assert content.status_code == 200
    assert content.content == PDF
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert (
        "filename*=UTF-8''Facture%20n%C2%B012%20%E2%80%93%20SOTELGUI.pdf"
        in (content.headers["content-disposition"])
    )
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["cache-control"] == "private, no-store"

    inline = ledger.client.get(
        f"{ledger.base}/attachments/{body['id']}/content",
        params={"disposition": "inline"},
        headers=ledger.company.headers,
    )
    assert inline.headers["content-disposition"].startswith("inline;")


@pytest.mark.parametrize(
    ("content", "expected"),
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp"), (PDF, "application/pdf")],
)
def test_le_type_est_lu_dans_le_fichier(ledger: Ledger, content: bytes, expected: str) -> None:
    # L'en-tête Content-Type envoyé (toujours application/pdf ici) est ignoré.
    response = _upload(ledger, _draft(ledger), content, "photo")
    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == expected


@pytest.mark.parametrize(
    "content",
    [b"<html><script>alert(1)</script></html>", b"MZ\x90\x00 executable", b"PK\x03\x04 zip"],
)
def test_formats_refuses(ledger: Ledger, content: bytes) -> None:
    entry_id = _draft(ledger)
    response = _upload(ledger, entry_id, content, "facture.pdf")
    assert response.status_code == 422
    assert "PDF, JPEG, PNG ou WebP" in response.json()["detail"]
    assert _list(ledger, entry_id) == []


def test_fichier_vide_refuse(ledger: Ledger) -> None:
    assert _upload(ledger, _draft(ledger), b"").status_code == 422


def test_fichier_trop_volumineux(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "attachment_max_bytes", 2048)
    entry_id = _draft(ledger)
    response = _upload(ledger, entry_id, PDF)
    assert response.status_code == 413
    assert response.json()["code"] == "fichier_trop_volumineux"
    assert _list(ledger, entry_id) == []


def test_meme_fichier_renvoye_une_seule_piece(ledger: Ledger) -> None:
    """Réessai après une coupure réseau (3G) : le même fichier n'est pas dupliqué."""
    entry_id = _draft(ledger)
    first = _upload(ledger, entry_id, PDF)
    again = _upload(ledger, entry_id, PDF, "autre-nom.pdf")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["filename"] == "facture.pdf"
    assert len(_list(ledger, entry_id)) == 1
    # Le même fichier peut justifier une autre écriture.
    assert _upload(ledger, _draft(ledger), PDF).status_code == 201


def test_nombre_de_pieces_limite(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "attachments_per_entry", 2)
    entry_id = _draft(ledger)
    assert _upload(ledger, entry_id, PNG).status_code == 201
    assert _upload(ledger, entry_id, JPEG).status_code == 201
    third = _upload(ledger, entry_id, PDF)
    assert third.status_code == 422
    assert "au plus 2 pièces" in third.json()["detail"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\Awa\\reçu.jpg", "reçu.jpg"),
        ("fac\x00ture\n.pdf", "facture.pdf"),
        ("   ", "piece"),
        ("..", "piece"),
        ("e\u0301te\u0301.pdf", "été.pdf"),
        ("x" * 300 + ".pdf", "x" * 200),
    ],
)
def test_nom_de_fichier_nettoye(raw: str, expected: str) -> None:
    assert service.clean_filename(raw) == expected


# --- Chiffrement et intégrité


def test_objet_chiffre_dans_le_stockage(ledger: Ledger) -> None:
    attachment_id = _upload(ledger, _draft(ledger), PDF).json()["id"]
    blob = objects.get(_key(ledger, attachment_id))
    assert PDF[:64] not in blob
    assert b"%PDF" not in blob
    # Nonce (12 octets) + texte chiffré + étiquette GCM (16 octets).
    assert len(blob) == len(PDF) + 28


def test_objet_altere_detecte(ledger: Ledger) -> None:
    attachment_id = _upload(ledger, _draft(ledger), PDF).json()["id"]
    key = _key(ledger, attachment_id)
    blob = bytearray(objects.get(key))
    blob[100] ^= 0xFF
    objects._client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=bytes(blob))
    response = ledger.client.get(
        f"{ledger.base}/attachments/{attachment_id}/content", headers=ledger.company.headers
    )
    assert response.status_code == 409
    assert "illisible" in response.json()["detail"]


def test_objet_deplace_sous_une_autre_cle_illisible(ledger: Ledger) -> None:
    """Le nom de l'objet est authentifié : copier l'objet d'une pièce à la place d'une
    autre (même dossier) ne permet pas de substituer un document."""
    entry_id = _draft(ledger)
    first = _upload(ledger, entry_id, PDF).json()["id"]
    second = _upload(ledger, entry_id, PNG).json()["id"]
    blob = objects.get(_key(ledger, first))
    objects._client().put_object(
        Bucket=get_settings().s3_bucket, Key=_key(ledger, second), Body=blob
    )
    response = ledger.client.get(
        f"{ledger.base}/attachments/{second}/content", headers=ledger.company.headers
    )
    assert response.status_code == 409


# --- Retrait et conservation


def test_retrait_d_une_piece_de_brouillon(ledger: Ledger) -> None:
    entry_id = _draft(ledger)
    attachment_id = _upload(ledger, entry_id, PDF).json()["id"]
    key = _key(ledger, attachment_id)
    assert _object_exists(key)
    response = ledger.client.delete(
        f"{ledger.base}/attachments/{attachment_id}", headers=ledger.company.headers
    )
    assert response.status_code == 204
    assert _list(ledger, entry_id) == []
    assert not _object_exists(key)


def test_piece_d_une_ecriture_validee_conservee(ledger: Ledger) -> None:
    entry_id = _draft(ledger)
    attachment_id = _upload(ledger, entry_id, PDF).json()["id"]
    assert ledger.post(entry_id).status_code == 200

    # Un justificatif peut encore être ajouté après la validation…
    assert _upload(ledger, entry_id, PNG, "recu.png").status_code == 201
    # … mais aucun ne peut être retiré.
    response = ledger.client.delete(
        f"{ledger.base}/attachments/{attachment_id}", headers=ledger.company.headers
    )
    assert response.status_code == 409
    assert "conservée" in response.json()["detail"]
    assert len(_list(ledger, entry_id)) == 2
    assert _object_exists(_key(ledger, attachment_id))


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("DELETE FROM attachments WHERE id = :id", "suppression interdite"),
        ("UPDATE attachments SET filename = 'x' WHERE id = :id", "modification interdite"),
    ],
)
@pytest.mark.parametrize("role", ["application", "proprietaire"])
def test_conservation_imposee_par_la_base(
    ledger: Ledger, owner_engine: Engine, statement: str, message: str, role: str
) -> None:
    entry_id = _draft(ledger)
    attachment_id = _upload(ledger, entry_id, PDF).json()["id"]
    assert ledger.post(entry_id).status_code == 200
    engine = owner_engine if role == "proprietaire" else get_sessionmaker().kw["bind"]
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(ledger.company.id)}
        )
        with pytest.raises(DBAPIError, match=message):
            connection.execute(text(statement), {"id": attachment_id})
        connection.rollback()
        connection.execute(text("SELECT set_config('app.tenant_id', '', false)"))


def test_suppression_d_un_brouillon_avec_pieces(ledger: Ledger) -> None:
    entry_id = _draft(ledger)
    keys = [_key(ledger, _upload(ledger, entry_id, c).json()["id"]) for c in (PDF, PNG)]
    response = ledger.client.delete(
        f"{ledger.base}/entries/{entry_id}", headers=ledger.company.headers
    )
    assert response.status_code == 204, response.text
    assert not any(_object_exists(k) for k in keys)


def test_audit_des_pieces(ledger: Ledger) -> None:
    entry_id = _draft(ledger)
    attachment_id = _upload(ledger, entry_id, PDF).json()["id"]
    ledger.client.delete(
        f"{ledger.base}/attachments/{attachment_id}", headers=ledger.company.headers
    )
    events = ledger.client.get(
        f"{ledger.base}/audit-events", headers=ledger.company.headers
    ).json()["items"]
    actions = {e["action"]: e for e in events if e["entity_type"] == "attachment"}
    assert set(actions) == {"attachment.added", "attachment.removed"}
    added = actions["attachment.added"]
    assert added["entity_id"] == attachment_id
    assert added["payload"] == {
        "entry_id": entry_id,
        "filename": "facture.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        "sha256": hashlib.sha256(PDF).hexdigest(),
    }


# --- Droits


def test_lecteur_consulte_sans_modifier(
    client: TestClient, ledger: Ledger, make_user: MakeUser
) -> None:
    entry_id = _draft(ledger)
    attachment_id = _upload(ledger, entry_id, PDF).json()["id"]
    reader = make_user()
    added = client.post(
        f"{ledger.base}/members",
        headers=ledger.company.headers,
        json={"email": reader.email, "role": "PME_LECTEUR"},
    )
    assert added.status_code == 201
    headers = reader.headers(client)

    listed = client.get(f"{ledger.base}/entries/{entry_id}/attachments", headers=headers)
    assert listed.status_code == 200
    content = client.get(f"{ledger.base}/attachments/{attachment_id}/content", headers=headers)
    assert content.content == PDF
    assert _upload(ledger, entry_id, PNG, headers=headers).status_code == 403
    removed = client.delete(f"{ledger.base}/attachments/{attachment_id}", headers=headers)
    assert removed.status_code == 403


def test_piece_d_un_autre_dossier_introuvable(ledger: Ledger, make_company: MakeCompany) -> None:
    attachment_id = _upload(ledger, _draft(ledger), PDF).json()["id"]
    other = make_company(owner=ledger.company.owner)
    base = f"/api/v1/companies/{other.id}"
    headers = ledger.company.headers
    assert (
        ledger.client.get(f"{base}/attachments/{attachment_id}/content", headers=headers)
    ).status_code == 404
    assert (
        ledger.client.delete(f"{base}/attachments/{attachment_id}", headers=headers).status_code
        == 404
    )
    # Écriture d'un autre dossier : pas d'ajout possible.
    foreign_entry = _draft(Ledger(ledger.client, other))
    response = ledger.client.post(
        f"{ledger.base}/entries/{foreign_entry}/attachments",
        params={"filename": "x.pdf"},
        content=PDF,
        headers=headers,
    )
    assert response.status_code == 404


# --- Pannes du stockage


def test_stockage_indisponible(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_: object) -> None:
        raise ServiceUnavailableError("Le stockage des pièces est momentanément indisponible.")

    monkeypatch.setattr(objects, "put", unavailable)
    entry_id = _draft(ledger)
    response = _upload(ledger, entry_id, PDF)
    assert response.status_code == 503
    assert _list(ledger, entry_id) == []


def test_echec_en_base_retire_l_objet(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("panne simulée après l'écriture de l'objet")

    monkeypatch.setattr(service, "_audit", broken)
    entry_id = _draft(ledger)
    with pytest.raises(RuntimeError):
        _upload(ledger, entry_id, PDF)
    listed = objects._client().list_objects_v2(
        Bucket=get_settings().s3_bucket, Prefix=f"attachments/{ledger.company.id}/"
    )
    assert listed.get("KeyCount", 0) == 0
    assert _list(ledger, entry_id) == []


def test_suppression_differee_si_le_stockage_ne_repond_pas(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry_id = _draft(ledger)
    attachment_id = _upload(ledger, entry_id, PDF).json()["id"]

    def unreachable(_: str) -> None:
        raise EndpointConnectionError(endpoint_url="http://storage:3900")

    monkeypatch.setattr(objects, "delete", unreachable)
    response = ledger.client.delete(
        f"{ledger.base}/attachments/{attachment_id}", headers=ledger.company.headers
    )
    assert response.status_code == 204
    assert _list(ledger, entry_id) == []
    assert isinstance(broker, StubBroker)
    queued = [m.decode() for m in broker.queues["default"].queue]
    assert any("delete_stored_object" in m and _key(ledger, attachment_id) in m for m in queued)
