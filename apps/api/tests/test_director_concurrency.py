"""Concurrence réelle entre deux départs de dirigeants (KF-07).

La course : `_ensure_a_director_remains` comptait les dirigeants sans verrou sur la
société. Deux rétrogradations (ou retraits) simultanés de deux dirigeants distincts
comptaient chacun deux dirigeants — l'autre transaction n'étant pas encore commitée —
et les deux passes pouvaient aboutir : dossier sans aucun dirigeant. Le verrou de ligne
(`FOR UPDATE`) posé sur `companies` sérialise les deux départs : la seconde transaction
attend le commit de la première, relit le comptage dans un instantané frais et est
refusée. Deux connexions réelles et une barrière déterministe (`pg_blocking_pids`),
comme les tests de clôture (KF-03) et de connexion (KF-06).
"""

import threading
import time
import uuid
from collections.abc import Callable
from queue import Queue

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from kora.auth import service as auth_service
from kora.core.errors import BusinessRuleError
from kora.db.session import get_engine, get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.identity import CompanyMembership
from kora.organization import service as organization_service
from tests.conftest import CompanyFixture, UserFixture

MakeCompany = Callable[..., CompanyFixture]
MakeUser = Callable[..., UserFixture]

DEMI_DIRIGEANT = "PME_COMPTABLE"


def _membres(client: TestClient, company: CompanyFixture) -> list[dict[str, str]]:
    response = client.get(f"/api/v1/companies/{company.id}/members", headers=company.headers)
    assert response.status_code == 200, response.text
    membres: list[dict[str, str]] = response.json()
    return membres


def _dossier_a_deux_dirigeants(
    client: TestClient, company: CompanyFixture, other: UserFixture
) -> dict[str, str]:
    """Ajoute le second dirigeant et renvoie {email : identifiant de membership}."""
    added = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": other.email, "role": "PME_DIRIGEANT"},
    )
    assert added.status_code == 201, added.text
    membres = _membres(client, company)
    assert len(membres) == 2
    return {m["email"]: m["id"] for m in membres}


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


def _nombre_dirigeants(company_id: object) -> int:
    with get_sessionmaker()() as check:
        return check.execute(
            select(func.count())
            .select_from(CompanyMembership)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.role == "PME_DIRIGEANT",
            )
        ).scalar_one()


def test_deux_demotions_simultanees_conservent_un_dirigeant(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser
) -> None:
    company = make_company()
    other = make_user(verified=True)
    par_email = _dossier_a_deux_dirigeants(client, company, other)
    premier_id = uuid.UUID(par_email[company.owner.email])
    second_id = uuid.UUID(par_email[other.email])
    assert _nombre_dirigeants(company.id) == 2

    pids: Queue[int] = Queue()
    errors: list[BaseException] = []

    def demotion_second() -> None:
        """Rétrogradation du second dirigeant par le vrai cas d'usage (KF-07)."""
        try:
            with get_sessionmaker()() as session:
                bind_tenant(session, company.id)
                session.execute(text("SET LOCAL lock_timeout = '10s'"))
                pids.put(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
                organization_service.change_member_role(
                    session,
                    organization_service.TenantLike(company_id=company.id, user_id=other.id),
                    second_id,
                    DEMI_DIRIGEANT,
                    auth_service.RequestContext(),
                )
        except BaseException as exc:  # remontée au fil principal
            errors.append(exc)

    with get_sessionmaker()() as premiere:
        # La première rétrogradation est en cours : société verrouillée, membre déjà
        # modifié, pas encore commitée — exactement la fenêtre de change_member_role.
        bind_tenant(premiere, company.id)
        premiere.execute(text("SET LOCAL lock_timeout = '10s'"))
        premiere.execute(
            text("SELECT id FROM companies WHERE id = :id FOR UPDATE"), {"id": str(company.id)}
        )
        premiere.execute(
            text("UPDATE company_memberships SET role = :role WHERE id = :id"),
            {"role": DEMI_DIRIGEANT, "id": str(premier_id)},
        )
        worker = threading.Thread(target=demotion_second)
        worker.start()
        bloque = False
        try:
            bloque = _attend_bloque(pids.get(timeout=5))
        finally:
            premiere.commit()
            worker.join(timeout=15)
        assert not worker.is_alive(), "La seconde démotion est restée bloquée."
        assert bloque, (
            "La seconde démotion doit attendre la fin de la première (verrou de la"
            " société) : sinon les deux comptages se croisent et le dossier peut se"
            " retrouver sans dirigeant."
        )

    assert len(errors) == 1, f"la seconde démotion doit être refusée : {errors!r}"
    assert isinstance(errors[0], BusinessRuleError), repr(errors[0])
    assert "au moins un dirigeant" in str(errors[0])
    assert _nombre_dirigeants(company.id) == 1, (
        "le dossier doit conserver le dirigeant de la seconde transaction"
    )
    roles = {m["email"]: m["role"] for m in _membres(client, company)}
    assert roles[company.owner.email] == DEMI_DIRIGEANT
    assert roles[other.email] == "PME_DIRIGEANT"


def test_retrait_du_dernier_autre_dirigeant_apres_commit_est_refuse(
    client: TestClient, make_company: MakeCompany, make_user: MakeUser
) -> None:
    """Sans course : une fois la première démotion commitée, le comptage voit un seul
    dirigeant et le retrait du second est refusé (comportement inchangé)."""
    company = make_company()
    other = make_user(verified=True)
    added = client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": other.email, "role": "PME_DIRIGEANT"},
    )
    assert added.status_code == 201, added.text
    membres = _membres(client, company)
    premier_id = next(m["id"] for m in membres if m["email"] == company.owner.email)

    demoted = client.patch(
        f"/api/v1/companies/{company.id}/members/{premier_id}",
        headers=company.headers,
        json={"role": DEMI_DIRIGEANT},
    )
    assert demoted.status_code == 200, demoted.text
    with get_sessionmaker()() as session:
        bind_tenant(session, company.id)
        other_membership = session.execute(
            select(CompanyMembership).where(
                CompanyMembership.company_id == company.id,
                CompanyMembership.user_id == other.id,
            )
        ).scalar_one()
        try:
            organization_service.remove_member(
                session,
                organization_service.TenantLike(company_id=company.id, user_id=other.id),
                other_membership.id,
                auth_service.RequestContext(),
            )
        except BusinessRuleError:
            pass
        else:
            raise AssertionError("le retrait du dernier dirigeant doit être refusé")
    assert _nombre_dirigeants(company.id) == 1
