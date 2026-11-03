"""Exécution d'un mini-scénario dans le bac à sable du moteur de simulations (simulations/simuler.py).

Réutilise `simuler.Bac` (base SQLite temporaire, LLM factice scriptable, horloge simulée, application
FastAPI de nexus-core lancée en local via TestClient). Rien n'est modifié dans nexus-core : seule la
source de veille est remplacée (patch) par les fiches du scénario. Renvoie les OBSERVATIONS
(réponses HTTP, missions, décisions, LEDGER, archive, fuites) que les oracles vérifient.
"""
import contextlib
import gzip
import json
import logging
import sqlite3
import sys
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import quote

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(RACINE / "simulations"))
sys.path.insert(0, str(ICI))

import simuler  # noqa: E402  (moteur réutilisé)
import generateur as gen  # noqa: E402

COMMENTAIRE_REVISION = "Merci de préciser la partie analyse."
TABLES_FTS_INTERNES = ("_data", "_idx", "_docsize", "_config")


def _env(sc: dict) -> dict:
    b = sc["briques"]
    env = {"COCKPIT_CODE_DECIDEUR": gen.charger_briques()["code_decideur"]}
    f = gen.variante("fonctionnement", b["fonctionnement"])
    if f.get("budget"):
        env.update(BUDGET_MONTHLY_EUR="5", ANTHROPIC_API_KEY="cle-simulation-anthropic")
    if b["evenement"] == "file-pleine":
        env["NEXUS_MAX_MISSIONS"] = "1"
    return env


class Joueur:
    def __init__(self, sc: dict):
        self.sc = sc
        self.b = sc["briques"]
        self.mat = gen.materialiser(sc)
        self.obs = {"graine": sc["graine"], "briques": dict(self.b), "http": [], "mission_id": None,
                    "missions_creees": [], "decision_cible": None, "decision_appels": [], "exceptions": [],
                    "actions": gen.actions(sc), "materiel": {k: v for k, v in self.mat.items() if k != "reponses"}}
        self.dernier_appel = None

    # --- HTTP ----------------------------------------------------------------------------
    def http(self, etape: str, methode: str, chemin: str, corps=None, entetes: str = "api") -> dict:
        spec = {"methode": methode, "chemin": chemin, "entetes": entetes}
        if corps is not None:
            spec["json"] = corps
        try:
            r = self.bac.a_http(spec)
        except Exception as e:  # une exception non rattrapée = erreur serveur
            r = {"status": 599, "json": None, "texte": f"{type(e).__name__}: {e}"}
            self.obs["exceptions"].append({"etape": etape, "trace": traceback.format_exc(limit=3)[-800:]})
        self.obs["http"].append({"etape": etape, "methode": methode, "chemin": chemin, "status": r["status"],
                                 "detail": (r["json"] or {}).get("detail") if isinstance(r["json"], dict) else None})
        return r

    # --- actions -------------------------------------------------------------------------
    def a_contenu(self, a: dict) -> None:
        c = self.mat["contenu"]
        projet = gen.variante("projet", self.b["projet"])["valeur"]
        if a["canal"] == "connaissance_api":
            pref = "/cockpit/api" if self.b["canal_creation"] == "cockpit" else "/api"
            self.http("contenu", "POST", f"{pref}/projets/{quote(projet)}/connaissances",
                      {"titre": c["titre"], "contenu": c["texte"]},
                      "cockpit" if self.b["canal_creation"] == "cockpit" else "api")
        elif a["canal"] == "connaissance_import":
            from app import memoire, projets
            code = projets.resoudre(projet)
            f = self.bac.tmp / "connaissances" / f"{code}.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"projet: {code}\n\n# {c['titre']}\n\n{c['texte']}\n", encoding="utf-8")
            try:
                self.obs["import"] = simuler.jsonable(memoire.importer())
            except Exception as e:
                self.obs["exceptions"].append({"etape": "import", "trace": f"{type(e).__name__}: {e}"})
        elif a["canal"] == "veille":
            from app import veille
            fiche = {"source_id": c["source_id"], "confiance": c["confiance"], "titre": c["titre"],
                     "resume": c["texte"], "date": "2026-11-01", "url": None}
            self.bac.patcher(veille, "fiches", lambda *x, **k: [dict(fiche)])

    def _corps_mission(self) -> dict:
        b, m = self.b, self.mat
        corps = {"titre": m["titre"], "consigne": m["consigne"],
                 "projet": gen.variante("projet", b["projet"])["valeur"]}
        srv = gen.variante("service", b["service"])["valeur"]
        if srv:
            corps["service"] = srv
        if m["montant_eur"]:
            corps["montant_eur"] = m["montant_eur"]
        if m["action"]:
            corps["action"] = m["action"]
        f = gen.variante("fonctionnement", b["fonctionnement"])
        if f.get("valeur"):
            corps["fonctionnement"] = f["valeur"]
            if "repli_f3" in f:
                corps["repli_f3"] = f["repli_f3"]
        return corps

    def a_creer_mission(self, a: dict) -> None:
        cockpit = a["canal"] == "cockpit"
        chemin = "/cockpit/api/missions" if cockpit else "/api/missions"
        ent = "cockpit" if cockpit else "api"
        corps = self._corps_mission()
        if a.get("file_pleine"):
            # Trois missions d'autres demandes arrivent en même temps (file bornée à 1 place).
            autres = [{"titre": f"Charge {i}", "consigne": f"Fais une synthèse courte n°{i}.",
                       "projet": "divers"} for i in range(3)]
            res = [None] * 4
            barriere = threading.Barrier(4)

            def tache(i, c):
                barriere.wait()
                res[i] = self.http("creation" if i == 0 else "charge", "POST", chemin, c, ent)

            fils = [threading.Thread(target=tache, args=(i, c)) for i, c in enumerate([corps] + autres)]
            for f in fils:
                f.start()
            for f in fils:
                f.join(60)
            r = res[0] or {"status": 599, "json": None}
            for x in res:
                if x and x["status"] == 202:
                    self.obs["missions_creees"].append(x["json"]["id"])
        else:
            r = self.http("creation", "POST", chemin, corps, ent)
            if r["status"] == 202:
                self.obs["missions_creees"].append(r["json"]["id"])
            if a.get("double"):
                r2 = self.http("creation_double_clic", "POST", chemin, corps, ent)
                if r2["status"] == 202:
                    self.obs["missions_creees"].append(r2["json"]["id"])
        if r["status"] == 202:
            self.obs["mission_id"] = r["json"]["id"]
        self._attendre()

    def _attendre(self) -> None:
        from app.file_missions import FILE
        FILE.attendre_vide(60)

    def a_redemarrer(self, a: dict) -> None:
        try:
            self.bac.a_redemarrer({})
        except Exception as e:
            self.obs["exceptions"].append({"etape": "redemarrage", "trace": f"{type(e).__name__}: {e}"})

    def _decision_en_attente(self) -> dict | None:
        mid = self.obs["mission_id"]
        if mid is None:
            return None
        from sqlalchemy import select
        from app.db import session_scope
        from app.models import Decision
        with session_scope() as s:
            d = s.execute(select(Decision).where(Decision.mission_id == mid, Decision.statut == "en_attente")
                          .order_by(Decision.id.desc())).scalars().first()
            return {"id": d.id, "risque": d.risque, "objet": d.objet} if d else None

    def a_decider(self, a: dict) -> None:
        d = self._decision_en_attente()
        self.obs["decision_cible"] = d
        if d is None:
            self.obs["decision_appels"].append({"voie": a["voie"], "choix": a["choix"], "sans_objet": True})
            return
        did, choix, voie = d["id"], a["choix"], a["voie"]
        code = {"bon": gen.charger_briques()["code_decideur"], "faux": "000000", "aucun": None, None: None}[a.get("code")]
        commentaire = COMMENTAIRE_REVISION if choix == "reviser" else None
        trace = {"voie": voie, "choix": choix, "code": a.get("code"), "decision": d, "statuts": []}
        if voie == "horloge":
            self.bac.a_horloge({"reculer_h": 25, "tables": ["Decision"]})
            from app import pipeline
            trace["expirees"] = pipeline.expirer_decisions()
        elif voie in ("api", "cockpit"):
            pref, ent = ("/api", "api") if voie == "api" else ("/cockpit/api", "cockpit")
            corps = {"commentaire": commentaire, "code": code}
            r = self.http(f"decision_{voie}", "POST", f"{pref}/decisions/{did}/{choix}", corps, ent)
            trace["statuts"].append(r["status"])
            self.dernier_appel = [("POST", f"{pref}/decisions/{did}/{choix}", corps, ent)]
        elif voie == "mobile":
            base = f"/cockpit/api/decideur/decisions/{did}"
            p = self.http("decision_mobile_preparer", "POST", f"{base}/preparer",
                          {"choix": choix, "commentaire": commentaire}, "cockpit")
            trace["statuts"].append(p["status"])
            trace["code_requis_annonce"] = (p["json"] or {}).get("code_requis") if isinstance(p["json"], dict) else None
            if p["status"] == 200:
                corps = {"choix": choix, "jeton": p["json"]["jeton"], "code": code, "commentaire": commentaire}
                r = self.http("decision_mobile_confirmer", "POST", f"{base}/confirmer", corps, "cockpit")
                trace["statuts"].append(r["status"])
                self.dernier_appel = [("POST", f"{base}/confirmer", corps, "cockpit")]
        self.obs["decision_appels"].append(trace)
        self._attendre()

    def a_double_clic(self, a: dict) -> None:
        if not self.dernier_appel:
            self.obs["double_clic"] = "sans_objet"
            return
        statuts = []
        for methode, chemin, corps, ent in self.dernier_appel:
            statuts.append(self.http("double_clic", methode, chemin, corps, ent)["status"])
        self.obs["double_clic"] = statuts
        self._attendre()

    def a_effacer_rgpd(self, a: dict) -> None:
        mid = self.obs["mission_id"]
        if mid is None:
            self.obs["effacement"] = "sans_objet"
            return
        r = self.http("effacement_rgpd", "POST", f"/cockpit/api/memoire/archive/effacer/{mid}",
                      {"motif": "droit à l'effacement"}, "cockpit")
        self.obs["effacement"] = {"status": r["status"]}

    # --- état final ----------------------------------------------------------------------
    def collecter(self) -> None:
        from sqlalchemy import select
        from app import archive, ledger
        from app.db import session_scope
        from app.models import Decision, ExportQG, Mission
        self._attendre()
        with session_scope() as s:
            ids = s.execute(select(Mission.id).order_by(Mission.id)).scalars().all()
            decisions = [simuler.jsonable(d) for d in s.execute(select(Decision).order_by(Decision.id)).scalars()]
            exports = [x.mission_id for x in s.execute(select(ExportQG)).scalars()]
        self.obs["missions"] = {mid: self.bac.instantane(mid) for mid in ids}
        self.obs["decisions"] = decisions
        self.obs["exports_qg"] = exports
        lg = self.bac.ledger_global()
        self.obs["ledger"] = {"verif": lg["verif"], "entrees": lg["entrees"]}
        try:
            self.obs["archive"] = archive.verifier()
        except Exception as e:
            self.obs["archive"] = {"valide": False, "motif": f"{type(e).__name__}: {e}"}
        self.obs["fuites"] = self.scanner([self.mat["secret"], self.mat["canari"], self.mat["marqueur"]])

    def scanner(self, litteraux: list[str]) -> dict:
        """Où chaque littéral apparaît : tables SQLite (colonne) et fichiers (data, archive)."""
        trouve = {x: [] for x in litteraux}
        db = self.bac.tmp / "nexus.db"
        with contextlib.closing(sqlite3.connect(db)) as c:
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tables:
                if t.endswith(TABLES_FTS_INTERNES) or t.startswith("sqlite_"):
                    continue
                try:
                    cur = c.execute(f'SELECT * FROM "{t}"')
                except sqlite3.Error:
                    continue
                cols = [d[0] for d in cur.description]
                for ligne in cur:
                    for col, v in zip(cols, ligne):
                        if v is None:
                            continue
                        sv = v.decode("utf-8", "ignore") if isinstance(v, bytes) else str(v)
                        for x in litteraux:
                            if x in sv:
                                lieu = f"{t}.{col}"
                                if t == "ledger":
                                    i = cols.index("action")
                                    lieu += f"[{ligne[i]}]"
                                if lieu not in trouve[x]:
                                    trouve[x].append(lieu)
        for dossier in ("data", "archive"):
            for f in sorted((self.bac.tmp / dossier).rglob("*")):
                if not f.is_file() or f.name.startswith("nexus.db"):
                    continue
                try:
                    brut = gzip.decompress(f.read_bytes()) if f.suffix == ".gz" else f.read_bytes()
                except OSError:
                    continue
                texte = brut.decode("utf-8", "ignore")
                for x in litteraux:
                    if x in texte:
                        trouve[x].append(f"fichier:{f.relative_to(self.bac.tmp)}")
        return trouve

    def jouer(self) -> dict:
        logging.disable(logging.CRITICAL)
        debut = time.perf_counter()
        bac_sc = {"id": f"IT-{self.sc['graine']}", "mode": "api_factice",
                  "preparation": {"env": _env(self.sc), "llm": self.mat["reponses"]}}
        try:
            with simuler.Bac(bac_sc) as bac:
                self.bac = bac
                for a in self.obs["actions"]:
                    getattr(self, f"a_{a['faire']}")(a)
                self.collecter()
        except Exception:
            self.obs["exceptions"].append({"etape": "execution", "trace": traceback.format_exc(limit=4)[-1500:]})
        self.obs["duree_ms"] = round((time.perf_counter() - debut) * 1000, 1)
        return self.obs


def jouer(sc: dict) -> dict:
    return Joueur(sc).jouer()
