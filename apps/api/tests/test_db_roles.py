"""Le rôle d'exécution ne doit ni contourner la RLS, ni modifier le schéma."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from kora.core.config import get_migration_settings, get_settings
from kora.db.session import get_engine


def test_role_applicatif_sans_privileges_eleves() -> None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


def test_role_applicatif_ne_peut_pas_creer_de_table() -> None:
    with get_engine().connect() as conn, pytest.raises(ProgrammingError, match="permission"):
        conn.execute(text("CREATE TABLE intrusion (id int)"))


def test_role_de_migration_n_est_pas_superutilisateur() -> None:
    engine = create_engine(str(get_migration_settings().database_migration_url))
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    engine.dispose()
    assert row.rolsuper is False
    assert row.rolbypassrls is False


def test_api_et_migrations_utilisent_des_roles_distincts() -> None:
    settings = get_settings()
    app_user = settings.database_url.hosts()[0]["username"]
    migration_user = get_migration_settings().database_migration_url.hosts()[0]["username"]
    assert app_user != migration_user
