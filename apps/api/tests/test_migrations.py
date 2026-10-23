from alembic import command
from alembic.script import ScriptDirectory

from tests.conftest import alembic_config


def test_historique_lineaire_une_seule_tete() -> None:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1, f"Plusieurs têtes Alembic : {heads}"


def test_aller_retour_complet_des_migrations() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_modeles_et_migrations_synchronises() -> None:
    # Échoue si un modèle a été modifié sans migration correspondante.
    command.check(alembic_config())
