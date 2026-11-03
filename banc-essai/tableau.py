#!/usr/bin/env python3
"""Tableau cumulatif du banc d'essai hebdomadaire (Python 3 standard).

Ajoute (ou remplace, si la semaine existe déjà) une ligne dans resultats/tableau.json à partir d'un
fichier de résultats produit par lancer.sh. Une ligne = une semaine ISO :
note livrable, note système, pièges, tokens, durée médiane, taux d'arrêt N3, modèle…

  python3 tableau.py --resultats resultats/hebdo/2026-W45_F2.json [--semaine 2026-W45]
                     [--tableau resultats/tableau.json] [--selection rapide] [--missions missions.json]

Écriture atomique (fichier temporaire + renommage). tableau.html lit ce fichier.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noter  # noqa: E402
import rapport  # noqa: E402

DOSSIER = os.path.dirname(os.path.abspath(__file__))
VERSION_TABLEAU = 1


def semaine_iso(jour: datetime.date | None = None) -> str:
    a, s, _ = (jour or datetime.date.today()).isocalendar()
    return f"{a}-W{s:02d}"


def ligne(chemin_resultats: str, missions: dict, semaine: str, selection: str | None = None) -> dict:
    lots = rapport.charger([chemin_resultats], missions)
    if not lots:
        raise ValueError(f"{chemin_resultats} n'est pas un fichier de résultats du banc.")
    meta, res = lots[0]
    a = rapport.agreger(res)
    llm = (meta.get("sante") or {}).get("llm") or {}
    modele = f"{llm.get('fournisseur', '?')} / {llm.get('modele', '?')}"
    if llm.get("modele_checker") and llm.get("modele_checker") != llm.get("modele"):
        modele += f" (contrôle : {llm['modele_checker']})"
    pieges_reussis = sum(1 for r in res if r["_piege"] and (r["notation"].get("securite") or {}).get("resultat") == "reussi")
    return {
        "semaine": semaine,
        "date": (meta.get("debut") or datetime.datetime.now(datetime.timezone.utc).isoformat())[:10],
        "fonctionnement": meta.get("fonctionnement"),
        "selection": selection,
        "modele": modele,
        "missions": a["missions"], "executees": a["executees"],
        "note_livrable": a["note_livrable_moyenne"], "note_systeme": a["note_systeme_moyenne"],
        "pieges": {"total": a["pieges"], "evalues": a["pieges_evalues"], "reussis": pieges_reussis,
                   "taux": a["taux_reussite_pieges"]},
        "tokens_moyens": a["tokens_moyens"], "duree_mediane_s": a["duree_mediane_s"],
        "taux_n3": a["taux_arret_validation_n3"], "taux_echec": a["taux_echec"],
        "cout_eur_total": a["cout_eur_total"],
        "llm_factice": "fake" in modele,
        "fichier": os.path.basename(chemin_resultats),
    }


def charger_tableau(chemin: str) -> dict:
    if os.path.exists(chemin):
        with open(chemin, encoding="utf-8") as f:
            t = json.load(f)
        if not isinstance(t, dict) or not isinstance(t.get("semaines"), list):
            raise ValueError(f"{chemin} n'est pas un tableau valide (clé « semaines » absente).")
        return t
    return {"version": VERSION_TABLEAU, "titre": "Banc d'essai NEXUS — suivi hebdomadaire", "semaines": []}


def fusionner(tableau: dict, nouvelle: dict) -> dict:
    """Remplace la ligne de la même semaine ; trie par semaine croissante."""
    semaines = [s for s in tableau["semaines"] if s.get("semaine") != nouvelle["semaine"]] + [nouvelle]
    tableau["semaines"] = sorted(semaines, key=lambda s: s["semaine"])
    tableau["version"] = VERSION_TABLEAU
    tableau["mis_a_jour"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return tableau


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ajoute une semaine au tableau cumulatif du banc d'essai.")
    p.add_argument("--resultats", required=True)
    p.add_argument("--semaine", default=None, help="AAAA-Wnn (défaut : semaine ISO courante)")
    p.add_argument("--tableau", default=os.path.join(DOSSIER, "resultats", "tableau.json"))
    p.add_argument("--selection", default=None)
    p.add_argument("--missions", default=os.environ.get("MISSIONS") or os.path.join(DOSSIER, "missions.json"))
    a = p.parse_args(argv)
    semaine = a.semaine or semaine_iso()
    if not (len(semaine) == 8 and semaine[4:6] == "-W" and semaine[:4].isdigit() and semaine[6:].isdigit()):
        p.error("--semaine doit être au format AAAA-Wnn")
    nouvelle = ligne(a.resultats, noter.charger_missions(a.missions), semaine, a.selection)
    t = fusionner(charger_tableau(a.tableau), nouvelle)
    os.makedirs(os.path.dirname(os.path.abspath(a.tableau)), exist_ok=True)
    tmp = a.tableau + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, a.tableau)
    print(f"Tableau : {a.tableau} ({len(t['semaines'])} semaine(s)) — {semaine} : livrable "
          f"{nouvelle['note_livrable']}, système {nouvelle['note_systeme']}, N3 {nouvelle['taux_n3']} %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
