"""API v1. `ROUTERS` est le registre de tous les routeurs exposés sous /api/v1 :
`main.py` l'inclut et les tests d'isolation le parcourent."""

from fastapi import APIRouter

from kora.api.v1 import (
    accounting,
    attachments,
    auth,
    closing,
    companies,
    dashboard,
    exports,
    firms,
    guided,
    invitations,
    ledger,
    lettering,
    mfa,
    reports,
    statements,
    treasury,
)

PREFIX = "/api/v1"

ROUTERS: tuple[APIRouter, ...] = (
    auth.router,
    mfa.router,
    companies.router,
    accounting.router,
    ledger.router,
    guided.router,
    attachments.router,
    reports.router,
    dashboard.router,
    lettering.router,
    closing.router,
    statements.router,
    exports.router,
    firms.router,
    invitations.router,
    treasury.router,
)
