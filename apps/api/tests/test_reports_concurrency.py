"""Concurrence réelle entre un rapport et une validation (KF-05).

Les rapports lus en plusieurs requêtes (grand livre complet : soldes puis lignes ;
grand livre d'un compte : totaux puis lignes) voient en READ COMMITTED un état de la
base différent à chaque requête. Une écriture validée **entre** deux requêtes produit
un rapport incohérent : soldes qui ne correspondent pas aux lignes, voire un compte
présent dans les lignes mais absent des soldes agrégés (KeyError avant le correctif).

`lecture_instantanee` isole chaque rapport dans une transaction REPEATABLE READ
dédiée. Les deux tests ci-dessous reproduisent exactement la course avec deux
connexions réelles et des barrières déterministes : le rapport signale sa première
requête (écoute des instructions SQL sur sa connexion), la validation concurrente
attend ce signal, se commit, puis le rapport poursuit sur son instantané.
"""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from kora.accounting.reports import (
    AccountLedger,
    AccountMovements,
    Period,
    account_ledger,
    full_ledger,
)
from kora.db.session import get_sessionmaker
from kora.db.snapshot import lecture_instantanee
from kora.db.tenant import bind_tenant
from kora.models.accounting import Account
from kora.models.organization import FiscalYear
from tests.conftest import CompanyFixture
from tests.ledger_helpers import Ledger
from tests.test_closing import _years

MakeCompany = Callable[..., CompanyFixture]

_TIMEOUT = 10.0


@dataclass
class CourseLivre:
    """Course complète du rapport, exécutée dans un fil dédié."""

    requete_passee: threading.Event
    ecriture_commitee: threading.Event
    livre: list[AccountMovements] | None = None
    erreur: BaseException | None = None


@dataclass
class CourseCompte:
    requete_passee: threading.Event
    ecriture_commitee: threading.Event
    ledger: AccountLedger | None = None
    erreur: BaseException | None = None


def _periode(ledger: Ledger, company: CompanyFixture) -> Period:
    """Période = exercice 2026 complet (lu hors rapport, une seule ligne stable)."""
    fy_id = uuid.UUID(_years(ledger)["2026"]["id"])
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        year = session.execute(select(FiscalYear).where(FiscalYear.id == fy_id)).scalar_one()
        return Period(year, year.start_date, year.end_date)


def _compte(company: CompanyFixture, number: str) -> uuid.UUID:
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        return session.execute(select(Account.id).where(Account.number == number)).scalar_one()


def _valider(company: CompanyFixture, entry_id: str) -> None:
    """Valide une écriture par SQL direct (kora_app, RLS), comme la clôture concurrente."""
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        session.execute(
            text(
                "UPDATE journal_entries SET status = 'POSTED', posted_at = now(),"
                " posted_by_user_id = :user WHERE id = :id"
            ),
            {"user": company.owner.id, "id": entry_id},
        )
        session.commit()


def _brancher_barriere(
    connection: object,
    motif: str,
    requete_passee: threading.Event,
    ecriture_commitee: threading.Event,
) -> None:
    """Barrière déterministe : au premier SQL correspondant à `motif`, le rapport
    signale `requete_passee` puis attend `ecriture_commitee` avant de poursuivre.
    Les événements appartiennent au fil principal ; l'écoute est branchée sur la
    connexion du rapport (dans son fil)."""
    vues = {"n": 0}

    @event.listens_for(connection, "after_cursor_execute")
    def _attendre(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        if motif in " ".join(statement.split()).lower() and vues["n"] == 0:
            vues["n"] = 1
            requete_passee.set()
            assert ecriture_commitee.wait(timeout=_TIMEOUT), (
                "la validation concurrente n'a pas abouti"
            )


def _attendre_premiere_requete(course: CourseLivre | CourseCompte, attente: str) -> None:
    assert course.requete_passee.wait(timeout=_TIMEOUT), attente


def test_grand_livre_complet_ignorera_une_validation_posterieure_a_l_instantane(
    client: TestClient, make_company: MakeCompany
) -> None:
    """full_ledger : les soldes (1ʳᵉ requête) et les lignes (2ᵉ requête) doivent venir
    du même instantané. Avant correctif, une validation intercalée d'un compte nouveau
    levait KeyError ; avec l'instantané, le rapport est entier et cohérent."""
    company = make_company()
    ledger = Ledger(client, company)
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="BQ", entry_date="2026-01-05"
    )
    draft = ledger.create(
        [("522", 2_000_000, 0), ("521", 0, 2_000_000)], journal="OD", entry_date="2026-01-20"
    ).json()
    period = _periode(ledger, company)

    course = CourseLivre(threading.Event(), threading.Event())

    def rapport() -> None:
        try:
            with lecture_instantanee(company.id) as snap:
                _brancher_barriere(
                    snap.connection(), "group by", course.requete_passee, course.ecriture_commitee
                )
                course.livre = full_ledger(snap, company.id, period)
        except BaseException as exc:  # remontée au fil principal
            course.erreur = exc

    thread = threading.Thread(target=rapport)
    thread.start()
    _attendre_premiere_requete(course, "la requête des soldes n'est pas passée")

    # La validation se commit entre les deux requêtes du rapport.
    _valider(company, draft["id"])
    course.ecriture_commitee.set()
    thread.join(timeout=30)
    assert not thread.is_alive(), "le rapport est resté bloqué"
    assert course.erreur is None, f"le rapport a échoué : {course.erreur!r}"
    assert course.livre is not None

    mouvements = {m.number: m for m in course.livre}
    assert "522" not in mouvements, (
        "un compte validé après l'instantané ne doit pas apparaître dans le grand livre"
    )
    banque = mouvements["521"]
    assert (banque.opening, banque.period_debit, banque.period_credit) == (0, 5_000_000, 0)
    assert len(banque.lines) == 1
    assert banque.lines[0].debit == 5_000_000
    assert banque.closing == 5_000_000
    # Cohérence interne : la somme des lignes égale les mouvements agrégés.
    assert sum(mouvement.debit for mouvement in banque.lines) == banque.period_debit
    assert sum(mouvement.credit for mouvement in banque.lines) == banque.period_credit


def test_grand_livre_compte_totaux_et_lignes_du_meme_instantane(
    client: TestClient, make_company: MakeCompany
) -> None:
    """account_ledger : totaux (1ʳᵉ requête) et lignes (2ᵉ requête) du même instantané.
    Avant correctif, la validation intercalée gonflait les lignes sans les totaux."""
    company = make_company()
    ledger = Ledger(client, company)
    ledger.posted(
        [("521", 5_000_000, 0), ("101", 0, 5_000_000)], journal="BQ", entry_date="2026-01-05"
    )
    draft = ledger.create(
        [("521", 2_000_000, 0), ("101", 0, 2_000_000)], journal="OD", entry_date="2026-01-20"
    ).json()
    period = _periode(ledger, company)
    compte = _compte(company, "521")

    course = CourseCompte(threading.Event(), threading.Event())

    def rapport() -> None:
        try:
            with lecture_instantanee(company.id) as snap:
                _brancher_barriere(
                    snap.connection(), "sum(", course.requete_passee, course.ecriture_commitee
                )
                course.ledger = account_ledger(
                    snap, company.id, compte, period, limit=100, offset=0
                )
        except BaseException as exc:  # remontée au fil principal
            course.erreur = exc

    thread = threading.Thread(target=rapport)
    thread.start()
    _attendre_premiere_requete(course, "la requête des totaux n'est pas passée")

    _valider(company, draft["id"])
    course.ecriture_commitee.set()
    thread.join(timeout=30)
    assert not thread.is_alive(), "le rapport est resté bloqué"
    assert course.erreur is None, f"le rapport a échoué : {course.erreur!r}"
    assert course.ledger is not None

    livre = course.ledger
    assert (livre.opening, livre.period_debit, livre.period_credit) == (0, 5_000_000, 0)
    assert livre.total_lines == 1
    assert len(livre.lines) == 1
    assert livre.lines[0].debit == 5_000_000
    # Cohérence interne : totaux, lignes et solde de clôture racontent la même histoire.
    assert sum(mouvement.debit for mouvement in livre.lines) == livre.period_debit
    assert sum(mouvement.credit for mouvement in livre.lines) == livre.period_credit
    assert livre.closing == livre.opening + livre.period_debit - livre.period_credit
    # La validation concurrente, elle, est bien en base : c'est l'instantané qui l'écarte.
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        statut = session.execute(
            text("SELECT status FROM journal_entries WHERE id = :id"), {"id": draft["id"]}
        ).scalar_one()
    assert statut == "POSTED"
