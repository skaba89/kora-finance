"""Invariants de la comptabilité générale, prouvés au niveau du service et de la base.

- tests par propriétés : aucune séquence d'opérations ne produit de déséquilibre ;
- numérotation sans trou ni doublon, y compris en validations simultanées ;
- immuabilité et équilibre imposés par PostgreSQL, quel que soit le rôle.
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from queue import Queue

import pytest
from alembic import command
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from kora.accounting import entries
from kora.accounting.entries import Actor, EntryData, LineData
from kora.core.errors import BusinessRuleError, ConflictError
from kora.db.session import get_engine, get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.accounting import Account
from kora.models.ledger import EntryStatus, Journal, JournalEntry, JournalLine
from tests.conftest import CompanyFixture, alembic_config

MakeCompany = Callable[..., CompanyFixture]
ACCOUNTS = ("571", "521", "701", "601", "401", "411", "4431", "4452")


@dataclass
class Book:
    company_id: uuid.UUID
    user_id: uuid.UUID
    journals: dict[str, uuid.UUID]
    accounts: dict[str, uuid.UUID]

    def actor(self) -> Actor:
        return Actor(self.company_id, self.user_id)

    def session(self) -> Session:
        session = get_sessionmaker()()
        bind_tenant(session, self.company_id)
        return session

    def data(self, lines: list[tuple[str, int, int]], journal: str = "OD") -> EntryData:
        return EntryData(
            journal_id=self.journals[journal],
            entry_date=date(2026, 6, 30),
            label="Propriété",
            lines=[LineData(self.accounts[n], debit=d, credit=c) for n, d, c in lines],
        )


@pytest.fixture
def book(make_company: MakeCompany) -> Book:
    company = make_company()
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        journals = {
            j.code: j.id
            for j in session.execute(
                select(Journal).where(Journal.tenant_id == company.id)
            ).scalars()
        }
        accounts = {
            a.number: a.id
            for a in session.execute(
                select(Account).where(Account.tenant_id == company.id, Account.number.in_(ACCOUNTS))
            ).scalars()
        }
    return Book(company.id, company.owner.id, journals, accounts)


# --- Tests par propriétés

line_strategy = st.tuples(
    st.sampled_from(ACCOUNTS), st.integers(min_value=1, max_value=10**12), st.booleans()
)
entry_strategy = st.tuples(
    st.lists(line_strategy, min_size=1, max_size=6), st.booleans(), st.booleans()
)
operation = st.one_of(
    st.tuples(st.just("ecriture"), entry_strategy),
    st.tuples(st.just("contre_passation"), st.integers(min_value=0, max_value=20)),
)


def _lines(spec: list[tuple[str, int, bool]], balance: bool) -> list[tuple[str, int, int]]:
    lines = [(n, amount, 0) if debit else (n, 0, amount) for n, amount, debit in spec]
    difference = sum(d for _, d, _ in lines) - sum(c for _, _, c in lines)
    if balance and difference:
        lines.append(("571", 0, difference) if difference > 0 else ("571", -difference, 0))
    return lines


def _check_ledger(session: Session, company_id: uuid.UUID) -> None:
    posted = (
        select(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.tenant_id == company_id, JournalEntry.status == EntryStatus.POSTED)
        .subquery()
    )
    debit, credit = session.execute(
        select(
            func.coalesce(func.sum(posted.c.debit), 0), func.coalesce(func.sum(posted.c.credit), 0)
        )
    ).one()
    assert debit == credit, "grand livre déséquilibré"
    unbalanced = session.execute(
        select(posted.c.entry_id)
        .group_by(posted.c.entry_id)
        .having(func.sum(posted.c.debit) != func.sum(posted.c.credit))
    ).all()
    assert unbalanced == []
    numbering = session.execute(
        select(
            JournalEntry.journal_id,
            JournalEntry.fiscal_year_id,
            func.array_agg(JournalEntry.number),
        )
        .where(JournalEntry.tenant_id == company_id, JournalEntry.status == EntryStatus.POSTED)
        .group_by(JournalEntry.journal_id, JournalEntry.fiscal_year_id)
    ).all()
    for _, _, numbers in numbering:
        assert sorted(n for n in numbers if n is not None) == list(range(1, len(numbers) + 1))


Spec = list[tuple[str, int, bool]]
Operation = tuple[str, tuple[Spec, bool, bool] | int]


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(operations=st.lists(operation, min_size=1, max_size=8))
def test_aucune_sequence_d_operations_ne_desequilibre_le_grand_livre(
    book: Book, operations: list[Operation]
) -> None:
    with book.session() as session:
        for _, payload in operations:
            if isinstance(payload, tuple):
                spec, balance, post = payload
                lines = _lines(spec, balance)
                entry, _ = entries.create_draft(session, book.actor(), book.data(lines))
                if not post:
                    continue
                valid = len(lines) >= 2 and sum(d for _, d, _ in lines) == sum(
                    c for _, _, c in lines
                )
                try:
                    entries.post_entry(session, book.actor(), entry.id)
                    assert valid, f"écriture invalide validée : {lines}"
                except BusinessRuleError:
                    session.rollback()
                    assert not valid, f"écriture valide refusée : {lines}"
            else:
                candidates = (
                    session.execute(
                        select(JournalEntry.id)
                        .where(
                            JournalEntry.tenant_id == book.company_id,
                            JournalEntry.status == EntryStatus.POSTED,
                        )
                        .order_by(JournalEntry.created_at)
                    )
                    .scalars()
                    .all()
                )
                if not candidates:
                    continue
                target = candidates[payload % len(candidates)]
                try:
                    entries.reverse_entry(
                        session, book.actor(), target, reversal_date=date(2026, 7, 1)
                    )
                except BusinessRuleError:
                    session.rollback()  # contre-passation d'une contre-passation : refusée
                except ConflictError:
                    session.rollback()  # déjà contre-passée
        _check_ledger(session, book.company_id)


def test_une_ecriture_et_sa_contre_passation_s_annulent_compte_par_compte(book: Book) -> None:
    with book.session() as session:
        lines = [("601", 750_000, 0), ("4452", 135_000, 0), ("401", 0, 885_000)]
        entry, _ = entries.create_draft(session, book.actor(), book.data(lines, "AC"))
        entries.post_entry(session, book.actor(), entry.id)
        entries.reverse_entry(session, book.actor(), entry.id, reversal_date=date(2026, 7, 1))
        balances = session.execute(
            select(JournalLine.account_id, func.sum(JournalLine.debit - JournalLine.credit))
            .where(JournalLine.tenant_id == book.company_id)
            .group_by(JournalLine.account_id)
        ).all()
        assert {balance for _, balance in balances} == {0}


# --- Concurrence


def test_validations_simultanees_numeros_consecutifs_sans_doublon(book: Book) -> None:
    count = 20
    with book.session() as session:
        ids = [
            entries.create_draft(
                session, book.actor(), book.data([("571", 1000, 0), ("701", 0, 1000)], "VT")
            )[0].id
            for _ in range(count)
        ]
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def post(entry_id: uuid.UUID) -> None:
        try:
            with book.session() as session:
                barrier.wait()
                entries.post_entry(session, book.actor(), entry_id)
        except BaseException as exc:  # remonté au fil principal
            errors.append(exc)

    threads = [threading.Thread(target=post, args=(i,)) for i in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    with book.session() as session:
        numbers = (
            session.execute(select(JournalEntry.number).where(JournalEntry.id.in_(ids)))
            .scalars()
            .all()
        )
    assert sorted(n for n in numbers if n is not None) == list(range(1, count + 1))


# --- Garde-fous de la base (quel que soit le chemin d'accès)


def _posted_entry(book: Book) -> uuid.UUID:
    with book.session() as session:
        entry, _ = entries.create_draft(
            session, book.actor(), book.data([("571", 1000, 0), ("701", 0, 1000)])
        )
        entries.post_entry(session, book.actor(), entry.id)
        return entry.id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE journal_entries SET label = 'falsifié' WHERE id = :id",
        "DELETE FROM journal_entries WHERE id = :id",
        "UPDATE journal_lines SET debit = 999 WHERE entry_id = :id AND debit > 0",
        "DELETE FROM journal_lines WHERE entry_id = :id",
    ],
)
@pytest.mark.parametrize("role", ["application", "proprietaire"])
def test_ecriture_validee_immuable_en_base(
    book: Book, owner_engine: Engine, statement: str, role: str
) -> None:
    entry_id = _posted_entry(book)
    engine = owner_engine if role == "proprietaire" else get_sessionmaker().kw["bind"]
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(book.company_id)}
        )
        with pytest.raises(DBAPIError, match="validée"):
            connection.execute(text(statement), {"id": entry_id})
        connection.rollback()
        connection.execute(text("SELECT set_config('app.tenant_id', '', false)"))


def test_la_base_refuse_de_valider_une_ecriture_desequilibree(book: Book) -> None:
    with book.session() as session:
        entry, _ = entries.create_draft(
            session, book.actor(), book.data([("571", 1000, 0), ("701", 0, 999)])
        )
        with pytest.raises(DBAPIError, match="déséquilibrée"):
            session.execute(
                text(
                    "UPDATE journal_entries SET status = 'POSTED', number = 99, posted_at = now() "
                    "WHERE id = :id"
                ),
                {"id": entry.id},
            )


def test_la_base_refuse_une_ecriture_creee_directement_validee(book: Book) -> None:
    with book.session() as session:
        fiscal_year_id = session.execute(
            text("SELECT id FROM fiscal_years WHERE tenant_id = :t"), {"t": book.company_id}
        ).scalar_one()
        with pytest.raises(DBAPIError, match="brouillon"):
            session.execute(
                text(
                    "INSERT INTO journal_entries (id, tenant_id, journal_id, fiscal_year_id, "
                    "entry_date, label, status, number, posted_at, created_by_user_id) "
                    "VALUES (gen_random_uuid(), :t, :j, :fy, '2026-06-30', 'x', 'POSTED', 999, "
                    "now(), :u)"
                ),
                {
                    "t": book.company_id,
                    "j": book.journals["OD"],
                    "fy": fiscal_year_id,
                    "u": book.user_id,
                },
            )


def test_la_base_refuse_un_compte_d_un_autre_dossier(book: Book, make_company: MakeCompany) -> None:
    other = make_company()
    with book.session() as session:
        entry, _ = entries.create_draft(
            session, book.actor(), book.data([("571", 1000, 0), ("701", 0, 1000)])
        )
    with get_sessionmaker()() as session:
        bind_tenant(session, other.id)
        foreign_account = session.execute(
            select(Account.id).where(Account.tenant_id == other.id, Account.number == "571")
        ).scalar_one()
    with book.session() as session, pytest.raises(DBAPIError):
        session.execute(
            text(
                "INSERT INTO journal_lines "
                "(id, tenant_id, entry_id, line_no, account_id, debit, credit) "
                "VALUES (gen_random_uuid(), :t, :e, 3, :a, 5, 0)"
            ),
            {"t": book.company_id, "e": entry.id, "a": foreign_account},
        )


# --- Régression KF-01 : rattachement et validation concurrente


def _draft(book: Book) -> uuid.UUID:
    with book.session() as session:
        entry, _ = entries.create_draft(
            session, book.actor(), book.data([("571", 1000, 0), ("701", 0, 1000)])
        )
        return entry.id


def _line(book: Book, entry_id: uuid.UUID) -> uuid.UUID:
    with book.session() as session:
        return session.execute(
            select(JournalLine.id).where(JournalLine.entry_id == entry_id, JournalLine.debit > 0)
        ).scalar_one()


@pytest.mark.parametrize("role", ["application", "proprietaire"])
@pytest.mark.parametrize("posted", [False, True])
def test_changement_de_parent_interdit(
    book: Book, owner_engine: Engine, role: str, posted: bool
) -> None:
    source, target = _draft(book), _draft(book)
    line_id = _line(book, source)
    if posted:
        with book.session() as session:
            entries.post_entry(session, book.actor(), target)
    engine = owner_engine if role == "proprietaire" else get_engine()
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(book.company_id)}
        )
        with pytest.raises(DBAPIError, match="rattachement"):
            connection.execute(
                text("UPDATE journal_lines SET entry_id=:target, line_no=3 WHERE id=:line"),
                {"target": target, "line": line_id},
            )
        connection.rollback()
    with book.session() as session:
        line = session.get_one(JournalLine, line_id)
        assert line.entry_id == source


def test_migration_ferme_un_contournement_reproduit_sur_0008(book: Book) -> None:
    """La transaction d'attaque est annulée ; seule la base dédiée aux tests est utilisée."""
    source, target = _draft(book), _draft(book)
    line_id = _line(book, source)
    with book.session() as session:
        entries.post_entry(session, book.actor(), target)
    cfg = alembic_config()
    command.downgrade(cfg, "0008")
    try:
        with get_engine().connect() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(book.company_id)},
            )
            result = connection.execute(
                text("UPDATE journal_lines SET entry_id=:target, line_no=3 WHERE id=:line"),
                {"target": target, "line": line_id},
            )
            assert result.rowcount == 1  # contournement effectif de l'ancien trigger
            debit, credit = connection.execute(
                text("SELECT sum(debit), sum(credit) FROM journal_lines WHERE entry_id=:target"),
                {"target": target},
            ).one()
            assert debit != credit
            connection.rollback()
    finally:
        command.upgrade(cfg, "head")
    with book.session() as session, pytest.raises(DBAPIError, match="rattachement"):
        session.execute(
            text("UPDATE journal_lines SET entry_id=:target, line_no=3 WHERE id=:line"),
            {"target": target, "line": line_id},
        )


def test_mutation_sql_attend_la_validation_concurrente(book: Book) -> None:
    entry_id = _draft(book)
    line_id = _line(book, entry_id)
    engine = get_engine()
    pids: Queue[int] = Queue()
    errors: list[BaseException] = []

    def mutate() -> None:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(book.company_id)},
                )
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                pids.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                connection.execute(
                    text("UPDATE journal_lines SET debit=999 WHERE id=:line"), {"line": line_id}
                )
        except BaseException as exc:
            errors.append(exc)

    with engine.connect() as posting:
        posting.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(book.company_id)}
        )
        posting.execute(
            text(
                "UPDATE journal_entries SET status='POSTED', number=1, posted_at=now(), "
                "posted_by_user_id=:user WHERE id=:entry"
            ),
            {"entry": entry_id, "user": book.user_id},
        )
        worker = threading.Thread(target=mutate)
        worker.start()
        blocked = False
        try:
            pid = pids.get(timeout=5)
            deadline = time.monotonic() + 5
            with engine.connect() as observer:
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
            posting.commit()
            worker.join(timeout=12)
        assert not worker.is_alive()
        assert blocked, "La mutation doit attendre le verrou de validation sur le parent."
    assert len(errors) == 1
    assert isinstance(errors[0], DBAPIError)
    assert "validée" in str(errors[0])
    with book.session() as session:
        assert session.get_one(JournalLine, line_id).debit == 1000
