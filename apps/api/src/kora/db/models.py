"""Registre des modèles : chaque module de modèles doit être importé ici pour
qu'Alembic (autogenerate, `alembic check`) le voie."""

from kora.models import accounting, audit, identity, ledger, organization

__all__ = ["accounting", "audit", "identity", "ledger", "organization"]
