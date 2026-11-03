#!/usr/bin/env python3
"""Agrège un ou plusieurs fichiers de résultats du banc d'essai (Python 3 standard).

Sorties : <sortie>/rapport.md et <sortie>/synthese.json (défaut : banc-essai/resultats/).
Avec --nom X : rapport_X.md et synthese_X.json (utile pour l'audit SYFER).

Utilisation :
  python3 rapport.py resultats/*_F?.json
  MISSIONS=audit-syfer/missions.json python3 rapport.py --nom audit-syfer resultats/*audit-syfer*.json
"""
import argparse
import datetime
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noter  # noqa: E402

DOSSIER = os.path.dirname(os.path.abspath(__file__))
SEUIL_PETIT_ECHANTILLON = 20
ECHECS = {"echouee", "erreur_creation", "delai_banc_depasse", "introuvable", "suspendue", "refusee"}


def p90(valeurs):
    if not valeurs:
        return None
    v = sorted(valeurs)
    return v[max(0, math.ceil(0.9 * len(v)) - 1)]


def _moy(valeurs):
    return round(statistics.mean(valeurs), 2) if valeurs else None


def _taux(n, total):
    return round(100.0 * n / total, 1) if total else None


def _duree(r):
    d = r.get("duree_s") or 0
    return d if d > 0 else (r.get("duree_banc_s") or 0)


def charger(fichiers, missions):
    """[(meta, [résultats notés])] ; la notation est (re)calculée en mémoire."""
    lots = []
    for chemin in fichiers:
        with open(chemin, encoding="utf-8") as f:
            d = json.load(f)
        res = []
        for r in d.get("resultats", []):
            definition = missions.get(r.get("id"))
            if definition is None:
                continue
            r = dict(r)
            r["notation"] = noter.noter_mission(definition, r)
            r["_piege"] = bool(definition.get("piege"))
            r["_service_attendu"] = definition["service_attendu"]
            res.append(r)
        lots.append(({k: d.get(k) for k in ("fonctionnement", "debut", "fin", "sante", "nexus_url")}
                     | {"fichier": os.path.basename(chemin)}, res))
    return lots


def agreger(res):
    executes = [r for r in res if r.get("mission_id") and r.get("statut") not in ("lancee", "erreur_creation")]
    normaux = [r for r in res if not r["_piege"]]
    pieges = [r["notation"]["securite"] for r in res if r["_piege"]]
    evalues = [p for p in pieges if p and p["resultat"] != "non_evalue"]
    statuts = {}
    for r in res:
        statuts[r.get("statut")] = statuts.get(r.get("statut"), 0) + 1
    appliques = {}
    for r in executes:
        appliques[r.get("fonctionnement")] = appliques.get(r.get("fonctionnement"), 0) + 1
    durees = [_duree(r) for r in executes if _duree(r) > 0]
    couts = [r.get("cout_eur") or 0.0 for r in executes]
    return {
        "missions": len(res), "executees": len(executes),
        "note_moyenne_qualite": _moy([r["notation"]["note"] for r in normaux]),
        "taux_routage_correct": _taux(sum(r.get("service") == r["_service_attendu"] for r in executes), len(executes)),
        "taux_niveau_correct": _taux(sum(r["notation"]["details"]["niveau"] == 20 for r in executes), len(executes)),
        "pieges": len(pieges), "pieges_evalues": len(evalues),
        "taux_reussite_pieges": _taux(sum(p["resultat"] == "reussi" for p in evalues), len(evalues)),
        "tokens_moyens": _moy([r.get("tokens") or 0 for r in executes]),
        "tokens_entree_moyens": _moy([r.get("tokens_entree") or 0 for r in executes]),
        "tokens_sortie_moyens": _moy([r.get("tokens_sortie") or 0 for r in executes]),
        "cout_eur_moyen": round(statistics.mean(couts), 6) if couts else None,
        "cout_eur_total": round(sum(couts), 6),
        "duree_mediane_s": round(statistics.median(durees), 2) if durees else None,
        "duree_p90_s": round(p90(durees), 2) if durees else None,
        "revisions_moyennes": _moy([r.get("revisions") or 0 for r in executes]),
        "taux_echec": _taux(sum(r.get("statut") in ECHECS for r in res), len(res)),
        "taux_plafond": _taux(statuts.get("plafond_atteint", 0), len(res)),
        "taux_a_reformuler": _taux(statuts.get("a_reformuler", 0), len(res)),
        "taux_arret_validation_n3": _taux(statuts.get("en_attente_n3", 0) + statuts.get("en_attente_decision", 0),
                                          len(res)),
        "statuts": statuts, "fonctionnement_applique": appliques,
    }


def construire(lots):
    par_f, par_service, tous = {}, {}, []
    modeles = {}
    for meta, res in lots:
        f = meta.get("fonctionnement") or "?"
        par_f.setdefault(f, []).extend(res)
        llm = (meta.get("sante") or {}).get("llm") or {}
        modeles.setdefault(f, set()).add(f"{llm.get('fournisseur', '?')} / {llm.get('modele', '?')}"
                                          f" (contrôle : {llm.get('modele_checker', '?')})")
        for r in res:
            r["_f"] = f
            tous.append(r)
            par_service.setdefault(r["_service_attendu"], {}).setdefault(f, []).append(r)
    synth = {
        "genere_le": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fichiers": [m for m, _ in lots],
        "modeles": {f: sorted(v) for f, v in modeles.items()},
        "par_fonctionnement": {f: agreger(r) for f, r in sorted(par_f.items())},
        "par_service": {s: {f: {"missions": len(r), "note_moyenne": _moy([x["notation"]["note"] for x in r]),
                                "routage_correct": _taux(sum(x.get("service") == s for x in r), len(r))}
                            for f, r in sorted(d.items())} for s, d in sorted(par_service.items())},
    }
    pires = sorted((r for r in tous if not r["_piege"]), key=lambda r: r["notation"]["note"])[:5]
    synth["pires_missions"] = [{"id": r["id"], "fonctionnement": r["_f"], "note": r["notation"]["note"],
                                "statut": r.get("statut"), "raisons": r["notation"]["raisons"][:4]} for r in pires]
    synth["pieges_echoues"] = [{"id": r["id"], "fonctionnement": r["_f"], "raison": r["notation"]["securite"]["raison"]}
                               for r in tous if r["_piege"] and r["notation"]["securite"]["resultat"] == "echoue"]
    synth["detail"] = [{"id": r["id"], "fonctionnement": r["_f"], "note": r["notation"]["note"],
                        "statut": r.get("statut"), "service": r.get("service"), "niveau": r.get("niveau"),
                        "fonctionnement_applique": r.get("fonctionnement"), "tokens": r.get("tokens"),
                        "cout_eur": r.get("cout_eur"), "duree_s": _duree(r), "revisions": r.get("revisions"),
                        "securite": (r["notation"]["securite"] or {}).get("resultat")} for r in tous]
    avert = []
    for f, a in synth["par_fonctionnement"].items():
        if a["executees"] < SEUIL_PETIT_ECHANTILLON:
            avert.append(f"{f} : échantillon petit ({a['executees']} mission(s) exécutée(s) < "
                         f"{SEUIL_PETIT_ECHANTILLON}) — chiffres indicatifs, pas des moyennes fiables.")
    if any("fake" in m for v in synth["modeles"].values() for m in v):
        avert.append("LLM FACTICE (fake) détecté : les notes de qualité ne sont pas représentatives ; "
                     "seuls routage, niveaux de décision et mécanique du banc sont vérifiés.")
    synth["avertissements"] = avert
    return synth


def _v(x, suffixe=""):
    return "—" if x is None else f"{x}{suffixe}"


def markdown(s):
    L = [f"# Banc d'essai NEXUS — rapport", "",
         f"- Généré le : {s['genere_le']}",
         "- Fichiers : " + ", ".join(f"`{m['fichier']}` ({m.get('fonctionnement')}, {m.get('debut') or '?'})"
                                     for m in s["fichiers"])]
    for f, mods in s["modeles"].items():
        L.append(f"- Modèle déclaré par /api/sante pendant {f} : " + " ; ".join(mods))
    L.append("- Rappel : F1 utilise toujours le modèle local ; F2/F3 le fournisseur courant ; F4 les modèles "
             "Anthropic (payant). Les niveaux peuvent être relevés automatiquement (colonne « F appliqué »).")
    if s["avertissements"]:
        L += ["", "> **Avertissements**"] + [f"> - {a}" for a in s["avertissements"]]
    L += ["", "## Par niveau de fonctionnement", "",
          "| Indicateur | " + " | ".join(s["par_fonctionnement"]) + " |",
          "|---|" + "---|" * len(s["par_fonctionnement"])]
    lignes = [("Missions (exécutées)", lambda a: f"{a['missions']} ({a['executees']})"),
              ("Note qualité moyenne /100 (hors pièges)", lambda a: _v(a["note_moyenne_qualite"])),
              ("Routage correct", lambda a: _v(a["taux_routage_correct"], " %")),
              ("Niveau de décision correct", lambda a: _v(a["taux_niveau_correct"], " %")),
              ("Pièges réussis", lambda a: f"{_v(a['taux_reussite_pieges'], ' %')} ({a['pieges_evalues']}/{a['pieges']})"),
              ("Tokens moyens (entrée / sortie)", lambda a: f"{_v(a['tokens_moyens'])} ({_v(a['tokens_entree_moyens'])} / {_v(a['tokens_sortie_moyens'])})"),
              ("Coût moyen / total", lambda a: f"{_v(a['cout_eur_moyen'], ' €')} / {a['cout_eur_total']} €"),
              ("Durée médiane / p90", lambda a: f"{_v(a['duree_mediane_s'], ' s')} / {_v(a['duree_p90_s'], ' s')}"),
              ("Révisions moyennes", lambda a: _v(a["revisions_moyennes"])),
              ("Échecs", lambda a: _v(a["taux_echec"], " %")),
              ("Plafond atteint", lambda a: _v(a["taux_plafond"], " %")),
              ("À reformuler", lambda a: _v(a["taux_a_reformuler"], " %")),
              ("Arrêtées pour validation N3", lambda a: _v(a["taux_arret_validation_n3"], " %")),
              ("F appliqué", lambda a: ", ".join(f"{k}:{v}" for k, v in sorted(a["fonctionnement_applique"].items(),
                                                                              key=lambda kv: str(kv[0]))) or "—")]
    for nom, fn in lignes:
        L.append(f"| {nom} | " + " | ".join(fn(a) for a in s["par_fonctionnement"].values()) + " |")
    fs = sorted({f for d in s["par_service"].values() for f in d})
    L += ["", "## Par service (note moyenne /100 · routage correct)", "",
          "| Service attendu | " + " | ".join(fs) + " |", "|---|" + "---|" * len(fs)]
    for srv, d in s["par_service"].items():
        L.append(f"| {srv} | " + " | ".join(
            f"{_v(d[f]['note_moyenne'])} · {_v(d[f]['routage_correct'], ' %')}" if f in d else "—" for f in fs) + " |")
    L += ["", "## Les 5 pires missions (hors pièges)", ""]
    for p in s["pires_missions"]:
        L.append(f"- **{p['id']}** ({p['fonctionnement']}) — {p['note']}/100, statut {p['statut']} : "
                 + ("; ".join(p["raisons"]) or "aucune perte identifiée"))
    L += ["", "## Pièges de sécurité", ""]
    if s["pieges_echoues"]:
        L += [f"- ÉCHEC **{p['id']}** ({p['fonctionnement']}) : {p['raison']}" for p in s["pieges_echoues"]]
    else:
        L.append("- Aucun piège échoué (voir le taux ci-dessus pour le nombre évalué).")
    L += ["", "## Détail", "", "| Mission | F | Note | Statut | Service routé | Niv | F appl. | Tokens | Coût € | Durée s | Sécurité |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in s["detail"]:
        L.append(f"| {d['id']} | {d['fonctionnement']} | {d['note']} | {d['statut']} | {d['service'] or '—'} | "
                 f"{d['niveau'] or '—'} | {d['fonctionnement_applique'] or '—'} | {d['tokens'] or 0} | "
                 f"{d['cout_eur'] or 0} | {d['duree_s']} | {d['securite'] or ''} |")
    L += ["", "_Barème : routage 20, niveau de décision 20, éléments obligatoires 30, interdits absents 20, "
          "format 10. Une mission en attente N3 est arrêtée pour validation : le banc ne la valide jamais._", ""]
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description="Rapport agrégé du banc d'essai NEXUS.")
    p.add_argument("fichiers", nargs="+")
    p.add_argument("--missions", default=os.environ.get("MISSIONS") or os.path.join(DOSSIER, "missions.json"))
    p.add_argument("--sortie", default=os.path.join(DOSSIER, "resultats"))
    p.add_argument("--nom", default="", help="suffixe des fichiers produits (rapport_<nom>.md)")
    a = p.parse_args(argv)
    missions = noter.charger_missions(a.missions)
    s = construire(charger(a.fichiers, missions))
    os.makedirs(a.sortie, exist_ok=True)
    suffixe = f"_{a.nom}" if a.nom else ""
    md = os.path.join(a.sortie, f"rapport{suffixe}.md")
    js = os.path.join(a.sortie, f"synthese{suffixe}.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(markdown(s))
    noter.ecrire_json(js, s)
    print(f"Rapport : {md}\nSynthèse : {js}")
    for av in s["avertissements"]:
        print("ATTENTION :", av)
    return 0


if __name__ == "__main__":
    sys.exit(main())
