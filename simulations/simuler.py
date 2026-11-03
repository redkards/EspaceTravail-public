#!/usr/bin/env python3
"""Moteur de simulations virtuelles de la structure SYFER (nexus-core).

Exécute les scénarios de `scenarios.json` :
- « hors_ligne »   : fonctions Python de nexus-core appelées directement, base SQLite temporaire ;
- « api_factice »  : application FastAPI de nexus-core lancée en local (TestClient), base temporaire ;
- « vps »          : réservé à une exécution réelle sur le serveur → toujours SAUTÉ ici.

Le LLM est remplacé par un LLM factice SCRIPTABLE par scénario (réponse bonne, mauvaise, injection,
secret, panne) ; l'horloge des missions est simulée. Aucun réseau, aucune donnée personnelle.
Un scénario dont un prérequis manque (module absent) est sauté proprement, avec la raison.

Usage :
    python3 simuler.py                       # tous les scénarios exécutables
    python3 simuler.py --methode decideur    # une méthode (nom ou numéro 1 à 10)
    python3 simuler.py --id SIM-001,SIM-042  # des scénarios précis
    python3 simuler.py --criticite critique  # par criticité
    python3 simuler.py --json                # résultat JSON sur la sortie standard
    python3 simuler.py --valider             # valide seulement scenarios.json contre schema.json
Résultats : resultats/AAAA-MM-JJ_HHMM.json et .md (réussis / échoués / sautés par méthode).
"""
import argparse
import ast
import contextlib
import dataclasses
import datetime as dt
import importlib
import importlib.util
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
CORE = RACINE / "nexus-core"
SCENARIOS = ICI / "scenarios.json"
SCHEMA = ICI / "schema.json"
RESULTATS = ICI / "resultats"

CLE_API = "cle-api-simulation-syfer"
COCKPIT_INTERNE = "cockpit-interne-simulation-syfer"
HOTE = "nexus.simulation.local"

METHODES = {
    "routage_prime": "1. Routage PRIME",
    "gate_decision": "2. Niveaux de décision GATE N0–N3",
    "fonctionnement": "3. Niveaux de fonctionnement F1–F4",
    "charte_qualite": "4. Charte projet et qualité",
    "memoire_lecons": "5. Mémoire collective et leçons",
    "securite_ia": "6. Sécurité IA / injection",
    "cybersecurite": "7. Cybersécurité défensive",
    "continuite": "8. Continuité",
    "decideur": "9. Décideur",
    "projets_pilotage": "10. Projets réels et pilotage",
}
# Prérequis → modules qui le satisfont (l'un d'eux suffit).
PREREQUIS = {
    "charte": ["app.charte"],
    "lecons": ["app.lecons"],
    "bouclier": ["app.bouclier"],
    "archive": ["app.archive"],
    "pilote": ["app.pilote"],
    "passerelle": ["@nexus-bridge/app/outils.py"],
}
ENV_A_EFFACER = [
    "NTFY_URL", "NTFY_TOPIC", "ANTHROPIC_API_KEY", "NEXUS_FONCTIONNEMENT_DEFAUT", "EUR_PAR_USD",
    "NEXUS_FONCTIONNEMENT_FILE", "BUDGET_MONTHLY_EUR", "LEDGER_HMAC_KEY", "NEXUS_MAX_MISSIONS",
    "NEXUS_PROJETS_FILE", "COCKPIT_CODE_DECIDEUR", "NEXUS_SESSIONS_N3", "NEXUS_MEMOIRE_AUTO",
    "NEXUS_MODELES_ROLES", "NEXUS_MODELES_CLOUD", "NEXUS_CHARTES_DIR", "NEXUS_WEBHOOK_QG",
    "NEXUS_WEBHOOK_SECRET", "NEXUS_RESUME_QUOTIDIEN", "NEXUS_EXEMPLES_SEUIL", "NEXUS_LECONS_SEUIL",
    "NEXUS_BANC_RESULTATS", "N3_TIMEOUT_HOURS", "N3_DAILY_CAP", "OLLAMA_API_KEY", "LLM_FALLBACK",
    "NEXUS_MODEL", "NEXUS_MODEL_CHECKER", "NEXUS_MODEL_LOCAL", "LLM_MAX_CHARS", "OLLAMA_NUM_CTX",
    "NEXUS_LECONS_REFORMULER", "NEXUS_API_PEUT_DECIDER", "NEXUS_LECONS_MESURES_MIN", "NEXUS_LECONS_BAISSE", "LLM_EUR_PAR_1K_TOKENS",
]

log = logging.getLogger("simulations")


# --- Import de nexus-core ---------------------------------------------------------------------

def _preparer_import() -> None:
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    # Valeurs neutres AVANT l'import (main.py lit la configuration à l'import).
    os.environ.setdefault("LLM_PROVIDER", "fake")
    os.environ.setdefault("NEXUS_TACHES_FOND", "0")


def module_existe(nom: str) -> bool:
    if nom.startswith("@"):
        return (RACINE / nom[1:]).is_file()
    _preparer_import()
    try:
        return importlib.util.find_spec(nom) is not None
    except (ImportError, ValueError):
        return False


def fonction_existe(chemin: str) -> bool:
    mod, _, attr = chemin.rpartition(".")
    if not module_existe(mod):
        return module_existe(chemin)
    try:
        return hasattr(importlib.import_module(mod), attr)
    except Exception:
        return False


def _objet(chemin: str):
    """« app.gate.classer » → objet Python (module, classe ou fonction)."""
    _preparer_import()
    morceaux = chemin.split(".")
    for i in range(len(morceaux), 0, -1):
        nom = ".".join(morceaux[:i])
        try:
            obj = importlib.import_module(nom)
        except ImportError:
            continue
        for attr in morceaux[i:]:
            obj = getattr(obj, attr)
        return obj
    raise ImportError(chemin)


# --- LLM factice scriptable et horloge simulée -------------------------------------------------

class EtatLLM:
    """Script par rôle (« analyst », « checker », « checker_local »…), compteurs et horloge simulée."""

    def __init__(self):
        self.script: dict[str, list] = {}
        self.appels: list[str] = []
        self.entrees: dict[str, list[str]] = {}
        self.tokens = 0
        self.tokens_par_appel: int | None = None
        self.avance_s = 1.0      # secondes simulées par appel
        self.pause_s = 0.0       # vraie pause (tests de file d'attente)
        self.horloge = 1000.0
        self.verrou = threading.Lock()

    def configurer(self, d: dict) -> None:
        for role, reponses in (d.get("script") or {}).items():
            self.script.setdefault(role, []).extend(reponses)
        for cle in ("tokens_par_appel", "avance_s", "pause_s"):
            if cle in d:
                setattr(self, cle, d[cle])

    def vue(self) -> dict:
        return {"appels": list(self.appels), "entrees": {k: list(v) for k, v in self.entrees.items()},
                "tokens": self.tokens, "nb_appels": len(self.appels)}


class SimLLM:
    """Fournisseur LLM de simulation : même interface que les fournisseurs de nexus-core."""
    nom = "fake"

    def __init__(self, etat: EtatLLM, canal: str = "principal"):
        self.etat, self.canal = etat, canal

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None, timeout: float | None = None):
        from app.llm import ErreurLLM, FournisseurFactice, Reponse, estimer_tokens
        e = self.etat
        cle = role + ("_local" if self.canal == "local" else "")
        with e.verrou:
            e.appels.append(cle)
            e.entrees.setdefault(cle, []).append(utilisateur)
            e.horloge += float(e.avance_s or 0)
            file = e.script.get(cle)
            rep = file.pop(0) if file else None
        if e.pause_s:
            time.sleep(e.pause_s)
        if isinstance(rep, dict) and "panne" in rep:
            raise ErreurLLM(str(rep["panne"]))
        if rep is None:
            texte = FournisseurFactice._defaut(role, utilisateur)
        elif isinstance(rep, dict) and "json" in rep:
            texte = json.dumps(rep["json"], ensure_ascii=False)
        else:
            texte = str(rep)
        if e.tokens_par_appel:
            r = Reponse(texte, int(e.tokens_par_appel), self.nom, modele or "sim")
        else:
            a, b = estimer_tokens(systeme + utilisateur), estimer_tokens(texte)
            r = Reponse(texte, a + b, self.nom, modele or "sim", tokens_entree=a, tokens_sortie=b)
        with e.verrou:
            e.tokens += r.tokens
        return r


def _simulateur(nom: str, etat: EtatLLM):
    """Comportements nommés utilisables par l'étape « patch »."""
    if nom == "ollama_cloud_en_panne":
        def chat(base_url, modele, systeme, utilisateur, role, temperature, en_tetes=None, local=True,
                 num_ctx=None, timeout=None):
            if not local:
                import httpx
                req = httpx.Request("POST", f"{base_url}/api/chat")
                raise httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))
            return {"message": {"content": "Réponse du modèle local (simulation)."}, "prompt_eval_count": 12,
                    "eval_count": 6}
        return chat
    if nom == "vrai":
        return lambda *a, **k: True
    if nom == "faux":
        return lambda *a, **k: False
    raise ValueError(f"simulateur inconnu : {nom}")


# --- Conversion des résultats en JSON ------------------------------------------------------------

def jsonable(x, profondeur: int = 0):
    if profondeur > 8:
        return str(x)
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if isinstance(x, (dt.datetime, dt.date)):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): jsonable(v, profondeur + 1) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v, profondeur + 1) for v in (sorted(x, key=str) if isinstance(x, set) else x)]
    if dataclasses.is_dataclass(x):
        d = dataclasses.asdict(x)
        for nom in dir(type(x)):  # propriétés calculées (ex. Verdict.alertes_transmises)
            if isinstance(getattr(type(x), nom, None), property):
                with contextlib.suppress(Exception):
                    d[nom] = getattr(x, nom)
        return jsonable(d, profondeur + 1)
    if hasattr(x, "__table__"):
        return {c.name: jsonable(getattr(x, c.name), profondeur + 1) for c in x.__table__.columns}
    if isinstance(x, Exception):
        return {"exception": type(x).__name__, "message": str(x)}
    return str(x)


# --- Chemins, gabarits, assertions ----------------------------------------------------------------

_GABARIT = re.compile(r"\$\{([^}]+)\}")
_FILTRE = re.compile(r"^([^\[]*)\[([^=\]]+)=([^\]]*)\]$")


def resoudre(ctx: dict, chemin: str):
    """« m.decisions.0.statut », « r.json[code=poker-winners].missions », « m.etapes#texte »."""
    chemin, _, suffixe = chemin.partition("#")
    v = ctx
    for part in [p for p in chemin.split(".") if p != ""]:
        f = _FILTRE.match(part)
        if f:
            nom, cle, val = f.groups()
            if nom:
                v = v[nom] if isinstance(v, dict) else v[int(nom)]
            v = next(x for x in v if str(x.get(cle)) == val)
            continue
        if isinstance(v, list):
            v = v[int(part)]
        elif isinstance(v, dict):
            v = v[part]
        else:
            v = getattr(v, part)
    if suffixe == "len":
        return len(v)
    if suffixe == "texte":
        return json.dumps(v, ensure_ascii=False, default=str)
    if suffixe == "lignes":
        return len([l for l in str(v or "").splitlines() if l.strip()])
    if suffixe == "nb_exceptions":
        return sum(1 for x in v if isinstance(x, dict) and "exception" in x)
    if suffixe == "nb_succes":
        return sum(1 for x in v if not (isinstance(x, dict) and "exception" in x))
    if suffixe:
        raise KeyError(f"suffixe inconnu #{suffixe}")
    return v


def _temps(spec: dict) -> dt.datetime:
    """{"$session": "12:30", "plus_min": 5} ou {"$maintenant_plus_h": 3} → datetime UTC naïf."""
    from app.models import maintenant
    if "$maintenant_plus_h" in spec:
        return maintenant() + dt.timedelta(hours=float(spec["$maintenant_plus_h"]))
    from app import decideur
    hh, mm = map(int, spec["$session"].split(":"))
    p = maintenant().replace(tzinfo=dt.timezone.utc).astimezone(decideur.PARIS)
    cand = p.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= p:
        cand += dt.timedelta(days=1)
    cand += dt.timedelta(minutes=float(spec.get("plus_min", 0)))
    return cand.astimezone(dt.timezone.utc).replace(tzinfo=None)


def rendre(obj, ctx: dict):
    """Remplace ${chemin} par la valeur du contexte (type conservé si le texte n'est que ${…})."""
    if isinstance(obj, str):
        m = _GABARIT.fullmatch(obj)
        if m:
            return resoudre(ctx, m.group(1))
        return _GABARIT.sub(lambda g: str(resoudre(ctx, g.group(1))), obj)
    if isinstance(obj, list):
        return [rendre(x, ctx) for x in obj]
    if isinstance(obj, dict):
        if "$session" in obj or "$maintenant_plus_h" in obj:
            return _temps(obj)
        if "$fonction" in obj:
            return _objet(obj["$fonction"])
        return {k: rendre(v, ctx) for k, v in obj.items()}
    return obj


def _norm(x) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower()


def verifier(op: str, obtenu, attendu) -> bool:
    if op == "egal":
        return obtenu == attendu
    if op == "different":
        return obtenu != attendu
    if op == "dans":
        return obtenu in attendu
    if op == "hors":
        return obtenu not in attendu
    if op in ("contient", "ne_contient_pas"):
        if isinstance(obtenu, (list, tuple)):
            ok = attendu in obtenu or any(_norm(attendu) in _norm(x) for x in obtenu if isinstance(x, str))
        else:
            ok = _norm(attendu) in _norm(obtenu if obtenu is not None else "")
        return ok if op == "contient" else not ok
    if op == "contient_tous":
        return all(verifier("contient", obtenu, a) for a in attendu)
    if op == "aucun_contient":
        return not any(verifier("contient", obtenu, a) for a in attendu)
    if op == "ge":
        return obtenu is not None and obtenu >= attendu
    if op == "le":
        return obtenu is not None and obtenu <= attendu
    if op == "gt":
        return obtenu is not None and obtenu > attendu
    if op == "lt":
        return obtenu is not None and obtenu < attendu
    if op == "vrai":
        return bool(obtenu) is True
    if op == "faux":
        return not obtenu
    if op == "existe":
        return obtenu is not None
    if op == "absent":
        return obtenu is None
    if op == "regex":
        return re.search(attendu, str(obtenu or "")) is not None
    raise ValueError(f"opérateur inconnu : {op}")


class CheminIntrouvable(Exception):
    pass


# --- Bac à sable d'un scénario ---------------------------------------------------------------------

class Bac:
    """Environnement isolé : dossier temporaire, variables d'environnement, base, LLM factice, patchs."""

    def __init__(self, sc: dict):
        self.sc = sc
        self.mode = sc["mode"]
        self.tmp = Path(tempfile.mkdtemp(prefix=f"sim-{sc['id']}-"))
        self.env_avant = dict(os.environ)
        self.patchs: list[tuple[object, str, object]] = []
        self.llm = EtatLLM()
        self.client = None
        self._client_cm = None
        self.ctx: dict = {"tmp": str(self.tmp)}

    # -- environnement
    def _env(self, valeurs: dict) -> None:
        for k, v in valeurs.items():
            v = rendre(v, self.ctx)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)

    def patcher(self, cible, nom: str, valeur) -> None:
        self.patchs.append((cible, nom, getattr(cible, nom)))
        setattr(cible, nom, valeur)

    def __enter__(self):
        for v in ENV_A_EFFACER:
            os.environ.pop(v, None)
        self._env({
            "DATABASE_URL": f"sqlite:///{self.tmp / 'nexus.db'}", "NEXUS_DATA_DIR": str(self.tmp / "data"),
            "LLM_PROVIDER": "fake", "NEXUS_API_KEY": CLE_API, "NEXUS_TACHES_FOND": "0",
            "COCKPIT_INTERNAL": COCKPIT_INTERNE, "NEXUS_HOST": HOTE, "BUDGET_TASK_TOKENS": "20000",
            "NEXUS_CONNAISSANCES_DIR": str(self.tmp / "connaissances"), "NEXUS_ARCHIVE_DIR": str(self.tmp / "archive"),
        })
        prep = self.sc.get("preparation") or {}
        self._env(prep.get("env") or {})
        _preparer_import()
        from app import db, decideur, fonctionnement, llm, pipeline
        fonctionnement.charger(recharger=True)
        db.reinitialiser()
        db.init_db()
        llm.FournisseurFactice.reinitialiser()
        with contextlib.suppress(Exception):
            decideur._jetons.clear()
        etat = self.llm
        fabrique = lambda *a, **k: SimLLM(etat, "principal")  # noqa: E731
        local = lambda *a, **k: SimLLM(etat, "local")  # noqa: E731
        for mod in (pipeline, llm):
            self.patcher(mod, "fournisseur_niveau", fabrique)
            self.patcher(mod, "fournisseur_controle_local", local)
        self.patcher(pipeline, "_horloge", lambda: etat.horloge)
        self.llm.configurer(prep.get("llm") or {})
        if self.mode == "api_factice":
            self._demarrer_client()
        return self

    def _demarrer_client(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app
        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()

    def _arreter_client(self) -> None:
        if self._client_cm is not None:
            with contextlib.suppress(Exception):
                self._client_cm.__exit__(None, None, None)
        self._client_cm = self.client = None

    def __exit__(self, *exc):
        self._arreter_client()
        with contextlib.suppress(Exception):
            from app.file_missions import FILE
            FILE.attendre_vide(20)
        for cible, nom, ancien in reversed(self.patchs):
            setattr(cible, nom, ancien)
        with contextlib.suppress(Exception):
            from app import db
            db.reinitialiser()
        os.environ.clear()
        os.environ.update(self.env_avant)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    # -- vues
    def vue_ctx(self) -> dict:
        self.ctx["llm"] = self.llm.vue()
        return self.ctx

    def instantane(self, mid: int) -> dict:
        from sqlalchemy import select
        from app.db import session_scope
        from app.models import Decision, Etape, Ledger, Mission
        with session_scope() as s:
            m = s.get(Mission, mid)
            if m is None:
                return {"id": mid, "introuvable": True}
            d = jsonable(m)
            d["livrable"] = d.get("livrable_texte")
            d["decisions"] = []
            for x in s.execute(select(Decision).where(Decision.mission_id == mid).order_by(Decision.id)).scalars():
                dd = jsonable(x)
                with contextlib.suppress(Exception):
                    dd["risque_raisons"] = json.loads(x.risque_raisons or "[]")
                d["decisions"].append(dd)
            d["etapes"] = [{"role": e.role, "agent_id": e.agent_id, "entree": e.entree, "sortie": e.sortie,
                            "verdict": e.verdict, "tokens": e.tokens}
                           for e in s.execute(select(Etape).where(Etape.mission_id == mid).order_by(Etape.id)).scalars()]
            d["roles"] = [e["role"] for e in d["etapes"]]
            lignes = s.execute(select(Ledger).where(Ledger.mission_id == mid).order_by(Ledger.id)).scalars().all()
            d["ledger"] = [{"acteur": l.acteur, "action": l.action, "details": json.loads(l.details_json or "{}")}
                           for l in lignes]
            d["ledger_actions"] = [l.action for l in lignes]
        with contextlib.suppress(Exception):
            d["charte_avertissements"] = json.loads(d.get("charte_avertissements") or "[]")
        fichier = self.tmp / "data" / "livrables" / (d.get("projet") or "divers") / f"{mid}.md"
        d["fichier_livrable"] = fichier.read_text(encoding="utf-8") if fichier.is_file() else None
        return d

    def ledger_global(self) -> dict:
        from sqlalchemy import select
        from app import ledger
        from app.db import session_scope
        from app.models import Ledger
        with session_scope() as s:
            lignes = s.execute(select(Ledger).order_by(Ledger.id)).scalars().all()
            entrees = [{"id": l.id, "acteur": l.acteur, "action": l.action, "mission_id": l.mission_id,
                        "details": json.loads(l.details_json or "{}")} for l in lignes]
        return {"entrees": entrees, "actions": [e["action"] for e in entrees], "verif": ledger.verifier()}

    # -- étapes
    def executer_etapes(self, etapes: list[dict]) -> None:
        for i, e in enumerate(etapes):
            self.vue_ctx()
            faire = e["faire"]
            fn = getattr(self, f"a_{faire}", None)
            if fn is None:
                raise ValueError(f"étape {i + 1} : action inconnue « {faire} »")
            res = fn(e)
            if e.get("nom"):
                self.ctx[e["nom"]] = res
        self.vue_ctx()

    def a_env(self, e):
        self._env(e["valeurs"])

    def a_llm(self, e):
        self.llm.configurer(rendre(e, self.ctx))

    def a_patch(self, e):
        cible_nom, _, attr = e["cible"].rpartition(".")
        cible = _objet(cible_nom)
        if "simulateur" in e:
            valeur = _simulateur(e["simulateur"], self.llm)
        else:
            v = e.get("valeur")
            valeur = lambda *a, **k: v  # noqa: E731
        self.patcher(cible, attr, valeur)

    def _appeler(self, spec: dict):
        spec = rendre(spec, self.ctx)
        try:
            obj = _objet(spec["fonction"])
            if "methode" in spec:
                c = spec.get("constructeur") or {}
                obj = getattr(obj(*c.get("args", []), **c.get("kwargs", {})), spec["methode"])
            return jsonable(obj(*spec.get("args", []), **spec.get("kwargs", {})))
        except Exception as ex:  # l'exception devient un résultat vérifiable
            return {"exception": type(ex).__name__, "message": str(ex)}

    def a_appel(self, e):
        return self._appeler(e)

    def a_parallele(self, e):
        appels = e["appels"]
        res = [None] * len(appels)
        barriere = threading.Barrier(len(appels))

        def tache(i, spec):
            barriere.wait()
            res[i] = self._appeler(spec)

        fils = [threading.Thread(target=tache, args=(i, s)) for i, s in enumerate(appels)]
        for f in fils:
            f.start()
        for f in fils:
            f.join(30)
        return res

    _COLONNES = {"titre", "consigne", "service", "projet", "fonctionnement", "fonctionnement_demande", "montant_eur",
                 "action", "statut", "livrable_texte", "note", "repli_f3", "niveau", "message", "attente"}

    def a_mission(self, e):
        """Crée une mission en base ; l'exécute dans le pipeline sauf « executer: false »."""
        from app import pipeline
        from app.db import session_scope
        from app.models import Mission
        e = rendre(e, self.ctx)
        champs = {k: v for k, v in e.items() if k in self._COLONNES}
        champs.setdefault("titre", "Mission de simulation")
        champs.setdefault("consigne", "Consigne de simulation")
        if "fonctionnement" in champs:
            champs.setdefault("fonctionnement_demande", champs["fonctionnement"])
        with session_scope() as s:
            m = Mission(**champs)
            s.add(m)
            s.flush()
            mid = m.id
        if e.get("executer", True) and champs.get("statut", "recue") == "recue":
            pipeline.traiter(mid)
        return self.instantane(mid)

    def a_traiter(self, e):
        from app import pipeline
        mid = int(rendre(e["mission"], self.ctx))
        pipeline.traiter(mid)
        return self.instantane(mid)

    def a_relire(self, e):
        return self.instantane(int(rendre(e["mission"], self.ctx)))

    def a_router(self, e):
        from app import pipeline
        from app.db import session_scope
        from app.models import Mission
        e = rendre(e, self.ctx)
        with session_scope() as s:
            m = Mission(titre=e["titre"], consigne=e.get("consigne", e["titre"]), projet=e.get("projet", "divers"),
                        service=e.get("service"))
            s.add(m)
            s.flush()
            mid = m.id
        with session_scope() as s:
            ctx = pipeline.Contexte(s.get(Mission, mid))
        service = pipeline.choisir_service(ctx)
        snap = self.instantane(mid)
        return {"service": service, "mission_id": mid, "ledger": snap["ledger"],
                "scores": {k: v for k, v in pipeline.scores_services(e["titre"], e.get("consigne", "")).items() if v}}

    def a_inserer(self, e):
        from app import models
        from app.db import session_scope
        e = rendre(e, self.ctx)
        with session_scope() as s:
            o = getattr(models, e["modele"])(**e["champs"])
            s.add(o)
            s.flush()
            return jsonable(o)

    def a_horloge(self, e):
        """Fait « passer le temps » : recule cree_le des tables visées de `reculer_h` heures."""
        from app import models
        from app.db import session_scope
        from sqlalchemy import select
        h = float(e["reculer_h"])
        n = 0
        with session_scope() as s:
            for nom in e.get("tables", ["Decision"]):
                classe = getattr(models, nom)
                for o in s.execute(select(classe)).scalars():
                    o.cree_le = o.cree_le - dt.timedelta(hours=h)
                    n += 1
        return n

    def a_sql(self, e):
        from sqlalchemy import text
        from app.db import engine
        e = rendre(e, self.ctx)
        with engine().begin() as c:
            r = c.execute(text(e["requete"]), e.get("params") or {})
            if r.returns_rows:
                return [list(jsonable(tuple(x))) for x in r.fetchall()]
            return r.rowcount

    def a_ledger(self, e):
        return self.ledger_global()

    def a_redemarrer(self, e):
        from app import pipeline
        from app.file_missions import FILE
        if self.mode == "api_factice":
            self._arreter_client()
            self._demarrer_client()
            res = {"redemarre": True}
        else:
            res = jsonable(pipeline.reprendre_au_demarrage())
        FILE.attendre_vide(30)
        return res

    def a_soumettre(self, e):
        from app import pipeline
        from app.file_missions import FILE
        ids = [int(x) for x in rendre(e["missions"], self.ctx)]
        for mid in ids:
            FILE.soumettre(mid, pipeline.traiter)
        FILE.attendre_vide(60)
        return [self.instantane(mid) for mid in ids]

    def a_attendre_file(self, e):
        from app.file_missions import FILE
        return FILE.attendre_vide(float(e.get("delai_s", 30)))

    def a_http(self, e):
        if self.client is None:
            raise RuntimeError("étape http hors du mode api_factice")
        e = rendre(e, self.ctx)
        ent = e.get("entetes", "api")
        entetes = {"api": {"X-Nexus-Key": CLE_API},
                   "cockpit": {"X-Cockpit-Auth": COCKPIT_INTERNE, "X-Cockpit": "1"},
                   "aucun": {}}.get(ent, ent) if isinstance(ent, str) else dict(ent)
        entetes = {**entetes, **(e.get("entetes_sup") or {})}
        kw = {"headers": entetes}
        if "json" in e:
            kw["json"] = e["json"]
        if "brut" in e:
            kw["content"] = e["brut"]
        r = self.client.request(e.get("methode", "GET"), e["chemin"], **kw)
        try:
            corps = r.json()
        except ValueError:
            corps = None
        return {"status": r.status_code, "json": corps, "texte": r.text[:4000]}

    def a_repeter(self, e):
        res = []
        for i in range(int(e["n"])):
            self.ctx["i"] = i + 1
            dernier = None
            for sous in e["etapes"]:
                self.vue_ctx()
                dernier = getattr(self, f"a_{sous['faire']}")(sous)
                if sous.get("nom"):
                    self.ctx[sous["nom"]] = dernier
            res.append(dernier)
        return res

    def a_ecrire_fichier(self, e):
        e = rendre(e, self.ctx)
        f = self.tmp / e["chemin"]
        f.parent.mkdir(parents=True, exist_ok=True)
        contenu = e["contenu"]
        f.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
        return str(f)

    def a_lire_fichier(self, e):
        f = RACINE / e["chemin"]
        return f.read_text(encoding="utf-8") if f.is_file() else None

    def a_sauvegarder(self, e):
        src = sqlite3.connect(self.tmp / "nexus.db")
        dst = sqlite3.connect(self.tmp / e.get("fichier", "sauvegarde.db"))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return (self.tmp / e.get("fichier", "sauvegarde.db")).stat().st_size

    def a_restaurer(self, e):
        from app import db
        db.reinitialiser()
        for suffixe in ("", "-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                (self.tmp / f"nexus.db{suffixe}").unlink()
        shutil.copy(self.tmp / e.get("fichier", "sauvegarde.db"), self.tmp / "nexus.db")
        db.reinitialiser()
        db.init_db()
        return True

    def a_outils_passerelle(self, e):
        """Liste les outils MCP de nexus-bridge par lecture du code (sans l'exécuter)."""
        f = RACINE / "nexus-bridge" / "app" / "outils.py"
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        outils = []
        for n in ast.walk(arbre):
            if isinstance(n, ast.FunctionDef):
                for d in n.decorator_list:
                    if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "outil" and d.args:
                        nom = d.args[0].value if isinstance(d.args[0], ast.Constant) else None
                        ecriture = any(k.arg == "ecriture" and getattr(k.value, "value", False) for k in d.keywords)
                        outils.append({"nom": nom, "fonction": n.name, "ecriture": ecriture})
        return {"outils": outils, "noms": [o["nom"] for o in outils]}


# --- Exécution ---------------------------------------------------------------------------------------

def manque(sc: dict) -> str | None:
    if sc["mode"] == "vps":
        return "mode « vps » : réservé à une exécution réelle sur le serveur"
    for p in sc.get("prerequis") or []:
        mods = PREREQUIS.get(p, [f"app.{p}"])
        if not any(module_existe(m) for m in mods):
            return f"prérequis « {p} » absent ({' ou '.join(mods)})"
    for f in (sc.get("preparation") or {}).get("fonctions_requises") or []:
        if not fonction_existe(f):
            return f"fonction requise absente : {f}"
    return None


def _court(x, n: int = 400) -> str:
    t = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return t if len(t) <= n else t[: n - 1] + "…"


def executer_scenario(sc: dict) -> dict:
    res = {"id": sc["id"], "methode": sc["methode"], "titre": sc["titre"], "criticite": sc["criticite"],
           "mode": sc["mode"], "statut": None, "motif": None, "echecs": [], "mesures": {}}
    raison = manque(sc)
    if raison:
        res.update(statut="saute", motif=raison)
        return res
    debut = time.perf_counter()
    try:
        with Bac(sc) as bac:
            bac.executer_etapes(sc["etapes"])
            ctx = bac.vue_ctx()
            for a in sc["attendus"]:
                attendu = rendre(a.get("valeur"), ctx) if "valeur" in a else None
                try:
                    obtenu = resoudre(ctx, a["chemin"])
                except (KeyError, IndexError, StopIteration, AttributeError, TypeError, ValueError) as ex:
                    res["echecs"].append({"libelle": a.get("libelle", ""), "chemin": a["chemin"], "op": a["op"],
                                          "attendu": _court(attendu), "obtenu": f"(chemin introuvable : {type(ex).__name__} {ex})"})
                    continue
                if not verifier(a["op"], obtenu, attendu):
                    res["echecs"].append({"libelle": a.get("libelle", ""), "chemin": a["chemin"], "op": a["op"],
                                          "attendu": _court(attendu), "obtenu": _court(obtenu)})
            mesures = {"duree_ms": None, "tokens_llm": ctx["llm"]["tokens"], "appels_llm": ctx["llm"]["nb_appels"]}
            for m in sc.get("mesures") or []:
                if isinstance(m, dict):
                    with contextlib.suppress(Exception):
                        mesures[m["nom"]] = jsonable(resoudre(ctx, m["chemin"]))
            res["mesures"] = mesures
        res["statut"] = "echoue" if res["echecs"] else "reussi"
    except Exception as ex:
        res["statut"] = "echoue"
        res["motif"] = f"erreur d'exécution : {type(ex).__name__} : {ex}"
        res["echecs"].append({"libelle": "exécution du scénario", "chemin": "-", "op": "-", "attendu": "aucune erreur",
                              "obtenu": _court(traceback.format_exc(limit=4), 1200)})
    res["mesures"]["duree_ms"] = round((time.perf_counter() - debut) * 1000, 1)
    return res


def charger_scenarios() -> list[dict]:
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def valider_schema(scenarios_doc: dict | None = None) -> list[str]:
    """Erreurs de validation (liste vide = valide). jsonschema si disponible, sinon contrôles essentiels."""
    doc = scenarios_doc or json.loads(SCENARIOS.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    erreurs = []
    try:
        import jsonschema
        v = jsonschema.Draft7Validator(schema)
        erreurs += [f"{'/'.join(map(str, e.path))} : {e.message}" for e in v.iter_errors(doc)]
    except ImportError:
        for sc in doc.get("scenarios", []):
            for champ in schema["definitions"]["scenario"]["required"]:
                if champ not in sc:
                    erreurs.append(f"{sc.get('id', '?')} : champ manquant {champ}")
    ids = [s.get("id") for s in doc.get("scenarios", [])]
    if len(ids) != len(set(ids)):
        erreurs.append("identifiants en double")
    return erreurs


def filtrer(scenarios: list[dict], methode: str | None, ids: str | None, criticite: str | None) -> list[dict]:
    res = scenarios
    if methode:
        cles = list(METHODES)
        if methode.isdigit():
            methode = cles[int(methode) - 1]
        res = [s for s in res if s["methode"] == methode or methode.lower() in METHODES[s["methode"]].lower()]
    if ids:
        voulus = {i.strip().upper() for i in ids.split(",") if i.strip()}
        res = [s for s in res if s["id"] in voulus]
    if criticite:
        res = [s for s in res if s["criticite"] == criticite]
    return res


def synthese(resultats: list[dict]) -> dict:
    par = {}
    for m in METHODES:
        rs = [r for r in resultats if r["methode"] == m]
        par[m] = {"libelle": METHODES[m], "total": len(rs),
                  "executes": sum(r["statut"] != "saute" for r in rs),
                  "reussis": sum(r["statut"] == "reussi" for r in rs),
                  "echoues": sum(r["statut"] == "echoue" for r in rs),
                  "sautes": sum(r["statut"] == "saute" for r in rs)}
    tot = {k: sum(p[k] for p in par.values()) for k in ("total", "executes", "reussis", "echoues", "sautes")}
    return {"par_methode": par, "total": tot}


_ORDRE_CRIT = {"critique": 0, "haute": 1, "moyenne": 2, "basse": 3}


def rapport_md(doc: dict) -> str:
    s = doc["synthese"]
    l = [f"# Simulations SYFER — {doc['horodatage']}", "",
         f"Scénarios : {s['total']['total']} · exécutés {s['total']['executes']} · réussis {s['total']['reussis']} · "
         f"échoués {s['total']['echoues']} · sautés {s['total']['sautes']} · durée {doc['duree_s']} s", "",
         "Un échec est un RÉSULTAT : il signale un écart entre le comportement attendu (spécification SYFER) et le "
         "code actuel de nexus-core. Le code n'a pas été modifié pour faire passer les scénarios.", "",
         "## Par méthode", "", "| Méthode | Total | Exécutés | Réussis | Échoués | Sautés |", "|---|---|---|---|---|---|"]
    for p in s["par_methode"].values():
        l.append(f"| {p['libelle']} | {p['total']} | {p['executes']} | {p['reussis']} | {p['echoues']} | {p['sautes']} |")
    echecs = sorted([r for r in doc["resultats"] if r["statut"] == "echoue"],
                    key=lambda r: (_ORDRE_CRIT.get(r["criticite"], 9), r["id"]))
    l += ["", f"## Échecs ({len(echecs)}) — attendu / obtenu", ""]
    if not echecs:
        l.append("Aucun échec.")
    for r in echecs:
        l += [f"### {r['id']} — {r['titre']} ({r['criticite']}, {r['mode']})", ""]
        if r.get("motif"):
            l.append(f"- Motif : {r['motif']}")
        for e in r["echecs"]:
            l.append(f"- **{e['libelle'] or e['chemin']}** — `{e['chemin']}` {e['op']} : attendu `{e['attendu']}` · "
                     f"obtenu `{e['obtenu']}`".replace("\n", " "))
        l.append("")
    sautes = [r for r in doc["resultats"] if r["statut"] == "saute"]
    l += [f"## Sautés ({len(sautes)})", ""]
    l += [f"- {r['id']} — {r['titre']} : {r['motif']}" for r in sautes] or ["Aucun."]
    l += ["", "## Mesures (scénarios exécutés)", "", "| Id | Statut | Durée (ms) | Appels LLM | Tokens LLM |",
          "|---|---|---|---|---|"]
    for r in doc["resultats"]:
        if r["statut"] != "saute":
            m = r["mesures"]
            l.append(f"| {r['id']} | {r['statut']} | {m.get('duree_ms')} | {m.get('appels_llm')} | {m.get('tokens_llm')} |")
    return "\n".join(l) + "\n"


def lancer(scenarios: list[dict], ecrire: bool = True, bavard: bool = True) -> dict:
    logging.disable(logging.CRITICAL)  # journaux de nexus-core masqués (exceptions simulées comprises)
    debut = time.perf_counter()
    resultats = []
    for sc in scenarios:
        r = executer_scenario(sc)
        resultats.append(r)
        if bavard:
            marque = {"reussi": "OK  ", "echoue": "ÉCHEC", "saute": "SAUTÉ"}[r["statut"]]
            print(f"[{marque}] {r['id']} {r['titre']}" + (f" — {r['motif']}" if r["statut"] == "saute" else ""),
                  file=sys.stderr)
    logging.disable(logging.NOTSET)
    maintenant = dt.datetime.now()
    doc = {"horodatage": maintenant.strftime("%Y-%m-%d %H:%M"), "duree_s": round(time.perf_counter() - debut, 1),
           "synthese": synthese(resultats), "resultats": resultats}
    if ecrire:
        RESULTATS.mkdir(exist_ok=True)
        base = RESULTATS / maintenant.strftime("%Y-%m-%d_%H%M")
        base.with_suffix(".json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        base.with_suffix(".md").write_text(rapport_md(doc), encoding="utf-8")
        doc["fichiers"] = [str(base.with_suffix(".json")), str(base.with_suffix(".md"))]
    return doc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Simulations virtuelles de la structure SYFER (nexus-core).")
    p.add_argument("--methode", help="nom (ex. decideur) ou numéro 1 à 10")
    p.add_argument("--id", help="identifiants séparés par des virgules (ex. SIM-001,SIM-042)")
    p.add_argument("--criticite", choices=["critique", "haute", "moyenne", "basse"])
    p.add_argument("--json", action="store_true", help="afficher le résultat complet en JSON")
    p.add_argument("--valider", action="store_true", help="valider scenarios.json contre schema.json et s'arrêter")
    p.add_argument("--sans-fichier", action="store_true", help="ne pas écrire dans resultats/")
    a = p.parse_args(argv)
    erreurs = valider_schema()
    if erreurs:
        print("scenarios.json invalide :\n- " + "\n- ".join(erreurs[:30]), file=sys.stderr)
        return 2
    if a.valider:
        print(f"scenarios.json valide ({len(charger_scenarios())} scénarios).")
        return 0
    choisis = filtrer(charger_scenarios(), a.methode, a.id, a.criticite)
    if not choisis:
        print("Aucun scénario ne correspond au filtre.", file=sys.stderr)
        return 1
    doc = lancer(choisis, ecrire=not a.sans_fichier, bavard=not a.json)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        t = doc["synthese"]["total"]
        print(f"\n{t['total']} scénario(s) : {t['reussis']} réussi(s), {t['echoues']} échoué(s), {t['sautes']} sauté(s).")
        for f in doc.get("fichiers", []):
            print(f"Rapport : {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
