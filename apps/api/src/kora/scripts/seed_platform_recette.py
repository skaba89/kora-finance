"""Jeu de recette E2E de l'administration plateforme des licences (SEC-1).

Crée, via les mêmes services que l'application (aucune écriture directe en
base), un compte administrateur plateforme de recette, une offre publiée et
des dossiers clients à états déterministes :

- « A Recette Licences Consultation » : lecture seule (FR/EN) — une période
  active payante, une programmée (essai), une expirée ;
- « A Recette Licences Suspension 1..N » : période active à suspendre puis à
  réactiver par la spécification (l'état est restauré par le test) ;
- « A Recette Licences Réactivation 1..N » : période suspendue en base ;
- « A Recette Licences Renouvellement 1..N » : période active renouvelable ;
- « A Recette Licences Conflit Suspension 1..N » : état actif, pour le 409
  d'état obsolète (double onglet) ;
- « A Recette Licences Conflit Renouvellement 1..N » : période renouvelable,
  pour le 409 de chevauchement (double onglet).

Idempotent : réexécutable à tout moment. Les états de suspension sont remis à
leur valeur attendue via le service audité `change_license_suspension` ; les
périodes déjà renouvelées ne sont pas supprimables (privilège refusé au rôle
applicatif) : les spécifications E2E sondent les dossiers du premier au
dernier numéro et utilisent le premier à l'état attendu.

Les noms commencent par « A » pour rester dans la première page de la liste
paginée des dossiers clients (tri par raison sociale, 50 par page).

Usage (conteneur api de la pile Docker, ou venv avec KORA_DATABASE_URL) :

    python -m kora.scripts.seed_platform_recette
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from kora.auth.service import RequestContext, register
from kora.core.errors import ConflictError
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.identity import Company, User
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from kora.organization.service import CompanyData, create_company
from kora.tenancy.license_assignment import assign_license
from kora.tenancy.license_suspension import change_license_suspension
from kora.tenancy.licenses import LicenseKind, LicensePeriod
from kora.tenancy.modules import Module
from kora.tenancy.offer_publication import publish_offer
from kora.tenancy.offers import OfferVersion

ADMIN_EMAIL = "admin@recette.kora.gn"
ADMIN_PASSWORD = "Recette-Plateforme-2026!"  # noqa: S105 — mot de passe fictif de recette
ADMIN_FULL_NAME = "Admin Recette Plateforme"
OFFER_CODE = "recette-plateforme"
OFFER_VERSION = 1
SLOT_COUNT = 4
CONSULTATION = "A Recette Licences Consultation"
SUSPENSION = "A Recette Licences Suspension"
REACTIVATION = "A Recette Licences Réactivation"
RENEWAL = "A Recette Licences Renouvellement"
CONFLICT_SUSPENSION = "A Recette Licences Conflit Suspension"
CONFLICT_RENEWAL = "A Recette Licences Conflit Renouvellement"
FISCAL_YEAR = (date(2026, 1, 1), date(2026, 12, 31))
RESET_REASON = "Remise à l'état initial du jeu de recette E2E (SEC-1)."
CTX = RequestContext(user_agent="seed-recette-plateforme")


def ensure_admin(session: Session) -> User:
    """Crée (ou reprend) l'administrateur plateforme de recette, vérifié et actif."""
    bind_tenant(session, None)
    user = session.scalar(select(User).where(User.email == ADMIN_EMAIL))
    if user is None:
        user = register(
            session,
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            full_name=ADMIN_FULL_NAME,
            locale="fr",
            ctx=CTX,
        )
        print(f"Administrateur {ADMIN_EMAIL} créé.")
    user.is_platform_admin = True
    user.email_verified_at = user.email_verified_at or user.created_at
    session.commit()
    return user


def ensure_offer(session: Session, actor_id: uuid.UUID) -> None:
    """Publie la version d'offre de recette si elle n'existe pas encore."""
    bind_tenant(session, None)
    if session.get(CommercialOfferVersion, (OFFER_CODE, OFFER_VERSION)) is None:
        publish_offer(
            session,
            actor_id=actor_id,
            offer=OfferVersion(
                code=OFFER_CODE, version=OFFER_VERSION, modules=frozenset({Module.ACCOUNTING})
            ),
        )
        session.commit()
        print(f"Offre {OFFER_CODE} v{OFFER_VERSION} publiée.")


def ensure_company(session: Session, admin: User, legal_name: str) -> Company:
    """Crée le dossier client de recette s'il n'existe pas encore."""
    # L'annuaire des dossiers se lit en contexte plateforme : les services
    # précédents laissent la session reliée à leur dossier (RLS fermée sinon).
    bind_tenant(session, None)
    company = session.scalar(select(Company).where(Company.legal_name == legal_name))
    if company is None:
        company = create_company(
            session,
            admin,
            CompanyData(legal_name=legal_name, legal_form="SARL", currency="GNF", city="Conakry"),
            firm_id=None,
            first_fiscal_year=FISCAL_YEAR,
            ctx=CTX,
        )
        session.commit()
        print(f"Dossier « {legal_name} » créé.")
    bind_tenant(session, None)
    return company


def paid_period(
    company: Company,
    today: date,
    *,
    starts_in: int,
    ends_in: int,
    kind: LicenseKind = LicenseKind.PAID,
    suspended: bool = False,
) -> LicensePeriod:
    """Période contractuelle déterministe, dates civiles relatives à aujourd'hui (UTC)."""
    return LicensePeriod(
        tenant_id=company.id,
        offer_code=OFFER_CODE,
        offer_version=OFFER_VERSION,
        kind=kind,
        starts_on=today + timedelta(days=starts_in),
        ends_on=today + timedelta(days=ends_in),
        suspended=suspended,
    )


def periods_of(session: Session, company: Company) -> list[CommercialLicensePeriod]:
    """Liste les périodes du dossier, dans son contexte RLS."""
    bind_tenant(session, company.id)
    rows = list(
        session.scalars(
            select(CommercialLicensePeriod).where(CommercialLicensePeriod.tenant_id == company.id)
        )
    )
    bind_tenant(session, None)
    return rows


def assign_periods(
    session: Session, admin: User, company: Company, wanted: list[LicensePeriod]
) -> None:
    """Attribue les périodes attendues une seule fois ; tolère un chevauchement hérité."""
    if len(periods_of(session, company)) >= len(wanted):
        return
    bind_tenant(session, None)
    for period in wanted:
        # assign_license vérifie l'admin PUIS lie le dossier à la RLS : le
        # contexte plateforme doit être rétabli avant chaque appel, sinon
        # l'attribution suivante repart d'un contexte tenant hérité.
        bind_tenant(session, None)
        try:
            assign_license(session, actor_id=admin.id, period=period)
        except ConflictError:
            # Dates héritées d'une exécution précédente : le sondage E2E passera
            # au dossier suivant, aucune donnée n'est écrasée. Le SAVEPOINT de
            # assign_license a déjà isolé l'échec : ne PAS annuler la transaction
            # externe, les attributions antérieures du lot doivent être conservées.
            print(f"  période chevauchante déjà présente pour « {company.legal_name} » : ignorée.")
    session.commit()
    bind_tenant(session, None)


def reset_suspension(session: Session, admin: User, company: Company, target: bool) -> None:
    """Ramène l'état de suspension de la première période à la valeur attendue."""
    rows = periods_of(session, company)
    if not rows or rows[0].suspended == target:
        return
    bind_tenant(session, None)
    change_license_suspension(
        session,
        actor_id=admin.id,
        company_id=company.id,
        license_id=rows[0].id,
        suspended=target,
        expected_suspended=rows[0].suspended,
        reason=RESET_REASON,
    )
    session.commit()
    bind_tenant(session, None)


def main() -> None:
    session = get_sessionmaker()()
    try:
        admin = ensure_admin(session)
        ensure_offer(session, admin.id)
        today = datetime.now(UTC).date()

        consultation = ensure_company(session, admin, CONSULTATION)
        assign_periods(
            session,
            admin,
            consultation,
            [
                # Périodes disjointes : la contrainte d'exclusion PostgreSQL
                # interdit le chevauchement (même partiel) au sein d'un dossier.
                paid_period(consultation, today, starts_in=-300, ends_in=-150),
                paid_period(consultation, today, starts_in=-10, ends_in=350),
                paid_period(
                    consultation, today, starts_in=400, ends_in=430, kind=LicenseKind.TRIAL
                ),
            ],
        )

        for slot in range(1, SLOT_COUNT + 1):
            suspension = ensure_company(session, admin, f"{SUSPENSION} {slot}")
            assign_periods(
                session,
                admin,
                suspension,
                [paid_period(suspension, today, starts_in=-10, ends_in=350)],
            )
            reset_suspension(session, admin, suspension, target=False)

            reactivation = ensure_company(session, admin, f"{REACTIVATION} {slot}")
            assign_periods(
                session,
                admin,
                reactivation,
                [paid_period(reactivation, today, starts_in=-10, ends_in=350, suspended=True)],
            )
            reset_suspension(session, admin, reactivation, target=True)

            renewal = ensure_company(session, admin, f"{RENEWAL} {slot}")
            assign_periods(
                session, admin, renewal, [paid_period(renewal, today, starts_in=-10, ends_in=90)]
            )

            conflict_s = ensure_company(session, admin, f"{CONFLICT_SUSPENSION} {slot}")
            assign_periods(
                session,
                admin,
                conflict_s,
                [paid_period(conflict_s, today, starts_in=-10, ends_in=350)],
            )
            reset_suspension(session, admin, conflict_s, target=False)

            conflict_r = ensure_company(session, admin, f"{CONFLICT_RENEWAL} {slot}")
            assign_periods(
                session,
                admin,
                conflict_r,
                [paid_period(conflict_r, today, starts_in=-10, ends_in=90)],
            )

        print("Jeu de recette plateforme prêt :")
        print(
            f"  - administrateur {ADMIN_EMAIL} (administrateur plateforme, mot de passe de recette)"
        )
        print(f"  - offre {OFFER_CODE} v{OFFER_VERSION}")
        print(f"  - {1 + 5 * SLOT_COUNT} dossiers clients à états déterministes")
    finally:
        session.close()


if __name__ == "__main__":
    main()
