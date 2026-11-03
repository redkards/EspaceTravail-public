"""Routes du Décideur mobile : /cockpit/decideur (page) et /cockpit/api/decideur/* (données, actions).

Protégées comme le reste du cockpit (basic auth Caddy + X-Cockpit-Auth + anti-CSRF, voir
securite.py). Toute action se fait en deux temps : `preparer` renvoie un jeton à usage unique,
`confirmer` l'exécute (et exige le code Décideur pour valider une décision à risque élevé).
"""
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import decideur, ledger, pipeline
from .db import session_scope
from .file_missions import FILE
from .models import Decision

page = APIRouter()
api = APIRouter(prefix="/cockpit/api/decideur")
_PAGE = Path(__file__).resolve().parent / "templates" / "decideur.html"
LIBELLES = {"valider": "valider", "refuser": "refuser", "reviser": "demander une révision de"}


@lru_cache(maxsize=1)
def _html() -> str:
    return _PAGE.read_text(encoding="utf-8")


@page.get("/cockpit/decideur", response_class=HTMLResponse, include_in_schema=False)
@page.get("/cockpit/decideur/", response_class=HTMLResponse, include_in_schema=False)
def page_decideur() -> HTMLResponse:
    return HTMLResponse(_html(), headers={"Cache-Control": "no-store"})


class Preparation(BaseModel):
    choix: Literal["valider", "refuser", "reviser"]
    commentaire: str | None = Field(default=None, max_length=200)


class Confirmation(Preparation):
    jeton: str = Field(min_length=10, max_length=64)
    code: str | None = Field(default=None, max_length=12)
    missions: list[int] = Field(default_factory=list, max_length=50)  # plan de la semaine : cases cochées


def utilisateur(request: Request) -> str:
    """Identité transmise par Caddy (X-Cockpit-Utilisateur, utilisateur basic auth), sinon « decideur »."""
    u = request.headers.get("x-cockpit-utilisateur", "").strip()
    return u if re.fullmatch(r"[\w.@-]{1,40}", u) else "decideur"


def _decision(did: int) -> Decision:
    with session_scope() as s:
        d = s.get(Decision, did)
        if d is None:
            raise HTTPException(404, "Décision introuvable.")
        return d


def _controles(d: Decision, corps: Preparation) -> None:
    if d.statut != "en_attente":
        raise HTTPException(409, f"Décision déjà traitée ({d.statut}).")
    if corps.choix == "reviser":
        if d.objet in ("lancement_f4", "plan_semaine"):
            raise HTTPException(409, "Révision impossible pour ce type de décision : valider ou refuser.")
        if len((corps.commentaire or "").strip()) < 3:
            raise HTTPException(422, "Indiquez un motif court pour la révision (3 à 200 caractères).")


@api.get("/etat")
def etat():
    from . import avis, lecons
    return {**decideur.etat_decideur(), "a_noter": avis.a_noter(), "lecons_proposees": lecons.lister("proposee"),
            "motifs_avis": avis.MOTIFS}


class NouvelAvis(BaseModel):
    valeur: Literal["positif", "negatif"]
    motif: str | None = Field(default=None, max_length=20)
    texte: str | None = Field(default=None, max_length=120)


@api.post("/avis/{mid}")
def noter(mid: int, corps: NouvelAvis, request: Request):
    """Note en un geste (cockpit uniquement, anti-CSRF)."""
    from . import avis
    try:
        return avis.enregistrer(mid, corps.valeur, corps.motif, corps.texte, utilisateur(request))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@api.post("/decisions/{did}/preparer")
def preparer(did: int, corps: Preparation):
    d = _decision(did)
    _controles(d, corps)
    code_requis = corps.choix == "valider" and decideur.code_exige_pour(did)
    return {"jeton": decideur.preparer(did, corps.choix), "expire_s": decideur.JETON_TTL_S,
            "libelle": f"Confirmer : {LIBELLES[corps.choix]} #{did}", "code_requis": code_requis,
            "code_configure": decideur.code_configure(), "verrou_restant_s": decideur.verrou_restant_s()}


@api.post("/decisions/{did}/confirmer")
def confirmer(did: int, corps: Confirmation, request: Request, taches: BackgroundTasks):
    qui = utilisateur(request)
    d = _decision(did)
    _controles(d, corps)
    if not decideur.jeton_valide(corps.jeton, did, corps.choix):
        raise HTTPException(409, "Confirmation requise ou expirée : appuyez de nouveau sur l'action.")
    code_requis = corps.choix == "valider" and decideur.code_exige_pour(did)
    if code_requis:
        try:
            decideur.verifier_code(corps.code, qui)
        except decideur.CodeRefuse as e:
            raise HTTPException(e.statut, str(e))
    if not decideur.consommer(corps.jeton, did, corps.choix):
        raise HTTPException(409, "Confirmation déjà utilisée ou expirée.")
    try:
        res = pipeline.decider(did, corps.choix, (corps.commentaire or "").strip() or None, corps.missions)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    ledger.journaliser("DECIDEUR", "decideur_action", res["mission_id"], decision_id=did, choix=corps.choix,
                       utilisateur=qui, source="decideur_mobile", risque=d.risque,
                       code_saisi=code_requis)
    if res.get("relance"):
        taches.add_task(FILE.executer, res["mission_id"], pipeline.relancer_revision, corps.commentaire)
    if res.get("lancer"):
        taches.add_task(FILE.executer, res["mission_id"], pipeline.traiter)
    for mid in res.get("missions_creees") or []:  # missions cochées du plan de la semaine
        taches.add_task(FILE.executer, mid, pipeline.traiter)
    return res
