"""Paramétrage comptable initial d'un dossier : plan SYSCOHADA révisé et taxes par défaut."""

import csv
import uuid
from functools import lru_cache
from importlib import resources

from sqlalchemy import insert
from sqlalchemy.orm import Session

from kora.accounting.fiscal_defaults_gn import DEFAULT_TAX_RATES, DEFAULT_VALID_FROM
from kora.audit.service import record_event
from kora.auth.service import RequestContext
from kora.models.accounting import Account, TaxRate
from kora.models.identity import Company

# Référentiel préchargé. À valider par un expert-comptable guinéen : libellés et
# exhaustivité (classes 1 à 8 ; la classe 9 — engagements hors bilan et comptabilité
# analytique — n'est pas préchargée).
CHART_REFERENCE = "SYSCOHADA_REVISE_2017"
_CHART_FILE = "syscohada_revise_2017.csv"


@lru_cache
def reference_chart() -> tuple[tuple[str, str], ...]:
    data = resources.files("kora.accounting.data").joinpath(_CHART_FILE)
    with data.open(encoding="utf-8") as handle:
        return tuple(
            (row["numero"], row["libelle"]) for row in csv.DictReader(handle, delimiter=";")
        )


def initialize_company(
    session: Session, company: Company, *, actor_user_id: uuid.UUID, ctx: RequestContext
) -> None:
    """Doit être appelé dans le contexte tenant du dossier (RLS)."""
    chart = reference_chart()
    session.execute(
        insert(Account),
        [
            {
                "id": uuid.uuid4(),
                "tenant_id": company.id,
                "number": number,
                "label": label,
                "reference": CHART_REFERENCE,
            }
            for number, label in chart
        ],
    )
    session.execute(
        insert(TaxRate),
        [
            {
                "id": uuid.uuid4(),
                "tenant_id": company.id,
                "code": rate.code,
                "label": rate.label,
                "kind": rate.kind,
                "rate_basis_points": rate.rate_basis_points,
                "valid_from": DEFAULT_VALID_FROM,
                "collected_account_number": rate.collected_account_number,
                "deductible_account_number": rate.deductible_account_number,
                "note": rate.note,
            }
            for rate in DEFAULT_TAX_RATES
        ],
    )
    record_event(
        session,
        action="company.accounting_initialized",
        entity_type="company",
        entity_id=company.id,
        payload={
            "plan_comptable": CHART_REFERENCE,
            "nombre_comptes": len(chart),
            "taxes": [rate.code for rate in DEFAULT_TAX_RATES],
        },
        actor_user_id=actor_user_id,
        ip_address=ctx.ip_address,
    )
