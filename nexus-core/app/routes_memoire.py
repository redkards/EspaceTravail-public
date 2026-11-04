"""Mémoire collective : recherche, leçons, rapport, archive.

Lecture : /api/memoire/* (clé) et /cockpit/api/memoire/* (cockpit).
Décisions (accepter / rejeter une leçon) et effacement d'archive : COCKPIT UNIQUEMENT (humain,
anti-CSRF) — ni la clé API, ni la passerelle ne peuvent changer le comportement des agents.
"""
import os
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import archive, exemples, lecons, memoire
from . import projets as registre
from .routes_decideur import utilisateur


def recherche_commune(q: str, projet: str | None, service: str | None, limite: int = 5) -> dict:
    if projet:
        try:
            projet = registre.resoudre(projet)
        except ValueError as e:
            raise HTTPException(404, str(e))
    codes = [projet] if projet else list(registre.charger())
    connaissances = []
    for code in codes:
        connaissances += memoire.rechercher(code, q, limite)
    connaissances.sort(key=lambda k: -(k.get("score") or 0))
    mots = [m for m in memoire._requete_fts(q or "").replace('"', "").replace("*", "").split(" OR ") if m]
    ex = [e for e in exemples.lister(service) if (not projet or e["projet"] == projet)
          and any(m in memoire.gate.normaliser(e["titre"] + " " + e["extrait"]) for m in mots)]
    return {
        "q": q, "projet": projet, "service": service,
        "connaissances": [{k: c[k] for k in ("projet", "titre", "source", "date", "contenu")} | {"contenu": c["contenu"][:600]}
                          for c in connaissances[:limite]],
        "lecons": [l for l in lecons.lister("acceptee", service, projet, q)][:limite],
        "exemples": [{k: e[k] for k in ("id", "service", "projet", "titre")} | {"extrait": e["extrait"][:400]}
                     for e in ex[:limite]],
        "archive": archive.rechercher(q, projet, service, limite),
    }


def lecture() -> APIRouter:
    r = APIRouter()

    @r.get("/memoire/recherche")
    def rechercher(q: str = Query(min_length=2, max_length=300), projet: str | None = None,
                   service: str | None = None, limite: int = Query(5, ge=1, le=20)):
        return recherche_commune(q, projet, service, limite)

    @r.get("/memoire/lecons")
    def lister_lecons(statut: str | None = "acceptee", service: str | None = None, projet: str | None = None,
                      q: str | None = None):
        return lecons.lister(statut or None, service, projet, q)

    @r.get("/memoire/rapport")
    def rapport(jours: int = Query(7, ge=1, le=90)):
        from . import avis
        return {**lecons.rapport(jours), "satisfaction": avis.statistiques(jours)}

    @r.get("/memoire/fantome")
    def etat_fantome():
        from . import fantome
        return fantome.etat()

    @r.get("/archive/verifier")
    def verifier_archive():
        return archive.verifier()

    @r.get("/archive/compaction")
    def statistiques_compaction():
        """Taille et ratio de la compaction (paliers tiède / froid) + archive « chaude » actuelle."""
        from . import compaction
        chaud = sum(f.stat().st_size for f in archive.dossier().glob("*.jsonl.gz")) if archive.dossier().is_dir() else 0
        stats = compaction.defaut().statistiques() if archive._compaction_active() else None
        derniere = compaction.defaut()._meta("derniere_nuit") if stats is not None else None
        return {"archive_chaude_octets": chaud, "compaction": stats, "derniere_nuit": derniere,
                "fenetre_nuit": os.environ.get("NEXUS_FENETRE_NUIT", "01:00-06:00")}

    return r


class Acceptation(BaseModel):
    texte: str | None = Field(default=None, max_length=300)  # reformulation par le propriétaire
    terme_charte: str | None = Field(default=None, max_length=80)
    confirmation_fantome: bool = False


class Motif(BaseModel):
    motif: str | None = Field(default=None, max_length=300)


cockpit = APIRouter(prefix="/cockpit/api/memoire")


@cockpit.post("/lecons/{lid}/accepter")
def accepter(lid: int, corps: Acceptation, request: Request):
    try:
        return lecons.accepter(lid, utilisateur(request), corps.texte, corps.terme_charte, corps.confirmation_fantome)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@cockpit.post("/lecons/{lid}/rejeter")
def rejeter(lid: int, corps: Motif, request: Request):
    try:
        return lecons.rejeter(lid, utilisateur(request), corps.motif)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))


class Fantome(BaseModel):
    type: str = Field(pattern="^(charte|modeles)$")
    valeur: str = Field(min_length=1, max_length=500)  # dossier de chartes candidat ou NEXUS_MODELES_ROLES
    service: str | None = Field(default=None, max_length=80)
    projet: str | None = Field(default=None, max_length=40)


@cockpit.post("/fantome")
def planifier_fantome(corps: Fantome):
    """Évaluer une charte modifiée ou un changement de modèles AVANT de l'appliquer (test de nuit)."""
    from . import fantome
    variante = {"charte_dir": corps.valeur} if corps.type == "charte" else {"modeles_roles": corps.valeur}
    return fantome.planifier(corps.type, corps.valeur[:60], variante, corps.service, corps.projet)


@cockpit.post("/archive/effacer/{mid}")
def effacer(mid: int, corps: Motif, request: Request):
    from .db import session_scope
    from .models import Mission
    with session_scope() as s:
        existe = s.get(Mission, mid) is not None
    n = archive.effacer(mid, utilisateur(request), corps.motif or "droit à l'effacement")
    if not n and not existe:
        raise HTTPException(404, "Mission inconnue : rien à effacer.")
    return {"mission_id": mid, "lignes_effacees": n}
