"""nexus-bridge — passerelle MCP « Streamable HTTP » (spécification MCP 2025-06-18) entre
Claude, ChatGPT et Gemini, avec mémoire commune, tâches, messages et passations.

- POST /mcp            jeton dans l'en-tête « Authorization: Bearer <jeton> »
- POST /mcp/<jeton>    jeton dans le chemin (connecteurs sans en-tête personnalisé)
- GET/DELETE /mcp…     405 (pas de flux SSE : réponses JSON uniquement, serveur sans session)
- GET /bridge          page HTML lecture seule (protégée par le basic auth de Caddy)
- GET /sante           sonde de santé interne (non publiée par Caddy)

JSON-RPC 2.0 implémenté ici : initialize, notifications/initialized, ping, tools/list, tools/call.
Le jeton identifie l'auteur (claude | chatgpt | gemini | proprietaire) ; il n'est jamais journalisé.
"""
import hmac
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import db
from .config import IDENTITES, cfg
from .garde import limiteur

LOT_MAX = 10  # éléments maximum dans un lot JSON-RPC
from .outils import OutilErreur, outils, resultat_texte, trouver
from .page import page_bridge
from .schema import ErreurArguments, valider

VERSION = "1.0.0"
VERSIONS_PROTOCOLE = ["2025-06-18", "2025-03-26", "2024-11-05"]
VERSION_PAR_DEFAUT_SANS_ENTETE = "2025-03-26"  # règle de la spécification si l'en-tête manque

log = logging.getLogger("nexus-bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")


class MasqueJeton(logging.Filter):
    """Ceinture et bretelles : masque tout « /mcp/<jeton> » dans les journaux (uvicorn, httpx…)."""
    _motif = re.compile(r"/mcp/[^\s\"'/?]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        if "/mcp/" in message:
            record.msg, record.args = self._motif.sub("/mcp/***", message), None
        return True


for _nom in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx", "nexus-bridge"):
    logging.getLogger(_nom).addFilter(MasqueJeton())
logging.getLogger("httpx").setLevel(logging.WARNING)

INSTRUCTIONS = (
    "Passerelle NEXUS : mémoire et coordination communes entre Claude, ChatGPT et Gemini pour le même propriétaire. "
    "En début de session : messages_lire, puis passation_derniere {projet} et tache_lister. "
    "Avant de répondre sur un projet : memoire_chercher. Notez les faits/décisions durables avec memoire_ecrire "
    "(jamais de secret), et terminez une session par passation_ecrire. Les codes projets sont donnés par projets_lister. "
    "Les outils mothership_* lisent et créent des missions mais ne valident rien : la validation N3 est réservée "
    "au propriétaire, dans le cockpit."
)

# --- Codes d'erreur JSON-RPC ---------------------------------------------------------------
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
RATE_LIMITED = -32029


def _erreur(id_, code: int, message: str, data=None) -> dict:
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": e}


def _ok(id_, resultat: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": resultat}


# --- Authentification ------------------------------------------------------------------------
def identifier(jeton: str | None) -> str | None:
    """Renvoie l'identité associée au jeton. Compare TOUS les jetons (temps constant, sans court-circuit)."""
    if not jeton:
        return None
    trouve = None
    candidat = jeton.encode()
    for ident in IDENTITES:
        attendu = cfg().jetons.get(ident)
        # Valeur factice de même longueur si l'identité n'a pas de jeton : même coût de comparaison.
        reference = attendu.encode() if attendu else b"\x00" * len(candidat)
        if hmac.compare_digest(candidat, reference) and attendu:
            trouve = ident
    return trouve


def _jeton_requete(request: Request, jeton_chemin: str | None) -> str | None:
    if jeton_chemin:
        return jeton_chemin
    auth = request.headers.get("authorization", "")
    schema, _, valeur = auth.partition(" ")
    if schema.lower() == "bearer" and valeur.strip():
        return valeur.strip()
    return None


def _non_autorise() -> JSONResponse:
    return JSONResponse(
        _erreur(None, -32001, "Non autorisé : jeton absent ou invalide. Utilisez l'URL /mcp/<jeton> fournie par "
                              "bridge-connecteurs.sh, ou l'en-tête « Authorization: Bearer <jeton> »."),
        status_code=401, headers={"WWW-Authenticate": 'Bearer realm="nexus-bridge"'})


# --- Application ----------------------------------------------------------------------------
@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    db.initialiser()
    c = cfg()
    manquants = [i for i in IDENTITES if i not in c.jetons]
    log.info("nexus-bridge %s démarré ; %d jeton(s) configuré(s)%s", VERSION, len(c.jetons),
             f" ; sans jeton : {', '.join(manquants)}" if manquants else "")
    yield


app = FastAPI(title="nexus-bridge", version=VERSION, lifespan=cycle_de_vie,
              docs_url=None, redoc_url=None, openapi_url=None)


def _chemin_masque(chemin: str) -> str:
    """Jamais de jeton dans les journaux : /mcp/<jeton> devient /mcp/***."""
    return "/mcp/***" if chemin.startswith("/mcp/") else chemin


@app.middleware("http")
async def journal_acces(request: Request, call_next):
    t0 = time.monotonic()
    reponse = await call_next(request)
    if request.url.path != "/sante":
        log.info("%s %s -> %d (%d ms) %s", request.method, _chemin_masque(request.url.path), reponse.status_code,
                 int((time.monotonic() - t0) * 1000), getattr(request.state, "identite", "-"))
    return reponse


@app.get("/sante", include_in_schema=False)
def sante():
    with db.connexion() as con:
        con.execute("SELECT 1")
    return {"statut": "ok", "service": "nexus-bridge", "version": VERSION, "jetons": len(cfg().jetons)}


@app.get("/bridge", response_class=HTMLResponse, include_in_schema=False)
@app.get("/bridge/", response_class=HTMLResponse, include_in_schema=False)
def bridge():
    return HTMLResponse(page_bridge(), headers={"Cache-Control": "no-store",
                                                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


# --- Point d'entrée MCP -----------------------------------------------------------------------
async def _mcp(request: Request, jeton_chemin: str | None = None) -> Response:
    identite = identifier(_jeton_requete(request, jeton_chemin))
    if not identite:
        return _non_autorise()
    request.state.identite = identite

    if request.method != "POST":
        # Pas de flux SSE côté serveur ni de session à fermer : spécification « 405 Method Not Allowed ».
        return Response(status_code=405, headers={"Allow": "POST"})

    origines = [o.strip() for o in os.environ.get("BRIDGE_ORIGINES", "").split(",") if o.strip()]
    origine = request.headers.get("origin")
    if origine and origines and origine not in origines:
        return JSONResponse(_erreur(None, INVALID_REQUEST, "Origine refusée."), status_code=403)

    version_entete = request.headers.get("mcp-protocol-version")
    if version_entete and version_entete not in VERSIONS_PROTOCOLE:
        return JSONResponse(_erreur(None, INVALID_REQUEST, f"Version de protocole MCP non prise en charge : {version_entete[:20]}. "
                                                           f"Versions acceptées : {', '.join(VERSIONS_PROTOCOLE)}."),
                            status_code=400)

    corps = await request.body()
    if len(corps) > cfg().corps_max_octets:
        return JSONResponse(_erreur(None, INVALID_REQUEST, "Requête trop volumineuse (64 Ko maximum)."), status_code=413)
    try:
        message = json.loads(corps)
    except (ValueError, UnicodeDecodeError):
        message = None
    if isinstance(message, list) and len(message) > LOT_MAX:
        return JSONResponse(_erreur(None, INVALID_REQUEST, f"Lot JSON-RPC trop grand : {LOT_MAX} éléments maximum."),
                            status_code=400)

    # Limite de débit : chaque élément d'un lot compte comme un appel (un lot ne contourne pas la limite).
    cout = len(message) if isinstance(message, list) and message else 1
    autorise, attente = limiteur.autoriser(identite, cfg().limite_par_minute, cout=cout)
    if not autorise:
        return JSONResponse(_erreur(None, RATE_LIMITED, f"Trop d'appels : limite de {cfg().limite_par_minute} par minute "
                                                         f"atteinte. Réessayez dans {attente} s."),
                            status_code=429, headers={"Retry-After": str(attente)})
    if message is None and corps.strip() != b"null":
        return JSONResponse(_erreur(None, PARSE_ERROR, "JSON invalide."), status_code=400)

    if isinstance(message, list):  # lots JSON-RPC (protocole 2025-03-26) : pris en charge par compatibilité
        if not message:
            return JSONResponse(_erreur(None, INVALID_REQUEST, "Lot JSON-RPC vide."), status_code=400)
        reponses = [r for r in [await _traiter(m, identite) for m in message] if r is not None]
        return JSONResponse(reponses) if reponses else Response(status_code=202)

    reponse = await _traiter(message, identite)
    if reponse is None:  # notification ou réponse du client : 202 sans corps
        return Response(status_code=202)
    statut = 400 if "error" in reponse and reponse["error"]["code"] in (PARSE_ERROR, INVALID_REQUEST) else 200
    return JSONResponse(reponse, status_code=statut)


async def _traiter(msg, identite: str) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _erreur(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST,
                       "Requête JSON-RPC 2.0 invalide (champ « jsonrpc »: « 2.0 » attendu).")
    methode = msg.get("method")
    if methode is None:
        # Réponse ou erreur envoyée par le client (on ne lui fait jamais de requête) : on l'accepte.
        return None if ("result" in msg or "error" in msg) else _erreur(msg.get("id"), INVALID_REQUEST, "Champ « method » manquant.")
    if not isinstance(methode, str):
        return _erreur(msg.get("id"), INVALID_REQUEST, "« method » doit être un texte.")
    est_notification = "id" not in msg
    id_ = msg.get("id")
    if not est_notification and (id_ is None or isinstance(id_, bool) or not isinstance(id_, (str, int))):
        return _erreur(None, INVALID_REQUEST, "« id » doit être un texte ou un entier (non nul).")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return None if est_notification else _erreur(id_, INVALID_PARAMS, "« params » doit être un objet.")

    if est_notification:
        # notifications/initialized, notifications/cancelled… : rien à faire (serveur sans état).
        return None

    try:
        if methode == "initialize":
            return _ok(id_, _initialiser(params))
        if methode == "ping":
            return _ok(id_, {})
        if methode == "tools/list":
            return _ok(id_, {"tools": [_decrire(o) for o in outils()]})
        if methode == "tools/call":
            return await _appeler(id_, params, identite)
        if methode in ("resources/list", "prompts/list"):
            return _erreur(id_, METHOD_NOT_FOUND, f"Méthode non prise en charge : {methode}")
        return _erreur(id_, METHOD_NOT_FOUND, f"Méthode inconnue : {methode[:80]}")
    except Exception:  # noqa: BLE001 — jamais de trace (ni de donnée) renvoyée au client
        log.exception("Erreur interne pendant %s", methode)
        return _erreur(id_, INTERNAL_ERROR, "Erreur interne de nexus-bridge.")


def _initialiser(params: dict) -> dict:
    demandee = params.get("protocolVersion")
    version = demandee if demandee in VERSIONS_PROTOCOLE else VERSIONS_PROTOCOLE[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "nexus-bridge", "title": "Passerelle NEXUS (Claude · ChatGPT · Gemini)", "version": VERSION},
        "instructions": INSTRUCTIONS,
    }


def _decrire(o) -> dict:
    return {
        "name": o.nom,
        "title": o.titre,
        "description": o.description,
        "inputSchema": o.schema,
        "annotations": {
            "title": o.titre,
            "readOnlyHint": not o.ecriture,
            "destructiveHint": False,       # rien n'est jamais supprimé (versions, archivage)
            "idempotentHint": o.nom in ("tache_prendre", "memoire_oublier") or not o.ecriture,
            "openWorldHint": o.nom.startswith("mothership_") or o.nom == "projets_lister",
        },
    }


async def _appeler(id_, params: dict, identite: str) -> dict:
    nom = params.get("name")
    o = trouver(nom) if isinstance(nom, str) else None
    if not o:
        return _erreur(id_, INVALID_PARAMS, f"Outil inconnu : {str(nom)[:80]}")
    try:
        args = valider(params.get("arguments"), o.schema)
        resultat = await run_in_threadpool(o.fonction, identite, args)
    except (ErreurArguments, OutilErreur) as e:
        if o.ecriture and isinstance(e, OutilErreur):
            await run_in_threadpool(db.journaliser_seul, identite, o.nom, "", "refuse")
        return _ok(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
    return _ok(id_, {"content": [{"type": "text", "text": resultat_texte(resultat)}],
                     "structuredContent": resultat, "isError": False})


@app.post("/mcp", include_in_schema=False)
@app.post("/mcp/", include_in_schema=False)
@app.get("/mcp", include_in_schema=False)
@app.delete("/mcp", include_in_schema=False)
async def mcp_entete(request: Request):
    return await _mcp(request)


@app.post("/mcp/{jeton}", include_in_schema=False)
@app.post("/mcp/{jeton}/", include_in_schema=False)
@app.get("/mcp/{jeton}", include_in_schema=False)
@app.delete("/mcp/{jeton}", include_in_schema=False)
async def mcp_chemin(request: Request, jeton: str):
    return await _mcp(request, jeton)
