"""Verrou de l'exercice dans le déclencheur : sérialisation avec la clôture.

Révision : 0010
Parente  : 0009

Aucune donnée ni ancienne migration modifiée : la fonction du déclencheur
`kora_ledger_protect_entry` (0005, redéfinie par 0007) est remplacée pour relire
`fiscal_years` avec `FOR UPDATE`.

La course corrigée : `close()` verrouille l'exercice (`closing._lock_year`) puis
agrège les écritures validées pour générer les à-nouveaux, tandis que la relecture
sans verrou du déclencheur laissait passer une validation concurrente engagée avant
le commit de la clôture — l'exercice se fermait sans que ses lignes figurent dans
les à-nouveaux. Avec le verrou de ligne, la validation concurrente attend la fin de
la transaction de clôture puis relit la version validée : exercice CLOSED ou période
verrouillée ⇒ refus. Ordre de verrous uniforme (exercice avant numérotation) : les
chemins applicatifs prennent le même verrou via `entries._fiscal_year_for(lock=True)`
avant `_next_number`, ce qui exclut tout interblocage avec la séquence de journal.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROTECT_HEAD = """
CREATE OR REPLACE FUNCTION kora_ledger_protect_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    total_debit bigint;
    total_credit bigint;
    line_count integer;
    year_status text;
    year_lock date;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'POSTED' THEN
            RAISE EXCEPTION 'Écriture validée % : suppression interdite', OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'INSERT' AND NEW.status <> 'DRAFT' THEN
        RAISE EXCEPTION 'Une écriture est créée en brouillon puis validée'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'POSTED' THEN
        RAISE EXCEPTION 'Écriture validée % : modification interdite', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
"""

# Identique à 0007, hormis le verrou de ligne `FOR UPDATE` : la relecture de
# l'exercice attend la fin d'une clôture ou d'un verrouillage concurrent, puis
# relit la version validée (READ COMMITTED). Le verrou est réentrant dans la
# transaction de la clôture elle-même (à-nouveaux : INSERT puis UPDATE).
_PERIOD_CHECK = """
    -- Exercice clôturé ou période verrouillée : ni création, ni modification, ni validation.
    -- FOR UPDATE : sérialise avec close()/lock_period() qui verrouillent l'exercice ;
    -- sans lui, une validation concurrente passerait après le calcul des à-nouveaux.
    SELECT status, locked_until INTO year_status, year_lock
      FROM fiscal_years WHERE id = NEW.fiscal_year_id
      FOR UPDATE;
    IF year_status <> 'OPEN' THEN
        RAISE EXCEPTION 'Exercice clôturé : écriture % refusée', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF year_lock IS NOT NULL AND NEW.entry_date <= year_lock THEN
        RAISE EXCEPTION 'Période verrouillée jusqu''au % : écriture % refusée', year_lock, NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
"""

# Identique à 0007 (version antérieure, sans verrou) : cible du downgrade.
_PERIOD_CHECK_0007 = """
    -- Exercice clôturé ou période verrouillée : ni création, ni modification, ni validation.
    SELECT status, locked_until INTO year_status, year_lock
      FROM fiscal_years WHERE id = NEW.fiscal_year_id;
    IF year_status <> 'OPEN' THEN
        RAISE EXCEPTION 'Exercice clôturé : écriture % refusée', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF year_lock IS NOT NULL AND NEW.entry_date <= year_lock THEN
        RAISE EXCEPTION 'Période verrouillée jusqu''au % : écriture % refusée', year_lock, NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
"""


_PROTECT_TAIL = """
    IF NEW.status = 'POSTED' THEN
        SELECT coalesce(sum(debit), 0), coalesce(sum(credit), 0), count(*)
          INTO total_debit, total_credit, line_count
          FROM journal_lines WHERE entry_id = NEW.id;
        IF line_count < 2 OR total_debit <> total_credit OR total_debit = 0 THEN
            RAISE EXCEPTION 'Écriture % déséquilibrée (débit %, crédit %, % lignes)',
                NEW.id, total_debit, total_credit, line_count
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""


def upgrade() -> None:
    op.execute(_PROTECT_HEAD + _PERIOD_CHECK + _PROTECT_TAIL)


def downgrade() -> None:
    # Version de 0007 (relecture de l'exercice sans verrou).
    op.execute(_PROTECT_HEAD + _PERIOD_CHECK_0007 + _PROTECT_TAIL)
