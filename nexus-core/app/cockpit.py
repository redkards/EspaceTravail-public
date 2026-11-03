"""Cockpit : page HTML autonome (aucune ressource externe) servie sur /cockpit.

Les appels de la page passent par /cockpit/api/* (voir main.py), qui réutilisent
les mêmes fonctions que /api/* mais sans clé : Caddy protège /cockpit par basic auth.
"""
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_PAGE = Path(__file__).resolve().parent / "templates" / "cockpit.html"


@lru_cache(maxsize=1)
def _html() -> str:
    return _PAGE.read_text(encoding="utf-8")


@router.get("/cockpit", response_class=HTMLResponse, include_in_schema=False)
@router.get("/cockpit/", response_class=HTMLResponse, include_in_schema=False)
def page() -> HTMLResponse:
    return HTMLResponse(_html(), headers={"Cache-Control": "no-store"})
