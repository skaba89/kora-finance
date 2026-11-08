"""Concurrence réelle entre la clôture (ou le verrouillage de période) et la validation.

La course : `close()` verrouille l'exercice puis calcule les à-nouveaux depuis les
écritures validées, tandis que le déclencheur `journal_entries_protect` relit
`fiscal_years` sans verrou. Une validation concurrente peut donc passer après le calcul
des à-nouveaux : l'exercice se ferme sans que ses lignes soient reportées. Le verrou de
ligne (`FOR UPDATE`) posé sur `fiscal_years` dans le déclencheur sérialise les deux
opérations : clôture d'abord ⇒ la validation est refusée ; validation d'abord ⇒ ses
lignes sont dans les à-nouveaux. Les trois tests reproduisent ces interleavings avec
deux connexions réelles et des barrières déterministes (`pg_blocking_pids`).
"""

import threading
import time
from collections.abc import Callable
from queue import Queue

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kora.db.session import get_engine, get_sessionmaker
from kora.db.tenant import bind_tenant
from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger
from tests.test_closing import _add_year, _balance, _fy_url, _years

MakeCompany = Callable[..., CompanyFixture]


def _attend_bloque(pid: int, deadline_s: float = 5.0) -> bool:
    """Vrai dès que la transaction du PID attend un verrou détenu par une autre."""
    deadline = time.monotonic() + deadline_s
    with get_engine().connect() as observer:
        while time.monotonic() < deadline:
            bloque = bool(
                observer.execute(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                ).scalar_one()
            )
            if bloque:
                return True
            time.sleep(0.01)
    return False


def _valider_en_parallele(
    company: CompanyFixture, entry_id: str
) -> tuple[Queue[int], list[BaseException], threading.Thread]:
    """Tente la validation SQL directe de l'écriture dans un fil séparé (kora_app, RLS)."""
    pids: Queue[int] = Queue()
    errors: list[BaseException] = []

    def valider() -> None:
        try:
            with get_sessionmaker()() as session:
                bind_tenant(session, company.id)
                session.execute(text("SET LOCAL lock_timeout = '10s'"))
                pids.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
                session.execute(
                    text(
                        "UPDATE journal_entries SET status = 'POSTED', posted_at = now(),"
                        " posted_by_user_id = :user WHERE id = :id"
                    ),
                    {"user": company.owner.id, "id": entry_id},
                )
                session.commit()
        except BaseException as exc:  # remontée au fil principal
            errors.append(exc)

    return pids, errors, threading.Thread(target=valider)


def _exercice_ferme(company: CompanyFixture, fy_id: str, entry_id: str) -> tuple[str, str]:
    """Statut de l'exercice et de l'écriture après la course."""
    with get_sessionmaker()() as check:
        bind_tenant(check, company.id)
        annee = check.execute(
            text("SELECT status FROM fiscal_years WHERE id = :id"), {"id": fy_id}
        ).scalar_one()
        ecriture = check.execute(
            text("SELECT status FROM journal_entries WHERE id = :id"), {"id": entry_id}
        ).scalar_one()
    return annee, ecriture


def test_cloture_en_cours_refuse_la_validation_concurrente(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    ledger = Ledger(client, company)
    _add_year(ledger, 2027)
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="AN", entry_date="2026-01-01"
    )
    draft = ledger.create(
        [("701", 90_000, 0), ("521", 0, 90_000)], journal="VT", entry_date="2026-06-01"
    ).json()
    fy_id = _years(ledger)["2026"]["id"]

    pids, errors, worker = _valider_en_parallele(company, draft["id"])
    with get_sessionmaker()() as closer:
        bind_tenant(closer, company.id)
        closer.execute(text("SET LOCAL lock_timeout = '10s'"))
        # Comme close()/_lock_year : l'exercice est verrouillé avant tout le reste.
        closer.execute(text("SELECT id FROM fiscal_years WHERE id = :id FOR UPDATE"), {"id": fy_id})
        worker.start()
        bloque = False
        try:
            pid = pids.get(timeout=5)
            bloque = _attend_bloque(pid)
        finally:
            # L'agrégat des à-nouveaux (lecture MVCC) ne voit pas la validation bloquée :
            # la clôture passe, l'exercice se ferme, puis la validation reprend.
            closer.execute(
                text(
                    "UPDATE fiscal_years SET status = 'CLOSED', closed_at = now(),"
                    " closed_by_user_id = :user WHERE id = :id"
                ),
                {"user": company.owner.id, "id": fy_id},
            )
            closer.commit()
            worker.join(timeout=15)
        assert not worker.is_alive(), "La validation concurrente est restée bloquée."
        assert bloque, (
            "La validation doit attendre la fin de la clôture (verrou de l'exercice dans le"
            " déclencheur) : sinon ses lignes manquent aux à-nouveaux."
        )

    assert len(errors) == 1, f"la validation concurrente doit être refusée : {errors!r}"
    assert isinstance(errors[0], DBAPIError), repr(errors[0])
    assert "Exercice clôturé" in str(errors[0])
    annee, ecriture = _exercice_ferme(company, fy_id, draft["id"])
    assert annee == "CLOSED"
    assert ecriture == "DRAFT", "la validation refusée doit être intégralement annulée"


def test_verrouillage_de_periode_en_cours_refuse_la_validation_concurrente(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = make_company()
    ledger = Ledger(client, company)
    draft = ledger.create(
        [("571", 10_000, 0), ("701", 0, 10_000)], journal="OD", entry_date="2026-03-15"
    ).json()
    fy_id = _years(ledger)["2026"]["id"]

    pids, errors, worker = _valider_en_parallele(company, draft["id"])
    with get_sessionmaker()() as closer:
        bind_tenant(closer, company.id)
        closer.execute(text("SET LOCAL lock_timeout = '10s'"))
        closer.execute(text("SELECT id FROM fiscal_years WHERE id = :id FOR UPDATE"), {"id": fy_id})
        worker.start()
        bloque = False
        try:
            pid = pids.get(timeout=5)
            bloque = _attend_bloque(pid)
        finally:
            # Comme lock_period() : l'exercice verrouillé, la date fixée, puis commit.
            closer.execute(
                text("UPDATE fiscal_years SET locked_until = '2026-03-31' WHERE id = :id"),
                {"id": fy_id},
            )
            closer.commit()
            worker.join(timeout=15)
        assert not worker.is_alive(), "La validation concurrente est restée bloquée."
        assert bloque, (
            "La validation doit attendre la fin du verrouillage de période : sinon une"
            " écriture antérieure à la date verrouillée peut encore être validée."
        )

    assert len(errors) == 1, f"la validation concurrente doit être refusée : {errors!r}"
    assert isinstance(errors[0], DBAPIError), repr(errors[0])
    assert "Période verrouillée" in str(errors[0])
    annee, ecriture = _exercice_ferme(company, fy_id, draft["id"])
    assert annee == "OPEN"
    assert ecriture == "DRAFT", "la validation refusée doit être intégralement annulée"


def test_cloture_apres_validation_inclut_l_ecriture_validee(
    client: TestClient, make_company: MakeCompany
) -> None:
    """L'interleaving inverse doit rester possible : une validation qui gagne la course
    (commit avant le verrou de la clôture) figure bien dans les à-nouveaux."""
    company = make_company()
    ledger = Ledger(client, company)
    _add_year(ledger, 2027)
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="AN", entry_date="2026-01-01"
    )
    created = ledger.create(
        [("521", 50_000, 0), ("101", 0, 50_000)], journal="OD", entry_date="2026-06-01"
    )
    assert ledger.post(created.json()["id"]).status_code == 200

    closed = ledger.client.post(_fy_url(ledger, "2026", "closing"), headers=company.headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["fiscal_year"]["status"] == "CLOSED"
    assert _balance(ledger, "2027")["ouv:521"] == 5_050_000, (
        "la validation antérieure à la clôture doit figurer dans les à-nouveaux"
    )
