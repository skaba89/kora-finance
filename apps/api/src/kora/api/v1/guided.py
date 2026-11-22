"""Saisie guidée : opérations courantes décrites simplement, traduites en écritures."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from kora.accounting import guided
from kora.accounting.entries import Actor
from kora.accounting.guided import GuidedData, Operation, Party, Sense
from kora.api.v1.common import TENANT_ERRORS, WRITE_ERRORS, Money, RequestBody
from kora.auth.deps import Ctx, DbSession
from kora.models.accounting import Account
from kora.models.common import utcnow
from kora.models.ledger import MAX_LINE_AMOUNT
from kora.tenancy.deps import EntriesWrite
from kora.tenancy.module_config import require_enabled_module
from kora.tenancy.modules import Module

router = APIRouter(prefix="/companies/{company_id}/guided-entries", tags=["saisie guidée"])


class AccountChoice(BaseModel):
    id: uuid.UUID
    number: str
    label: str

    @classmethod
    def of(cls, account: Account) -> "AccountChoice":
        return cls(id=account.id, number=account.number, label=account.label)


class NatureChoiceOut(BaseModel):
    code: str
    label: str
    label_en: str
    vat_possible: bool
    note: str
    account: AccountChoice


class OperationOut(BaseModel):
    code: Operation
    nature: Sense | None
    treasury: bool
    target_treasury: bool
    party: Party | None


class VatOut(BaseModel):
    rate_basis_points: int
    verified: bool


class GuidedOptions(BaseModel):
    reference: str
    operations: list[OperationOut]
    natures: dict[Sense, list[NatureChoiceOut]]
    treasury_accounts: list[AccountChoice]
    party_accounts: dict[Party, list[AccountChoice]]
    vat: VatOut | None = Field(description="Taux TVA_NORMAL en vigueur à la date demandée")


@router.get("/options", responses=TENANT_ERRORS)
def guided_options(tenant: EntriesWrite, db: DbSession, on: date | None = None) -> GuidedOptions:
    company_id = tenant.company_id
    vat = guided.vat_rate(db, company_id, on or utcnow().date())
    return GuidedOptions(
        reference=guided.REFERENCE,
        operations=[
            OperationOut(
                code=code,
                nature=spec.nature,
                treasury=spec.treasury,
                target_treasury=spec.target_treasury,
                party=spec.party,
            )
            for code, spec in guided.SPECS.items()
        ],
        natures={
            sense: [
                NatureChoiceOut(
                    code=c.nature.code,
                    label=c.nature.label,
                    label_en=c.nature.label_en,
                    vat_possible=c.nature.vat_possible,
                    note=c.nature.note,
                    account=AccountChoice.of(c.account),
                )
                for c in guided.nature_choices(db, company_id, sense)
            ]
            for sense in Sense
        },
        treasury_accounts=[AccountChoice.of(a) for a in guided.treasury_accounts(db, company_id)],
        party_accounts={
            party: [AccountChoice.of(a) for a in guided.party_accounts(db, company_id, party)]
            for party in Party
        },
        vat=VatOut(rate_basis_points=vat.rate_basis_points, verified=vat.verified) if vat else None,
    )


class GuidedIn(RequestBody):
    operation: Operation
    entry_date: date
    amount: Annotated[Money, Field(gt=0, le=MAX_LINE_AMOUNT, description="Montant total (TTC)")]
    label: Annotated[str | None, Field(max_length=200)] = None
    reference: Annotated[str | None, Field(max_length=60)] = None
    nature_account_id: uuid.UUID | None = None
    treasury_account_id: uuid.UUID | None = None
    target_treasury_account_id: uuid.UUID | None = None
    party_account_id: uuid.UUID | None = None
    vat_included: bool = False

    def data(self) -> GuidedData:
        # Pas de model_dump : le sérialiseur de Money produirait des chaînes.
        return GuidedData(
            operation=self.operation,
            entry_date=self.entry_date,
            amount=self.amount,
            label=self.label,
            reference=self.reference,
            nature_account_id=self.nature_account_id,
            treasury_account_id=self.treasury_account_id,
            target_treasury_account_id=self.target_treasury_account_id,
            party_account_id=self.party_account_id,
            vat_included=self.vat_included,
        )


class GuidedCreate(GuidedIn):
    id: uuid.UUID | None = Field(
        default=None,
        description="Identifiant choisi par le client : rend l'enregistrement idempotent.",
    )


class PreviewLine(BaseModel):
    account_id: uuid.UUID
    account_number: str
    account_label: str
    debit: Money
    credit: Money


class GuidedPreview(BaseModel):
    journal_code: str
    journal_label: str
    label: str
    reference: str | None
    lines: list[PreviewLine]
    vat_amount: Money
    warnings: list[str]


@router.post("/preview", responses=WRITE_ERRORS)
def preview_guided_entry(tenant: EntriesWrite, db: DbSession, body: GuidedIn) -> GuidedPreview:
    built = guided.build(db, tenant.company_id, body.data())
    return GuidedPreview(
        journal_code=built.journal.code,
        journal_label=built.journal.label,
        label=built.label,
        reference=built.reference,
        lines=[
            PreviewLine(
                account_id=line.account.id,
                account_number=line.account.number,
                account_label=line.account.label,
                debit=line.debit,
                credit=line.credit,
            )
            for line in built.lines
        ],
        vat_amount=built.vat_amount,
        warnings=built.warnings,
    )


class GuidedCreated(BaseModel):
    id: uuid.UUID


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**WRITE_ERRORS, 200: {"model": GuidedCreated, "description": "Déjà enregistrée"}},
)
def create_guided_entry(
    tenant: EntriesWrite,
    db: DbSession,
    ctx: Ctx,
    body: GuidedCreate,
    response: Response,
    request: Request,
) -> GuidedCreated:
    if "x-kora-offline-sync" in request.headers:
        require_enabled_module(db, tenant.company_id, Module.OFFLINE)
    entry, created = guided.create(
        db, Actor(tenant.company_id, tenant.user.id, ctx), body.data(), entry_id=body.id
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return GuidedCreated(id=entry.id)
