"""Le verrouillage de connexion doit résister aux écritures concurrentes réelles."""

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from queue import Queue

import pytest
from sqlalchemy import select, text

from kora.auth import service
from kora.core.config import get_settings
from kora.db.session import get_engine, get_sessionmaker
from kora.models.common import utcnow
from kora.models.identity import User
from tests.conftest import UserFixture


@pytest.mark.parametrize(
    ("already_locked", "correct_password"), [(False, False), (True, False), (True, True)]
)
def test_login_attend_et_relit_l_etat_concurrent(
    make_user: Callable[..., UserFixture], already_locked: bool, correct_password: bool
) -> None:
    user = make_user()
    settings = get_settings()
    pids: Queue[int] = Queue()
    errors: list[BaseException] = []

    def attempt() -> None:
        try:
            with get_sessionmaker()() as session:
                # Une instance en cache ne doit pas masquer l'état après attente.
                cached = session.get_one(User, user.id)
                assert cached.failed_login_count == 0
                session.execute(text("SET LOCAL lock_timeout = '10s'"))
                pids.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
                service.login(
                    session,
                    email=user.email.upper(),
                    password=user.password if correct_password else "Mauvais-mot-de-passe-1",
                    ctx=service.RequestContext(),
                )
        except BaseException as exc:
            errors.append(exc)

    with get_sessionmaker()() as writer:
        stored = writer.execute(
            select(User).where(User.id == user.id).with_for_update()
        ).scalar_one()
        stored.failed_login_count = settings.login_max_failures - 1
        if already_locked:
            stored.locked_until = utcnow() + timedelta(seconds=settings.login_lockout_seconds)
        writer.flush()
        worker = threading.Thread(target=attempt)
        worker.start()
        blocked = False
        try:
            pid = pids.get(timeout=5)
            deadline = time.monotonic() + 5
            with get_engine().connect() as observer:
                while time.monotonic() < deadline:
                    blocked = bool(
                        observer.execute(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                        ).scalar_one()
                    )
                    if blocked:
                        break
                    time.sleep(0.01)
        finally:
            writer.commit()
            worker.join(timeout=12)
        assert not worker.is_alive()
        assert blocked, "La connexion doit attendre la transaction concurrente."

    assert len(errors) == 1
    expected = service.AccountLockedError if already_locked else service.InvalidCredentialsError
    assert isinstance(errors[0], expected), repr(errors[0])
    with get_sessionmaker()() as check:
        stored = check.get_one(User, user.id)
        assert stored.locked_until is not None
        assert stored.locked_until > utcnow()
        assert stored.failed_login_count == (
            settings.login_max_failures - 1 if already_locked else 0
        )
