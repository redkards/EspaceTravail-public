"""Routes métier, montées deux fois : /api (clé X-Nexus-Key) et /cockpit/api (basic auth Caddy)."""
import json
import os
from typing import Literal

import threading
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import agents as reg
from . import budget, ledger, pipeline, sentinel
from . import fonctionnement as fct
from . import exemples, memoire
from .file_missions import FILE
from . import projets as registre
from .db import session_scope
from .models import Decision, Etape, Mission, maintenant


_VERROU_CREATION = threading.Lock()
DOUBLON_S = 30  # même titre + consigne + projet en moins de 30 s : doublon (double clic)


class NouvelleMission(BaseModel):
    titre: str = Field(min_length=1, max_length=200)
    consigne: str = Field(min_length=1, max_length=20000)
    service: str | None = None
    montant_eur: float | None = Field(default=None, ge=0)
    action: str | None = Field(default=None, max_length=40, pattern=r"^[a-z_]+$")
    projet: str | None = Field(default=None, max_length=60)
    # Niveau de fonctionnement F1..F4 (défaut : NEXUS_FONCTIONNEMENT_DEFAUT).
    fonctionnement: Literal["F1", "F2", "F3", "F4"] | None = None
    # F4 indisponible (budget, clé) : lancer en F3 plutôt que refuser.
    repli_f3: bool = True


class Commentaire(BaseModel):
    commentaire: str | None = Field(default=None, max_length=4000)
    code: str | None = Field(default=None, max_length=12)  # code Décideur (cockpit, risque élevé)


class NouvelleConnaissance(BaseModel):
    titre: str = Field(min_length=1, max_length=200)
    contenu: str = Field(min_length=1, max_length=20000)
    source: str | None = Field(default=None, max_length=300)


class Note(BaseModel):
    note: int = Field(ge=1, le=5)


class KillSwitch(BaseModel):
    portee: Literal["grille", "direction", "agent"]
    cible: str | None = None
    actif: bool


def _mission(m: Mission, etapes: list[Etape] | None = None) -> dict:
    d = {"id": m.id, "projet": m.projet, "titre": m.titre, "consigne": m.consigne, "service": m.service,
         "directeur": m.directeur, "statut": m.statut, "niveau": m.niveau,
         "montant_eur": m.montant_eur, "action": m.action, "message": m.message,
         "cree_le": m.cree_le.isoformat(), "maj_le": m.maj_le.isoformat(),
         "livrable_texte": m.livrable_texte, "tokens": m.tokens, "cout_eur": m.cout_eur,
         "fonctionnement_demande": m.fonctionnement_demande, "fonctionnement": m.fonctionnement,
         "fonctionnement_raison": m.fonctionnement_raison, "repli_f3": m.repli_f3,
         "tokens_entree": m.tokens_entree, "tokens_sortie": m.tokens_sortie,
         "duree_s": m.duree_s, "revisions": m.revisions, "attente": m.attente,
         "modeles": json.loads(m.modeles_json) if m.modeles_json else {},
         "charte_avertissements": json.loads(m.charte_avertissements) if m.charte_avertissements else [],
         "alertes_bouclier": json.loads(m.alertes_bouclier) if m.alertes_bouclier else [],
         "note": m.note}
    if etapes is not None:
        d["etapes"] = [{"id": e.id, "agent_id": e.agent_id, "role": e.role, "entree": e.entree,
                        "sortie": e.sortie, "verdict": e.verdict, "tokens": e.tokens,
                        "cree_le": e.cree_le.isoformat()} for e in etapes]
    return d


def _decision(d: Decision, titre: str | None = None, projet: str | None = None) -> dict:
    return {"id": d.id, "mission_id": d.mission_id, "mission_titre": titre, "projet": projet,
            "niveau": d.niveau, "objet": d.objet,
            "resume": d.resume, "recommandation": d.recommandation,
            "cout_estime_eur": d.cout_estime_eur, "risque": d.risque, "sources": d.sources,
            "avis_checker": d.avis_checker, "statut": d.statut, "cree_le": d.cree_le.isoformat(),
            "decide_le": d.decide_le.isoformat() if d.decide_le else None,
            "commentaire": d.commentaire}


def _filtre_projet(projet: str | None) -> str | None:
    """Filtre ?projet= : vide → aucun filtre ; inconnu → 422."""
    if not projet:
        return None
    try:
        return registre.resoudre(projet)
    except ValueError as e:
        raise HTTPException(422, str(e))


def creer_routeur(cockpit: bool = False) -> APIRouter:
    """Routes métier ; `cockpit=True` : valider une décision à risque élevé exige le code Décideur."""
    r = APIRouter()

    @r.get("/sante")
    def sante():
        """État du service (sans dépendance au LLM)."""
        with session_scope() as s:
            s.execute(select(1))
        from .llm import info
        return {"statut": "ok", "service": "nexus-core", "llm": info(), "agents": len(reg.charger()),
                "fonctionnement_defaut": fct.defaut(),
                "ledger_hmac": ledger.avertissement() is None,
                "avertissements": [a for a in (ledger.avertissement(),) if a],
                "arret_urgence": bool(sentinel.actifs().get("kill:grille"))}

    @r.post("/missions", status_code=202)
    def creer_mission(corps: NouvelleMission, taches: BackgroundTasks,
                      cle_idempotence: str | None = Header(None, alias="Idempotency-Key")):
        with _VERROU_CREATION:  # contrôle de doublon + insertion atomiques (double clic, double envoi)
            return _creer_mission(corps, taches, cle_idempotence)

    def _doublon(cle: str | None, titre: str, consigne: str, projet: str, corps: NouvelleMission) -> int | None:
        """Même demande (titre, consigne, projet, service, niveau, montant, action) en moins de DOUBLON_S s,
        hors missions refusées ou échouées (une nouvelle demande identique est alors légitime)."""
        if cle:
            mid = sentinel.lire(f"idem:{cle[:120]}")
            if mid:
                return int(mid)
        depuis = maintenant() - timedelta(seconds=DOUBLON_S)
        with session_scope() as s:
            return s.execute(select(Mission.id).where(
                Mission.titre == titre, Mission.consigne == consigne, Mission.projet == projet,
                True if corps.service is None else Mission.service == corps.service,  # sinon choisi par PRIME
                Mission.fonctionnement_demande == (corps.fonctionnement or fct.defaut()),
                Mission.montant_eur == (corps.montant_eur or 0.0),
                Mission.action.is_(None) if corps.action is None else Mission.action == corps.action,
                Mission.statut.notin_(("refusee", "echouee", "a_reformuler", "plafond_atteint", "annulee")),
                Mission.fantome.is_(False), Mission.cree_le >= depuis).order_by(Mission.id.desc())).scalars().first()

    def _creer_mission(corps: NouvelleMission, taches: BackgroundTasks, cle: str | None):
        if corps.service and corps.service not in reg.services():
            raise HTTPException(422, f"Service inconnu : {corps.service}")
        try:
            projet = registre.resoudre(corps.projet)
        except ValueError as e:
            raise HTTPException(422, str(e))
        # Secret ou canari collé dans la consigne ou le titre : masqué avant TOUT stockage.
        titre, consigne = pipeline._assainir(corps.titre.strip()), pipeline._assainir(corps.consigne.strip())
        if titre != corps.titre.strip() or consigne != corps.consigne.strip():
            ledger.journaliser("NEXUS-SENTINEL", "secret_masque_a_la_creation", None)
        existant = _doublon(cle, titre, consigne, projet, corps)
        if existant is not None:
            ledger.journaliser("API", "mission_doublon_ignoree", existant, cle_idempotence=bool(cle))
            with session_scope() as s:
                m = s.get(Mission, existant)
                # 200 (et non 202) : rien de nouveau n'est accepté, la mission existante est renvoyée.
                return JSONResponse({"id": existant, "statut": m.statut, "projet": m.projet, "doublon": True,
                                     "fonctionnement_demande": m.fonctionnement_demande,
                                     "fonctionnement": m.fonctionnement,
                                     "message": "Mission identique déjà créée il y a moins de 30 s : "
                                                "aucune nouvelle mission."}, status_code=200)
        demande = corps.fonctionnement or fct.defaut()
        applique, raison, attente_f4 = demande, None, False
        if demande == "F4":
            indispo = fct.disponibilite_f4()
            if indispo and not corps.repli_f3:
                ledger.journaliser("NEXUS-BUDGET", "f4_refuse", None, titre=corps.titre, raison=indispo)
                raise HTTPException(422, f"F4 indisponible : {indispo}. Mission non créée "
                                         "(cochez « repli_f3 » pour la lancer en F3).")
            if indispo:
                applique, raison = "F3", f"F4 indisponible : {indispo} — mission lancée en F3"
            else:
                attente_f4 = True
        with session_scope() as s:
            m = Mission(titre=titre, consigne=consigne, service=corps.service,
                        montant_eur=corps.montant_eur or 0.0, action=corps.action,
                        statut="en_attente_n3" if attente_f4 else "recue", projet=projet,
                        fonctionnement_demande=demande, fonctionnement=applique,
                        fonctionnement_raison=raison, repli_f3=corps.repli_f3,
                        attente="lancement_f4" if attente_f4 else None, message=raison)
            s.add(m)
            s.flush()
            mid = m.id
        if cle:
            sentinel.ecrire(f"idem:{cle[:120]}", str(mid))
        ledger.journaliser("API", "mission_recue", mid, titre=titre, service=corps.service,
                           projet=projet, fonctionnement_demande=demande, fonctionnement=applique,
                           raison=raison)
        rep = {"id": mid, "statut": "recue", "projet": projet, "fonctionnement_demande": demande,
               "fonctionnement": applique, "message": raison}
        if attente_f4:
            # Aucune exécution avant l'accord du propriétaire (décision N3 « Lancer en F4 »).
            did = pipeline.creer_decision_lancement_f4(mid)
            est = fct.estimer_cout_eur("F4")
            rep.update(statut="en_attente_n3", decision_id=did, cout_estime_eur=est["cout_estime_eur"],
                       message=f"Lancement F4 soumis à validation — coût estimé {est['cout_estime_eur']:.2f} €.")
            return rep
        taches.add_task(FILE.executer, mid, pipeline.traiter)  # file FIFO bornée (NEXUS_MAX_MISSIONS)
        return rep

    @r.get("/missions")
    def lister_missions(statut: str | None = None, projet: str | None = None,
                        limit: int = Query(50, ge=1, le=500)):
        code = _filtre_projet(projet)
        with session_scope() as s:
            q = select(Mission).order_by(Mission.id.desc()).limit(limit)
            if statut != "fantome":  # rejeux du test fantôme : visibles seulement sur demande
                q = q.where(Mission.fantome.is_(False))
            if statut:
                q = q.where(Mission.statut == statut)
            if code:
                q = q.where(Mission.projet == code)
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
    def lister_decisions(statut: str | None = None, projet: str | None = None,
                         limit: int = Query(100, ge=1, le=500)):
        code = _filtre_projet(projet)
        with session_scope() as s:
            q = (select(Decision, Mission.titre, Mission.projet)
                 .join(Mission, Mission.id == Decision.mission_id)
                 .order_by(Decision.id.desc()).limit(limit))
            if statut:
                q = q.where(Decision.statut == statut)
            if code:
                q = q.where(Mission.projet == code)
            return [_decision(d, t, p) for d, t, p in s.execute(q).all()]

    @r.get("/projets")
    def lister_projets(recharger: bool = False):
        """Registre des projets avec compteurs ; ?recharger=1 relit projets.yaml."""
        try:
            reg_projets = registre.charger(recharger=recharger)
        except Exception as e:
            raise HTTPException(500, f"projets.yaml invalide, ancien registre conservé : {e}")
        if recharger:
            ledger.journaliser("DECIDEUR", "projets_recharges", None, nombre=len(reg_projets))
        with session_scope() as s:
            missions = dict(s.execute(select(Mission.projet, func.count(Mission.id))
                                      .where(Mission.fantome.is_(False)).group_by(Mission.projet)).all())
            en_cours = dict(s.execute(select(Mission.projet, func.count(Mission.id))
                                      .where(Mission.statut.in_(("recue", "en_cours")))
                                      .group_by(Mission.projet)).all())
            attente = dict(s.execute(select(Mission.projet, func.count(Decision.id))
                                     .join(Mission, Mission.id == Decision.mission_id)
                                     .where(Decision.statut == "en_attente")
                                     .group_by(Mission.projet)).all())
        return [{**p, "missions": missions.get(c, 0), "missions_en_cours": en_cours.get(c, 0),
                 "decisions_en_attente": attente.get(c, 0)} for c, p in reg_projets.items()]

    def _decider(did: int, choix: str, corps: Commentaire | None, taches: BackgroundTasks | None = None):
        commentaire = corps.commentaire if corps else None
        try:
            res = pipeline.decider(did, choix, commentaire)
            if res.get("relance") and taches is not None:
                taches.add_task(FILE.executer, res["mission_id"], pipeline.relancer_revision, commentaire)
            if res.get("lancer") and taches is not None:
                taches.add_task(FILE.executer, res["mission_id"], pipeline.traiter)  # lancement F4 approuvé
            return res
        except LookupError as e:
            raise HTTPException(404, str(e))
        except PermissionError as e:
            raise HTTPException(409, str(e))

    def _api_peut_decider() -> None:
        """Valider / refuser / réviser une N3 : réservé au Décideur via le cockpit (X-Cockpit-Auth +
        anti-CSRF ; code pour un risque élevé). La clé API (passerelle IA, n8n) ne décide jamais.
        NEXUS_API_PEUT_DECIDER=1 : option réservée aux tests (défaut 0)."""
        if not cockpit and os.environ.get("NEXUS_API_PEUT_DECIDER", "0").strip() != "1":
            ledger.journaliser("NEXUS-GATE", "decision_api_refusee", None)
            raise HTTPException(403, "Validation réservée au Décideur via le cockpit "
                                     "(la clé API ne peut ni valider, ni refuser, ni réviser une décision).")

    @r.post("/decisions/{did}/valider")
    def valider(did: int, taches: BackgroundTasks, corps: Commentaire | None = None):
        _api_peut_decider()
        if True:  # risque élevé : code Décideur exigé (cockpit, et API en mode test)
            from . import decideur
            if decideur.code_exige_pour(did):  # risque élevé ou montant ≥ seuil
                try:
                    decideur.verifier_code(corps.code if corps else None, "cockpit" if cockpit else "api")
                except decideur.CodeRefuse as e:
                    raise HTTPException(e.statut, str(e))
        return _decider(did, "valider", corps, taches)

    @r.post("/decisions/{did}/refuser")
    def refuser(did: int, corps: Commentaire | None = None):
        _api_peut_decider()
        return _decider(did, "refuser", corps)

    @r.post("/decisions/{did}/reviser")
    def reviser(did: int, taches: BackgroundTasks, corps: Commentaire | None = None):
        _api_peut_decider()
        return _decider(did, "reviser", corps, taches)

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
                        "outils_autorises": a["outils_autorises"], "type": a.get("type", "llm"),
                        "appelle_llm": reg.appelle_llm(a),
                        "statut": "suspendu" if suspendu else "actif"})
        return res

    @r.get("/projets/{code}/connaissances")
    def lire_connaissances(code: str, q: str | None = Query(default=None, max_length=300),
                           limite: int = Query(10, ge=1, le=50)):
        """Mémoire du projet : recherche plein texte (q) ou dernières connaissances."""
        try:
            return memoire.rechercher(code, q, limite)
        except ValueError as e:
            raise HTTPException(404, str(e))

    @r.post("/projets/{code}/connaissances", status_code=201)
    def ajouter_connaissance(code: str, corps: NouvelleConnaissance):
        auteur = "proprietaire" if cockpit else "api"
        try:
            registre.resoudre(code)
        except ValueError as e:
            raise HTTPException(404, str(e))
        try:
            return memoire.ajouter(code, corps.titre, corps.contenu,
                                   corps.source or f"{auteur} {maintenant().strftime('%Y-%m-%d %H:%M:%S.%f')}",
                                   auteur, origine="manuel")
        except (memoire.SecretRefuse, memoire.InjectionRefusee) as e:
            raise HTTPException(422, str(e))

    @r.post("/missions/{mid}/note")
    def noter_mission(mid: int, corps: Note):
        """Note du propriétaire (1 à 5) ; ≥ NEXUS_EXEMPLES_SEUIL → le livrable devient un exemple."""
        with session_scope() as s:
            m = s.get(Mission, mid)
            if m is None:
                raise HTTPException(404, "Mission introuvable")
            m.note = corps.note
        ledger.journaliser("DECIDEUR", "mission_notee", mid, note=corps.note)
        exemple = exemples.proposer(mid, "note") if corps.note >= exemples.seuil() else None
        return {"mission_id": mid, "note": corps.note, "exemple": exemple}

    @r.post("/missions/{mid}/exemple")
    def garder_exemple(mid: int):
        """« Garder comme exemple » (cockpit) : refusé si secret, charte violée ou mission non validée."""
        try:
            return exemples.proposer(mid, "manuel", manuel=True)
        except exemples.ExempleRefuse as e:
            raise HTTPException(422, str(e))

    @r.get("/export-qg")
    def etat_export_qg():
        from . import export_qg
        return export_qg.etat()

    @r.get("/exemples")
    def lister_exemples(service: str | None = None, tous: bool = False):
        return exemples.lister(service, tous)

    @r.post("/exemples/{eid}/retirer")
    def retirer_exemple(eid: int):
        if not exemples.retirer(eid):
            raise HTTPException(404, "Exemple introuvable")
        return {"id": eid, "actif": False}

    @r.get("/fonctionnement")
    def lire_fonctionnement():
        """Grille F1..F4 et consommation du mois par niveau appliqué."""
        debut = maintenant().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with session_scope() as s:
            rows = s.execute(
                select(Mission.fonctionnement, func.count(Mission.id), func.coalesce(func.sum(Mission.tokens), 0),
                       func.coalesce(func.sum(Mission.tokens_entree), 0),
                       func.coalesce(func.sum(Mission.tokens_sortie), 0),
                       func.coalesce(func.sum(Mission.cout_eur), 0.0), func.avg(Mission.duree_s))
                .where(Mission.cree_le >= debut).where(Mission.fantome.is_(False))
                .group_by(Mission.fonctionnement)).all()
        conso = {r[0]: r for r in rows}
        mois = []
        for code in fct.CODES:
            r = conso.get(code)
            mois.append({"code": code, "missions": r[1] if r else 0, "tokens": int(r[2]) if r else 0,
                         "tokens_entree": int(r[3]) if r else 0, "tokens_sortie": int(r[4]) if r else 0,
                         "cout_eur": round(float(r[5]), 4) if r else 0.0,
                         "duree_moyenne_s": round(float(r[6]), 1) if r and r[6] is not None else None})
        return {**fct.grille_publique(), "mois": debut.strftime("%Y-%m"), "consommation": mois}

    @r.get("/budget")
    def lire_budget():
        return budget.resume()

    return r
