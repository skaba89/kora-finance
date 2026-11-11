"""Jeu de données fictif pour tester Kora en local (démonstration « Djouma Distribution SARL »).

Crée, via les mêmes services que l'application (aucune écriture directe en base) :
utilisateurs, dossier, exercice, sous-comptes clients/fournisseurs, comptes financiers,
puis sept mois d'opérations réalistes (avril → novembre 2026) : factures clients et
fournisseurs, ventes et dépenses comptant, encaissements et règlements tracés comme
mouvements de trésorerie, virements internes, frais bancaires, lettrage automatique.

Le script génère aussi, à partir des mouvements réellement créés, trois fichiers de
relevés bancaires fictifs (CSV et OFX) à importer dans l'interface pour tester
l'import (phase 3B) puis le rapprochement assisté (phase 3C). Chaque relevé contient
quelques opérations « surprises » absentes de la comptabilité — c'est exprès : elles
servent à tester le rapprochement (une à enregistrer, une à ignorer, une à régulariser).

Toutes les données sont fictives et deterministic : exécuter deux fois le script avec
`--reset` produit exactement la même démonstration. Les noms d'entreprises, RCCM et
NIF sont inventés ; aucun lien avec une entité réelle.

Usage (dans le conteneur api de la pile Docker, ou dans le venv avec KORA_DATABASE_URL) :

    python -m kora.scripts.seed_demo                 # crée la démonstration
    python -m kora.scripts.seed_demo --reset         # la supprime puis la recrée
    python -m kora.scripts.seed_demo --out ./demo    # dossier des relevés générés

Connexions de démonstration (http://localhost:3100) :
    directeur@demo.kora.gn / KoraDemo2026!   (PME_DIRIGEANT, créateur du dossier)
    comptable@demo.kora.gn / KoraDemo2026!   (PME_COMPTABLE)
    lecteur@demo.kora.gn   / KoraDemo2026!   (PME_LECTEUR)
"""

import argparse
import os
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import TextClause, create_engine, func, select, text
from sqlalchemy.orm import Session

from kora.accounting import guided
from kora.accounting import service as accounting_service
from kora.accounting.entries import Actor, EntryData, LineData, create_draft, post_entry
from kora.accounting.lettering import auto_letter_by_reference
from kora.auth.service import RequestContext, register
from kora.core.config import get_settings
from kora.db.session import get_sessionmaker
from kora.db.tenant import bind_tenant
from kora.models.accounting import Account
from kora.models.identity import Company, User
from kora.models.ledger import Journal, JournalEntry
from kora.models.treasury import FinancialMovement
from kora.organization.service import CompanyData, TenantLike, add_member, create_company
from kora.tenancy.roles import Role
from kora.treasury import service as treasury_service
from kora.treasury.service import AccountData, MovementData, TransferData

# --- Constantes de la démonstration -----------------------------------------

DEMO_DOMAIN = "demo.kora.gn"
DEMO_PASSWORD = "KoraDemo2026!"  # noqa: S105 (mot de passe fictif de démonstration)
DEMO_COMPANY_LEGAL_NAME = "Djouma Distribution SARL"

USERS: tuple[tuple[str, str, Role], ...] = (
    ("directeur", "Fatoumata Diallo", Role.PME_DIRIGEANT),
    ("comptable", "Mamadou Sylla", Role.PME_COMPTABLE),
    ("lecteur", "Aïssatou Baldé", Role.PME_LECTEUR),
)

FISCAL_YEAR = (date(2026, 1, 1), date(2026, 12, 31))

# Sous-comptes de tiers et de trésorerie créés sous le référentiel SYSCOHADA préchargé.
SUB_ACCOUNTS: tuple[tuple[str, str], ...] = (
    ("4111", "Client Sahel Agro SARL"),
    ("4112", "Client Kalan Supermarché"),
    ("4113", "Client Niaga Services SARLU"),
    ("4114", "Client Fouta BTP SARL"),
    ("4011", "Fournisseur Mamaya Import-Export"),
    ("4012", "Fournisseur Conakry Fournitures SA"),
    ("4013", "Fournisseur Soleil Élec SARL"),
    ("5211", "Banque Fouta Express"),
    ("5212", "Orange Money"),
)

# Relevés fictifs : opérations présentes à la banque mais absentes de la comptabilité.
ANOMALIES_BANQUE_OCTOBRE = (
    (date(2026, 10, 9), -182_500, "AGIOS ET COMMISSIONS TRIMESTRE", None),
    (date(2026, 10, 21), 9_800_000, "REMISE CHEQUE 000341 - SAHEL AGRO", "CHQ-000341"),
    (date(2026, 10, 27), -25_000, "FRAIS ALERTE SMS", None),
)
ANOMALIES_BANQUE_NOVEMBRE = (
    (date(2026, 11, 5), -145_000, "COMMISSION DOSSIER RECOUVREMENT", None),
)
ANOMALIES_MM = ((date(2026, 10, 8), -12_000, "COMMISSION DEPOT AGENT KOULOUBA", None),)

# --- Petits utilitaires -------------------------------------------------------


def _fmt_gnf(amount: int) -> str:
    """1 234 567 GNF : séparateur de milliers pour les fichiers bancaires."""
    return f"{abs(amount):,}".replace(",", " ")


def _signed(amount: int, direction: str) -> int:
    """Montant signé du point de vue du titulaire (+ entree, - sortie)."""
    return amount if direction == "DEBIT" else -amount


def _account_number(session: Session, company_id: uuid.UUID, number: str) -> Account:
    """Compte du plan du dossier par numéro (le référentiel est préchargé par create_company)."""
    account = session.execute(
        select(Account).where(Account.tenant_id == company_id, Account.number == number)
    ).scalar_one_or_none()
    if account is None:
        raise SystemExit(f"Compte {number} introuvable dans le dossier (seed démo incohérent).")
    return account


def _journal_by_code(session: Session, company_id: uuid.UUID, code: str) -> Journal:
    journal = session.execute(
        select(Journal).where(Journal.tenant_id == company_id, Journal.code == code)
    ).scalar_one_or_none()
    if journal is None:
        raise SystemExit(f"Journal {code} introuvable dans le dossier.")
    return journal


# --- Remise à zéro ------------------------------------------------------------


# Déclencheurs d'immuabilité posés par les migrations (grand livre, mouvements,
# pièces) : le grand livre est en ajout seul, une erreur se corrige par
# contre-passation. La remise à zéro de la démonstration — opération d'exploitation
# assumée — désactive ces déclencheurs le temps de la suppression en cascade, puis
# les réactive. Elle exige donc les droits du propriétaire des schémas.
RESET_HINT = (
    "La remise à zéro exige KORA_DATABASE_MIGRATION_URL (rôle propriétaire du schéma).\n"
    "Depuis la pile Docker, relancez :\n"
    '  docker compose exec -e KORA_DATABASE_MIGRATION_URL="postgresql+psycopg://'
    'kora_owner:${KORA_DB_OWNER_PASSWORD}@postgres:5432/kora" api '
    "python -m kora.scripts.seed_demo --reset"
)

# DDL littéral : les noms de tables et déclencheurs sont des constantes des
# migrations (aucune interpolation — le garde-fou du dépôt l'impose).
RESET_DISABLE_TRIGGERS: tuple[TextClause, ...] = (
    text("ALTER TABLE journal_entries DISABLE TRIGGER journal_entries_protect"),
    text("ALTER TABLE journal_lines DISABLE TRIGGER journal_lines_protect"),
    text("ALTER TABLE attachments DISABLE TRIGGER attachments_protect"),
    text("ALTER TABLE financial_movements DISABLE TRIGGER financial_movements_protect"),
)
RESET_ENABLE_TRIGGERS: tuple[TextClause, ...] = (
    text("ALTER TABLE journal_entries ENABLE TRIGGER journal_entries_protect"),
    text("ALTER TABLE journal_lines ENABLE TRIGGER journal_lines_protect"),
    text("ALTER TABLE attachments ENABLE TRIGGER attachments_protect"),
    text("ALTER TABLE financial_movements ENABLE TRIGGER financial_movements_protect"),
)


def reset_demo() -> None:
    """Supprime le dossier de démonstration et ses utilisateurs.

    La connexion propriétaire est requise : les tables tenant sont sous RLS forcée
    (aucun rôle ne la contourne) et le grand livre est protégé en ajout seul. La
    suppression désactive donc temporairement les déclencheurs d'immuabilité, fixe
    le tenant courant le temps de la cascade, puis remet tout en place — dans une
    seule transaction.
    """
    owner_url = os.environ.get("KORA_DATABASE_MIGRATION_URL")
    if not owner_url:
        raise SystemExit(RESET_HINT)
    engine = create_engine(owner_url)
    try:
        with engine.begin() as conn:
            company_id = conn.execute(
                text("SELECT id FROM companies WHERE legal_name = :name"),
                {"name": DEMO_COMPANY_LEGAL_NAME},
            ).scalar_one_or_none()
            if company_id is not None:
                for ddl in RESET_DISABLE_TRIGGERS:
                    conn.execute(ddl)
                conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(company_id)},
                )
                conn.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company_id})
                for ddl in RESET_ENABLE_TRIGGERS:
                    conn.execute(ddl)
                print(f"Dossier « {DEMO_COMPANY_LEGAL_NAME} » supprimé (cascade).")
            for local, _, _ in USERS:
                email = f"{local}@{DEMO_DOMAIN}"
                result = conn.execute(
                    text("DELETE FROM users WHERE email = :email"), {"email": email}
                )
                if result.rowcount:
                    print(f"Utilisateur {email} supprimé.")
    finally:
        engine.dispose()


# --- Création des comptes de la démonstration ---------------------------------


def create_users(session: Session) -> list[User]:
    created = []
    for local, full_name, _role in USERS:
        user = register(
            session,
            email=f"{local}@{DEMO_DOMAIN}",
            password=DEMO_PASSWORD,
            full_name=full_name,
            locale="fr",
            ctx=RequestContext(user_agent="seed-demo"),
        )
        user.email_verified_at = user.email_verified_at or user.created_at
        session.commit()
        created.append(user)
        print(f"Utilisateur {user.email} créé ({full_name}).")
    return created


def create_demo_company(session: Session, directeur: User) -> Company:
    company = create_company(
        session,
        directeur,
        CompanyData(
            legal_name=DEMO_COMPANY_LEGAL_NAME,
            trade_name="Djouma",
            legal_form="SARL",
            # Identifiants fictifs (format guinéen indicatif) : ne correspondent à aucune entité.
            rccm="GX-KAL-2026-B-0142",
            nif="3021457-A",
            currency="GNF",
            address="Rue de la Renaissance, Quartier Kaloum",
            city="Conakry",
            phone="+224 622 12 34 56",
        ),
        firm_id=None,
        first_fiscal_year=FISCAL_YEAR,
        ctx=RequestContext(user_agent="seed-demo"),
    )
    # create_company a déjà lié le tenant ; on re-lie explicitement pour les étapes suivantes.
    bind_tenant(session, company.id)
    print(f"Dossier « {company.legal_name} » créé (exercice {FISCAL_YEAR[0]} → {FISCAL_YEAR[1]}).")
    return company


def create_memberships(session: Session, company: Company, comptable: User, lecteur: User) -> None:
    tenant = TenantLike(company.id, comptable.id)
    for user, role in ((comptable, Role.PME_COMPTABLE), (lecteur, Role.PME_LECTEUR)):
        add_member(
            session,
            tenant,
            email=user.email,
            role=role.value,
            ctx=RequestContext(user_agent="seed-demo"),
        )
        print(f"Accès {role.value} accordé à {user.email}.")


def create_subaccounts(session: Session, actor: Actor) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    service_actor = accounting_service.Actor(company_id=actor.company_id, user_id=actor.user_id)
    for number, label in SUB_ACCOUNTS:
        account = accounting_service.create_account(
            session, service_actor, number=number, label=label, ctx=actor.ctx
        )
        ids[number] = account.id
    print(f"{len(SUB_ACCOUNTS)} sous-comptes créés (clients, fournisseurs, trésorerie).")
    return ids


def create_financial_accounts(
    session: Session, actor: Actor, accounts: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    bank = treasury_service.create_account(
        session,
        actor,
        AccountData(
            name="Banque Fouta Express — Compte courant",
            kind="BANQUE",
            gl_account_id=accounts["5211"],
            account_number_masked="****-4037",
        ),
    )
    cash = treasury_service.create_account(
        session,
        actor,
        AccountData(name="Caisse du siège", kind="CAISSE", gl_account_id=accounts["571"]),
    )
    mobile = treasury_service.create_account(
        session,
        actor,
        AccountData(
            name="Orange Money — Boutique",
            kind="MOBILE_MONEY",
            gl_account_id=accounts["5212"],
            operator="ORANGE_MONEY_GN",
            account_number_masked="+224 6** *** 456",
        ),
    )
    print("Comptes financiers créés : banque, caisse, Orange Money.")
    return {"banque": bank.id, "caisse": cash.id, "mobile": mobile.id}


# --- Opérations de la démonstration -------------------------------------------
# Toutes les données sont fictives et ordonnées explicitement (aucun hasard).


def _guided_create(session: Session, actor: Actor, data: guided.GuidedData) -> None:
    try:
        entry, _created = guided.create(session, actor, data, entry_id=uuid.uuid4())
        post_entry(session, actor, entry.id)
    except Exception:
        print(f"Échec de l'opération guidée : {data.operation} {data.entry_date} « {data.label} »")
        raise


def apply_guided_operations(session: Session, actor: Actor, accounts: dict[str, uuid.UUID]) -> None:
    """Factures, ventes et dépenses comptant : écritures sans trace bancaire directe."""

    def acc(number: str) -> uuid.UUID:
        return _account_number(session, actor.company_id, number).id

    op = guided.Operation
    g = guided.GuidedData

    operations: list[guided.GuidedData] = [
        # Ventes comptant en caisse (la caisse n'a pas de relevé : pas de mouvement).
        g(
            op.VENTE_COMPTANT,
            date(2026, 4, 21),
            1_500_000,
            "Vente comptant marché Madina",
            nature_account_id=acc("701"),
            treasury_account_id=acc("571"),
        ),
        g(
            op.VENTE_COMPTANT,
            date(2026, 6, 18),
            2_950_000,
            "Vente comptant gros Matam",
            nature_account_id=acc("701"),
            treasury_account_id=acc("571"),
            vat_included=True,
        ),
        g(
            op.VENTE_COMPTANT,
            date(2026, 8, 8),
            5_900_000,
            "Vente comptant fin de mois",
            nature_account_id=acc("701"),
            treasury_account_id=acc("571"),
            vat_included=True,
        ),
        g(
            op.VENTE_COMPTANT,
            date(2026, 9, 12),
            900_000,
            "Vente comptant accès boutique",
            nature_account_id=acc("706"),
            treasury_account_id=acc("571"),
        ),
        # Factures clients (journal VT), TVA 18 % incluse quand le montant le permet.
        g(
            op.FACTURE_CLIENT,
            date(2026, 4, 9),
            23_600_000,
            "Marchandises diverses — Sahel Agro",
            reference="FAC-2026-001",
            nature_account_id=acc("701"),
            party_account_id=acc("4111"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 4, 23),
            9_000_000,
            "Produits de première nécessité — Kalan",
            reference="FAC-2026-002",
            nature_account_id=acc("701"),
            party_account_id=acc("4112"),
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 5, 5),
            11_800_000,
            "Marchandises — Niaga Services",
            reference="FAC-2026-003",
            nature_account_id=acc("701"),
            party_account_id=acc("4113"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 5, 19),
            17_700_000,
            "Commande saisonnière — Sahel Agro",
            reference="FAC-2026-004",
            nature_account_id=acc("701"),
            party_account_id=acc("4111"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 6, 9),
            14_250_000,
            "Matériaux livrés — Fouta BTP",
            reference="FAC-2026-005",
            nature_account_id=acc("701"),
            party_account_id=acc("4114"),
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 6, 25),
            5_900_000,
            "Réassort mensuel — Kalan",
            reference="FAC-2026-006",
            nature_account_id=acc("701"),
            party_account_id=acc("4112"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 7, 14),
            8_850_000,
            "Marchandises — Niaga Services",
            reference="FAC-2026-007",
            nature_account_id=acc("701"),
            party_account_id=acc("4113"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 8, 4),
            29_500_000,
            "Conteneur revendu — Sahel Agro",
            reference="FAC-2026-008",
            nature_account_id=acc("701"),
            party_account_id=acc("4111"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 8, 26),
            6_000_000,
            "Chantier expédié — Fouta BTP",
            reference="FAC-2026-009",
            nature_account_id=acc("701"),
            party_account_id=acc("4114"),
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 9, 17),
            13_570_000,
            "Commande rentrée — Kalan",
            reference="FAC-2026-010",
            nature_account_id=acc("701"),
            party_account_id=acc("4112"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 10, 6),
            10_620_000,
            "Marchandises — Niaga Services",
            reference="FAC-2026-011",
            nature_account_id=acc("701"),
            party_account_id=acc("4113"),
            vat_included=True,
        ),
        g(
            op.FACTURE_CLIENT,
            date(2026, 10, 15),
            7_080_000,
            "Réassort — Sahel Agro",
            reference="FAC-2026-012",
            nature_account_id=acc("701"),
            party_account_id=acc("4111"),
            vat_included=True,
        ),
        # Factures fournisseurs (journal AC).
        g(
            op.FACTURE_FOURNISSEUR,
            date(2026, 4, 15),
            17_700_000,
            "Conteneur riz — Mamaya",
            reference="FAC-F-2026-014",
            nature_account_id=acc("601"),
            party_account_id=acc("4011"),
            vat_included=True,
        ),
        g(
            op.FACTURE_FOURNISSEUR,
            date(2026, 5, 22),
            6_000_000,
            "Fournitures bureau — Conakry F.",
            reference="FAC-F-2026-021",
            nature_account_id=acc("601"),
            party_account_id=acc("4012"),
        ),
        g(
            op.FACTURE_FOURNISSEUR,
            date(2026, 6, 11),
            23_600_000,
            "Marchandises générales — Mamaya",
            reference="FAC-F-2026-033",
            nature_account_id=acc("601"),
            party_account_id=acc("4011"),
            vat_included=True,
        ),
        g(
            op.FACTURE_FOURNISSEUR,
            date(2026, 7, 29),
            4_130_000,
            "Éclairage entrepôt — Soleil Élec",
            reference="FAC-F-2026-047",
            nature_account_id=acc("601"),
            party_account_id=acc("4013"),
            vat_included=True,
        ),
        g(
            op.FACTURE_FOURNISSEUR,
            date(2026, 9, 9),
            9_500_000,
            "Emballages — Conakry F.",
            reference="FAC-F-2026-062",
            nature_account_id=acc("601"),
            party_account_id=acc("4012"),
        ),
        g(
            op.FACTURE_FOURNISSEUR,
            date(2026, 10, 19),
            15_000_000,
            "Stock fin de saison — Mamaya",
            reference="FAC-F-2026-078",
            nature_account_id=acc("601"),
            party_account_id=acc("4011"),
        ),
        # Dépenses comptant en caisse (sans relevé bancaire).
        g(
            op.ACHAT_COMPTANT,
            date(2026, 4, 25),
            300_000,
            "Carburant groupe électrogène",
            nature_account_id=acc("605"),
            treasury_account_id=acc("571"),
        ),
        g(
            op.ACHAT_COMPTANT,
            date(2026, 6, 20),
            850_000,
            "Fournitures bureau",
            nature_account_id=acc("604"),
            treasury_account_id=acc("571"),
        ),
        g(
            op.ACHAT_COMPTANT,
            date(2026, 10, 30),
            460_000,
            "Électricité boutique",
            nature_account_id=acc("605"),
            treasury_account_id=acc("571"),
        ),
        # Loyers mensuels réglés par banque (mouvement : voir apply_treasury_operations).
    ]
    for data in operations:
        _guided_create(session, actor, data)
    print(f"{len(operations)} opérations guidées créées (factures, ventes, dépenses).")


def apply_treasury_operations(
    session: Session, actor: Actor, accounts: dict[str, uuid.UUID]
) -> None:
    """Tout ce que la banque voit passe par les mouvements : dépôts, retraits, frais,
    virements internes. Chaque mouvement crée atomiquement son écriture validée."""

    def acc(number: str) -> Account:
        return _account_number(session, actor.company_id, number)

    banque, caisse, mobile = accounts["banque"], accounts["caisse"], accounts["mobile"]

    deposits = [  # (compte, date, montant, libellé, contrepartie, référence)
        (banque, date(2026, 4, 6), 120_000_000, "Capital social versé", "101", None),
        (caisse, date(2026, 4, 6), 8_000_000, "Fonds de caisse initial", "101", None),
        (mobile, date(2026, 4, 8), 3_000_000, "Alimentation Orange Money", "101", None),
        (
            banque,
            date(2026, 4, 28),
            23_600_000,
            "Virement client Sahel Agro",
            "4111",
            "FAC-2026-001",
        ),
        (
            banque,
            date(2026, 5, 14),
            9_000_000,
            "Virement client Kalan Supermarché",
            "4112",
            "FAC-2026-002",
        ),
        (
            mobile,
            date(2026, 6, 2),
            8_000_000,
            "Orange Money client Niaga Services",
            "4113",
            "FAC-2026-003",
        ),
        (
            banque,
            date(2026, 6, 30),
            17_700_000,
            "Virement client Sahel Agro",
            "4111",
            "FAC-2026-004",
        ),
        (
            mobile,
            date(2026, 8, 11),
            15_000_000,
            "Orange Money client Sahel Agro",
            "4111",
            "FAC-2026-008",
        ),
        (
            banque,
            date(2026, 9, 5),
            5_900_000,
            "Virement client Kalan Supermarché",
            "4112",
            "FAC-2026-006",
        ),
        (
            banque,
            date(2026, 10, 9),
            14_500_000,
            "Virement client Sahel Agro",
            "4111",
            "FAC-2026-008",
        ),
        (mobile, date(2026, 10, 8), 4_720_000, "Dépôts ventes boutique octobre", "701", None),
        (
            mobile,
            date(2026, 10, 22),
            4_000_000,
            "Orange Money client Niaga Services",
            "4113",
            "FAC-2026-007",
        ),
        (
            banque,
            date(2026, 10, 16),
            10_620_000,
            "Virement client Niaga Services",
            "4113",
            "FAC-2026-011",
        ),
        (mobile, date(2026, 11, 9), 2_360_000, "Dépôts ventes boutique novembre", "701", None),
        (banque, date(2026, 11, 4), 6_000_000, "Virement client Fouta BTP", "4114", "FAC-2026-009"),
    ]
    for account_id, day, amount, label, counterpart, reference in deposits:
        treasury_service.record_movement(
            session,
            actor,
            account_id,
            MovementData(
                kind="DEPOT",
                amount=amount,
                movement_date=day,
                label=label,
                counterpart_account_id=acc(counterpart).id,
                reference=reference,
            ),
        )

    withdrawals = [  # (compte, date, montant, libellé, contrepartie, référence)
        (banque, date(2026, 4, 10), 4_720_000, "Achat marchandises Mamaya", "601", None),
        (
            banque,
            date(2026, 4, 29),
            10_000_000,
            "Règlement fournisseur Mamaya",
            "4011",
            "FAC-F-2026-014",
        ),
        (banque, date(2026, 5, 8), 1_180_000, "Forfaits télécom", "628", None),
        (
            banque,
            date(2026, 5, 30),
            6_000_000,
            "Règlement fournisseur Conakry F.",
            "4012",
            "FAC-F-2026-021",
        ),
        (
            banque,
            date(2026, 6, 26),
            12_000_000,
            "Règlement fournisseur Mamaya",
            "4011",
            "FAC-F-2026-033",
        ),
        (banque, date(2026, 7, 7), 3_540_000, "Transport livraisons", "618", None),
        (
            banque,
            date(2026, 8, 5),
            4_130_000,
            "Règlement fournisseur Soleil Élec",
            "4013",
            "FAC-F-2026-047",
        ),
        (banque, date(2026, 9, 24), 5_310_000, "Réparation camionnette", "624", None),
        (
            banque,
            date(2026, 10, 8),
            9_500_000,
            "Règlement fournisseur Conakry F.",
            "4012",
            "FAC-F-2026-062",
        ),
        (banque, date(2026, 10, 12), 990_000, "Honoraires comptable", "632", None),
        (banque, date(2026, 10, 21), 3_540_000, "Transport distribution octobre", "618", None),
        (
            banque,
            date(2026, 10, 27),
            7_770_000,
            "Règlement fournisseur Mamaya",
            "4011",
            "FAC-F-2026-033",
        ),
        (mobile, date(2026, 11, 6), 790_000, "Divers imprévus boutique", "638", None),
        (
            banque,
            date(2026, 11, 3),
            3_000_000,
            "Règlement fournisseur Mamaya",
            "4011",
            "FAC-F-2026-078",
        ),
    ]
    for account_id, day, amount, label, counterpart, reference in withdrawals:
        treasury_service.record_movement(
            session,
            actor,
            account_id,
            MovementData(
                kind="RETRAIT",
                amount=amount,
                movement_date=day,
                label=label,
                counterpart_account_id=acc(counterpart).id,
                reference=reference,
            ),
        )

    # Loyers mensuels réglés par banque (libellés déjà en français, sans strftime).
    mois_fr = {5: "mai", 6: "juin", 7: "juillet", 8: "août", 9: "septembre", 10: "octobre"}
    for day in (
        date(2026, 5, 3),
        date(2026, 6, 3),
        date(2026, 7, 3),
        date(2026, 8, 3),
        date(2026, 9, 3),
        date(2026, 10, 3),
    ):
        treasury_service.record_movement(
            session,
            actor,
            banque,
            MovementData(
                kind="RETRAIT",
                amount=2_500_000,
                movement_date=day,
                label=f"Loyer entrepôt {mois_fr[day.month]} {day.year}",
                counterpart_account_id=acc("622").id,
            ),
        )

    # Frais bancaires et Mobile Money (compte 631).
    for day, amount in (
        (date(2026, 4, 30), 175_000),
        (date(2026, 5, 31), 210_000),
        (date(2026, 6, 30), 240_000),
        (date(2026, 7, 31), 250_000),
        (date(2026, 8, 31), 195_000),
        (date(2026, 9, 30), 205_000),
        (date(2026, 10, 31), 205_000),
    ):
        treasury_service.record_movement(
            session,
            actor,
            banque,
            MovementData(
                kind="FRAIS",
                amount=amount,
                movement_date=day,
                label="Frais bancaires du mois",
                counterpart_account_id=acc("631").id,
            ),
        )
    treasury_service.record_movement(
        session,
        actor,
        mobile,
        MovementData(
            kind="FRAIS",
            amount=85_000,
            movement_date=date(2026, 10, 31),
            label="Commissions Orange Money octobre",
            counterpart_account_id=acc("631").id,
        ),
    )

    # Virements internes (une écriture, deux mouvements liés).
    transfers = (
        (mobile, banque, date(2026, 5, 6), 5_000_000, "Transfert encaissements Orange vers banque"),
        (banque, caisse, date(2026, 5, 6), 4_000_000, "Alimentation caisse"),
        (mobile, banque, date(2026, 7, 1), 6_500_000, "Transfert encaissements Orange vers banque"),
        (mobile, banque, date(2026, 9, 1), 8_000_000, "Transfert encaissements Orange vers banque"),
        (banque, caisse, date(2026, 9, 1), 4_000_000, "Alimentation caisse"),
        (
            mobile,
            banque,
            date(2026, 11, 5),
            7_000_000,
            "Transfert encaissements Orange vers banque",
        ),
    )
    for source, target, day, amount, label in transfers:
        treasury_service.record_transfer(
            session,
            actor,
            source,
            target,
            TransferData(amount=amount, movement_date=day, label=label),
        )

    print(
        f"{len(deposits)} dépôts, {len(withdrawals) + 7} retraits/frais, "
        f"{len(transfers)} virements internes créés (mouvements + écritures)."
    )


def create_draft_example(
    session: Session, actor: Actor, accounts_gl: dict[str, uuid.UUID]
) -> uuid.UUID:
    """Une écriture en brouillon volontairement laissée à valider depuis l'interface."""
    od = _journal_by_code(session, actor.company_id, "OD")
    entry, _created = create_draft(
        session,
        actor,
        EntryData(
            journal_id=od.id,
            entry_date=date(2026, 10, 28),
            label="Caution eau-électricité versée (à régulariser)",
            reference="CAUT-001",
            lines=[
                LineData(
                    account_id=accounts_gl["471"], debit=1_500_000, credit=0, label="Caution versée"
                ),
                LineData(
                    account_id=accounts_gl["5211"],
                    debit=0,
                    credit=1_500_000,
                    label="Caution versée",
                ),
            ],
        ),
    )
    print("Brouillon laissé à valider : caution eau-électricité (OD, 1 500 000 GNF).")
    return entry.id


def apply_lettering(session: Session, actor: Actor, accounts_gl: dict[str, uuid.UUID]) -> int:
    """Lettrage automatique des factures entièrement réglées (références identiques)."""
    total = 0
    for number in ("4111", "4112", "4113", "4114", "4011", "4012", "4013"):
        total += auto_letter_by_reference(session, actor, accounts_gl[number])
    print(f"Lettrage automatique : {total} factures lettrées.")
    return total


# --- Génération des relevés fictifs -------------------------------------------


def _movements(
    session: Session, company_id: uuid.UUID, account_id: uuid.UUID, start: date, end: date
) -> list[tuple[FinancialMovement, str | None]]:
    """Mouvements d'un compte sur la période, avec la référence de leur écriture."""
    rows = session.execute(
        select(FinancialMovement, JournalEntry.reference)
        .join(
            JournalEntry,
            (JournalEntry.tenant_id == FinancialMovement.tenant_id)
            & (JournalEntry.id == FinancialMovement.entry_id),
        )
        .where(
            FinancialMovement.tenant_id == company_id,
            FinancialMovement.financial_account_id == account_id,
            FinancialMovement.movement_date >= start,
            FinancialMovement.movement_date <= end,
        )
        .order_by(
            FinancialMovement.movement_date, FinancialMovement.created_at, FinancialMovement.id
        )
    ).all()
    return list(rows)


def _bank_rows(
    movements: list[tuple[FinancialMovement, str | None]],
    anomalies: tuple[tuple[date, int, str, str | None], ...],
) -> list[tuple[date, int, str, str | None]]:
    """Lignes du relevé : mouvements réels + opérations « surprises » triées par date."""
    rows = [
        (m.movement_date, _signed(m.amount, m.direction), m.label, reference)
        for m, reference in movements
    ]
    rows.extend((day, amount, label, reference) for day, amount, label, reference in anomalies)
    return sorted(rows, key=lambda row: (row[0], row[1]))


def _solde_initial(
    session: Session, company_id: uuid.UUID, account_id: uuid.UUID, before: date
) -> int:
    rows = (
        session.execute(
            select(FinancialMovement).where(
                FinancialMovement.tenant_id == company_id,
                FinancialMovement.financial_account_id == account_id,
                FinancialMovement.movement_date < before,
            )
        )
        .scalars()
        .all()
    )
    return sum(_signed(m.amount, m.direction) for m in rows)


def write_csv(
    path: Path,
    rows: list[tuple[date, int, str, str | None]],
    *,
    with_balance: bool,
    initial_balance: int = 0,
) -> None:
    """Export bancaire francophone : Date;Libellé;Référence;Montant[;Solde] (d/m/aaaa)."""
    lines = ["Date;Libellé;Référence;Montant" + (";Solde" if with_balance else "")]
    balance = initial_balance
    for day, amount, label, reference in rows:
        balance += amount
        cells = [
            day.strftime("%d/%m/%Y"),
            label,
            reference or "",
            f"{'-' if amount < 0 else ''}{_fmt_gnf(amount)}",
        ]
        if with_balance:
            cells.append(f"{'-' if balance < 0 else ''}{_fmt_gnf(balance)}")
        lines.append(";".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ofx(
    path: Path,
    rows: list[tuple[date, int, str, str | None]],
    *,
    final_balance: int,
    bank_id: str,
    acct_id: str,
) -> None:
    """Relevé OFX 1.x (SGML) tel qu'un export bancaire : blocs STMTTRN non fermés."""
    header = (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\n"
        "CHARSET:1252\nCOMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
    )
    start = rows[0][0].strftime("%Y%m%d")
    end = rows[-1][0].strftime("%Y%m%d")
    body = [
        "<OFX>",
        "<BANKMSGSRSV1><STMTTRNRS><TRNUID>0",
        "<STATUS><CODE>0<SEVERITY>INFO",
        "<STMTRS><CURDEF>GNF",
        f"<BANKACCTFROM><BANKID>{bank_id}<ACCTID>{acct_id}<ACCTTYPE>CHECKING",
        "<BANKTRANLIST>",
        f"<DTSTART>{start}<DTEND>{end}",
    ]
    for index, (day, amount, label, reference) in enumerate(rows, start=1):
        trntype = "CREDIT" if amount > 0 else "DEBIT"
        body.append("<STMTTRN>")
        body.append(f"<TRNTYPE>{trntype}")
        body.append(f"<DTPOSTED>{day.strftime('%Y%m%d')}120000")
        body.append(f"<TRNAMT>{Decimal(amount):.2f}")
        body.append(f"<FITID>{reference or f'{day.strftime("%Y%m%d")}-{index}'}")
        body.append(f"<NAME>{label[:60]}")
        body.append(f"<MEMO>{label[:60]}")
        body.append("</STMTTRN>")
    body.append("</BANKTRANLIST>")
    body.append(f"<LEDGERBAL><BALAMT>{Decimal(final_balance):.2f}<DTASOF>{end}120000")
    body.append("</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>")
    path.write_text(header + "\n".join(body) + "\n", encoding="utf-8")


def write_statements(
    session: Session, company_id: uuid.UUID, accounts: dict[str, uuid.UUID], out_dir: Path
) -> list[Path]:
    """Trois fichiers de relevés fictifs, construits depuis les mouvements réellement
    créés (cohérence garantie) plus les opérations absentes de la comptabilité."""
    out_dir.mkdir(parents=True, exist_ok=True)
    bank = _movements(
        session, company_id, accounts["banque"], date(2026, 10, 1), date(2026, 10, 31)
    )
    bank_nov = _movements(
        session, company_id, accounts["banque"], date(2026, 11, 1), date(2026, 11, 12)
    )
    mobile = _movements(
        session, company_id, accounts["mobile"], date(2026, 10, 1), date(2026, 11, 12)
    )

    bank_rows = _bank_rows(bank, ANOMALIES_BANQUE_OCTOBRE)
    bank_nov_rows = _bank_rows(bank_nov, ANOMALIES_BANQUE_NOVEMBRE)
    mobile_rows = _bank_rows(mobile, ANOMALIES_MM)

    initial_oct = _solde_initial(session, company_id, accounts["banque"], date(2026, 10, 1))
    initial_nov = _solde_initial(session, company_id, accounts["banque"], date(2026, 11, 1))

    files: list[Path] = []
    bank_csv = out_dir / "releve-banque-fouta-2026-10.csv"
    write_csv(bank_csv, bank_rows, with_balance=True, initial_balance=initial_oct)
    bank_ofx = out_dir / "releve-banque-fouta-2026-11.ofx"
    write_ofx(
        bank_ofx,
        bank_nov_rows,
        final_balance=initial_nov + sum(r[1] for r in bank_nov_rows),
        bank_id="FOUTAGN",
        acct_id="0004037",
    )
    mobile_csv = out_dir / "releve-orange-money-2026-10-11.csv"
    write_csv(mobile_csv, mobile_rows, with_balance=False)
    files.extend((bank_csv, bank_ofx, mobile_csv))

    print("Relevés fictifs générés dans", out_dir)
    for path, count in (
        (bank_csv, len(bank_rows)),
        (bank_ofx, len(bank_nov_rows)),
        (mobile_csv, len(mobile_rows)),
    ):
        print(f"  {path.name} — {count} lignes")
    return files


# --- Orchestration ------------------------------------------------------------


def balances(session: Session, company_id: uuid.UUID, accounts: dict[str, uuid.UUID]) -> str:
    parts = []
    for name, label in (("banque", "Banque"), ("caisse", "Caisse"), ("mobile", "Orange Money")):
        rows = (
            session.execute(
                select(FinancialMovement).where(
                    FinancialMovement.tenant_id == company_id,
                    FinancialMovement.financial_account_id == accounts[name],
                )
            )
            .scalars()
            .all()
        )
        total = sum(_signed(m.amount, m.direction) for m in rows)
        parts.append(f"{label} {_fmt_gnf(total)} GNF")
    return " · ".join(parts)


def print_summary(
    session: Session, company: Company, accounts_fin: dict[str, uuid.UUID], files: list[Path]
) -> None:
    """Récapitulatif final : connexions, volumes, soldes, scénario de test."""
    entries_count = session.execute(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.tenant_id == company.id)
    ).scalar_one()
    drafts = session.execute(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.tenant_id == company.id, JournalEntry.status == "DRAFT")
    ).scalar_one()

    print()
    print("=" * 64)
    print("Démonstration prête — tout est fictif.")
    print("Connexion : http://localhost:3100")
    for local, full_name, role in USERS:
        print(f"  {local}@{DEMO_DOMAIN} / {DEMO_PASSWORD}  ({role.value} — {full_name})")
    print(f"Écritures du dossier : {entries_count} (dont {drafts} brouillon à valider)")
    print("Soldes :", balances(session, company.id, accounts_fin))
    print("Relevés à importer (Trésorerie → compte → Importer un relevé) :")
    for path in files:
        print(f"  {path}")
    print("Scénario : importez les relevés, puis Rapprochement → confirmez les")
    print("propositions ; 5 opérations « surprises » n'ont aucun candidat :")
    print("  agios -182 500, commission recouvrement -145 000, commission dépôt agent")
    print("  -12 000 → enregistrez-les (Frais bancaires et Mobile Money) ;")
    print("  remise chèque +9 800 000 → enregistrez le dépôt, puis rapprochez ;")
    print("  alerte SMS -25 000 → Ignorez la ligne (déjà suivie ailleurs).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crée le jeu de données fictif de démonstration.")
    parser.add_argument(
        "--reset", action="store_true", help="supprime la démonstration existante puis la recrée"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("demo"),
        help="dossier des relevés générés (défaut : ./demo)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    # On n'affiche jamais l'URL complète : elle contient le mot de passe de la base.
    url = settings.database_url
    host = url.hosts()[0]
    database = url.path.lstrip("/") if url.path else "?"
    print(f"Base cible : {host['host']}:{host.get('port')}/{database}")

    session = get_sessionmaker()()
    try:
        existing = session.execute(
            select(Company).where(Company.legal_name == DEMO_COMPANY_LEGAL_NAME)
        ).scalar_one_or_none()
        if existing is not None and not args.reset:
            raise SystemExit(
                "La démonstration existe déjà ; utilisez --reset pour la recréer à l'identique."
            )
        if args.reset:
            reset_demo()

        directeur, comptable, lecteur = create_users(session)
        company = create_demo_company(session, directeur)
        bind_tenant(session, company.id)
        create_memberships(session, company, comptable, lecteur)

        ctx = RequestContext(user_agent="seed-demo")
        actor = Actor(company_id=company.id, user_id=directeur.id, ctx=ctx)

        accounts_gl = create_subaccounts(session, actor)
        # 101 et 471 du référentiel, ajoutés aux sous-comptes utiles.
        accounts_gl["101"] = _account_number(session, company.id, "101").id
        accounts_gl["471"] = _account_number(session, company.id, "471").id
        accounts_gl["571"] = _account_number(session, company.id, "571").id
        accounts_fin = create_financial_accounts(session, actor, accounts_gl)

        apply_guided_operations(session, actor, accounts_gl)
        apply_treasury_operations(session, actor, accounts_fin)
        create_draft_example(session, actor, accounts_gl)
        apply_lettering(session, actor, accounts_gl)

        files = write_statements(session, company.id, accounts_fin, args.out)
        print_summary(session, company, accounts_fin, files)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
