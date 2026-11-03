"""Épreuves orchestrées. Chaque épreuve renvoie un dictionnaire normalisé :

{"nom", "titre", "statut": reussi|echoue|saute|erreur|delai, "motif", "duree_s", "commandes",
 "mesures": {...}, "defauts": [ {id, suite, gravite, titre, preuve, correction, responsable} ]}

Une épreuve dont le dossier ou le script manque est SAUTÉE avec la raison (agents encore au travail) ;
elle est intégrée automatiquement dès que le dossier apparaît (détection à chaque exécution).
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import commun as C

GRAVITES = ["critique", "majeure", "mineure", "info"]
CRIT_VERS_GRAVITE = {"critique": "critique", "haute": "majeure", "moyenne": "mineure", "basse": "info",
                     "bloquant": "critique", "majeur": "majeure", "majeure": "majeure", "mineur": "mineure",
                     "mineure": "mineure", "critique": "critique", "info": "info", "elevee": "majeure",
                     "élevée": "majeure", "faible": "mineure"}

RESPONSABLES = {
    "nexus-core": "Dév nexus-core (Mothership)", "nexus-bridge": "Dév nexus-bridge (passerelle MCP)",
    "automatisations": "Exploitation VPS (automatisations)", "banc-essai": "Qualité (banc d'essai)",
    "veille": "R&D-PARADOX (veille)", "securite-ia": "CYBER-FORTRESS (sécurité IA)",
    "simulations": "Dév nexus-core (Mothership)", "protocole": "Architecture (protocole NEXUS)",
    "compaction": "Dév nexus-core (compaction)", "iterations-100": "Dév nexus-core (Mothership)",
    "charge-200": "Exploitation VPS (performance)", "jumeau-numerique": "Architecture (dimensionnement)",
    "statiques": "Exploitation VPS (scripts et conteneurs)",
}
RESP_METHODE = {"securite_ia": "CYBER-FORTRESS (sécurité IA)", "cybersecurite": "CYBER-FORTRESS (sécurité IA)",
                "decideur": "Dév nexus-core (cockpit Décideur)", "continuite": "Exploitation VPS (continuité)"}

DOSSIERS_TESTS = ["nexus-core", "nexus-bridge", "automatisations", "banc-essai", "veille", "securite-ia",
                  "simulations", "protocole", "compaction", "iterations-100", "charge-200", "jumeau-numerique"]

CRITERES_PERTE = ("missions_perdues_max", "doublons_max", "ledger_valide", "archive_valide", "compteurs_exacts",
                  "integrite_sqlite", "perte", "donnees")


class Contexte:
    """Paramètres d'une exécution : bac à sable, profil de version, mode, dossiers, graine."""

    def __init__(self, bac: Path, sortie: Path, profil: dict, mode: str = "tout", graine: int = 2026,
                 echelle: float = 1.0):
        self.bac, self.sortie, self.profil, self.mode, self.graine = bac, sortie, profil, mode, graine
        self.echelle = echelle  # multiplicateur des délais max (tests de l'orchestrateur)
        self.journal = sortie / "journal.log"
        self.tmp = sortie / "_tmp"

    @property
    def rapide(self) -> bool:
        return self.mode == "rapide"

    def env(self, extra: dict | None = None, avec_profil: bool = True) -> dict:
        e = dict(self.profil.get("env", {})) if avec_profil else {}
        e.update(extra or {})
        return C.env_base(e, self.tmp / f"t{time.time_ns()}")

    def delai(self, s: float) -> float:
        return s * self.echelle


def _res(nom, titre, statut="reussi", motif=None, duree=0.0, mesures=None, defauts=None, commandes=None):
    return {"nom": nom, "titre": titre, "statut": statut, "motif": motif, "duree_s": round(duree, 1),
            "commandes": commandes or [], "mesures": mesures or {}, "defauts": defauts or []}


def defaut(suite, gravite, titre, preuve, correction, responsable, ident=None):
    g = CRIT_VERS_GRAVITE.get(str(gravite).lower(), "mineure")
    return {"id": ident or f"{suite}:{abs(hash(titre)) % 10**6:06d}", "suite": suite, "gravite": g,
            "titre": C.masquer(str(titre))[:300], "preuve": C.masquer(str(preuve))[:600],
            "correction": correction, "responsable": responsable}


def saute(nom, titre, motif):
    return _res(nom, titre, "saute", motif)


# =========================================================================== 1. tests unitaires

def _junit(chemin: Path) -> dict:
    d = {"total": 0, "reussis": 0, "echoues": 0, "erreurs": 0, "sautes": 0, "echecs": []}
    try:
        racine = ET.parse(chemin).getroot()
    except Exception:  # noqa: BLE001
        return d
    for cas in racine.iter("testcase"):
        d["total"] += 1
        nom = f"{cas.get('classname', '')}::{cas.get('name', '')}"
        e = cas.find("failure")
        er = cas.find("error")
        s = cas.find("skipped")
        if e is not None or er is not None:
            x = e if e is not None else er
            d["echoues" if e is not None else "erreurs"] += 1
            msg = (x.get("message") or (x.text or "")).strip().splitlines()
            d["echecs"].append({"test": nom, "type": "échec" if e is not None else "erreur",
                                "message": (msg[0] if msg else "")[:300]})
        elif s is not None:
            d["sautes"] += 1
        else:
            d["reussis"] += 1
    return d


def suite_tests(ctx: Contexte) -> dict:
    t0 = time.time()
    par, defauts, cmds = {}, [], []
    for dossier in DOSSIERS_TESTS:
        rep = ctx.bac / dossier
        if not rep.is_dir():
            par[dossier] = {"statut": "saute", "motif": "dossier absent (en construction)"}
            continue
        fichiers = [p for p in rep.rglob("test_*.py") if "__pycache__" not in p.parts] + \
                   [p for p in rep.rglob("*_test.py") if "__pycache__" not in p.parts]
        if not fichiers:
            par[dossier] = {"statut": "saute", "motif": "aucun fichier de test"}
            continue
        xml = ctx.tmp / f"junit_{dossier}.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"]
        cmds.append(f"(cd {dossier} && pytest -q)")
        r = C.executer(cmd, rep, ctx.env(), ctx.delai(900 if dossier == "nexus-core" else 600), ctx.journal)
        j = _junit(xml)
        if r["delai_depasse"]:
            st = "delai"
        elif r["rc"] == 5 or j["total"] == 0:
            st = "saute" if r["rc"] == 5 else "erreur"
        else:
            st = "reussi" if j["echoues"] + j["erreurs"] == 0 and r["rc"] == 0 else "echoue"
        par[dossier] = {"statut": st, "duree_s": r["duree_s"], **{k: j[k] for k in
                        ("total", "reussis", "echoues", "erreurs", "sautes")}, "echecs": j["echecs"][:30]}
        if st == "saute":
            par[dossier]["motif"] = "aucun test collecté"
        if st == "erreur":
            par[dossier]["motif"] = (r["erreurs"] or r["sortie"]).strip().splitlines()[-1:] or ["rc=%s" % r["rc"]]
        if st == "delai":
            defauts.append(defaut("tests", "majeure", f"Tests {dossier} : délai max dépassé",
                                  f"{r['duree_s']} s", "Réduire la durée des tests ou relever le délai.",
                                  RESPONSABLES.get(dossier, "?")))
        for e in j["echecs"]:
            grav = "critique" if dossier in ("securite-ia",) or re.search(r"secret|bouclier|cyber|gate|n3", e["test"], re.I) \
                else "majeure"
            defauts.append(defaut("tests", grav, f"Test en échec : {dossier} · {e['test'].split('::')[-1]}",
                                  f"{e['type']} — {e['message']}",
                                  "Corriger le code (ou le test s'il est devenu faux) puis relancer la suite.",
                                  RESPONSABLES.get(dossier, "?"), ident=f"tests:{dossier}:{e['test']}"))
    exe = [v for v in par.values() if v["statut"] not in ("saute",)]
    tot = {k: sum(v.get(k, 0) for v in exe) for k in ("total", "reussis", "echoues", "erreurs", "sautes")}
    sautes = [f"{d} ({v['motif']})" for d, v in par.items() if v["statut"] == "saute"]
    statut = "reussi" if exe and all(v["statut"] == "reussi" for v in exe) else ("saute" if not exe else "echoue")
    return _res("tests", "Tests unitaires (pytest)", statut, "; ".join(sautes) or None, time.time() - t0,
                {"par_dossier": par, **tot, "dossiers_sautes": sautes,
                 "taux_reussite": round(100 * tot["reussis"] / max(1, tot["total"] - tot["sautes"]), 2)},
                defauts, cmds)


# =========================================================================== 2. protocole

def suite_protocole(ctx: Contexte) -> dict:
    rep = ctx.bac / "protocole"
    if not (rep / "valider.py").exists():
        return saute("protocole", "Protocole NEXUS v1", "protocole/valider.py absent")
    t0, env, defauts, controles = time.time(), ctx.env(), [], []

    def ctrl(nom, args):
        r = C.executer([sys.executable, "valider.py", *args], rep, env, ctx.delai(300), ctx.journal)
        ok = r["rc"] == 0 and not r["delai_depasse"]
        derniere = (r["sortie"].strip().splitlines() or [""])[-1]
        controles.append({"controle": nom, "ok": ok, "resume": derniere[:200]})
        if not ok:
            ko = [l for l in r["sortie"].splitlines() if l.startswith(("KO", "ERREUR"))][:5]
            defauts.append(defaut("protocole", "majeure", f"Protocole NEXUS : {nom} non conforme",
                                  "; ".join(ko) or derniere or r["erreurs"][-300:],
                                  "Mettre le composant (ou le schéma) en conformité avec protocole/schemas.",
                                  RESPONSABLES["protocole"]))
        return r

    ctrl("schémas cohérents", ["--verifier-schemas"])
    if (ctx.bac / "nexus-core" / "agents").is_dir():
        ctrl("fiches agents", ["--agents", str(ctx.bac / "nexus-core" / "agents")])
    ex = rep / "exemples"
    groupes: dict[str, list[str]] = {}
    for f in sorted(ex.glob("*.json")) if ex.is_dir() else []:
        if f.name.startswith("_"):
            continue
        groupes.setdefault(f.name.split("__")[0].replace("@", "#"), []).append(str(f))
    nb_ex = nb_ok = 0
    for cible, fichiers in groupes.items():
        r = C.executer([sys.executable, "valider.py", cible, *fichiers], rep, env, ctx.delai(120), ctx.journal)
        oks = sum(1 for l in r["sortie"].splitlines() if l.startswith("OK "))
        nb_ex += len(fichiers)
        nb_ok += oks
        if oks < len(fichiers):
            defauts.append(defaut("protocole", "majeure", f"Exemples non conformes pour « {cible} »",
                                  f"{len(fichiers) - oks}/{len(fichiers)} KO",
                                  "Régénérer les exemples (produire_exemples.py) ou corriger le composant.",
                                  RESPONSABLES["protocole"]))
    controles.append({"controle": "exemples réels", "ok": nb_ok == nb_ex, "resume": f"{nb_ok}/{nb_ex} conformes"})
    ok = all(c["ok"] for c in controles)
    return _res("protocole", "Protocole NEXUS v1", "reussi" if ok else "echoue", None, time.time() - t0,
                {"controles": controles, "exemples": nb_ex, "exemples_conformes": nb_ok,
                 "taux_conformite": round(100 * sum(c["ok"] for c in controles) / len(controles), 1)},
                defauts, ["protocole/valider.py --verifier-schemas | --agents | <cible> exemples/*.json"])


# =========================================================================== 3. simulations

def suite_simulations(ctx: Contexte) -> dict:
    rep = ctx.bac / "simulations"
    if not (rep / "simuler.py").exists():
        return saute("simulations", "Scénarios fonctionnels", "simulations/simuler.py absent")
    t0 = time.time()
    r = C.executer([sys.executable, "simuler.py", "--json", "--sans-fichier"], rep, ctx.env(), ctx.delai(900),
                   ctx.journal)
    if r["delai_depasse"]:
        return _res("simulations", "Scénarios fonctionnels", "delai", "délai max dépassé", time.time() - t0)
    try:
        doc = json.loads(r["sortie"])
    except json.JSONDecodeError:
        return _res("simulations", "Scénarios fonctionnels", "erreur",
                    "sortie JSON illisible : " + (r["erreurs"].strip().splitlines() or ["?"])[-1][:200], time.time() - t0)
    tot = doc["synthese"]["total"]
    par = {m: {**v} for m, v in doc["synthese"]["par_methode"].items()}
    defauts = []
    for x in doc["resultats"]:
        if x["statut"] != "echoue":
            continue
        preuve = "; ".join(f"{e.get('libelle') or e.get('chemin')} : attendu {e.get('attendu')} · obtenu {e.get('obtenu')}"
                           for e in x.get("echecs", [])[:3]) or x.get("motif") or ""
        defauts.append(defaut("simulations", x.get("criticite", "moyenne"), f"{x['id']} — {x['titre']}", preuve,
                              "Aligner nexus-core sur la spécification SYFER du scénario (ne pas modifier le scénario).",
                              RESP_METHODE.get(x["methode"], RESPONSABLES["simulations"]), ident=f"simulations:{x['id']}"))
    taux = round(100 * tot["reussis"] / max(1, tot["executes"]), 2)
    statut = "reussi" if tot["echoues"] == 0 and tot["executes"] > 0 else "echoue"
    return _res("simulations", "Scénarios fonctionnels", statut,
                f"{tot['sautes']} scénario(s) sauté(s)" if tot["sautes"] else None, time.time() - t0,
                {**tot, "taux_reussite": taux, "par_methode": par,
                 "echoues_ids": [x["id"] for x in doc["resultats"] if x["statut"] == "echoue"]},
                defauts, ["simulations/simuler.py --json --sans-fichier"])


# =========================================================================== 4. itérations

def _parcourir(obj, chemin=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{chemin}.{k}" if chemin else str(k), k, v
            yield from _parcourir(v, f"{chemin}.{k}" if chemin else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5000]):
            yield from _parcourir(v, f"{chemin}[{i}]")


def _premier(obj, cles):
    for _, k, v in _parcourir(obj):
        if str(k).lower() in cles and isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return None


def extraire_defauts_generiques(obj) -> list[dict]:
    """Défauts déclarés par une épreuve tierce : toute liste de dicts sous une clé contenant « defaut »."""
    out, vus = [], set()
    for _, k, v in _parcourir(obj):
        if "defaut" in str(k).lower() and isinstance(v, list):
            for d in v:
                if isinstance(d, dict):
                    cle = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)[:400]
                    if cle not in vus:
                        vus.add(cle)
                        out.append(d)
    return out


def _gravite(d: dict) -> str:
    for k in ("gravite", "gravité", "severite", "sévérité", "criticite", "criticité", "niveau"):
        if k in d:
            return CRIT_VERS_GRAVITE.get(str(d[k]).lower(), "mineure")
    return "mineure"


def _ouvert(d: dict) -> bool:
    st = str(d.get("statut", d.get("etat", "ouvert"))).lower()
    return not any(x in st for x in ("corrig", "ferm", "resolu", "résolu", "clos"))


def _defauts_fichiers(rep: Path) -> list[dict]:
    """Fiches de défauts (JSON/YAML/Markdown) d'un dossier defauts/."""
    out = []
    if not rep.is_dir():
        return out
    for f in sorted(rep.rglob("*")):
        if not f.is_file():
            continue
        try:
            t = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if f.suffix == ".json":
            d = C.lire_json(f)
            ds = d if isinstance(d, list) else extraire_defauts_generiques(d) or ([d] if isinstance(d, dict) else [])
        elif f.suffix in (".yaml", ".yml"):
            try:
                import yaml
                d = yaml.safe_load(t)
            except Exception:  # noqa: BLE001
                d = None
            ds = d if isinstance(d, list) else (extraire_defauts_generiques(d) or ([d] if isinstance(d, dict) else []))
        elif f.suffix == ".md":
            g = re.search(r"(?im)^\W*(?:gravit[ée]|s[ée]v[ée]rit[ée]|criticit[ée])\W*[:=]\s*\**\s*([\wéè]+)", t)
            s = re.search(r"(?im)^\W*(?:statut|[ée]tat)\W*[:=]\s*\**\s*([\wéè ]+)", t)
            titre = (re.search(r"(?m)^#\s+(.+)$", t) or re.search(r"(.+)", t)).group(1)
            ds = [{"titre": titre.strip(), "gravite": g.group(1) if g else "mineure",
                   "statut": s.group(1).strip() if s else "ouvert", "preuve": f.name}]
        else:
            continue
        for d in ds:
            if isinstance(d, dict):
                d.setdefault("_fichier", f.name)
                out.append(d)
    return out


def suite_iterations(ctx: Contexte) -> dict:
    rep = ctx.bac / "iterations-100"
    titre = "100 itérations de mini-scénarios"
    script = next((rep / n for n in ("iterer.py",) if (rep / n).exists()), None)
    if not rep.is_dir():
        return saute("iterations", titre, "dossier iterations-100/ absent")
    if script is None:
        return saute("iterations", titre, "iterations-100/iterer.py absent (en construction)")
    t0, env = time.time(), ctx.env()
    aide = C.options_aide(script, rep, env)
    nb = 20 if ctx.rapide else 100
    args = []
    o = C.choisir_option(aide, ["--iterations", "--nombre", "--nb", "-n", "--n"])
    if o:
        args += [o, str(nb)]
    o = C.choisir_option(aide, ["--graine", "--seed"])
    if o:
        args += [o, str(ctx.graine)]
    if ctx.rapide:
        o = C.choisir_option(aide, ["--rapide", "--court"])
        if o:
            args.append(o)
    sortie_json = None
    o = C.choisir_option(aide, ["--sortie", "--resultats", "--dossier-resultats"])
    dossier_res = ctx.tmp / "iterations"
    if o:
        dossier_res.mkdir(parents=True, exist_ok=True)
        args += [o, str(dossier_res)]
    if C.choisir_option(aide, ["--json"]):
        args.append("--json")
        sortie_json = True
    debut = time.time()
    r = C.executer([sys.executable, script.name, *args], rep, env, ctx.delai(600 if ctx.rapide else 1500), ctx.journal)
    cmd = f"iterations-100/{script.name} {' '.join(args)}"
    if r["delai_depasse"]:
        return _res("iterations", titre, "delai", "délai max dépassé", time.time() - t0, commandes=[cmd])
    doc = None
    if sortie_json:
        try:
            doc = json.loads(r["sortie"])
        except json.JSONDecodeError:
            doc = None
    if doc is None:
        f = C.plus_recent_json(dossier_res, debut) or C.plus_recent_json(rep / "resultats", debut)
        doc = C.lire_json(f) if f else None
    if doc is None:
        motif = (r["erreurs"].strip().splitlines() or r["sortie"].strip().splitlines() or [f"rc={r['rc']}"])[-1]
        return _res("iterations", titre, "erreur", f"aucun résultat JSON lisible ({motif[:160]})", time.time() - t0,
                    commandes=[cmd])
    total = _premier(doc, {"total", "iterations", "nb_iterations", "scenarios"})
    reussis = _premier(doc, {"reussis", "reussies", "succes", "ok", "conformes"})
    echoues = _premier(doc, {"echoues", "echouees", "echecs", "ko", "non_conformes"})
    if reussis is None and total is not None and echoues is not None:
        reussis = total - echoues
    bruts = extraire_defauts_generiques(doc) + _defauts_fichiers(rep / "defauts")
    defauts, crit_ouverts = [], 0
    for d in bruts:
        g = _gravite(d)
        ouvert = _ouvert(d)
        if g == "critique" and ouvert:
            crit_ouverts += 1
        if ouvert:
            defauts.append(defaut("iterations", g, d.get("titre") or d.get("description") or d.get("id") or "défaut",
                                  d.get("preuve") or d.get("reproduction") or d.get("graine") or d.get("_fichier", ""),
                                  d.get("correction") or d.get("correction_suggeree") or "Corriger puis rejouer la graine.",
                                  d.get("responsable") or RESPONSABLES["iterations-100"],
                                  ident=f"iterations:{d.get('id') or d.get('_fichier') or len(defauts)}"))
    taux = round(100 * reussis / total, 2) if (total and reussis is not None) else None
    statut = "reussi" if r["rc"] == 0 and crit_ouverts == 0 and (echoues in (None, 0)) else "echoue"
    return _res("iterations", titre, statut, None, time.time() - t0,
                {"iterations": total, "reussis": reussis, "echoues": echoues, "taux_reussite": taux,
                 "defauts_total": len(bruts), "defauts_ouverts": len(defauts), "critiques_ouverts": crit_ouverts,
                 "rc": r["rc"], "options": args}, defauts, [cmd])


# =========================================================================== 5. attaque

def suite_attaque(ctx: Contexte) -> dict:
    rep = ctx.bac / "securite-ia"
    if not (rep / "attaque_simulee.py").exists():
        return saute("attaque", "Attaque simulée hors-ligne", "securite-ia/attaque_simulee.py absent")
    t0 = time.time()
    sortie = ctx.tmp / "attaque"
    sortie.mkdir(parents=True, exist_ok=True)
    r = C.executer([sys.executable, "attaque_simulee.py", "--mode", "hors-ligne", "--sortie", str(sortie)], rep,
                   ctx.env(), ctx.delai(300), ctx.journal)
    f = C.plus_recent_json(sortie, t0)
    doc = C.lire_json(f) if f else None
    if r["delai_depasse"] or not doc:
        return _res("attaque", "Attaque simulée hors-ligne", "delai" if r["delai_depasse"] else "erreur",
                    "aucun résultat" if not doc else "délai max dépassé", time.time() - t0)
    h = doc.get("hors_ligne", doc)
    s = h["synthese"]
    defauts = []
    for e in s.get("echecs", []):
        e = e if isinstance(e, dict) else {"id": e}
        defauts.append(defaut("attaque", "critique", f"Attaque non bloquée : {e.get('id')} ({e.get('categorie', '?')})",
                              f"attendu {e.get('attendu')} · obtenu {e.get('obtenu')}",
                              "Renforcer le bouclier (nexus-core/app/bouclier.py) pour cette famille d'attaque.",
                              RESPONSABLES["securite-ia"], ident=f"attaque:{e.get('id')}"))
    fp_bloquants = 0
    for e in s.get("faux_positifs_detail", []):
        e = e if isinstance(e, dict) else {"id": e}
        bloquant = str(e.get("obtenu", "bloque")).lower() in ("bloque", "refus", "refuse", "rejet")
        fp_bloquants += bloquant
        defauts.append(defaut("attaque", "majeure" if bloquant else "mineure",
                              f"Faux positif{' bloquant' if bloquant else ''} : {e.get('id')}",
                              f"texte légitime classé « {e.get('obtenu')} »",
                              "Ajouter un contexte « méta » / affiner le motif pour ne pas bloquer un texte légitime.",
                              RESPONSABLES["securite-ia"], ident=f"attaque:fp:{e.get('id')}"))
    taux = float(s.get("taux_blocage_pct", 0))
    ok = taux >= 95 and fp_bloquants == 0
    return _res("attaque", "Attaque simulée hors-ligne", "reussi" if ok else "echoue", None, time.time() - t0,
                {"attaques": s.get("attaques"), "bloquees": s.get("attaques_conformes"), "taux_blocage_pct": taux,
                 "rejet_strict_pct": s.get("rejet_strict_pct"), "legitimes": s.get("legitimes"),
                 "faux_positifs": s.get("faux_positifs"), "faux_positifs_bloquants": fp_bloquants,
                 "taux_faux_positifs_pct": s.get("taux_faux_positifs_pct"), "par_categorie": s.get("par_categorie")},
                defauts, ["securite-ia/attaque_simulee.py --mode hors-ligne"])


# =========================================================================== 6. banc d'essai

def _port_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def suite_banc(ctx: Contexte) -> dict:
    rep = ctx.bac / "banc-essai"
    titre = "Banc d'essai qualité (LLM factice local)"
    if not (rep / "lancer.sh").exists():
        return saute("banc", titre, "banc-essai/lancer.sh absent")
    for outil in ("jq", "curl", "bash"):
        if not shutil.which(outil):
            return saute("banc", titre, f"outil « {outil} » introuvable")
    core = ctx.bac / "nexus-core"
    if not (core / "app" / "main.py").exists():
        return saute("banc", titre, "nexus-core absent")
    t0 = time.time()
    donnees = ctx.tmp / "banc_donnees"
    donnees.mkdir(parents=True, exist_ok=True)
    cle = "banc-local-" + os.urandom(12).hex()
    port = _port_libre()
    env_core = ctx.env({"NEXUS_DATA_DIR": donnees, "NEXUS_API_KEY": cle, "NEXUS_ARCHIVE_DIR": donnees / "archive",
                        "NEXUS_VEILLE_DIR": donnees / "veille", "NEXUS_COMPACTION_DIR": donnees / "compaction",
                        "NEXUS_BANC_DIR": donnees / "banc", "NEXUS_CONNAISSANCES_DIR": donnees / "connaissances",
                        "COCKPIT_CODE_DECIDEUR": "246810", "NEXUS_HOST": "127.0.0.1"})
    log = open(ctx.tmp / "banc_core.log", "ab")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
                             "--log-level", "warning"], cwd=str(core), env=env_core, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        import urllib.request
        pret = False
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sante", timeout=1) as rr:
                    pret = rr.status == 200
                    sante = json.loads(rr.read())
                    break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
        if not pret:
            return _res("banc", titre, "erreur", "nexus-core local ne démarre pas (voir journal)", time.time() - t0)
        f_niv = ctx.profil.get("banc_fonctionnement", "F2")
        res = ctx.tmp / "banc_resultats.json"
        env_banc = ctx.env({"NEXUS_URL": f"http://127.0.0.1:{port}", "NEXUS_API_KEY": cle, "FONCTIONNEMENT": f_niv,
                            "SELECTION": "rapide" if ctx.rapide else "", "INTERVALLE_S": "1", "DELAI_MAX_S": "180",
                            "ENV_FILE": str(ctx.tmp / "absent.env"), "FICHIER_RESULTATS": str(res)},
                           avec_profil=False)
        r = C.executer(["bash", "lancer.sh"], rep, env_banc, ctx.delai(600 if ctx.rapide else 1500), ctx.journal)
    finally:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            pass
        proc.wait()
        log.close()
    doc = C.lire_json(res)
    if not doc or not doc.get("resultats"):
        return _res("banc", titre, "delai" if r["delai_depasse"] else "erreur",
                    (r["erreurs"].strip().splitlines() or ["aucun résultat"])[-1][:200], time.time() - t0)
    missions = {m["id"]: m for m in (C.lire_json(rep / "missions.json", {}) or {}).get("missions", [])}
    notes_l, notes_s, pieges, defauts = [], [], [], []
    for x in doc["resultats"]:
        n = x.get("notation") or {}
        if "note_livrable" in n:
            notes_l.append(n["note_livrable"])
            notes_s.append(n["note_systeme"])
        sec = n.get("securite")
        if sec:
            pieges.append(sec.get("resultat") == "reussi")
            if sec.get("resultat") != "reussi":
                defauts.append(defaut("banc", "critique", f"Piège de sécurité raté : {x['id']} ({sec.get('type')})",
                                      sec.get("raison") or x.get("statut"),
                                      "Vérifier GATE/bouclier pour ce type de piège.", RESPONSABLES["securite-ia"],
                                      ident=f"banc:piege:{x['id']}"))
        if n.get("note_systeme", 100) < 100:
            m = missions.get(x["id"], {})
            defauts.append(defaut("banc", "mineure", f"Aiguillage imparfait : {x['id']} — {m.get('titre', '')[:60]}",
                                  f"routé {x.get('service')} {x.get('niveau')} (statut {x.get('statut')}) · attendu "
                                  f"{m.get('service_attendu')} {m.get('niveau_decision_attendu')} · note système {n.get('note_systeme')}",
                                  "Ajuster les règles PRIME/GATE (mots-clés, plancher de niveau).",
                                  RESPONSABLES["nexus-core"], ident=f"banc:routage:{x['id']}"))
    moy = lambda v: round(sum(v) / len(v), 1) if v else None  # noqa: E731
    p_pct = round(100 * sum(pieges) / len(pieges), 1) if pieges else None
    return _res("banc", titre, "reussi" if r["rc"] == 0 and (p_pct in (None, 100.0)) else "echoue",
                "LLM factice : la note livrable ne mesure PAS la qualité réelle (banc réel sur le VPS)",
                time.time() - t0,
                {"missions": len(doc["resultats"]), "fonctionnement": f_niv, "llm": (sante.get("llm") or {}).get("fournisseur"),
                 "note_livrable_moy": moy(notes_l), "note_systeme_moy": moy(notes_s), "pieges_reussis_pct": p_pct,
                 "statuts": {s: sum(1 for x in doc["resultats"] if x.get("statut") == s)
                             for s in sorted({x.get("statut") for x in doc["resultats"]})}},
                defauts, [f"nexus-core local (LLM factice) + FONCTIONNEMENT={f_niv} banc-essai/lancer.sh"])


# =========================================================================== 7. charge 200 %

def suite_charge(ctx: Contexte, ids: str | None = None) -> dict:
    rep = ctx.bac / "charge-200"
    titre = "Campagne de charge à 200 %"
    if not (rep / "charge.py").exists():
        return saute("charge", titre, "charge-200/charge.py absent (en construction)")
    t0, env = time.time(), ctx.env()
    aide = C.options_aide(rep / "charge.py", rep, env)
    args = []
    if C.choisir_option(aide, ["--rapide"]):
        args.append("--rapide")
    if C.choisir_option(aide, ["--sans-rapport"]):
        args.append("--sans-rapport")
    if ids is None:
        ids = "S01,S04" if ctx.rapide else None
    if ids and C.choisir_option(aide, ["--ids"]):
        args += ["--ids", ids]
    r = C.executer([sys.executable, "charge.py", *args], rep, env, ctx.delai(600 if ctx.rapide else 1800), ctx.journal)
    cmd = "charge-200/charge.py " + " ".join(args)
    f = C.plus_recent_json(rep / "resultats", t0)
    doc = C.lire_json(f) if f else None
    if not doc or "resultats" not in doc:
        return _res("charge", titre, "delai" if r["delai_depasse"] else "erreur",
                    (r["erreurs"].strip().splitlines() or r["sortie"].strip().splitlines() or ["aucun résultat"])[-1][:200],
                    time.time() - t0, commandes=[cmd])
    defauts, pertes, crit_ok, crit_tot, fam = [], [], 0, 0, {}
    executes = [x for x in doc["resultats"] if not x.get("saute")]
    for x in executes:
        fa = x.get("famille", "?")
        fam.setdefault(fa, {"total": 0, "reussis": 0})
        fam[fa]["total"] += 1
        fam[fa]["reussis"] += bool(x.get("reussi"))
        if x.get("erreur"):
            defauts.append(defaut("charge", "majeure", f"Scénario de charge en erreur : {x['id']} {x.get('nom', '')}",
                                  x["erreur"], "Analyser la trace et corriger l'outil ou nexus-core.",
                                  RESPONSABLES["charge-200"], ident=f"charge:{x['id']}:erreur"))
        for c in x.get("criteres", []):
            if c.get("ok") is None:
                continue
            crit_tot += 1
            crit_ok += bool(c["ok"])
            if c["ok"] is False:
                perte = any(p in c["critere"] for p in CRITERES_PERTE)
                if perte:
                    pertes.append(f"{x['id']}:{c['critere']}")
                defauts.append(defaut("charge", "critique" if perte else "majeure",
                                      f"Charge {x['id']} : critère « {c['critere']} » non tenu",
                                      f"mesuré {c.get('mesure', c.get('valeur'))} · seuil {c.get('seuil', c.get('attendu'))}",
                                      "Intégrité des données d'abord (transactions, verrous)." if perte else
                                      "Optimiser le chemin chaud (pool de fils, file, index SQLite) ou ajuster le seuil documenté.",
                                      RESPONSABLES["charge-200"], ident=f"charge:{x['id']}:{c['critere']}"))
    reussis = sum(bool(x.get("reussi")) for x in executes)
    integ = [c["ok"] for x in executes for c in x.get("criteres", [])
             if c.get("ok") is not None and c["critere"] in ("ledger_valide", "archive_valide", "integrite_sqlite",
                                                              "compteurs_exacts")]
    return _res("charge", titre, "reussi" if executes and reussis == len(executes) else "echoue",
                "mode court (--rapide : durées ÷ 3)" if "--rapide" in args else None, time.time() - t0,
                {"scenarios": len(executes), "reussis": reussis, "sautes": len(doc["resultats"]) - len(executes),
                 "criteres_ok": crit_ok, "criteres_total": crit_tot, "pertes_donnees": pertes,
                 "par_famille": fam, "rapide": doc.get("rapide"), "duree_campagne_s": doc.get("duree_totale_s"),
                 "taux_reussite": round(100 * reussis / max(1, len(executes)), 1),
                 "integrite_ok": sum(integ), "integrite_total": len(integ),
                 "taux_criteres": round(100 * crit_ok / max(1, crit_tot), 1)},
                defauts, [cmd])


# =========================================================================== 8. jumeau numérique

def _module_jumeau(rep: Path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(f"jumeau_bac_{abs(hash(str(rep)))}", rep / "jumeau.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def jumeau_version(rep: Path, profil: dict, tirages: int, graine: int, jours: int = 30) -> dict:
    """Jumeau numérique appliqué au profil de version : nominal + panne du cloud 10 j + Décideur absent 3 j."""
    J = _module_jumeau(rep)
    hyp = J.charger_hypotheses(str(rep / "hypotheses.json"))
    base = J.charger_scenarios(str(rep / "scenarios.yaml"))[0]
    sc = {k: v for k, v in base.items() if k not in ("id", "nom", "description")}
    sc.update({k: v for k, v in profil.get("jumeau", {}).items() if k != "surcharges"})
    sc["surcharges"] = dict(profil.get("jumeau", {}).get("surcharges") or {})
    sc["id"], sc["nom"] = f"V{profil.get('code', '?')}", profil.get("nom", "?")
    out = {}
    for nom, delta in (("nominal", {}), ("panne_cloud", {"panne_cloud_debut_j": 5, "panne_cloud_duree_j": 10}),
                       ("absence_decideur", {"absence_debut_j": 9, "absence_duree_j": 3})):
        s = dict(sc, **delta)
        r = J.resumer(J.monte_carlo(s, hyp, tirages, graine, jours))
        out[nom] = {k: (r[k]["moy"] if isinstance(r.get(k), dict) and "moy" in r[k] else r.get(k)) for k in
                    ("livrees_jour", "ratio_livraison", "attente_p90_s", "cout_total_eur", "cout_api_eur", "qualite",
                     "score", "n3_jour", "decisions_expirees", "delai_decision_p50_h", "echecs_delai", "redemarrages",
                     "ram_pic_go", "ram_ok_part", "part_au_dessus_plafond")}
        out[nom]["delai_p90_f2_s"] = (r["delai_p90"].get("F2") or {}).get("moy")
        out[nom]["delai_p90_f3_s"] = (r["delai_p90"].get("F3") or {}).get("moy")
    out["tirages"], out["graine"], out["jours"] = tirages, graine, jours
    return out


def suite_jumeau(ctx: Contexte, lancer_global: bool = True) -> dict:
    rep = ctx.bac / "jumeau-numerique"
    titre = "Jumeau numérique"
    if not (rep / "jumeau.py").exists():
        return saute("jumeau", titre, "jumeau-numerique/jumeau.py absent (en construction)")
    t0, mesures, defauts, cmds = time.time(), {}, [], []
    tirages = 10 if ctx.rapide else 40
    if lancer_global and (rep / "lancer.py").exists():
        args = ["--tirages", str(10 if ctx.rapide else 20), "--sensibilite", "0", "--graine", str(ctx.graine)]
        r = C.executer([sys.executable, "lancer.py", *args], rep, ctx.env(), ctx.delai(600 if ctx.rapide else 1200),
                       ctx.journal)
        cmds.append("jumeau-numerique/lancer.py " + " ".join(args))
        fj = rep / "resultats" / "resultats.json"
        doc = C.lire_json(fj) if fj.exists() and fj.stat().st_mtime >= t0 - 1 else None
        if doc and not r["delai_depasse"]:
            mesures["catalogue"] = {"recommandation": doc.get("recommandation"), "classement": doc.get("classement", [])[:5],
                                    "scenarios": len(doc.get("scenarios", {}))}
        else:
            mesures["catalogue"] = {"erreur": "lancer.py " + ("délai dépassé" if r["delai_depasse"] else f"rc={r['rc']}")}
    try:
        v = jumeau_version(rep, ctx.profil, tirages, ctx.graine)
    except Exception as e:  # noqa: BLE001
        return _res("jumeau", titre, "erreur", f"{type(e).__name__}: {e}"[:200], time.time() - t0, mesures,
                    commandes=cmds)
    mesures["version"] = v
    cmds.append(f"jumeau.monte_carlo(profil {ctx.profil.get('code')}, {tirages} tirages, graine {ctx.graine})")
    n = v["nominal"]
    if (n.get("ram_ok_part") or 0) < 1:
        defauts.append(defaut("jumeau", "majeure", f"RAM insuffisante pour la version {ctx.profil.get('code')}",
                              f"RAM OK dans {100 * (n.get('ram_ok_part') or 0):.0f} % des tirages (pic {n.get('ram_pic_go', 0):.1f} Go)",
                              "Réduire les modèles chargés ou passer à l'offre supérieure.", RESPONSABLES["jumeau-numerique"]))
    if (n.get("ratio_livraison") or 0) < 0.8:
        defauts.append(defaut("jumeau", "majeure", f"Débit insuffisant (version {ctx.profil.get('code')})",
                              f"{100 * n['ratio_livraison']:.0f} % des missions livrées dans le mois simulé",
                              "Activer les optimisations V2, augmenter NEXUS_MAX_MISSIONS ou la machine.",
                              RESPONSABLES["jumeau-numerique"]))
    if (n.get("n3_jour") or 0) > 8:
        defauts.append(defaut("jumeau", "majeure", "Charge Décideur trop élevée",
                              f"{n['n3_jour']:.1f} décisions N3 par jour", "Relever l'autonomie (préclassement GATE).",
                              RESPONSABLES["nexus-core"]))
    if (n.get("decisions_expirees") or 0) > 5:
        defauts.append(defaut("jumeau", "mineure", "Décisions N3 expirées",
                              f"{n['decisions_expirees']:.1f} décisions expirées par mois simulé",
                              "Rappels ntfy plus tôt ou 3e session de décision.", RESPONSABLES["nexus-core"]))
    return _res("jumeau", titre, "reussi", None, time.time() - t0, mesures, defauts, cmds)


# =========================================================================== 9. compaction

def suite_compaction(ctx: Contexte) -> dict:
    rep = ctx.bac / "compaction"
    titre = "Compaction (mesure)"
    module = (ctx.bac / "nexus-core" / "app" / "compaction.py").exists()
    if not rep.is_dir():
        return saute("compaction", titre, "dossier compaction/ absent (en construction)"
                     + (" ; nexus-core/app/compaction.py présent" if module else ""))
    script = rep / "mesure.py"
    if not script.exists():
        return saute("compaction", titre, "compaction/mesure.py absent (en construction)")
    t0, env = time.time(), ctx.env()
    aide = C.options_aide(script, rep, env)
    args = []
    o = C.choisir_option(aide, ["--rapide", "--court"])
    if o:
        args.append(o)
    o = C.choisir_option(aide, ["--graine", "--seed"])
    if o:
        args += [o, str(ctx.graine)]
    dossier_res = ctx.tmp / "compaction"
    o = C.choisir_option(aide, ["--sortie", "--resultats"])
    if o:
        dossier_res.mkdir(parents=True, exist_ok=True)
        args += [o, str(dossier_res)]
    json_stdout = bool(C.choisir_option(aide, ["--json"]))
    if json_stdout:
        args.append("--json")
    r = C.executer([sys.executable, "mesure.py", *args], rep, env, ctx.delai(600 if ctx.rapide else 1200), ctx.journal)
    cmd = "compaction/mesure.py " + " ".join(args)
    doc = None
    if json_stdout:
        try:
            doc = json.loads(r["sortie"])
        except json.JSONDecodeError:
            doc = None
    if doc is None:
        f = C.plus_recent_json(dossier_res, t0) or C.plus_recent_json(rep / "resultats", t0)
        doc = C.lire_json(f) if f else None
    if r["delai_depasse"]:
        return _res("compaction", titre, "delai", "délai max dépassé", time.time() - t0, commandes=[cmd])
    mes = {"rc": r["rc"], "options": args, "module_nexus_core": module}
    if isinstance(doc, dict):
        mes["indicateurs"] = {k: v for _, k, v in _parcourir(doc)
                              if isinstance(v, (int, float)) and not isinstance(v, bool) and
                              re.search(r"gain|ratio|taux|perte|octets|economie|duree|integr", str(k), re.I)}
        mes["indicateurs"] = dict(list(mes["indicateurs"].items())[:30])
    defauts = []
    pertes = [k for k, v in (mes.get("indicateurs") or {}).items() if "perte" in k and v]
    if pertes:
        defauts.append(defaut("compaction", "critique", "Compaction : perte d'information mesurée", ", ".join(pertes),
                              "Revoir la compaction (aucune donnée ne doit disparaître sans archive).",
                              RESPONSABLES["compaction"]))
    if r["rc"] != 0:
        defauts.append(defaut("compaction", "majeure", "Mesure de compaction en échec", f"rc={r['rc']} " +
                              (r["erreurs"].strip().splitlines() or [""])[-1][:200], "Analyser le journal.",
                              RESPONSABLES["compaction"]))
    return _res("compaction", titre, "reussi" if r["rc"] == 0 and not pertes else "echoue", None,
                time.time() - t0, mes, defauts, [cmd])


# =========================================================================== 10. contrôles statiques

def correspond(rel: str, motifs: list[str]) -> bool:
    nom = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel, m) or fnmatch.fnmatch(nom, m) for m in motifs)


def rechercher_secrets(racine: Path, conf: dict | None = None) -> dict:
    """Recherche des secrets dans le dépôt avec les motifs du filtre anti-secret de nexus-core."""
    conf = conf or C.lire_json(C.CONFIG / "secrets_autorises.json", {}) or {}
    motifs, aff, gab, origine = C.motifs_secrets(racine)
    marqueurs = [m.lower() for m in conf.get("marqueurs_factices", [])]
    trouves, fichiers = [], 0
    for p in sorted(racine.rglob("*")):
        rel = p.relative_to(racine).as_posix()
        if not p.is_file() or any(part in (".git", "__pycache__", ".pytest_cache") for part in p.parts):
            continue
        if rel.startswith("syfer-test-system/resultats/") or p.stat().st_size > conf.get("taille_max_octets", 3_000_000):
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        fichiers += 1
        coups = [(lib, x.group(0)) for lib, m in motifs for x in m.finditer(t)]
        if aff and correspond(rel, conf.get("affectation_fichiers", [])):
            for x in aff.finditer(t):
                v = x.group(3)
                if (gab and gab.search(v)) or not (re.search(r"\d", v) and re.search(r"[A-Za-z]", v)) or re.search(r"[({$.]", v):
                    continue
                coups.append(("mot de passe en clair", x.group(0)))
        for lib, val in coups:
            factice = correspond(rel, conf.get("chemins_factices", [])) or any(m in val.lower() for m in marqueurs)
            trouves.append({"fichier": rel, "type": lib, "classe": "factice" if factice else "suspect",
                            "extrait": val[:6] + "…<masqué>"})
    return {"origine_motifs": origine, "fichiers_analyses": fichiers,
            "suspects": [t for t in trouves if t["classe"] == "suspect"],
            "factices": len([t for t in trouves if t["classe"] == "factice"])}


def suite_statiques(ctx: Contexte) -> dict:
    t0, controles, defauts = time.time(), {}, []
    env = ctx.env(avec_profil=False)
    # bash -n
    scripts = sorted(p for p in ctx.bac.rglob("*.sh") if "resultats" not in p.parts)
    ko = []
    for s in scripts:
        r = C.executer(["bash", "-n", str(s)], ctx.bac, env, 30)
        if r["rc"] != 0:
            ko.append((s.relative_to(ctx.bac).as_posix(), (r["erreurs"].strip().splitlines() or [""])[0]))
    controles["bash_n"] = {"total": len(scripts), "ok": len(scripts) - len(ko), "statut": "reussi" if not ko else "echoue"}
    for f, e in ko:
        defauts.append(defaut("statiques", "majeure", f"Erreur de syntaxe bash : {f}", e, "Corriger le script.",
                              RESPONSABLES["statiques"]))
    # shellcheck
    if shutil.which("shellcheck"):
        r = C.executer(["shellcheck", "-S", "error", "-f", "gcc", *map(str, scripts)], ctx.bac, env, ctx.delai(300))
        lignes = [l for l in r["sortie"].splitlines() if ": error:" in l]
        controles["shellcheck"] = {"statut": "reussi" if not lignes else "echoue", "erreurs": len(lignes)}
        for l in lignes[:20]:
            defauts.append(defaut("statiques", "mineure", "shellcheck : " + l.split(": error:")[-1].strip()[:120],
                                  l.replace(str(ctx.bac) + "/", "")[:300], "Appliquer la recommandation shellcheck.",
                                  RESPONSABLES["statiques"]))
    else:
        controles["shellcheck"] = {"statut": "saute", "motif": "shellcheck non installé"}
    # YAML / JSON
    try:
        import yaml
    except ImportError:
        yaml = None
    y_ko, y_tot, j_ko, j_tot = [], 0, [], 0
    for p in sorted(ctx.bac.rglob("*")):
        if not p.is_file() or "resultats" in p.parts:
            continue
        rel = p.relative_to(ctx.bac).as_posix()
        if p.suffix in (".yml", ".yaml") and yaml:
            y_tot += 1
            try:
                list(yaml.safe_load_all(p.read_text(encoding="utf-8")))
            except Exception as e:  # noqa: BLE001
                y_ko.append((rel, str(e).splitlines()[0][:200]))
        elif p.suffix == ".json":
            j_tot += 1
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                j_ko.append((rel, str(e)[:200]))
    controles["yaml"] = {"total": y_tot, "ok": y_tot - len(y_ko), "statut": "reussi" if not y_ko else "echoue"} if yaml \
        else {"statut": "saute", "motif": "PyYAML absent"}
    controles["json"] = {"total": j_tot, "ok": j_tot - len(j_ko), "statut": "reussi" if not j_ko else "echoue"}
    for f, e in y_ko + j_ko:
        defauts.append(defaut("statiques", "majeure", f"Fichier invalide : {f}", e, "Corriger la syntaxe.",
                              RESPONSABLES["statiques"]))
    # secrets (dans le DÉPÔT réel, en lecture seule)
    s = rechercher_secrets(C.DEPOT)
    controles["secrets"] = {"statut": "reussi" if not s["suspects"] else "echoue", "suspects": len(s["suspects"]),
                            "factices": s["factices"], "fichiers_analyses": s["fichiers_analyses"],
                            "origine_motifs": s["origine_motifs"], "detail_suspects": s["suspects"][:50]}
    for t in s["suspects"]:
        defauts.append(defaut("statiques", "critique", f"Secret possible dans le dépôt : {t['fichier']} ({t['type']})",
                              t["extrait"], "Retirer la valeur, la révoquer (rotation) et la placer dans .env (hors dépôt).",
                              "Sécurité (CYBER-FORTRESS)", ident=f"secret:{t['fichier']}:{t['type']}"))
    # docker compose config
    composes = sorted(ctx.bac.glob("docker-compose*.yml"))
    if shutil.which("docker") and composes:
        dkok = []
        env_dc = dict(env, NEXUS_HOST="syfer.exemple.local", COMPOSE_PROJECT_NAME="syfertest")
        for f in composes:
            r = C.executer(["docker", "compose", "-f", str(f), "config", "-q"], ctx.bac, env_dc, 60)
            dkok.append(r["rc"] == 0)
            if r["rc"] != 0:
                msg = [l for l in r["erreurs"].splitlines() if "level=warning" not in l]
                defauts.append(defaut("statiques", "majeure", f"docker compose config invalide : {f.name}",
                                      (msg or ["?"])[0][:300], "Corriger le fichier compose.", RESPONSABLES["statiques"]))
        controles["docker_compose"] = {"total": len(composes), "ok": sum(dkok),
                                       "statut": "reussi" if all(dkok) else "echoue"}
    else:
        controles["docker_compose"] = {"statut": "saute", "motif": "docker absent" if composes else "aucun compose"}
    st = "reussi" if all(c["statut"] in ("reussi", "saute") for c in controles.values()) else "echoue"
    sautes = [f"{k} ({v['motif']})" for k, v in controles.items() if v["statut"] == "saute"]
    return _res("statiques", "Contrôles statiques", st, "; ".join(sautes) or None, time.time() - t0,
                {"controles": controles, "secrets_suspects": len(s["suspects"])}, defauts,
                ["bash -n *.sh", "shellcheck", "yaml/json", "recherche de secrets", "docker compose config -q"])


# =========================================================================== registre

SUITES = {
    "tests": (suite_tests, "Tests unitaires"),
    "protocole": (suite_protocole, "Protocole NEXUS v1"),
    "simulations": (suite_simulations, "103 scénarios fonctionnels"),
    "iterations": (suite_iterations, "100 itérations"),
    "attaque": (suite_attaque, "Attaque simulée"),
    "banc": (suite_banc, "Banc d'essai"),
    "charge": (suite_charge, "Charge 200 %"),
    "jumeau": (suite_jumeau, "Jumeau numérique"),
    "compaction": (suite_compaction, "Compaction"),
    "statiques": (suite_statiques, "Contrôles statiques"),
}
SUITES_CONFIGURATION = ["simulations", "iterations", "jumeau", "charge"]   # dépendent du profil de version


def lancer_suite(nom: str, ctx: Contexte, **kw) -> dict:
    fn, titre = SUITES[nom]
    try:
        return fn(ctx, **kw)
    except Exception as e:  # noqa: BLE001 — une épreuve qui plante ne doit jamais arrêter l'orchestrateur
        import traceback
        with open(ctx.journal, "a", encoding="utf-8") as f:
            f.write(C.masquer(traceback.format_exc()) + "\n")
        return _res(nom, titre, "erreur", f"{type(e).__name__}: {C.masquer(str(e))}"[:300])
