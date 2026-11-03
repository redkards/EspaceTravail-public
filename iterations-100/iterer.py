#!/usr/bin/env python3
"""Méthode des 100 itérations de mini-scénarios (tests internes SYFER).

Chaque itération génère N mini-scénarios (briques tirées au hasard, graine reproductible), les exécute
dans le bac à sable de simulations/simuler.py, vérifie les oracles, puis pour chaque violation :
réduction automatique au plus petit cas reproductible, dédoublonnage par cause, enregistrement dans
defauts/<id>.json. Les itérations suivantes donnent plus de poids aux briques des défauts trouvés.

Usage :
    python3 iterer.py --iterations 100 --taille 20 --graine 2026
    python3 iterer.py --rejouer O07-1a2b3c4d          # rejoue un défaut (code 1 s'il se reproduit)
    python3 iterer.py --jusqu-a-stabilite --max-iterations 400   # critère de sortie complet
Résultats : resultats/AAAA-MM-JJ_HHMM.json, rapport.md (et copie datée dans resultats/).
"""
import argparse
import datetime as dt
import hashlib
import itertools
import re
import json
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import generateur as gen  # noqa: E402
import executer  # noqa: E402
import oracles  # noqa: E402

DEFAUTS = ICI / "defauts"
RESULTATS = ICI / "resultats"
RAPPORT = ICI / "rapport.md"
CRITERE_STABILITE = 100

# Corrections suggérées (par oracle, puis affinées selon la brique du cas minimal).
SUGGESTIONS = {
    "O01": "Après une révision, recalculer le GATE avec le plancher du classement précédent "
           "(niveau = max(ancien, nouveau)) : une révision ne doit jamais faire sortir une mission du circuit N3.",
    "O02": "Compléter MOTS_N3 (formes à la 2e personne et synonymes : « paie », « vire », « mets en ligne », "
           "« efface »…) et la détection des montants (lettres, M€, $ à l'anglaise), puis ajouter des tests.",
    "O03": "Interdire le statut « terminee » à toute mission dont un classement GATE a déjà valu N3 "
           "(exiger une décision « validee » sur le dernier livrable).",
    "O04": "Faire comprendre à _montant_cite / _MONTANT les formats manquants (séparateur anglais « 2,000 », "
           "« M€ », montants en lettres) ; à défaut, risque « eleve » par prudence quand un montant est ambigu.",
    "O05": "Exiger le code Décideur dès que le montant (champ ou cité) atteint le seuil, indépendamment du risque calculé.",
    "O06": "Conserver le refus 403 de la clé API (NEXUS_API_PEUT_DECIDER=0 par défaut).",
    "O07": "Appliquer cyber.masquer (et le masquage des canaris) à la consigne et au titre dès la création de la "
           "mission, ainsi qu'à toute donnée entrante (veille, import) avant stockage ou envoi au LLM.",
    "O08": "Abaisser le seuil d'alerte du bouclier pour les consignes de dispense de relecture, ou marquer "
           "« suspect » toute source qui parle de validation, de relecture ou de niveau N.",
    "O09": "Étendre affirmations_d : repérer aussi le contenu de la fiche D (pas seulement le préfixe veille:…) "
           "et refuser toute ligne qui le reprend sans formule de prudence.",
    "O10": "Ajouter « à préciser », « XX € » (et variantes) aux marqueurs d'inachevé ; refuser l'inachevé dans "
           "tout livrable N3 validable, pas seulement en publication.",
    "O11": "Rendre la création idempotente (clé d'idempotence ou refus d'un doublon identique sous quelques "
           "secondes) et vérifier la reprise de la file au redémarrage.",
    "O12": "Vérifier la chaîne après chaque écriture concurrente ; sérialiser LEDGER et archive.",
    "O13": "Ne journaliser au LEDGER que des identifiants (pas le titre) ou les remplacer à l'effacement ; "
           "permettre l'effacement d'une mission sans archive (404 actuel).",
    "O14": "Appliquer appliquer_planchers aussi après la relance, la révision et le repli F4→F3.",
    "O15": "Revérifier l'accord F4 juste avant chaque appel payant.",
    "O16": "Rattraper l'erreur et renvoyer un 4xx explicite ; ajouter un test de non-régression.",
    "O17": "Après refus ou expiration, bloquer toute exécution et tout export de la mission.",
    "O18": "Conserver la mise à jour atomique (UPDATE … WHERE statut='en_attente').",
}


def _cle(briques: dict) -> str:
    """Cause = cas minimal (briques non neutres) : deux oracles violés par le même cas minimal = un défaut."""
    return gen.signature(briques)


def _id_defaut(oid: str, cle: str) -> str:
    return f"{oid}-{hashlib.sha1(cle.encode()).hexdigest()[:8]}"


def _propre(texte: str) -> str:
    return re.sub(r"/tmp/sim-[^/ ]+/", "<bac>/", texte or "")


class Methode:
    def __init__(self, graine: int, taille: int, bavard: bool = True):
        self.graine, self.taille, self.bavard = graine, taille, bavard
        self.poids_base = gen.poids_initiaux()
        self.poids = {d: dict(v) for d, v in self.poids_base.items()}
        self.defauts: dict[str, dict] = {}       # cle -> défaut
        self.cache: dict[str, list] = {}         # (graine, signature) -> violations
        self.executions = 0
        self.executions_reduction = 0
        self.singles: set = set()
        self.paires: set = set()
        self.iterations: list[dict] = []
        dims = gen.dimensions()
        self.total_singles = sum(len(self.poids_base[d]) for d in dims)
        self.total_paires = sum(len(self.poids_base[a]) * len(self.poids_base[b])
                                for a, b in itertools.combinations(dims, 2))

    # --- exécution avec cache -----------------------------------------------------------------
    def executer(self, sc: dict, reduction: bool = False) -> tuple[list, dict | None]:
        k = f"{sc['graine']}|{json.dumps(sc['briques'], sort_keys=True)}"
        if k in self.cache:
            return self.cache[k], None
        obs = executer.jouer(sc)
        v = oracles.verifier(obs)
        self.cache[k] = v
        self.executions += 1
        if reduction:
            self.executions_reduction += 1
        return v, obs

    def couvrir(self, briques: dict) -> None:
        items = sorted(briques.items())
        self.singles.update(items)
        self.paires.update(itertools.combinations(items, 2))

    # --- réduction ----------------------------------------------------------------------------
    def reduire(self, sc: dict, oid: str) -> dict:
        """Enlève des briques (→ neutre) tant que le même oracle reste violé (cas 1-minimal)."""
        cour = dict(sc["briques"])
        change = True
        while change:
            change = False
            for d in gen.dimensions():
                if cour[d] == gen.neutre(d):
                    continue
                cand = {**cour, d: gen.neutre(d)}
                v, _ = self.executer({"graine": sc["graine"], "briques": cand}, reduction=True)
                if any(x["oracle"] == oid for x in v):
                    cour, change = cand, True
        return cour

    def deja_explique(self, oid: str, briques: dict) -> dict | None:
        """Défaut connu dont la cause (briques causales pour cet oracle) est contenue dans le scénario."""
        for d in self.defauts.values():
            cause = d["causes"].get(oid)
            if cause is not None and all(briques.get(k) == val for k, val in cause.items()):
                return d
        return None

    def _ecrire(self, d: dict) -> None:
        DEFAUTS.mkdir(exist_ok=True)
        (DEFAUTS / f"{d['id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    def enregistrer(self, oid: str, sc: dict, minimal: dict, iteration: int) -> tuple[dict, bool]:
        sig = _cle(minimal)
        cause = oracles.cause(oid, minimal)
        for d in self.defauts.values():
            if d["signature"] == sig or d["causes"].get(oid) == cause:
                d["occurrences"] += 1
                if oid not in d["causes"]:  # même cas minimal, autre invariant violé : on complète la fiche
                    d["causes"][oid] = cause
                    d["oracles"].append(oid)
                    vs = [x for x in oracles.verifier(executer.jouer({"graine": d["graine"], "briques": minimal}))
                          if x["oracle"] == oid]
                    if vs:
                        d["autres_violations"].append({"oracle": oid, "titre": oracles.PAR_ID[oid]["titre"],
                                                       "observe": _propre(vs[0]["observe"]), "attendu": vs[0]["attendu"]})
                    d["gravite"] = min(d["gravite"], oracles.PAR_ID[oid]["gravite"])
                    self._ecrire(d)
                return d, False
        sc_min = {"graine": sc["graine"], "briques": minimal}
        obs = executer.jouer(sc_min)
        vs = [x for x in oracles.verifier(obs) if x["oracle"] == oid]
        v = vs[0] if vs else {"observe": "(non reproduit lors de l'enregistrement : instable)", "attendu": "",
                              "gravite": oracles.PAR_ID[oid]["gravite"]}
        o = oracles.PAR_ID[oid]
        did = _id_defaut(oid, sig)
        mat = obs.get("materiel", {})
        d = {"id": did, "oracle": oid, "oracles": [oid], "causes": {oid: cause}, "signature": sig,
             "oracle_titre": o["titre"], "gravite": o["gravite"],
             "graine": sc["graine"], "iteration": iteration, "occurrences": 1,
             "cas_minimal": minimal, "non_neutres": gen.non_neutres(minimal),
             "description": gen.decrire(sc_min), "scenario_initial": gen.non_neutres(sc["briques"]),
             "actions": gen.actions(sc_min),
             "consigne": mat.get("consigne"), "montant_texte": mat.get("montant_texte"),
             "observe": _propre(v["observe"]), "attendu": v["attendu"], "reproduit": bool(vs),
             "autres_violations": [],
             "fichier_ligne_probable": oracles.localisation(oid, v, minimal),
             "correction_suggeree": SUGGESTIONS.get(oid, ""),
             "rejouer": f"python3 iterer.py --rejouer {did}"}
        self.defauts[sig] = d
        self._ecrire(d)
        return d, True

    # --- exploration guidée -------------------------------------------------------------------
    def ajuster_poids(self) -> None:
        compte: dict = {}
        for d in self.defauts.values():
            for dim, v in d["non_neutres"].items():
                compte[(dim, v)] = compte.get((dim, v), 0) + 1
        for dim, vs in self.poids_base.items():
            for v, p in vs.items():
                self.poids[dim][v] = p * min(4.0, 1 + 0.5 * compte.get((dim, v), 0))

    # --- une itération ------------------------------------------------------------------------
    def iteration(self, i: int) -> dict:
        debut = time.perf_counter()
        voisins = [d["cas_minimal"] for d in self.defauts.values()]
        nb_viol, en_echec, nouveaux, connus = 0, 0, [], 0
        par_oracle: dict = {}
        for r in range(self.taille):
            sc = gen.generer(gen.graine_scenario(self.graine, i, r), self.poids, voisins)
            self.couvrir(sc["briques"])
            vs, _ = self.executer(sc)
            if vs:
                en_echec += 1
            nb_viol += len(vs)
            for oid in sorted({v["oracle"] for v in vs}):
                par_oracle[oid] = par_oracle.get(oid, 0) + 1
                if self.deja_explique(oid, sc["briques"]):
                    connus += 1
                    self.deja_explique(oid, sc["briques"])["occurrences"] += 1
                    continue
                minimal = self.reduire(sc, oid)
                d, neuf = self.enregistrer(oid, sc, minimal, i)
                if neuf:
                    nouveaux.append(d["id"])
                else:
                    connus += 1
        self.ajuster_poids()
        bilan = {"iteration": i, "scenarios": self.taille, "scenarios_en_echec": en_echec, "violations": nb_viol,
                 "violations_par_oracle": par_oracle, "nouveaux_defauts": nouveaux, "violations_connues": connus,
                 "defauts_uniques_cumul": len(self.defauts),
                 "couverture_paires": round(len(self.paires) / self.total_paires, 4),
                 "couverture_briques": round(len(self.singles) / self.total_singles, 4),
                 "duree_s": round(time.perf_counter() - debut, 2)}
        self.iterations.append(bilan)
        if self.bavard:
            print(f"[it {i:3d}] {en_echec:2d}/{self.taille} en échec · {nb_viol:3d} violation(s) · "
                  f"nouveaux {len(nouveaux)} {' '.join(nouveaux)} · uniques {len(self.defauts)} · "
                  f"paires {bilan['couverture_paires']:.1%} · {bilan['duree_s']} s", file=sys.stderr, flush=True)
        return bilan

    def sans_nouveaute_consecutives(self) -> int:
        n = 0
        for b in reversed(self.iterations):
            if b["nouveaux_defauts"]:
                break
            n += 1
        return n


# --- Rapport ------------------------------------------------------------------------------------

def _barres(valeurs: list[int], hauteur: int = 8) -> list[str]:
    haut = max(valeurs) or 1
    lignes = []
    for h in range(hauteur, 0, -1):
        seuil = haut * (h - 0.5) / hauteur
        lignes.append(f"{round(haut * h / hauteur):>4} │" + "".join("█" if v >= seuil else " " for v in valeurs))
    lignes.append("     └" + "─" * len(valeurs))
    lignes.append("      " + "".join(str(i // 10 % 10) if i % 10 == 0 else " " for i in range(1, len(valeurs) + 1)))
    return lignes


def rapport_md(doc: dict) -> str:
    its = doc["iterations"]
    defs = sorted(doc["defauts"], key=lambda d: (d["gravite"], -d["occurrences"], d["id"]))
    viol = [b["violations"] for b in its]
    cumul = [b["defauts_uniques_cumul"] for b in its]
    l = [f"# Méthode des 100 itérations — {doc['horodatage']}", "",
         f"- Itérations : **{len(its)}** × {doc['parametres']['taille']} mini-scénarios = "
         f"**{doc['totaux']['mini_scenarios']}** mini-scénarios (graine {doc['parametres']['graine']}) ; "
         f"+ {doc['totaux']['executions_reduction']} exécutions de réduction ; durée {doc['duree_s']} s.",
         f"- Violations d'oracles : **{doc['totaux']['violations']}** dans {doc['totaux']['scenarios_en_echec']} "
         f"mini-scénarios ; **{len(defs)} défauts UNIQUES** après réduction et dédoublonnage.",
         f"- Couverture : {doc['couverture']['briques']:.1%} des briques, {doc['couverture']['paires']:.1%} des paires "
         f"de briques ({doc['couverture']['paires_vues']}/{doc['couverture']['paires_total']}).",
         f"- Critère de sortie ({CRITERE_STABILITE} itérations consécutives sans violation nouvelle) : "
         f"{'ATTEINT' if doc['critere_sortie']['atteint'] else 'NON ATTEINT'} — "
         f"{doc['critere_sortie']['consecutives_sans_nouveaute']} itération(s) consécutive(s) sans nouveauté en fin "
         f"de course ; dernier défaut nouveau à l'itération {doc['critere_sortie']['derniere_nouveaute']}.", "",
         "Les défauts sont des RÉSULTATS : nexus-core n'a pas été modifié.", "",
         "## Violations par itération", "", "```", *_barres(viol), "```", "",
         "## Défauts uniques cumulés", "", "```", *_barres(cumul), "```", "",
         "## Couverture des paires de briques", "", "| Itération | 1 | 10 | 25 | 50 | 75 | 100 |", "|---|---|---|---|---|---|---|"]
    pts = [its[min(i, len(its)) - 1]["couverture_paires"] if its else 0 for i in (1, 10, 25, 50, 75, 100)]
    l.append("| Paires couvertes | " + " | ".join(f"{p:.1%}" for p in pts) + " |")
    l += ["", "## Violations par oracle (mini-scénarios touchés)", "", "| Oracle | Titre | Mini-scénarios |", "|---|---|---|"]
    tot: dict = {}
    for b in its:
        for k, n in b["violations_par_oracle"].items():
            tot[k] = tot.get(k, 0) + n
    for o in oracles.ORACLES:
        l.append(f"| {o['id']} | {o['titre']} | {tot.get(o['id'], 0)} |")
    l += ["", f"## Défauts uniques ({len(defs)}) — du plus grave au moins grave", ""]
    for d in defs:
        l += [f"### {d['id']} — {d['oracle_titre']} (gravité {d['gravite']}, {d['occurrences']} occurrence(s))", "",
              f"- Oracles violés : {', '.join(d['oracles'])}",
              f"- Cas minimal : `{d['description']}`",
              f"- Consigne : « {(d.get('consigne') or '').replace(chr(10), ' ')[:220]} »",
              f"- Observé : {d['observe']}", f"- Attendu : {d['attendu']}",
              *[f"- Aussi ({x['oracle']}) : {x['observe']} — attendu : {x['attendu']}" for x in d.get("autres_violations", [])],
              f"- Fichier probable : `{d['fichier_ligne_probable']}`",
              f"- Correction suggérée : {d['correction_suggeree']}",
              f"- Rejouer : `{d['rejouer']}`", ""]
    l += ["## Tableau des itérations", "", "| It. | Échecs | Violations | Nouveaux | Uniques | Paires | Durée (s) |",
          "|---|---|---|---|---|---|---|"]
    for b in its:
        l.append(f"| {b['iteration']} | {b['scenarios_en_echec']} | {b['violations']} | {len(b['nouveaux_defauts'])} | "
                 f"{b['defauts_uniques_cumul']} | {b['couverture_paires']:.1%} | {b['duree_s']} |")
    return "\n".join(l) + "\n"


def lancer(iterations: int, taille: int, graine: int, stabilite: bool = False, max_iterations: int = 400,
           ecrire: bool = True, bavard: bool = True) -> dict:
    if ecrire:
        DEFAUTS.mkdir(exist_ok=True)
        for f in DEFAUTS.glob("*.json"):
            f.unlink()  # défauts de la course précédente (dossier propre à la méthode)
    m = Methode(graine, taille, bavard)
    debut = time.perf_counter()
    i = 0
    while True:
        i += 1
        m.iteration(i)
        if not stabilite and i >= iterations:
            break
        if stabilite and (m.sans_nouveaute_consecutives() >= CRITERE_STABILITE or i >= max_iterations):
            break
    maintenant = dt.datetime.now()
    nouveautes = [b["iteration"] for b in m.iterations if b["nouveaux_defauts"]]
    doc = {"horodatage": maintenant.strftime("%Y-%m-%d %H:%M"), "duree_s": round(time.perf_counter() - debut, 1),
           "parametres": {"iterations": i, "taille": taille, "graine": graine, "stabilite": stabilite},
           "totaux": {"mini_scenarios": i * taille, "executions": m.executions,
                      "executions_reduction": m.executions_reduction,
                      "violations": sum(b["violations"] for b in m.iterations),
                      "scenarios_en_echec": sum(b["scenarios_en_echec"] for b in m.iterations)},
           "couverture": {"briques": len(m.singles) / m.total_singles, "paires": len(m.paires) / m.total_paires,
                          "paires_vues": len(m.paires), "paires_total": m.total_paires},
           "critere_sortie": {"exige": CRITERE_STABILITE, "consecutives_sans_nouveaute": m.sans_nouveaute_consecutives(),
                              "derniere_nouveaute": nouveautes[-1] if nouveautes else None,
                              "atteint": m.sans_nouveaute_consecutives() >= CRITERE_STABILITE},
           "iterations": m.iterations,
           "defauts": sorted(m.defauts.values(), key=lambda d: (d["gravite"], d["id"]))}
    if ecrire:
        RESULTATS.mkdir(exist_ok=True)
        base = RESULTATS / maintenant.strftime("%Y-%m-%d_%H%M")
        base.with_suffix(".json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        texte = rapport_md(doc)
        RAPPORT.write_text(texte, encoding="utf-8")
        base.with_suffix(".md").write_text(texte, encoding="utf-8")
        doc["fichiers"] = [str(base.with_suffix(".json")), str(RAPPORT)]
    return doc


def rejouer(ref: str) -> int:
    f = Path(ref)
    if not f.is_file():
        f = DEFAUTS / (ref if ref.endswith(".json") else f"{ref}.json")
    d = json.loads(f.read_text(encoding="utf-8"))
    sc = {"graine": d["graine"], "briques": d["cas_minimal"]}
    print(f"Défaut {d['id']} — {d['oracle']} {d['oracle_titre']}")
    print(f"Cas minimal : {gen.decrire(sc)}  (graine {d['graine']})")
    obs = executer.jouer(sc)
    vs = [v for v in oracles.verifier(obs) if v["oracle"] in d.get("oracles", [d["oracle"]])]
    if vs:
        for v in vs:
            print(f"REPRODUIT ({v['oracle']}) — observé : {_propre(v['observe'])}\n            attendu : {v['attendu']}")
        print(f"Fichier probable : {d['fichier_ligne_probable']}")
        return 1
    print("NON REPRODUIT : l'oracle tient (défaut corrigé, ou cas instable).")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Méthode des 100 itérations de mini-scénarios (SYFER).")
    p.add_argument("--iterations", type=int, default=100)
    p.add_argument("--taille", type=int, default=20, help="mini-scénarios par itération")
    p.add_argument("--graine", type=int, default=2026)
    p.add_argument("--rejouer", metavar="DEFAUT", help="identifiant (ex. O07-1a2b3c4d) ou chemin d'un défaut")
    p.add_argument("--jusqu-a-stabilite", action="store_true",
                   help=f"continuer jusqu'à {CRITERE_STABILITE} itérations consécutives sans défaut nouveau")
    p.add_argument("--max-iterations", type=int, default=400)
    p.add_argument("--sans-fichier", action="store_true")
    a = p.parse_args(argv)
    if a.rejouer:
        return rejouer(a.rejouer)
    doc = lancer(a.iterations, a.taille, a.graine, a.jusqu_a_stabilite, a.max_iterations, not a.sans_fichier)
    t = doc["totaux"]
    print(f"\n{t['mini_scenarios']} mini-scénarios · {t['violations']} violation(s) · "
          f"{len(doc['defauts'])} défaut(s) unique(s) · couverture paires {doc['couverture']['paires']:.1%} · "
          f"{doc['duree_s']} s")
    for f in doc.get("fichiers", []):
        print(f"Rapport : {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
