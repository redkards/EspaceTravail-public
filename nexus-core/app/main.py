"""Point d'entrée FastAPI de nexus-core.

- /api/*         : API protégée par l'en-tête X-Nexus-Key (NEXUS_API_KEY).
- /cockpit       : page HTML ; /cockpit/api/* : mêmes routes sans clé X-Nexus-Key, protégées par
                   basic auth Caddy + en-tête interne X-Cockpit-Auth et contrôles anti-CSRF (securite.py).
- /              : redirige vers /cockpit.
"""
import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import agents as reg
from . import ledger, pipeline
from . import projets as registre
from .cockpit import router as cockpit_router
from .config import cfg
from .db import init_db
from .routes import creer_routeur
from .routes_decideur import api as decideur_api
from .routes_decideur import page as decideur_page
from .securite import garde_cockpit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
log = logging.getLogger("nexus")

PERIODE_FOND_S = 600  # tâche de fond toutes les 10 minutes


def maintenance() -> None:
    """Expiration des décisions N3 et reprise de la file N3 (plafond journalier)."""
    try:
        n = pipeline.expirer_decisions()
        f = pipeline.traiter_file_n3()
        if n or f:
            log.info("Maintenance : %s décision(s) expirée(s), %s fiche(s) N3 créée(s).", n, f)
    except Exception:
        log.exception("Erreur pendant la maintenance")


async def _boucle_fond() -> None:
    while True:
        await asyncio.sleep(PERIODE_FOND_S)
        await asyncio.to_thread(maintenance)


def tick_decideur() -> None:
    from . import decideur
    try:
        decideur.tick()
    except Exception:
        log.exception("Erreur pendant la tâche des sessions de décision")


async def _boucle_minute() -> None:
    """Sessions de décision N3 et rappels avant expiration (chaque minute)."""
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(tick_decideur)


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    # Dossier des livrables (NEXUS_DATA_DIR/livrables), monté depuis l'hôte.
    dossier = cfg().data_dir / "livrables"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("Impossible de créer %s (%s) : vérifier les droits du montage (UID 10001).", dossier, e)
    init_db()
    reg.charger()
    registre.charger()  # échec explicite au démarrage si projets.yaml est invalide
    from . import fonctionnement
    fonctionnement.charger()  # idem pour fonctionnement.yaml
    log.info("Fonctionnement par défaut : %s", fonctionnement.defaut())
    ledger.journaliser("NEXUS-PRIME", "demarrage", None, agents=len(reg.charger()))
    # Garde-fou « tout gratuit » : refus d'Anthropic sans budget, message clair au démarrage.
    from .llm import info, refus_anthropic
    if cfg().llm_provider == "anthropic" and refus_anthropic():
        log.error(refus_anthropic())
        ledger.journaliser("NEXUS-BUDGET", "fournisseur_refuse", None, demande="anthropic",
                           actif=info()["fournisseur"], motif=refus_anthropic())
    log.info("LLM actif : %s", info())
    if not cfg().api_key:
        log.warning("NEXUS_API_KEY vide : l'API /api refusera toutes les requêtes (sauf /api/sante).")
    reprise = pipeline.reprendre_au_demarrage()
    if reprise["interrompues"] or reprise["relancees"]:
        log.info("Reprise au démarrage : %s", reprise)
    taches = [asyncio.create_task(_boucle_fond()), asyncio.create_task(_boucle_minute())] \
        if cfg().taches_fond else []
    yield
    for t in taches:
        t.cancel()


def verifier_cle(x_nexus_key: str | None = Header(default=None)) -> None:
    """Exige X-Nexus-Key égale à NEXUS_API_KEY (comparaison à temps constant)."""
    attendu = cfg().api_key
    if not attendu or not x_nexus_key or not hmac.compare_digest(x_nexus_key, attendu):
        raise HTTPException(status_code=401, detail="Clé API absente ou invalide (en-tête X-Nexus-Key).")


app = FastAPI(title="NEXUS Mothership — nexus-core", version="1.0.0", lifespan=cycle_de_vie,
              docs_url=None, redoc_url=None, openapi_url=None)


# /api/sante reste accessible sans clé pour les sondes (Docker, Uptime Kuma).
@app.get("/api/sante", include_in_schema=False)
def sante_publique():
    from .fonctionnement import defaut
    from .llm import info
    from .ledger import avertissement
    avert = [a for a in (avertissement(),) if a]
    return {"statut": "ok", "service": "nexus-core", "llm": info(), "fonctionnement_defaut": defaut(),
            "ledger_hmac": not avert, "avertissements": avert}


app.include_router(creer_routeur(), prefix="/api", dependencies=[Depends(verifier_cle)])
app.include_router(creer_routeur(cockpit=True), prefix="/cockpit/api")
app.include_router(decideur_api)  # /cockpit/api/decideur/* : même garde que tout /cockpit/api
app.include_router(decideur_page)


@app.middleware("http")
async def proteger_cockpit_api(request: Request, call_next):
    """Garde anti-CSRF appliquée AVANT routage et validation sur tout /cockpit/api/*."""
    if request.url.path == "/cockpit/api" or request.url.path.startswith("/cockpit/api/"):
        try:
            await garde_cockpit(request)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(request)
app.include_router(cockpit_router)


@app.get("/", include_in_schema=False)
def racine():
    return RedirectResponse("/cockpit")
