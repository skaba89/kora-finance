"""Document d'export de la prévision de trésorerie (PDF / Excel) — Phase 3E.

Construit le `Document` tabulaire neutre rendu par `kora.exports` : synthèse de la
prévision, tableau journalier (engagés, estimés, solde projeté, statut) et projection
par compte. Les hypothèses du calcul sont rappelées en notes de bas de document :
l'utilisateur voit toujours comment chaque chiffre a été produit.
"""

import re
import unicodedata
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from kora.audit.service import record_event
from kora.cashflow.assumptions import SCENARIO_ASSUMPTIONS, ForecastStatus, Scenario
from kora.cashflow.engine import ForecastResult
from kora.cashflow.service import ExcludedDraft, build_forecast
from kora.core.errors import BusinessRuleError, NotFoundError
from kora.db.snapshot import lecture_instantanee
from kora.exports import pdf, xlsx
from kora.exports.builders import EXPERT_NOTICE
from kora.exports.document import Column, Document, Section, format_date
from kora.exports.service import MEDIA_TYPES, ExportFile
from kora.models.identity import Company

_STATUS_LABELS = {
    ForecastStatus.SAIN.value: "Sain",
    ForecastStatus.SOUS_SURVEILLANCE.value: "Sous surveillance",
    ForecastStatus.CRITIQUE.value: "Critique",
}

SCENARIO_LABELS = {
    "OPTIMISTE": "Optimiste",
    "NEUTRE": "Neutre",
    "PRUDENT": "Prudent",
}


def previsions_document(
    session: Session,
    company: Company,
    result: ForecastResult,
    *,
    drafts: list[ExcludedDraft],
) -> Document:
    """Assemble le document d'export de la prévision calculée."""
    scenario_label = SCENARIO_LABELS[result.scenario.value]
    document = Document(
        title=f"Prévision de trésorerie {result.horizon_days} jours — scénario {scenario_label}",
        company_name=company.legal_name,
        identifiers=" — ".join(
            part
            for part in (
                f"RCCM : {company.rccm}" if company.rccm else None,
                f"NIF : {company.nif}" if company.nif else None,
            )
            if part
        )
        or "RCCM et NIF non renseignés",
        period=(
            f"Projeté du {format_date(result.as_of + timedelta(days=1))} "
            f"au {format_date(_horizon_end(result))}"
        ),
        currency=company.currency,
        generated_at=datetime.now(UTC),
        notes=_notes(result, drafts),
        landscape=True,
    )

    synthesis = Section(
        "Synthèse",
        [
            Column("Indicateur", width=42),
            Column("Valeur", "text", 30),
        ],
    )
    synthesis.add(
        "Solde de trésorerie observé à la date de calcul", f"{result.opening_total_minor}"
    )
    synthesis.add(
        "Statut global",
        _STATUS_LABELS.get(result.status.value, result.status.value),
    )
    synthesis.add(
        "Première date sous le seuil critique",
        format_date(result.first_critical_date) if result.first_critical_date else "Aucune",
    )
    synthesis.add(
        "Solde projeté le plus bas",
        f"{result.lowest_balance_minor} ({format_date(result.lowest_balance_date)})",
    )
    if result.beyond_horizon_inflow_minor:
        synthesis.add(
            "Encaissements estimés repoussés au-delà de l'horizon (scénario prudent)",
            f"{result.beyond_horizon_inflow_minor}",
        )
    if result.insufficient_data:
        synthesis.add(
            "Historique exploitable",
            "Insuffisant : prévision limitée aux soldes observés et aux flux engagés",
        )
    document.sections.append(synthesis)

    daily = Section(
        "Projection journalière consolidée",
        [
            Column("Date", "date", 12),
            Column("Engagés entrée", "amount", 16),
            Column("Engagés sortie", "amount", 16),
            Column("Estimés entrée", "amount", 16),
            Column("Estimés sortie", "amount", 16),
            Column("Solde projeté", "amount", 18),
            Column("Statut", "text", 18),
        ],
    )
    for day in result.days:
        daily.add(
            day.flow_date,
            day.committed_inflow_minor,
            day.committed_outflow_minor,
            day.estimated_inflow_minor,
            day.estimated_outflow_minor,
            day.balance_minor,
            _STATUS_LABELS.get(day.status.value, day.status.value),
        )
    document.sections.append(daily)

    accounts = Section(
        "Projection par compte (soldes observés et flux engagés)",
        [
            Column("Compte", width=10),
            Column("Libellé", width=34),
            Column("Solde observé", "amount", 16),
            Column("Engagés (net)", "amount", 16),
            Column("Projeté fin d'horizon", "amount", 18),
        ],
    )
    for account in result.accounts:
        accounts.add(
            account.number,
            account.label,
            account.opening_minor,
            account.committed_net_minor,
            account.projected_minor,
        )
    document.sections.append(accounts)
    return document


def _notes(result: ForecastResult, drafts: list[ExcludedDraft]) -> list[str]:
    notes: list[str] = [
        "Sources : soldes observés (écritures validées) ; flux engagés (écritures validées "
        "datées dans l'horizon, non ajustables) ; flux estimés (moyenne mensuelle de "
        "l'historique, ajustés par le scénario). Aucune transaction future n'est inventée.",
        "Périmètre de trésorerie : comptes de classe 5 hors 58x (virements internes).",
        "Hypothèses du scénario : "
        f"encaissements ×{SCENARIO_ASSUMPTIONS[result.scenario].inflow_numerator}/"
        f"{SCENARIO_ASSUMPTIONS[result.scenario].inflow_denominator}, "
        f"décaissements ×{SCENARIO_ASSUMPTIONS[result.scenario].outflow_numerator}/"
        f"{SCENARIO_ASSUMPTIONS[result.scenario].outflow_denominator}, "
        f"retard encaissements {SCENARIO_ASSUMPTIONS[result.scenario].inflow_delay_days} j, "
        f"avance décaissements {SCENARIO_ASSUMPTIONS[result.scenario].outflow_advance_days} j.",
        "Montants en unités de la devise du dossier, arrondis entiers (aucun flottant).",
        EXPERT_NOTICE,
    ]
    if drafts:
        notes.append(
            "Brouillons futurs exclus de la projection (non validés) : "
            + "; ".join(f"{format_date(d.entry_date)} — {d.label}" for d in drafts[:10])
            + ("…" if len(drafts) > 10 else "")
        )
    return notes


def _horizon_end(result: ForecastResult) -> date:
    return result.as_of + timedelta(days=result.horizon_days)


def _slug(text: str) -> str:
    """« Société Élégance » → « societe-elegance » (convention kora.exports.service)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower() or "dossier"


def render_forecast_export(
    session: Session,
    company_id: uuid.UUID,
    *,
    horizon_days: int,
    scenario: Scenario,
    file_format: str,
    actor_user_id: uuid.UUID,
    ip_address: str | None,
) -> ExportFile:
    """Génère l'export de la prévision : document → PDF/Excel → journal d'audit.

    Réutilise les moteurs de rendu `kora.exports` (fonts, numérotation, style) sans
    toucher au registre `Kind` existant : la prévision n'est ni une balance ni un
    état financier, elle a sa propre fonction d'assemblage (phase 3E).
    """
    company = session.get(Company, company_id)
    if company is None:
        raise NotFoundError("Dossier introuvable.")
    with lecture_instantanee(company_id) as snap:
        # Calcul et document sous un unique instantané : l'export rend exactement
        # l'état de la base utilisé pour le calcul (KF-05).
        result, drafts = build_forecast(
            snap, company_id, horizon_days=horizon_days, scenario=scenario
        )
        document = previsions_document(snap, company, result, drafts=drafts)

    rows = sum(len(section.rows) for section in document.sections)
    if file_format == "pdf" and rows > 20_000:
        raise BusinessRuleError(
            f"{rows} lignes : trop volumineux pour un PDF. Utilisez l'export Excel."
        )
    content = pdf.render(document) if file_format == "pdf" else xlsx.render(document)
    dates = f"{result.as_of:%Y%m%d}-{_horizon_end(result):%Y%m%d}"
    filename = f"previsions-tresorerie-{_slug(company.legal_name)}-{dates}.{file_format}"
    record_event(
        session,
        action="export.generated",
        entity_type="export",
        entity_id=None,
        payload={
            "type": "previsions-tresorerie",
            "format": file_format,
            "scenario": scenario.value,
            "du": result.as_of.isoformat(),
            "au": _horizon_end(result).isoformat(),
            "lignes": rows,
        },
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )
    session.commit()
    return ExportFile(content, filename, MEDIA_TYPES[file_format])
