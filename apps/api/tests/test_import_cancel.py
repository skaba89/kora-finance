"""Annulation d'un batch d'import non validé (IMP-3).

Contrats vérifiés : un dépôt simple disparaît (référence + objet chiffré,
capacité libérée) ; un batch confirmé voit ses brouillons encore présents
supprimés dans une transaction unique ; toute écriture déjà validée interdit
l'annulation (409, contre-passation obligatoire) ; le même fichier peut être
redéposé aussitôt (reprise) ; isolation inter-dossiers et rôles ; sérialisation
sur le verrou de ligne du batch.
"""

import threading
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from queue import Empty, Queue
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from kora.accounting.entries import Actor
from kora.accounting.import_cancel import cancel_staged_import
from kora.auth.service import RequestContext
from kora.db.session import get_engine, get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.common import utcnow
from kora.models.identity import CompanyMembership, User
from kora.models.imports import ImportBatch, ImportBatchEntry
from kora.models.ledger import EntryStatus, JournalEntry
from kora.storage import objects
from kora.tenancy.roles import Role
from tests.conftest import CompanyFixture, UserFixture
from tests.test_import_service import HEADER

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]

URL = "/api/v1/companies/{company_id}/accounting-imports"


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}

    def put(key: str, sealed: objects.SealedObject) -> None:
        assert key not in blobs
        blobs[key] = sealed.blob

    def get(key: str, *, max_bytes: int | None = None) -> bytes:
        return blobs[key]

    monkeypatch.setattr(objects, "put", put)
    monkeypatch.setattr(objects, "get", get)
    monkeypatch.setattr(objects, "delete", lambda key: blobs.pop(key, None))
    return blobs


def _upload(client: TestClient, company: CompanyFixture, content: bytes) -> str:
    response = client.post(
        URL.format(company_id=company.id),
        params={"file_format": "csv", "source_currency": "GNF"},
        headers=company.headers,
        content=content,
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _cancel(client: TestClient, company: CompanyFixture, batch_id: str) -> Any:
    return client.post(
        f"{URL.format(company_id=company.id)}/{batch_id}/cancel", headers=company.headers
    )


def _confirm(client: TestClient, company: CompanyFixture, batch_id: str) -> Any:
    return client.post(
        f"{URL.format(company_id=company.id)}/{batch_id}/confirm", headers=company.headers
    )


def _csv_deux_ecritures() -> bytes:
    """Deux écritures équilibrées du journal VT ; libellé partagé par écriture."""
    return (
        HEADER
        + "VT;FA-2026-001;2026-02-01;571;Vente comptant;1500000;0\n"
        + "VT;FA-2026-001;2026-02-01;701;Vente comptant;0;1500000\n"
        + "VT;FA-2026-002;2026-02-10;571;Vente à crédit;3000000;0\n"
        + "VT;FA-2026-002;2026-02-10;411;Vente à crédit;0;3000000\n"
    ).encode()


def test_cancel_un_depot_simple_libere_immediatement(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    assert len(storage) == 1
    reponse = _cancel(client, company, batch_id)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["entries_removed"], corps["lines_removed"]) == (0, 0)
    assert corps["cancelled_at"]
    # La référence, le rapport et l'objet chiffré ont disparu.
    assert len(storage) == 0
    relit = client.get(
        f"{URL.format(company_id=company.id)}/{batch_id}/precheck", headers=company.headers
    )
    assert relit.status_code == 404
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert db.scalar(select(func.count()).select_from(ImportBatchEntry)) == 0
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0
    # Traçabilité : l'annulation d'un dépôt laisse une trace dédiée.
    evenement = db.execute(
        select(AuditEvent).where(AuditEvent.action == "import.cancelled")
    ).scalar_one()
    assert evenement.entity_type == "accounting_import_batch"
    assert evenement.payload["brouillons"] == 0


def test_cancel_supprime_les_brouillons_encore_presents(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    confirme = _confirm(client, company, batch_id)
    assert confirme.status_code == 200, confirme.text
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 2
    db.rollback()
    reponse = _cancel(client, company, batch_id)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["entries_removed"], corps["lines_removed"]) == (2, 4)
    # Tout ou rien : brouillons, liens, référence et objet partent ensemble.
    assert len(storage) == 0
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0
    assert db.scalar(select(func.count()).select_from(ImportBatchEntry)) == 0
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 0
    # La chaîne d'audit garde les deux actes : confirmation puis annulation.
    confirmation = db.execute(
        select(AuditEvent).where(AuditEvent.action == "import.confirmed")
    ).scalar_one()
    assert confirmation.payload["entrees"] == 2
    annulation = db.execute(
        select(AuditEvent).where(AuditEvent.action == "import.cancelled")
    ).scalar_one()
    assert annulation.payload["brouillons"] == 2
    assert annulation.payload["lignes"] == 4
    assert annulation.payload["confirmes"] == 2


def test_cancel_refuse_une_ecriture_deja_validee(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    confirme = _confirm(client, company, batch_id)
    assert confirme.status_code == 200, confirme.text
    bind_tenant(db, company.id)
    premiere = db.scalars(select(JournalEntry).order_by(JournalEntry.created_at)).first()
    assert premiere is not None
    db.commit()
    # Le brouillon est validé par son auteur : le batch n'est plus annulable.
    valider = client.post(
        f"/api/v1/companies/{company.id}/entries/{premiere.id}/post", headers=company.headers
    )
    assert valider.status_code == 200, valider.text
    refuse = _cancel(client, company, batch_id)
    assert refuse.status_code == 409, refuse.text
    assert "contre-passation" in refuse.text
    # Rien n'a été détruit : ni les écritures, ni le batch, ni l'objet chiffré.
    db.expire_all()  # la validation a eu lieu hors session : purge le cache local.
    bind_tenant(db, company.id)
    entrees = db.execute(select(JournalEntry)).scalars().all()
    assert {entree.status for entree in entrees} == {EntryStatus.DRAFT, EntryStatus.POSTED}
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 1
    assert db.scalar(select(func.count()).select_from(ImportBatchEntry)) == 2
    assert len(storage) == 1
    refuses = db.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "import.cancelled")
    ).scalar_one()
    assert refuses == 0


def test_cancel_puis_reprise_du_meme_fichier(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    """Après annulation, le même fichier repart sur un batch neuf, confirmable."""
    company = make_company()
    contenu = _csv_deux_ecritures()
    premier = _upload(client, company, contenu)
    assert _confirm(client, company, premier).status_code == 200
    assert _cancel(client, company, premier).status_code == 200
    second = _upload(client, company, contenu)
    assert second != premier
    precheck = client.post(
        f"{URL.format(company_id=company.id)}/{second}/precheck", headers=company.headers
    )
    assert precheck.status_code == 200, precheck.text
    assert precheck.json()["valid"] is True
    confirme = _confirm(client, company, second)
    assert confirme.status_code == 200, confirme.text
    assert confirme.json()["entries"] == 2
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 2
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 1


def test_cancel_isole_par_dossier_et_par_role(
    db: Session,
    client: TestClient,
    make_company: MakeCompany,
    make_user: MakeUser,
    storage: dict[str, bytes],
) -> None:
    mine, other = make_company(), make_company()
    batch_id = _upload(client, mine, _csv_deux_ecritures())
    assert _cancel(client, other, batch_id).status_code == 404
    lecteur = make_user()
    db.add(CompanyMembership(company_id=mine.id, user_id=lecteur.id, role=Role.PME_LECTEUR))
    db.commit()
    refuse = client.post(
        f"{URL.format(company_id=mine.id)}/{batch_id}/cancel", headers=lecteur.headers(client)
    )
    assert refuse.status_code == 403
    # Les refus n'ont rien changé : le dirigeant annule toujours son dépôt.
    assert _cancel(client, mine, batch_id).status_code == 200
    assert _cancel(client, mine, batch_id).status_code == 404


def test_cancel_inconnu_ou_expire_repond_404(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    assert _cancel(client, company, str(uuid.uuid4())).status_code == 404
    batch_id = _upload(client, company, _csv_deux_ecritures())
    bind_tenant(db, company.id)
    batch = db.get_one(ImportBatch, uuid.UUID(batch_id))
    batch.created_at = utcnow() - timedelta(days=2)
    batch.expires_at = utcnow() - timedelta(days=1)
    db.commit()
    assert _cancel(client, company, batch_id).status_code == 404
    # Un batch expiré refusé reste entier : la purge worker reste maîtresse.
    assert len(storage) == 1


def test_cancel_attend_le_verrou_du_batch(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    """Une annulation simultanée d'une confirmation attend le verrou puis s'exécute."""
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    holder = get_sessionmaker()()
    bind_tenant(holder, company.id)
    holder.begin()
    holder.execute(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == company.id, ImportBatch.id == uuid.UUID(batch_id))
        .with_for_update()
    )
    resultat: Queue[BaseException | None] = Queue()

    def annuler_reel() -> None:
        try:
            with get_sessionmaker()() as session:
                bind_tenant(session, company.id)
                user = session.get_one(User, company.owner.id)
                cancel_staged_import(
                    user,
                    company.id,
                    uuid.UUID(batch_id),
                    actor=Actor(company.id, user.id, RequestContext()),
                )
            resultat.put(None)
        except BaseException as exc:
            resultat.put(exc)

    thread = threading.Thread(target=annuler_reel)
    thread.start()
    echeance = time.monotonic() + 5.0
    bloque = False
    with get_engine().connect() as observer:
        while time.monotonic() < echeance and thread.is_alive():
            attente = observer.execute(
                text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            ).scalar_one()
            if attente:
                bloque = True
                break
            time.sleep(0.05)
    assert bloque, "l'annulation concurrente devrait attendre le verrou du batch"
    holder.commit()
    holder.close()
    thread.join(timeout=30)
    assert thread.is_alive() is False
    try:
        erreur = resultat.get_nowait()
    except Empty as exc:
        raise AssertionError("l'annulation concurrente n'a pas abouti") from exc
    assert erreur is None, erreur
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert len(storage) == 0
