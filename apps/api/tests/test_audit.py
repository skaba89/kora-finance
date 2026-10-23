"""Journal d'audit chaîné : intégrité, ajout seul, isolation par tenant."""

import threading
import uuid

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from kora.audit.service import AuditPayloadError, record_event, verify_chain
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.audit import GENESIS_HASH, AuditEvent


def _new_chain(db: Session, events: int = 3) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    bind_tenant(db, tenant_id)
    for i in range(events):
        record_event(
            db,
            action="test.action",
            entity_type="test",
            entity_id=str(i),
            payload={"montant_gnf": 150_000 * (i + 1), "libelle": "Écriture n°" + str(i)},
        )
    db.commit()
    return tenant_id


def _tamper(owner_engine: Engine, tenant_id: uuid.UUID, sql: str) -> None:
    """Simule un attaquant ayant les droits propriétaire : désactive le trigger et modifie."""
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only"))
        conn.execute(text(sql), {"t": tenant_id})
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only"))


def test_chaine_intacte_est_verifiee(db: Session) -> None:
    _new_chain(db, events=5)
    result = verify_chain(db)
    assert result.ok
    assert result.events_checked == 5


def test_premier_evenement_part_du_hash_genesis(db: Session) -> None:
    tenant_id = _new_chain(db, events=2)
    first = (
        db.execute(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq)
        )
        .scalars()
        .first()
    )
    assert first is not None
    assert first.seq == 1
    assert first.prev_hash == GENESIS_HASH


def test_modification_du_contenu_detectee(db: Session, owner_engine: Engine) -> None:
    tenant_id = _new_chain(db)
    _tamper(
        owner_engine,
        tenant_id,
        "UPDATE audit_events SET payload = jsonb_build_object('montant_gnf', 1) "
        "WHERE tenant_id = :t AND seq = 2",
    )
    result = verify_chain(db)
    assert not result.ok
    assert result.broken_at_seq == 2
    assert result.reason == "contenu altéré"


def test_suppression_au_milieu_detectee(db: Session, owner_engine: Engine) -> None:
    tenant_id = _new_chain(db)
    _tamper(owner_engine, tenant_id, "DELETE FROM audit_events WHERE tenant_id = :t AND seq = 2")
    result = verify_chain(db)
    assert not result.ok
    assert result.broken_at_seq == 2


def test_suppression_de_la_fin_detectee(db: Session, owner_engine: Engine) -> None:
    tenant_id = _new_chain(db)
    _tamper(owner_engine, tenant_id, "DELETE FROM audit_events WHERE tenant_id = :t AND seq = 3")
    result = verify_chain(db)
    assert not result.ok
    assert result.reason == "fin de chaîne supprimée ou tête altérée"


def test_role_applicatif_ne_peut_ni_modifier_ni_supprimer(db: Session) -> None:
    tenant_id = _new_chain(db)
    bind_tenant(db, tenant_id)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(
            text("UPDATE audit_events SET action = 'x' WHERE tenant_id = :t"), {"t": tenant_id}
        )
    db.rollback()
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(text("DELETE FROM audit_events WHERE tenant_id = :t"), {"t": tenant_id})


def test_trigger_bloque_meme_le_proprietaire(db: Session, owner_engine: Engine) -> None:
    tenant_id = _new_chain(db)
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        update = text("UPDATE audit_events SET action = 'x' WHERE tenant_id = :t")
        with pytest.raises(DBAPIError, match="ajout seul"):
            conn.execute(update, {"t": tenant_id})


def test_rls_un_tenant_ne_voit_pas_la_chaine_d_un_autre(db: Session) -> None:
    tenant_a = _new_chain(db, events=2)
    tenant_b = _new_chain(db, events=4)

    bind_tenant(db, tenant_a)
    visible = db.execute(
        select(AuditEvent.tenant_id, func.count()).group_by(AuditEvent.tenant_id)
    ).all()
    db.commit()
    assert visible == [(tenant_a, 2)]

    bind_tenant(db, tenant_b)
    assert db.execute(select(func.count()).select_from(AuditEvent)).scalar_one() == 4


def test_rls_aucun_evenement_tenant_visible_sans_contexte(db: Session) -> None:
    _new_chain(db, events=2)
    bind_tenant(db, None)
    tenant_rows = db.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id.is_not(None))
    ).scalar_one()
    assert tenant_rows == 0


def test_rls_ecriture_dans_un_autre_tenant_refusee(db: Session) -> None:
    bind_tenant(db, uuid.uuid4())
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.execute(
            text(
                "INSERT INTO audit_chain_heads (tenant_id, last_seq, last_hash) VALUES (:t, 0, :h)"
            ),
            {"t": uuid.uuid4(), "h": GENESIS_HASH},
        )


def test_contexte_tenant_ne_fuit_pas_entre_transactions(db: Session) -> None:
    tenant_id = _new_chain(db, events=1)
    bind_tenant(db, tenant_id)
    assert db.execute(select(func.count()).select_from(AuditEvent)).scalar_one() == 1
    db.commit()
    # Nouvelle session sur le même pool : aucun tenant hérité.
    with get_sessionmaker()() as other:
        assert other.execute(
            text("SELECT current_setting('app.tenant_id', true)")
        ).scalar_one() in ("", None)


def test_chaine_plateforme_hors_contexte_tenant(db: Session) -> None:
    bind_tenant(db, None)
    record_event(db, action="auth.login", entity_type="user", entity_id=str(uuid.uuid4()))
    db.commit()
    assert verify_chain(db).ok


@pytest.mark.parametrize("payload", [{"montant": 1.5}, {"liste": [1, 2.0]}, {"objet": object()}])
def test_payload_refuse_les_types_non_json_exacts(db: Session, payload: dict[str, object]) -> None:
    bind_tenant(db, uuid.uuid4())
    with pytest.raises(AuditPayloadError):
        record_event(db, action="x", entity_type="y", payload=payload)


def test_ecritures_concurrentes_restent_chainees(db: Session) -> None:
    """Le verrou sur la tête de chaîne sérialise les ajouts concurrents d'un même tenant."""
    tenant_id = uuid.uuid4()
    errors: list[BaseException] = []

    def writer(worker: int) -> None:
        try:
            for i in range(10):
                with get_sessionmaker()() as session:
                    bind_tenant(session, tenant_id)
                    record_event(
                        session,
                        action="test.concurrent",
                        entity_type="test",
                        payload={"worker": worker, "i": i},
                    )
                    session.commit()
        except BaseException as exc:  # remonté au thread principal
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    bind_tenant(db, tenant_id)
    result = verify_chain(db)
    assert result.ok
    assert result.events_checked == 40
