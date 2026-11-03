"""Routes métier, montées deux fois : /api (clé X-Nexus-Key) et /cockpit/api (basic auth Caddy)."""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import agents as reg
from . import budget, ledger, pipeline, sentinel
from .db import session_scope
from .models import Decision, Etape, Mission


class NouvelleMission(BaseModel):
    titre: str = Field(min_length=1, max_length=200)
    consigne: str = Field(min_length=1, max_length=20000)
    service: str | None = None
    montant_eur: float | None = Field(default=None, ge=0)
    action: str | None = Field(default=None, max_length=40, pattern=r"^[a-z_]+$")


class Commentaire(BaseModel):
    commentaire: str | None = Field(default=None, max_length=4000)


class KillSwitch(BaseModel):
    portee: Literal["grille", "direction", "agent"]
    cible: str | None = None
    actif: bool


def _mission(m: Mission, etapes: list[Etape] | None = None) -> dict:
    d = {"id": m.id, "titre": m.titre, "consigne": m.consigne, "service": m.service,
         "directeur": m.directeur, "statut": m.statut, "niveau": m.niveau,
         "montant_eur": m.montant_eur, "action": m.action, "message": m.message,
         "cree_le": m.cree_le.isoformat(), "maj_le": m.maj_le.isoformat(),
         "livrable_texte": m.livrable_texte, "tokens": m.tokens, "cout_eur": m.cout_eur}
    if etapes is not None:
        d["etapes"] = [{"id": e.id, "agent_id": e.agent_id, "role": e.role, "entree": e.entree,
                        "sortie": e.sortie, "verdict": e.verdict, "tokens": e.tokens,
                        "cree_le": e.cree_le.isoformat()} for e in etapes]
    return d


def _decision(d: Decision, titre: str | None = None) -> dict:
    return {"id": d.id, "mission_id": d.mission_id, "mission_titre": titre, "niveau": d.niveau,
            "resume": d.resume, "recommandation": d.recommandation,
            "cout_estime_eur": d.cout_estime_eur, "risque": d.risque, "sources": d.sources,
            "avis_checker": d.avis_checker, "statut": d.statut, "cree_le": d.cree_le.isoformat(),
            "decide_le": d.decide_le.isoformat() if d.decide_le else None,
            "commentaire": d.commentaire}


def creer_routeur() -> APIRouter:
    r = APIRouter()

    @r.get("/sante")
    def sante():
        """État du service (sans dépendance au LLM)."""
        with session_scope() as s:
            s.execute(select(1))
        from .llm import info
        return {"statut": "ok", "service": "nexus-core", "llm": info(), "agents": len(reg.charger()),
                "arret_urgence": bool(sentinel.actifs().get("kill:grille"))}

    @r.post("/missions", status_code=202)
    def creer_mission(corps: NouvelleMission, taches: BackgroundTasks):
        if corps.service and corps.service not in reg.services():
            raise HTTPException(422, f"Service inconnu : {corps.service}")
        with session_scope() as s:
            m = Mission(titre=corps.titre.strip(), consigne=corps.consigne.strip(), service=corps.service,
                        montant_eur=corps.montant_eur or 0.0, action=corps.action, statut="recue")
            s.add(m)
            s.flush()
            mid = m.id
        ledger.journaliser("API", "mission_recue", mid, titre=corps.titre, service=corps.service)
        taches.add_task(pipeline.traiter, mid)
        return {"id": mid, "statut": "recue"}

    @r.get("/missions")
    def lister_missions(statut: str | None = None, limit: int = Query(50, ge=1, le=500)):
        with session_scope() as s:
            q = select(Mission).order_by(Mission.id.desc()).limit(limit)
            if statut:
                q = q.where(Mission.statut == statut)
            return [_mission(m) for m in s.execute(q).scalars()]

    @r.get("/missions/{mid}")
    def detail_mission(mid: int):
        with session_scope() as s:
            m = s.get(Mission, mid)
            if m is None:
                raise HTTPException(404, "Mission introuvable")
            etapes = s.execute(select(Etape).where(Etape.mission_id == mid).order_by(Etape.id)).scalars().all()
            return _mission(m, list(etapes))

    @r.get("/decisions")
    def lister_decisions(statut: str | None = None, limit: int = Query(100, ge=1, le=500)):
        with session_scope() as s:
            q = (select(Decision, Mission.titre).join(Mission, Mission.id == Decision.mission_id)
                 .order_by(Decision.id.desc()).limit(limit))
            if statut:
                q = q.where(Decision.statut == statut)
            return [_decision(d, t) for d, t in s.execute(q).all()]

    def _decider(did: int, choix: str, corps: Commentaire | None):
        try:
            return pipeline.decider(did, choix, corps.commentaire if corps else None)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except PermissionError as e:
            raise HTTPException(409, str(e))

    @r.post("/decisions/{did}/valider")
    def valider(did: int, corps: Commentaire | None = None):
        return _decider(did, "valider", corps)

    @r.post("/decisions/{did}/refuser")
    def refuser(did: int, corps: Commentaire | None = None):
        return _decider(did, "refuser", corps)

    @r.post("/decisions/{did}/reviser")
    def reviser(did: int, corps: Commentaire | None = None):
        return _decider(did, "reviser", corps)

    @r.post("/killswitch")
    def killswitch(corps: KillSwitch):
        if corps.portee != "grille" and not (corps.cible or "").strip():
            raise HTTPException(422, "cible obligatoire pour une direction ou un agent")
        if corps.portee == "agent" and corps.cible not in reg.charger():
            raise HTTPException(422, f"Agent inconnu : {corps.cible}")
        cle = sentinel.basculer(corps.portee, corps.cible, corps.actif)
        ledger.journaliser("DECIDEUR", "killswitch_on" if corps.actif else "killswitch_off", None, cle=cle)
        return {"cle": cle, "actif": corps.actif, "interrupteurs": sentinel.actifs()}

    @r.get("/ledger")
    def lire_ledger(limit: int = Query(50, ge=1, le=500)):
        return ledger.lister(limit)

    @r.get("/ledger/verifier")
    def verifier_ledger():
        return ledger.verifier()

    @r.get("/agents")
    def lister_agents():
        k = sentinel.actifs()
        res = []
        for a in reg.charger().values():
            suspendu = bool(k.get("kill:grille") or k.get(f"kill:agent:{a['id']}")
                            or k.get(f"kill:dir:{sentinel.normaliser_direction(a['direction'])}"))
            res.append({"id": a["id"], "nom": a["nom"], "role": a["role"], "direction": a["direction"],
                        "departement": a["departement"], "service": a["service"], "mission": a["mission"],
                        "outils_autorises": a["outils_autorises"],
                        "statut": "suspendu" if suspendu else "actif"})
        return res

    @r.get("/budget")
    def lire_budget():
        return budget.resume()

    return r
