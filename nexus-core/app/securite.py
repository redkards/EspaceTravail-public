"""Protection des routes /cockpit/api/* (CSRF et contournement de la validation N3).

Le cockpit n'utilise pas la clé X-Nexus-Key : Caddy protège /cockpit* par basic auth et
injecte l'en-tête interne `X-Cockpit-Auth: <COCKPIT_INTERNAL>`. nexus-core exige :
- toujours : X-Cockpit-Auth égal à COCKPIT_INTERNAL (temps constant) — une requête qui ne
  passe pas par Caddy (autre conteneur, port exposé par erreur) est refusée ;
- en écriture (POST/PUT/PATCH/DELETE) : en-tête `X-Cockpit: 1` (posé par le JavaScript du
  cockpit, impossible depuis un simple formulaire HTML d'un site tiers), Origin éventuel égal
  à https://NEXUS_HOST, et un corps JSON (Content-Type application/json).
"""
import hmac
import json
import os

from fastapi import HTTPException, Request

from .config import cfg

ECRITURES = {"POST", "PUT", "PATCH", "DELETE"}


def cle_interne() -> str:
    return os.environ.get("COCKPIT_INTERNAL", "").strip()


def origines_autorisees() -> set[str]:
    hote = (cfg().nexus_host or "").strip().rstrip("/")
    return {f"https://{hote}", f"https://{hote}:443"} if hote else set()


def _refus(message: str) -> HTTPException:
    return HTTPException(status_code=403, detail=message)


async def garde_cockpit(request: Request) -> None:
    attendu = cle_interne()
    ecriture = request.method.upper() in ECRITURES
    if not attendu:
        raise _refus("Cockpit verrouillé : COCKPIT_INTERNAL n'est pas configuré sur nexus-core "
                     "(variable partagée avec Caddy). Aucune lecture ni écriture via /cockpit/api.")
    recu = request.headers.get("x-cockpit-auth", "")
    if not recu or not hmac.compare_digest(recu.encode(), attendu.encode()):
        raise _refus("Accès cockpit refusé : la requête doit passer par le proxy Caddy (X-Cockpit-Auth).")
    if not ecriture:
        return
    if request.headers.get("x-cockpit", "") != "1":
        raise _refus("Écriture cockpit refusée : en-tête X-Cockpit absent (requête hors cockpit).")
    origine = request.headers.get("origin")
    if origine is not None and origine.rstrip("/") not in origines_autorisees():
        raise _refus(f"Écriture cockpit refusée : origine « {origine} » non autorisée.")
    type_contenu = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if type_contenu != "application/json":
        raise _refus("Écriture cockpit refusée : corps JSON obligatoire (Content-Type: application/json).")
    try:
        json.loads(await request.body() or b"")
    except ValueError:
        raise _refus("Écriture cockpit refusée : corps JSON invalide ou absent.")
