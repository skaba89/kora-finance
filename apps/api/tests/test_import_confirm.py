"""Confirmation d'un import : brouillons générés en une transaction, jamais validés.

Contrats vérifiés : aucune écriture POSTED ni numéro consommé ; échec partiel
impossible (tout ou rien) ; un second appel ne duplique rien (verrou de ligne +
marqueur de confirmation) ; les références sont revérifiées au moment décisif
(journal désactivé, période verrouillée) ; isolation inter-dossiers et rôles.
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
from kora.accounting.import_confirm import confirm_staged_import
from kora.auth.service import RequestContext
from kora.db.session import get_engine, get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.audit import AuditEvent
from kora.models.common import utcnow
from kora.models.identity import CompanyMembership, User
from kora.models.imports import ImportBatch, ImportBatchEntry
from kora.models.ledger import EntryStatus, JournalEntry, JournalLine, JournalSequence
from kora.models.organization import FiscalYear
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


def _csv_deux_ecritures() -> bytes:
    """Deux écritures équilibrées du journal VT ; libellé partagé par écriture."""
    return (
        HEADER
        + "VT;FA-2026-001;2026-02-01;571;Vente comptant;1500000;0\n"
        + "VT;FA-2026-001;2026-02-01;701;Vente comptant;0;1500000\n"
        + "VT;FA-2026-002;2026-02-10;571;Vente à crédit;3000000;0\n"
        + "VT;FA-2026-002;2026-02-10;411;Vente à crédit;0;3000000\n"
    ).encode()


def _confirm(client: TestClient, company: CompanyFixture, batch_id: str) -> Any:
    return client.post(
        f"{URL.format(company_id=company.id)}/{batch_id}/confirm", headers=company.headers
    )


def _batch_de_validite(db: Session, company: CompanyFixture, batch_id: str) -> ImportBatch:
    bind_tenant(db, company.id)
    return db.get_one(ImportBatch, uuid.UUID(batch_id))


def test_confirm_cree_des_brouillons_sans_les_valider(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    reponse = _confirm(client, company, batch_id)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert (corps["entries"], corps["lines"], corps["debit"], corps["credit"]) == (
        2,
        4,
        "4500000",
        "4500000",
    )
    assert corps["confirmed_at"]
    bind_tenant(db, company.id)
    entrees = db.execute(select(JournalEntry).order_by(JournalEntry.created_at)).scalars().all()
    assert len(entrees) == 2
    for entree in entrees:
        assert entree.status == EntryStatus.DRAFT
        assert entree.number is None
        assert entree.posted_at is None
        assert entree.origin == "MANUAL"
        assert entree.reference in {"FA-2026-001", "FA-2026-002"}
    # Lignes : la première écriture porte la référence FA-2026-001.
    premiere = next(e for e in entrees if e.reference == "FA-2026-001")
    lignes = (
        db.execute(
            select(JournalLine)
            .where(JournalLine.entry_id == premiere.id)
            .order_by(JournalLine.line_no)
        )
        .scalars()
        .all()
    )
    assert [(ligne.debit, ligne.credit) for ligne in lignes] == [(1500000, 0), (0, 1500000)]
    assert [ligne.label for ligne in lignes] == ["Vente comptant", "Vente comptant"]
    # Traçabilité : liens batch → brouillons et marqueurs de confirmation.
    liens = db.execute(select(ImportBatchEntry)).scalars().all()
    assert {str(lien.entry_id) for lien in liens} == {str(e.id) for e in entrees}
    assert all(lien.batch_id == uuid.UUID(batch_id) for lien in liens)
    batch = _batch_de_validite(db, company, batch_id)
    assert batch.confirmed_at is not None
    assert batch.confirmed_by_user_id == company.owner.id
    assert batch.confirmed_entries == 2
    # Aucun numéro consommé : les séquences restent vierges.
    assert db.scalar(select(func.count()).select_from(JournalSequence)) == 0
    # Trace d'audit unique et bornée.
    evenement = db.execute(
        select(AuditEvent).where(AuditEvent.action == "import.confirmed")
    ).scalar_one()
    assert evenement.entity_type == "accounting_import_batch"
    assert evenement.payload["entrees"] == 2


def test_confirm_est_idempotent_aucune_duplication(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    assert _confirm(client, company, batch_id).status_code == 200
    second = _confirm(client, company, batch_id)
    assert second.status_code == 409, second.text
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 2
    assert db.scalar(select(func.count()).select_from(ImportBatchEntry)) == 2


def test_confirm_refuse_un_fichier_anomale_sans_aucune_ecriture(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    contenu = (HEADER + "ZZ;1;2026-02-01;571;Vente;10;0\nZZ;1;2026-02-01;701;Vente;0;10\n").encode()
    batch_id = _upload(client, company, contenu)
    reponse = _confirm(client, company, batch_id)
    assert reponse.status_code == 422, reponse.text
    assert "unknown_journal" in reponse.text
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0
    batch = _batch_de_validite(db, company, batch_id)
    assert batch.confirmed_at is None


def test_confirm_revalide_les_references_au_moment_decisif(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    """Journal désactivé après un précontrôle vert : la confirmation doit refuser."""
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    # Désactivation via l'API des journaux (le dirigeant possède JOURNALS_MANAGE).
    journaux = client.get(
        f"/api/v1/companies/{company.id}/journals", headers=company.headers
    ).json()
    code_vt = next(j["id"] for j in journaux if j["code"] == "VT")
    desactive = client.patch(
        f"/api/v1/companies/{company.id}/journals/{code_vt}",
        headers=company.headers,
        json={"is_active": False},
    )
    assert desactive.status_code == 200, desactive.text
    refuse = _confirm(client, company, batch_id)
    assert refuse.status_code == 422, refuse.text
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0
    # Réactivation : la même confirmation aboutit alors, preuve de la revalidation.
    reactive = client.patch(
        f"/api/v1/companies/{company.id}/journals/{code_vt}",
        headers=company.headers,
        json={"is_active": True},
    )
    assert reactive.status_code == 200, reactive.text
    assert _confirm(client, company, batch_id).status_code == 200


def test_confirm_refuse_une_periode_verrouillee(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    bind_tenant(db, company.id)
    exercice = db.get_one(
        FiscalYear,
        db.scalar(select(FiscalYear.id).where(FiscalYear.tenant_id == company.id)),
    )
    exercice.locked_until = exercice.start_date + timedelta(days=60)  # couvre le 2026-02-*
    db.commit()
    refuse = _confirm(client, company, batch_id)
    assert refuse.status_code == 422, refuse.text
    assert "locked_period" in refuse.text
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_confirm_refuse_un_batch_expire(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    company = make_company()
    batch_id = _upload(client, company, _csv_deux_ecritures())
    bind_tenant(db, company.id)
    batch = db.get_one(ImportBatch, uuid.UUID(batch_id))
    batch.created_at = utcnow() - timedelta(days=2)
    batch.expires_at = utcnow() - timedelta(days=1)
    db.commit()
    assert _confirm(client, company, batch_id).status_code == 404
    assert _confirm(client, company, str(uuid.uuid4())).status_code == 404


def test_confirm_isole_par_dossier_et_par_role(
    db: Session,
    client: TestClient,
    make_company: MakeCompany,
    make_user: MakeUser,
    storage: dict[str, bytes],
) -> None:
    mine, other = make_company(), make_company()
    batch_id = _upload(client, mine, _csv_deux_ecritures())
    etranger = _confirm(client, other, batch_id)
    assert etranger.status_code == 404
    lecteur = make_user()
    db.add(CompanyMembership(company_id=mine.id, user_id=lecteur.id, role=Role.PME_LECTEUR))
    db.commit()
    refuse = client.post(
        f"{URL.format(company_id=mine.id)}/{batch_id}/confirm", headers=lecteur.headers(client)
    )
    assert refuse.status_code == 403


def test_confirm_concurrents_se_serialisent_sur_le_verrou(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    """Deux confirmations simultanées : une seule crée les brouillons, l'autre attend
    puis constate la confirmation (409). Aucun doublon ne peut naître."""
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

    # Le service ouvre ses propres sessions : on l'appelle avec l'utilisateur réel.
    def confirmer_reel() -> None:
        try:
            with get_sessionmaker()() as session:
                bind_tenant(session, company.id)
                user = session.get_one(User, company.owner.id)
                confirm_staged_import(
                    user,
                    company.id,
                    uuid.UUID(batch_id),
                    actor=Actor(company.id, user.id, RequestContext()),
                )
            resultat.put(None)
        except BaseException as exc:
            resultat.put(exc)

    thread = threading.Thread(target=confirmer_reel)
    thread.start()
    # Preuve d'attente réelle : un verrou de transaction n'est pas octroyé (pg_locks,
    # lisible quel que soit le rôle) tant que le batch reste verrouillé par le holder.
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
    if not bloque and not thread.is_alive():
        # Diagnostic : le thread s'est achevé sans jamais attendre le verrou.
        try:
            erreur = resultat.get_nowait()
        except Empty:
            erreur = None
        raise AssertionError(f"le thread concurrent s'est achevé sans attendre : {erreur!r}")
    assert bloque, "la confirmation concurrente devrait attendre le verrou du batch"
    holder.commit()
    holder.close()
    thread.join(timeout=30)
    assert thread.is_alive() is False
    try:
        erreur = resultat.get_nowait()
    except Empty as exc:
        raise AssertionError("le thread concurrent n'a pas abouti") from exc
    assert erreur is None, erreur
    bind_tenant(db, company.id)
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 2
    # Une confirmation HTTP de plus : déjà confirmé, rien ne bouge.
    assert _confirm(client, company, batch_id).status_code == 409
    assert db.scalar(select(func.count()).select_from(JournalEntry)) == 2



def test_meme_fichier_deux_dossiers_isole_tous_les_parcours(
    db: Session, client: TestClient, make_company: MakeCompany, storage: dict[str, bytes]
) -> None:
    """IMP-4 : même SHA source, mais dépôts, rapports et confirmations isolés.

    Un dossier ne peut ni relire ni précontrôler ni confirmer le batch d'un
    autre ; les refus n'empêchent pas le propriétaire de terminer son import.
    """
    mine, other = make_company(), make_company()
    content = _csv_deux_ecritures()
    mine_batch = _upload(client, mine, content)
    other_batch = _upload(client, other, content)
    assert mine_batch != other_batch
    assert len(storage) == 2

    mine_url = URL.format(company_id=mine.id)
    other_url = URL.format(company_id=other.id)
    for foreign_url, foreign_headers, batch_id in (
        (other_url, other.headers, mine_batch),
        (mine_url, mine.headers, other_batch),
    ):
        assert (
            client.post(f"{foreign_url}/{batch_id}/precheck", headers=foreign_headers).status_code
            == 404
        )
        assert (
            client.get(f"{foreign_url}/{batch_id}/precheck", headers=foreign_headers).status_code
            == 404
        )
        assert (
            client.post(f"{foreign_url}/{batch_id}/confirm", headers=foreign_headers).status_code
            == 404
        )

    for company, batch_id in ((mine, mine_batch), (other, other_batch)):
        own_url = URL.format(company_id=company.id)
        precheck = client.post(f"{own_url}/{batch_id}/precheck", headers=company.headers)
        assert precheck.status_code == 200, precheck.text
        assert precheck.json()["valid"] is True
        report = client.get(f"{own_url}/{batch_id}/precheck", headers=company.headers)
        assert report.status_code == 200, report.text
        assert report.json()["entries"] == 2
        confirmed = _confirm(client, company, batch_id)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["entries"] == 2
        assert _confirm(client, company, batch_id).status_code == 409

    for company in (mine, other):
        bind_tenant(db, company.id)
        entries = db.execute(select(JournalEntry)).scalars().all()
        links = db.execute(select(ImportBatchEntry)).scalars().all()
        assert len(entries) == len(links) == 2
        assert all(e.tenant_id == company.id and e.status == EntryStatus.DRAFT for e in entries)
        assert all(link.tenant_id == company.id for link in links)
        db.rollback()
