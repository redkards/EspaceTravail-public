#!/usr/bin/env python3
"""SYFER Test System v1 — système de test unifié de SYFER.

Commandes :
  tout                      toutes les épreuves (mode normal, campagne de charge en mode court)
  rapide                    sélection rapide (≤ 5 min)
  suite <nom>               une épreuve : tests, protocole, simulations, iterations, attaque, banc,
                            charge, jumeau, compaction, statiques
  version <A|B|C|D|E|tous>  épreuves dépendant de la configuration, pour un profil ou les 5
  porte                     porte de qualité sur le dernier passage (VERT/ROUGE + raisons)
  rapport                   rapport PDF du dernier passage (+ comparaison des versions)
  liste                     épreuves et profils disponibles, présence des dossiers

Codes de sortie : 0 tout est vert (porte VERTE) · 1 au moins un échec (porte ROUGE) · 2 usage ou
configuration invalide · 3 aucun résultat disponible · 130 interruption.
Le dépôt n'est JAMAIS modifié : chaque passage travaille dans une copie jetable (bac à sable).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sts import NOM, VERSION  # noqa: E402
from sts import commun as C  # noqa: E402
from sts import porte as P  # noqa: E402
from sts import score as S  # noqa: E402
from sts import suites as T  # noqa: E402

ORDRE_GRAVITE = {"critique": 0, "majeure": 1, "mineure": 2, "info": 3}
ORDRE_TOUT = ["statiques", "tests", "protocole", "simulations", "iterations", "attaque", "banc", "jumeau",
              "compaction", "charge"]
CODES_VERSIONS = ["A", "B", "C", "D", "E"]
SCHEMA = "syfer-test/1"


def charger_profil(code: str) -> dict:
    p = C.lire_json(C.VERSIONS / f"{code.upper()}.json")
    if not p:
        raise SystemExit(f"Profil de version introuvable : versions/{code.upper()}.json")
    return p


def dossiers_presents() -> dict:
    pres = {d: (C.DEPOT / d).is_dir() for d in T.DOSSIERS_TESTS}
    pres["compaction (nexus-core/app/compaction.py)"] = (C.DEPOT / "nexus-core/app/compaction.py").exists()
    pres["iterations-100/iterer.py"] = (C.DEPOT / "iterations-100/iterer.py").exists()
    pres["compaction/mesure.py"] = (C.DEPOT / "compaction/mesure.py").exists()
    return pres


def passages(sauf: Path | None = None, avec=("tout", "rapide", "suite")) -> list[dict]:
    """Passages précédents (plus ancien → plus récent)."""
    out = []
    if not C.RESULTATS.exists():
        return out
    for f in sorted(C.RESULTATS.glob("*/syfer_test.json")):
        if sauf and f.parent == sauf:
            continue
        d = C.lire_json(f)
        if d and d.get("schema") == SCHEMA and d.get("mode") in avec:
            d["_dossier"] = str(f.parent)
            out.append(d)
    return out


def trier_defauts(defs: list[dict]) -> list[dict]:
    vus, out = set(), []
    for d in defs:
        if d["id"] in vus:
            continue
        vus.add(d["id"])
        out.append(d)
    return sorted(out, key=lambda d: (ORDRE_GRAVITE.get(d["gravite"], 9), d["suite"], d["titre"]))


def indice_banc(fiche: dict) -> float | None:
    return (fiche["axes"].get("qualite") or {}).get("score")


def afficher_suite(r: dict) -> None:
    marque = {"reussi": "OK    ", "echoue": "ÉCHEC ", "saute": "SAUTÉE", "erreur": "ERREUR", "delai": "DÉLAI "}[r["statut"]]
    m = r["mesures"]
    resume = {
        "tests": lambda: f"{m.get('reussis')}/{m.get('total', 0) - m.get('sautes', 0)} verts",
        "simulations": lambda: f"{m.get('reussis')}/{m.get('executes')} réussis",
        "attaque": lambda: f"{m.get('taux_blocage_pct')} % bloquées, FP {m.get('faux_positifs')}",
        "banc": lambda: f"système {m.get('note_systeme_moy')} · pièges {m.get('pieges_reussis_pct')} %",
        "charge": lambda: f"{m.get('reussis')}/{m.get('scenarios')} scénarios, critères {m.get('taux_criteres')} %",
        "jumeau": lambda: f"score {round((m.get('version') or {}).get('nominal', {}).get('score') or 0, 1)}",
        "protocole": lambda: f"{m.get('exemples_conformes')}/{m.get('exemples')} exemples conformes",
        "statiques": lambda: f"secrets suspects {m.get('secrets_suspects')}",
        "iterations": lambda: f"{m.get('reussis')}/{m.get('iterations')} · critiques ouverts {m.get('critiques_ouverts')}",
    }.get(r["nom"], lambda: "")
    try:
        txt = resume() if r["statut"] in ("reussi", "echoue") else (r.get("motif") or "")
    except Exception:  # noqa: BLE001
        txt = ""
    print(f"  [{marque}] {r['nom']:12} {r['duree_s']:7.1f} s  {txt}", flush=True)


def executer(noms: list[str], profil: dict, mode: str, graine: int, sortie: Path, suites_kw: dict | None = None,
             bac: Path | None = None) -> dict:
    """Exécute des épreuves dans un bac à sable. Renvoie {nom: résultat}."""
    propre = bac is None
    bac = bac or C.creer_bac()
    ctx = T.Contexte(bac, sortie, profil, mode, graine)
    res = {}
    try:
        for n in noms:
            print(f"→ {n} …", flush=True)
            r = T.lancer_suite(n, ctx, **(suites_kw or {}).get(n, {}))
            res[n] = r
            afficher_suite(r)
    finally:
        if propre:
            C.supprimer_bac(bac)
        import shutil
        shutil.rmtree(ctx.tmp, ignore_errors=True)
    return res


def passage(noms: list[str], mode: str, code: str, graine: int, pdf: bool = True) -> int:
    t0 = time.time()
    profil = charger_profil(code)
    sortie = C.RESULTATS / C.horodatage()
    sortie.mkdir(parents=True, exist_ok=True)
    print(f"{NOM} — {mode} · profil {profil['code']} ({profil['nom']}) · graine {graine}")
    print(f"Résultats : {sortie}")
    res = executer(noms, profil, mode, graine, sortie)
    fiche = S.fiche(res)
    prec = passages(sauf=sortie)
    prec_banc = next((p.get("indice_banc") for p in reversed(prec) if p.get("indice_banc") is not None), None)
    ib = indice_banc(fiche) if T._res and res.get("banc", {}).get("statut") in ("reussi", "echoue") else None
    porte = P.evaluer(res, ib, prec_banc)
    doc = {"schema": SCHEMA, "systeme": NOM, "version_systeme": VERSION, "horodatage": sortie.name, "mode": mode,
           "graine": graine, "profil": {"code": profil["code"], "nom": profil["nom"]},
           "duree_s": round(time.time() - t0, 1), "depot": {"chemin": str(C.DEPOT), "presence": dossiers_presents()},
           "suites": res, "score": fiche, "indice_banc": ib, "porte": porte,
           "defauts": trier_defauts([d for r in res.values() for d in r["defauts"]]),
           "tendance": [{"horodatage": p["horodatage"], "mode": p["mode"], "global": (p.get("score") or {}).get("global"),
                         "verdict": (p.get("porte") or {}).get("verdict"),
                         "axes": {k: v.get("score") for k, v in ((p.get("score") or {}).get("axes") or {}).items()}}
                        for p in prec[-10:]]}
    C.ecrire_json(sortie / "syfer_test.json", doc)
    print(f"\nScore global : {fiche['global']} / 100 (couverture {int(100 * fiche['couverture_globale'])} %)")
    for k, a in fiche["axes"].items():
        print(f"  {a['libelle']:16} {a['score'] if a['score'] is not None else '—':>6}")
    print(f"PORTE DE QUALITÉ : {porte['verdict']}")
    for r in porte["raisons"]:
        print(f"  - {r}")
    if pdf:
        faire_rapport(sortie)
    return 0 if all(r["statut"] in ("reussi", "saute") for r in res.values()) else 1


def versions(codes: list[str], mode: str, graine: int, pdf: bool = True) -> int:
    t0 = time.time()
    sortie = C.RESULTATS / C.horodatage()
    sortie.mkdir(parents=True, exist_ok=True)
    tous = len(codes) > 1
    print(f"{NOM} — versions {', '.join(codes)} · graine {graine} (identique pour toutes)")
    out, rc = {}, 0
    for code in codes:
        profil = charger_profil(code)
        noms = T.SUITES_CONFIGURATION if tous else [n for n in ORDRE_TOUT if n in profil.get("suites", [])]
        print(f"\n=== Version {code} — {profil['nom']} : {profil['resume']}")
        kw = {"jumeau": {"lancer_global": False}, "charge": {"ids": "S01,S04,S18"}}
        res = executer(noms, profil, mode, graine, sortie / code, kw)
        fiche = S.fiche(res)
        out[code] = {"profil": profil, "suites": res, "score": fiche,
                     "defauts": trier_defauts([d for r in res.values() for d in r["defauts"]])}
        rc |= 0 if all(r["statut"] in ("reussi", "saute") for r in res.values()) else 1
        print(f"  Score {code} : {fiche['global']} / 100")
    classement = sorted(out, key=lambda c: -(out[c]["score"]["global"] or 0))
    doc = {"schema": SCHEMA, "systeme": NOM, "version_systeme": VERSION, "horodatage": sortie.name, "mode": "version",
           "graine": graine, "duree_s": round(time.time() - t0, 1), "versions": out, "classement": classement,
           "suites_comparees": T.SUITES_CONFIGURATION if tous else None}
    C.ecrire_json(sortie / "syfer_test.json", doc)
    print("\nClassement : " + " > ".join(f"{c} {out[c]['profil']['nom']} ({out[c]['score']['global']})" for c in classement))
    if pdf:
        faire_rapport()
    return rc


def dernier(modes) -> dict | None:
    p = passages(avec=modes)
    return p[-1] if p else None


def faire_rapport(dossier: Path | None = None) -> Path | None:
    from sts import rapport_pdf
    base = C.lire_json(dossier / "syfer_test.json") if dossier else dernier(("tout", "rapide", "suite"))
    if base and dossier:
        base["_dossier"] = str(dossier)
    vers = dernier(("version",))
    if not base and not vers:
        print("Aucun résultat : lancez d'abord « syfer_test.py tout ».", file=sys.stderr)
        return None
    cible = Path((base or vers)["_dossier"]) / "rapport.pdf"
    prec = passages(sauf=Path(base["_dossier"])) if base else []
    rapport_pdf.produire(base, vers, prec, cible)
    print(f"Rapport PDF : {cible}")
    return cible


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="syfer_test.py", description=f"{NOM} ({VERSION}) — système de test unifié de SYFER",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--graine", type=int, default=2026, help="graine commune (défaut 2026)")
    ap.add_argument("--sans-pdf", action="store_true", help="ne pas produire le PDF à la fin")
    sp = ap.add_subparsers(dest="commande", required=True)
    for nom, aide in (("tout", "toutes les épreuves"), ("rapide", "sélection rapide (≤ 5 min)")):
        p = sp.add_parser(nom, help=aide)
        p.add_argument("--version", default="A", choices=CODES_VERSIONS, help="profil appliqué (défaut A)")
    p = sp.add_parser("suite", help="une épreuve")
    p.add_argument("nom", choices=list(T.SUITES))
    p.add_argument("--version", default="A", choices=CODES_VERSIONS)
    p.add_argument("--rapide", action="store_true")
    p = sp.add_parser("version", help="épreuves dépendant de la configuration")
    p.add_argument("code", choices=CODES_VERSIONS + ["tous"])
    p.add_argument("--complet", action="store_true", help="mode normal (défaut : mode rapide des épreuves)")
    p = sp.add_parser("porte", help="porte de qualité sur le dernier passage")
    p.add_argument("--relancer", action="store_true", help="relancer « tout » avant d'évaluer")
    p = sp.add_parser("rapport", help="rapport PDF")
    p.add_argument("dossier", nargs="?", type=Path)
    sp.add_parser("liste", help="épreuves, profils et présence des dossiers")
    a = ap.parse_args(argv)
    pdf = not a.sans_pdf
    try:
        if a.commande == "tout":
            return passage(ORDRE_TOUT, "tout", a.version, a.graine, pdf)
        if a.commande == "rapide":
            return passage(ORDRE_TOUT, "rapide", a.version, a.graine, pdf)
        if a.commande == "suite":
            return passage([a.nom], "suite" if not a.rapide else "rapide", a.version, a.graine, False)
        if a.commande == "version":
            codes = CODES_VERSIONS if a.code == "tous" else [a.code]
            return versions(codes, "tout" if a.complet else "rapide", a.graine, pdf)
        if a.commande == "porte":
            if a.relancer:
                passage(ORDRE_TOUT, "tout", "A", a.graine, pdf)
            d = dernier(("tout", "rapide", "suite"))
            if not d:
                print("Aucun passage : lancez « syfer_test.py tout ».", file=sys.stderr)
                return 3
            prec = passages(sauf=Path(d["_dossier"]))
            pb = next((p.get("indice_banc") for p in reversed(prec) if p.get("indice_banc") is not None), None)
            pt = P.evaluer(d["suites"], d.get("indice_banc"), pb)
            print(f"PORTE DE QUALITÉ ({d['horodatage']}, {d['mode']}) : {pt['verdict']}")
            for c in pt["criteres"]:
                print(f"  [{c['etat']:10}] {c['libelle']} — {c['mesure'] or ''} {('· ' + c['raison']) if c['raison'] else ''}")
            print("Déploiement AUTORISÉ." if pt["deploiement_autorise"] else "Déploiement REFUSÉ.")
            return 0 if pt["deploiement_autorise"] else 1
        if a.commande == "rapport":
            return 0 if faire_rapport(a.dossier) else 3
        if a.commande == "liste":
            print("Épreuves : " + ", ".join(T.SUITES))
            for c in CODES_VERSIONS:
                p = charger_profil(c)
                print(f"Version {c} — {p['nom']} : {p['resume']}")
            for k, v in dossiers_presents().items():
                print(f"  {'présent' if v else 'ABSENT ':8} {k}")
            return 0
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
