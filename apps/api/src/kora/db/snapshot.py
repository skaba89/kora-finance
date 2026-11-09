"""Lectures de rapports sous un unique instantané de la base (KF-05).

Les rapports qui lisent la base en plusieurs requêtes (grand livre d'un compte :
totaux puis lignes ; grand livre complet : soldes puis lignes ; états financiers N et
N-1 ; exports) doivent voir **un seul état** de la base. En READ COMMITTED, chaque
requête prend son propre instantané : une écriture validée entre deux requêtes produit
un rapport qui mélange deux instants — soldes qui ne correspondent pas aux lignes,
voire un compte présent dans les lignes mais absent des soldes (KeyError).

`lecture_instantanee` isole le calcul dans une transaction **REPEATABLE READ** dédiée :
une seule connexion du pool, un seul instantané pour toutes les requêtes du bloc,
RLS et contexte tenant inchangés (`set_config('app.tenant_id', …)` reste la première
instruction, posée par l'événement `after_begin` habituel). Le niveau s'applique sur
une connexion neuve, avant toute instruction : le moteur psycopg le porte sur le
`BEGIN` de la transaction. La transaction est en lecture seule d'effet : aucun commit,
aucune écriture — elle est annulée en fin de bloc.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from kora.db.session import get_engine
from kora.db.tenant import bind_tenant


@contextmanager
def lecture_instantanee(tenant_id: uuid.UUID | None) -> Iterator[Session]:
    """Session dédiée à un rapport, en REPEATABLE READ : toutes les requêtes du bloc
    voient exactement le même instantané, même si une écriture est validée pendant le
    calcul. La session rendue ne doit servir qu'à lire ; elle n'est jamais commitée.
    """
    with get_engine().connect() as connection:
        # Connexion sortie du pool, hors transaction : l'option est portée par le
        # prochain BEGIN (une option posée en pleine transaction est refusée par
        # SQLAlchemy, et un SET TRANSACTION après coup échouerait puisque le contexte
        # tenant est écrit avant la première requête du rapport).
        connection.execution_options(isolation_level="REPEATABLE READ")
        session = Session(bind=connection, expire_on_commit=False, autoflush=False)
        try:
            bind_tenant(session, tenant_id)
            yield session
        finally:
            session.close()
            connection.rollback()
