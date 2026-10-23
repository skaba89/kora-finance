"""API v1. `ROUTERS` est le registre de tous les routeurs exposés sous /api/v1 :
`main.py` l'inclut et les tests d'isolation le parcourent."""

from fastapi import APIRouter

from kora.api.v1 import accounting, auth, companies, firms, mfa

PREFIX = "/api/v1"

ROUTERS: tuple[APIRouter, ...] = (
    auth.router,
    mfa.router,
    companies.router,
    accounting.router,
    firms.router,
)
