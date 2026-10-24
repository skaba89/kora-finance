"""Routes de la comptabilité générale : journaux et écritures."""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from kora.accounting import entries, journals
from kora.accounting.entries import Actor, EntryData, EntryFilters, LineData
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Limit, Money, Offset, Page, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.models.ledger import (
    MAX_LINE_AMOUNT,
    MAX_LINES_PER_ENTRY,
    EntryStatus,
    Journal,
    JournalKind,
)
from kora.tenancy.deps import EntriesPost, EntriesRead, EntriesWrite, JournalsManage, TenantContext

router = APIRouter(prefix="/companies/{company_id}", tags=["comptabilité générale"])


def _actor(tenant: TenantContext, ctx: Ctx) -> Actor:
    return Actor(tenant.company_id, tenant.user.id, ctx)


# --- Journaux


class JournalOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    kind: JournalKind
    is_active: bool

    @classmethod
    def of(cls, journal: Journal) -> "JournalOut":
        return cls.model_validate(journal, from_attributes=True)


class JournalCreate(RequestBody):
    code: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,8}$")]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    kind: JournalKind


class JournalUpdate(RequestBody):
    label: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    is_active: bool | None = None


@router.get("/journals", responses=TENANT_ERRORS)
def list_journals(tenant: EntriesRead, db: DbSession) -> list[JournalOut]:
    return [JournalOut.of(j) for j in journals.list_journals(db, tenant.company_id)]


@router.post("/journals", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_journal(
    body: JournalCreate, tenant: JournalsManage, db: DbSession, ctx: Ctx
) -> JournalOut:
    journal = journals.create_journal(
        db,
        tenant.company_id,
        code=body.code,
        label=body.label,
        kind=body.kind,
        actor=tenant.user.id,
        ctx=ctx,
    )
    return JournalOut.of(journal)


@router.patch("/journals/{journal_id}", responses=WRITE_ERRORS)
def update_journal(
    journal_id: uuid.UUID, body: JournalUpdate, tenant: JournalsManage, db: DbSession, ctx: Ctx
) -> JournalOut:
    journal = journals.update_journal(
        db,
        tenant.company_id,
        journal_id,
        label=body.label,
        is_active=body.is_active,
        actor=tenant.user.id,
        ctx=ctx,
    )
    return JournalOut.of(journal)


# --- Écritures


LineAmount = Annotated[Money, Field(ge=0, le=MAX_LINE_AMOUNT)]


class LineIn(RequestBody):
    account_id: uuid.UUID
    label: Annotated[str | None, Field(max_length=200)] = None
    debit: LineAmount = 0
    credit: LineAmount = 0


class EntryIn(RequestBody):
    journal_id: uuid.UUID
    entry_date: date
    label: Annotated[str, Field(min_length=1, max_length=200)]
    reference: Annotated[str | None, Field(max_length=60)] = None
    lines: Annotated[list[LineIn], Field(min_length=1, max_length=MAX_LINES_PER_ENTRY)]

    def data(self) -> EntryData:
        return EntryData(
            journal_id=self.journal_id,
            entry_date=self.entry_date,
            label=self.label,
            reference=self.reference,
            lines=[
                LineData(account_id=ln.account_id, debit=ln.debit, credit=ln.credit, label=ln.label)
                for ln in self.lines
            ],
        )


class EntryCreate(EntryIn):
    id: uuid.UUID | None = Field(
        default=None,
        description="Identifiant choisi par le client : rend la création idempotente "
        "(renvoi d'un brouillon saisi hors connexion).",
    )


class ReversalIn(RequestBody):
    entry_date: date = Field(description="Date de la contre-passation")


class LineOut(BaseModel):
    line_no: int
    account_id: uuid.UUID
    account_number: str
    account_label: str
    label: str | None
    debit: Money
    credit: Money


class EntrySummaryOut(BaseModel):
    id: uuid.UUID
    journal_id: uuid.UUID
    journal_code: str
    fiscal_year_id: uuid.UUID
    entry_date: date
    number: int | None
    reference: str | None
    label: str
    status: EntryStatus
    total_debit: Money
    total_credit: Money
    reversal_of_id: uuid.UUID | None
    created_at: datetime
    posted_at: datetime | None


class EntryOut(EntrySummaryOut):
    lines: list[LineOut]
    reversed_by_id: uuid.UUID | None


def _entry_out(db: DbSession, company_id: uuid.UUID, entry_id: uuid.UUID) -> EntryOut:
    view = entries.get_entry(db, company_id, entry_id)
    entry = view.entry
    return EntryOut(
        id=entry.id,
        journal_id=entry.journal_id,
        journal_code=view.journal.code,
        fiscal_year_id=entry.fiscal_year_id,
        entry_date=entry.entry_date,
        number=entry.number,
        reference=entry.reference,
        label=entry.label,
        status=EntryStatus(entry.status),
        total_debit=sum(line.debit for line, _ in view.lines),
        total_credit=sum(line.credit for line, _ in view.lines),
        reversal_of_id=entry.reversal_of_id,
        created_at=entry.created_at,
        posted_at=entry.posted_at,
        lines=[
            LineOut(
                line_no=line.line_no,
                account_id=account.id,
                account_number=account.number,
                account_label=account.label,
                label=line.label,
                debit=line.debit,
                credit=line.credit,
            )
            for line, account in view.lines
        ],
        reversed_by_id=entries.reversal_id_of(db, company_id, entry.id),
    )


@router.get("/entries", responses=TENANT_ERRORS)
def list_entries(
    tenant: EntriesRead,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
    journal_id: uuid.UUID | None = None,
    fiscal_year_id: uuid.UUID | None = None,
    entry_status: Annotated[EntryStatus | None, Query(alias="status")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Libellé ou référence")] = None,
) -> Page[EntrySummaryOut]:
    filters = EntryFilters(
        journal_id=journal_id,
        fiscal_year_id=fiscal_year_id,
        status=entry_status,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        search=q.strip() if q and q.strip() else None,
    )
    rows, total = entries.list_entries(db, tenant.company_id, filters, limit=limit, offset=offset)
    items = [
        EntrySummaryOut(
            id=r.entry.id,
            journal_id=r.entry.journal_id,
            journal_code=r.journal_code,
            fiscal_year_id=r.entry.fiscal_year_id,
            entry_date=r.entry.entry_date,
            number=r.entry.number,
            reference=r.entry.reference,
            label=r.entry.label,
            status=EntryStatus(r.entry.status),
            total_debit=r.total_debit,
            total_credit=r.total_credit,
            reversal_of_id=r.entry.reversal_of_id,
            created_at=r.entry.created_at,
            posted_at=r.entry.posted_at,
        )
        for r in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/entries", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS)
def create_entry(
    body: EntryCreate, tenant: EntriesWrite, db: DbSession, ctx: Ctx, response: Response
) -> EntryOut:
    """Crée un brouillon. Avec un `id` déjà connu du dossier : renvoie l'existant (200)."""
    entry, created = entries.create_draft(db, _actor(tenant, ctx), body.data(), entry_id=body.id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _entry_out(db, tenant.company_id, entry.id)


@router.get("/entries/{entry_id}", responses=TENANT_ERRORS)
def get_entry(entry_id: uuid.UUID, tenant: EntriesRead, db: DbSession) -> EntryOut:
    return _entry_out(db, tenant.company_id, entry_id)


@router.put("/entries/{entry_id}", responses=WRITE_ERRORS)
def update_entry(
    entry_id: uuid.UUID, body: EntryIn, tenant: EntriesWrite, db: DbSession, ctx: Ctx
) -> EntryOut:
    entries.update_draft(db, _actor(tenant, ctx), entry_id, body.data())
    return _entry_out(db, tenant.company_id, entry_id)


@router.delete(
    "/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, responses=WRITE_ERRORS
)
def delete_entry(entry_id: uuid.UUID, tenant: EntriesWrite, db: DbSession, ctx: Ctx) -> None:
    entries.delete_draft(db, _actor(tenant, ctx), entry_id)


@router.post("/entries/{entry_id}/post", responses=WRITE_ERRORS)
def post_entry(entry_id: uuid.UUID, tenant: EntriesPost, db: DbSession, ctx: Ctx) -> EntryOut:
    """Valide l'écriture : contrôles, numéro définitif, puis immuable."""
    entries.post_entry(db, _actor(tenant, ctx), entry_id)
    return _entry_out(db, tenant.company_id, entry_id)


@router.post(
    "/entries/{entry_id}/reversal", status_code=status.HTTP_201_CREATED, responses=WRITE_ERRORS
)
def reverse_entry(
    entry_id: uuid.UUID, body: ReversalIn, tenant: EntriesPost, db: DbSession, ctx: Ctx
) -> EntryOut:
    """Contre-passe une écriture validée ; renvoie l'écriture de contre-passation."""
    reversal = entries.reverse_entry(
        db, _actor(tenant, ctx), entry_id, reversal_date=body.entry_date
    )
    return _entry_out(db, tenant.company_id, reversal.id)
