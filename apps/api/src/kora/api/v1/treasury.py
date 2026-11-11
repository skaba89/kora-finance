"""Routes de la trésorerie : comptes financiers, mouvements (3A), relevés
bancaires importés (3B) et rapprochement (3C)."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from kora.accounting.entries import Actor
from kora.api.v1.common import (
    TENANT_ERRORS,
    WRITE_ERRORS,
    Limit,
    Money,
    Offset,
    RequestBody,
    SignedMoney,
)
from kora.auth.deps import Ctx, DbSession
from kora.core.config import get_settings
from kora.core.errors import ErrorResponse
from kora.models.treasury import BankStatement, StatementLineStatus
from kora.tenancy.deps import TenantContext, TreasuryManage, TreasuryRead
from kora.treasury import reconciliation, service, statements
from kora.treasury.service import AccountData, MovementData, TransferData

router = APIRouter(prefix="/companies/{company_id}", tags=["trésorerie"])

ACCOUNT_KINDS = Literal["BANQUE", "CAISSE", "MOBILE_MONEY"]
MOVEMENT_KINDS = Literal["DEPOT", "RETRAIT", "FRAIS"]


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


class FinancialAccountOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: ACCOUNT_KINDS
    operator: str | None
    account_number_masked: str | None
    gl_account_id: uuid.UUID
    gl_account_number: str
    gl_account_label: str
    is_active: bool
    balance: SignedMoney = Field(description="Solde du compte comptable lié (positif = débiteur)")
    created_at: str


class FinancialAccountsOut(BaseModel):
    items: list[FinancialAccountOut]


class FinancialAccountCreate(RequestBody):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    kind: ACCOUNT_KINDS
    gl_account_id: uuid.UUID
    operator: Annotated[str | None, Field(pattern=r"^[A-Z0-9_]{2,24}$")] = None
    account_number_masked: Annotated[str | None, Field(max_length=40)] = None


class FinancialMovementOut(BaseModel):
    id: uuid.UUID
    kind: Literal["DEPOT", "RETRAIT", "VIREMENT_INTERNE", "FRAIS"]
    direction: Literal["DEBIT", "CREDIT"]
    amount: Money
    movement_date: date
    label: str
    counterpart_number: str | None
    counterpart_label: str | None
    entry_id: uuid.UUID
    entry_number: int | None
    created_at: str


class FinancialMovementsOut(BaseModel):
    account_id: uuid.UUID
    balance: SignedMoney
    items: list[FinancialMovementOut]
    total: int
    limit: int
    offset: int


class FinancialMovementCreate(RequestBody):
    kind: MOVEMENT_KINDS
    amount: Money
    movement_date: date
    label: Annotated[str, Field(min_length=1, max_length=200)]
    counterpart_account_id: uuid.UUID
    reference: Annotated[str | None, Field(max_length=60)] = None


class FinancialMovementRecorded(BaseModel):
    id: uuid.UUID
    entry_id: uuid.UUID


class TransferCreate(RequestBody):
    source_account_id: uuid.UUID
    target_account_id: uuid.UUID
    amount: Money
    movement_date: date
    label: Annotated[str, Field(min_length=1, max_length=200)]
    reference: Annotated[str | None, Field(max_length=60)] = None


class TransferRecorded(BaseModel):
    entry_id: uuid.UUID
    source_movement_id: uuid.UUID
    target_movement_id: uuid.UUID


# --- Relevés bancaires (3B)


class BankStatementOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    filename: str
    format: Literal["OFX", "CSV"]
    size_bytes: int
    sha256: str
    line_count: int
    period_start: date
    period_end: date
    created_at: str


class BankStatementsOut(BaseModel):
    account_id: uuid.UUID
    items: list[BankStatementOut]
    total: int
    limit: int
    offset: int


class StatementLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    value_date: date
    # Montant signé du point de vue du titulaire : positif = entrée de fonds.
    amount: SignedMoney
    label: str
    reference: str | None
    balance_after: SignedMoney | None
    status: Literal["PENDING", "MATCHED", "IGNORED"]
    # La même opération figure déjà sur un autre relevé du même compte.
    duplicate: bool


class StatementLinesOut(BaseModel):
    statement_id: uuid.UUID
    items: list[StatementLineOut]
    total: int
    limit: int
    offset: int


class StatementLineSet(BaseModel):
    id: uuid.UUID
    status: Literal["PENDING", "MATCHED", "IGNORED"]


# --- Rapprochement (3C)


class MatchCandidateOut(BaseModel):
    id: uuid.UUID
    kind: Literal["DEPOT", "RETRAIT", "VIREMENT_INTERNE", "FRAIS"]
    direction: Literal["DEBIT", "CREDIT"]
    amount: Money
    movement_date: date
    label: str
    entry_number: int | None
    days_apart: int
    score: int


class MatchCandidatesOut(BaseModel):
    line_id: uuid.UUID
    line_no: int
    value_date: date
    amount: SignedMoney
    label: str
    # Propositions classées (score décroissant) : jamais appliquées automatiquement,
    # la confirmation reste un acte humain.
    candidates: list[MatchCandidateOut]


class MatchConfirm(RequestBody):
    movement_id: uuid.UUID


class ReconciliationOut(BaseModel):
    account_id: uuid.UUID
    lines_pending: int
    lines_matched: int
    lines_ignored: int
    # Somme signée des lignes à rapprocher : ce que le relevé attend d'explications.
    pending_net: SignedMoney
    movements_unmatched: int


@router.get("/treasury/accounts", responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]})
def list_accounts(tenant: TreasuryRead, db: DbSession) -> FinancialAccountsOut:
    """Comptes financiers du dossier (banques, caisses, Mobile Money) et leurs soldes."""
    return FinancialAccountsOut(
        items=[
            FinancialAccountOut(
                id=view.account.id,
                name=view.account.name,
                kind=view.account.kind,
                operator=view.account.operator,
                account_number_masked=view.account.account_number_masked,
                gl_account_id=view.account.gl_account_id,
                gl_account_number=view.gl_account_number,
                gl_account_label=view.gl_account_label,
                is_active=view.account.is_active,
                balance=view.balance,
                created_at=view.account.created_at.isoformat(),
            )
            for view in service.list_accounts(db, tenant.company_id)
        ]
    )


@router.post("/treasury/accounts", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_account(
    body: FinancialAccountCreate, tenant: TreasuryManage, db: DbSession, ctx: Ctx
) -> FinancialAccountOut:
    created = service.create_account(
        db,
        _actor(tenant, ctx),
        AccountData(
            name=body.name,
            kind=body.kind,
            gl_account_id=body.gl_account_id,
            operator=body.operator,
            account_number_masked=body.account_number_masked,
        ),
    )
    view = service.get_account(db, tenant.company_id, created.id)
    return FinancialAccountOut(
        id=view.account.id,
        name=view.account.name,
        kind=view.account.kind,
        operator=view.account.operator,
        account_number_masked=view.account.account_number_masked,
        gl_account_id=view.account.gl_account_id,
        gl_account_number=view.gl_account_number,
        gl_account_label=view.gl_account_label,
        is_active=view.account.is_active,
        balance=view.balance,
        created_at=view.account.created_at.isoformat(),
    )


@router.get(
    "/treasury/accounts/{account_id}/movements",
    responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]},
)
def list_movements(
    account_id: uuid.UUID,
    tenant: TreasuryRead,
    db: DbSession,
    limit: Limit = 100,
    offset: Offset = 0,
) -> FinancialMovementsOut:
    """Historique des mouvements du compte, du plus ancien au plus récent."""
    page = service.list_movements(db, tenant.company_id, account_id, limit=limit, offset=offset)
    return FinancialMovementsOut(
        account_id=page.account.id,
        balance=page.balance,
        items=[
            FinancialMovementOut(
                id=row.id,
                kind=row.kind,
                direction=row.direction,
                amount=row.amount,
                movement_date=row.movement_date,
                label=row.label,
                counterpart_number=row.counterpart_number,
                counterpart_label=row.counterpart_label,
                entry_id=row.entry_id,
                entry_number=row.entry_number,
                created_at=row.created_at,
            )
            for row in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/treasury/accounts/{account_id}/movements",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
def record_movement(
    account_id: uuid.UUID,
    body: FinancialMovementCreate,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> FinancialMovementRecorded:
    """Dépôt, retrait ou frais bancaires : crée l'écriture validée et sa trace."""
    movement = service.record_movement(
        db,
        _actor(tenant, ctx),
        account_id,
        MovementData(
            kind=body.kind,
            amount=body.amount,
            movement_date=body.movement_date,
            label=body.label,
            counterpart_account_id=body.counterpart_account_id,
            reference=body.reference,
        ),
    )
    return FinancialMovementRecorded(id=movement.id, entry_id=movement.entry_id)


@router.post("/treasury/transfers", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def record_transfer(
    body: TransferCreate, tenant: TreasuryManage, db: DbSession, ctx: Ctx
) -> TransferRecorded:
    """Virement interne entre deux comptes financiers du dossier."""
    source, target = service.record_transfer(
        db,
        _actor(tenant, ctx),
        body.source_account_id,
        body.target_account_id,
        TransferData(
            amount=body.amount,
            movement_date=body.movement_date,
            label=body.label,
            reference=body.reference,
        ),
    )
    return TransferRecorded(
        entry_id=source.entry_id,
        source_movement_id=source.id,
        target_movement_id=target.id,
    )


# --- Relevés bancaires importés (3B)


async def _read_body(request: Request) -> bytes:
    """Corps brut de l'import : lu par morceaux, refusé dès que la taille maximale
    est dépassée (même mécanisme que les pièces justificatives)."""
    limit = get_settings().statement_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise statements.too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise statements.too_large()
        chunks.append(chunk)
    return b"".join(chunks)


_STATEMENT_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": f"Contenu brut du relevé ({statements.ACCEPTED_FORMATS})",
        "content": {
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


def _statement_out(statement: BankStatement, account_id: uuid.UUID) -> BankStatementOut:
    return BankStatementOut(
        id=statement.id,
        account_id=account_id,
        filename=statement.filename,
        format=statement.format,
        size_bytes=statement.size_bytes,
        sha256=statement.sha256,
        line_count=statement.line_count,
        period_start=statement.period_start,
        period_end=statement.period_end,
        created_at=statement.created_at.isoformat(),
    )


@router.post(
    "/treasury/accounts/{account_id}/statements",
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_STATEMENT_UPLOAD_BODY,
    responses={
        **WRITE_ERRORS,
        413: {"model": ErrorResponse},
    },
)
async def import_statement(
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
    account_id: uuid.UUID,
    request: Request,
    filename: Annotated[str | None, Query(max_length=200)] = None,
) -> BankStatementOut:
    """Importe un relevé bancaire (OFX ou CSV) sur un compte financier : lignes en
    attente de rapprochement, fichier original conservé, réimport refusé."""
    content = await _read_body(request)
    # Le nom du fichier sert à l'affichage et à l'audit : la détection du format
    # ne se fie qu'au contenu.
    statement = statements.import_statement(
        db,
        _actor(tenant, ctx),
        account_id,
        filename or "releve",
        content,
    )
    return _statement_out(statement, account_id)


@router.get(
    "/treasury/accounts/{account_id}/statements",
    responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]},
)
def list_statements(
    account_id: uuid.UUID,
    tenant: TreasuryRead,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
) -> BankStatementsOut:
    """Relevés importés d'un compte, du plus récent au plus ancien."""
    page = statements.list_statements(db, tenant.company_id, account_id, limit=limit, offset=offset)
    return BankStatementsOut(
        account_id=account_id,
        items=[_statement_out(view.statement, account_id) for view in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/treasury/statements/{statement_id}/lines",
    responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]},
)
def list_statement_lines(
    statement_id: uuid.UUID,
    tenant: TreasuryRead,
    db: DbSession,
    limit: Limit = 100,
    offset: Offset = 0,
) -> StatementLinesOut:
    """Lignes d'un relevé, dans l'ordre du fichier, doublons signalés."""
    page = statements.list_statement_lines(
        db, tenant.company_id, statement_id, limit=limit, offset=offset
    )
    return StatementLinesOut(
        statement_id=statement_id,
        items=[
            StatementLineOut(
                id=row.id,
                line_no=row.line_no,
                value_date=date.fromisoformat(row.value_date),
                amount=row.amount,
                label=row.label,
                reference=row.reference,
                balance_after=row.balance_after,
                status=row.status,
                duplicate=row.duplicate,
            )
            for row in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/treasury/statements/{statement_id}/lines/{line_id}/ignore",
    responses={**WRITE_ERRORS, 422: TENANT_ERRORS[404]},
)
def ignore_statement_line(
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> StatementLineSet:
    """Écarte une ligne du rapprochement (agios déjà comptabilisés, doublon d'export…) ;
    la ligne reste dans le relevé pour la traçabilité."""
    line = statements.set_line_status(
        db,
        _actor(tenant, ctx),
        statement_id,
        line_id,
        StatementLineStatus.IGNORED,
    )
    return StatementLineSet(id=line.id, status=line.status)


@router.post(
    "/treasury/statements/{statement_id}/lines/{line_id}/restore",
    responses={**WRITE_ERRORS, 422: TENANT_ERRORS[404]},
)
def restore_statement_line(
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> StatementLineSet:
    """Remet une ligne ignorée en attente de rapprochement."""
    line = statements.set_line_status(
        db,
        _actor(tenant, ctx),
        statement_id,
        line_id,
        StatementLineStatus.PENDING,
    )
    return StatementLineSet(id=line.id, status=line.status)


@router.delete(
    "/treasury/statements/{statement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**WRITE_ERRORS, 422: TENANT_ERRORS[404]},
)
def delete_statement(
    statement_id: uuid.UUID,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> None:
    """Supprime un relevé non rapproché (et son fichier original conservé)."""
    statements.delete_statement(db, _actor(tenant, ctx), statement_id)


# --- Rapprochement (3C)


@router.get(
    "/treasury/statements/{statement_id}/lines/{line_id}/candidates",
    responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]},
)
def match_candidates(
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    tenant: TreasuryRead,
    db: DbSession,
) -> MatchCandidatesOut:
    """Candidats de rapprochement d'une ligne en attente : mouvements du même
    compte, montant égal, direction cohérente, jamais rapprochés — classés par
    ressemblance. Propositions seulement : la confirmation reste humaine."""
    line = reconciliation.propose_candidates(db, tenant.company_id, statement_id, line_id)
    return MatchCandidatesOut(
        line_id=line.line_id,
        line_no=line.line_no,
        value_date=date.fromisoformat(line.value_date),
        amount=line.amount,
        label=line.label,
        candidates=[
            MatchCandidateOut(
                id=c.id,
                kind=c.kind,
                direction=c.direction,
                amount=c.amount,
                movement_date=date.fromisoformat(c.movement_date),
                label=c.label,
                entry_number=c.entry_number,
                days_apart=c.days_apart,
                score=c.score,
            )
            for c in line.candidates
        ],
    )


@router.post(
    "/treasury/statements/{statement_id}/lines/{line_id}/match",
    responses={**WRITE_ERRORS, 422: TENANT_ERRORS[404]},
)
def confirm_match(
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    body: MatchConfirm,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> StatementLineSet:
    """Confirme le rapprochement d'une ligne avec le mouvement choisi : la ligne
    passe en MATCHED, le lien est tracé dans le journal d'audit, réversible."""
    line = reconciliation.confirm_match(
        db, _actor(tenant, ctx), statement_id, line_id, body.movement_id
    )
    return StatementLineSet(id=line.id, status=line.status)


@router.post(
    "/treasury/statements/{statement_id}/lines/{line_id}/unmatch",
    responses={**WRITE_ERRORS, 422: TENANT_ERRORS[404]},
)
def unmatch_statement_line(
    statement_id: uuid.UUID,
    line_id: uuid.UUID,
    tenant: TreasuryManage,
    db: DbSession,
    ctx: Ctx,
) -> StatementLineSet:
    """Retire le rapprochement d'une ligne : elle repasse en attente, le mouvement
    redevient disponible."""
    line = reconciliation.unmatch_line(db, _actor(tenant, ctx), statement_id, line_id)
    return StatementLineSet(id=line.id, status=line.status)


@router.get(
    "/treasury/accounts/{account_id}/reconciliation",
    responses={**TENANT_ERRORS, 422: TENANT_ERRORS[404]},
)
def reconciliation_overview(
    account_id: uuid.UUID,
    tenant: TreasuryRead,
    db: DbSession,
) -> ReconciliationOut:
    """Vue d'ensemble du rapprochement d'un compte : compteurs par statut, solde
    des lignes en attente, mouvements restés sans ligne."""
    view = reconciliation.reconciliation_overview(db, tenant.company_id, account_id)
    return ReconciliationOut(
        account_id=view.account_id,
        lines_pending=view.lines_pending,
        lines_matched=view.lines_matched,
        lines_ignored=view.lines_ignored,
        pending_net=view.pending_net,
        movements_unmatched=view.movements_unmatched,
    )
