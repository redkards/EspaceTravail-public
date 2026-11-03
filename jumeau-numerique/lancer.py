"""Exécute tous les scénarios du jumeau numérique SYFER V2 et produit les résultats.

Usage : python3 lancer.py [--tirages 200] [--jours 30] [--graine 2026] [--sensibilite 24] [--rapide]
Sorties : resultats/resultats.json, resultats/rapport.md, resultats/*.png (ou *.svg sans matplotlib).
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import time

import jumeau as J

ICI = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ICI, "resultats")
# Scénarios de conception (candidats à la recommandation) ; les autres sont des tests de stress.
CONCEPTION = ["S1", "S1L", "S2", "S2L", "S3", "S4", "S5", "S6", "S7", "S13", "S14", "S16"]
TRACES = ["S4", "S8", "S11"]
# Palette catégorielle validée (skill dataviz, palette de référence, mode clair)
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
ENCRE, ENCRE2, GRILLE, FOND = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"


def fmt_duree(s):
    if s is None:
        return "—"
    if s < 90:
        return f"{s:.0f} s"
    if s < 5400:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"


def m(res, cle, champ="moy"):
    v = res.get(cle)
    return None if v is None else v[champ]


# --------------------------------------------------------------------------- calculs

def executer_tout(hyp, scenarios, tirages, jours, base, pool):
    resultats = {}
    for sc in scenarios:
        t0 = time.time()
        runs = J.monte_carlo(sc, hyp, tirages, base, jours, pool)
        resultats[sc["id"]] = {"scenario": {k: v for k, v in sc.items()}, "resume": J.resumer(runs)}
        r = resultats[sc["id"]]["resume"]
        print(f"  {sc['id']:4} {sc['nom']:26} {time.time() - t0:5.1f} s  livrées/j {r['livrees_jour']['moy']:5.1f}  "
              f"p90 F2 {fmt_duree(m(r['delai_p90'], 'F2')):>7}  coût {r['cout_total_eur']['moy']:6.1f} €  "
              f"score {r['score']['moy']:5.1f}", flush=True)
    return resultats


POIDS_PANNE = 0.25


def variante_panne(sc):
    """Même conception avec le cloud gratuit en panne du jour 5 au jour 15 (sans objet si pas de cloud)."""
    if not sc["cloud_gratuit"]:
        return None
    v = dict(sc)
    v["panne_cloud_debut_j"], v["panne_cloud_duree_j"] = 5, 10
    return v


def robustesse(hyp, scenarios, tirages, jours, base, pool, resultats):
    """Score robuste = 0,75 × score nominal + 0,25 × score avec 10 jours de panne du cloud gratuit."""
    for sc in scenarios:
        if sc["id"] not in CONCEPTION:
            continue
        r = resultats[sc["id"]]["resume"]
        v = variante_panne(sc)
        if v is None:
            panne = r["score"]["moy"]
        else:
            runs = J.monte_carlo(v, hyp, tirages, base, jours, pool)
            panne = sum(x["score"] for x in runs) / len(runs)
        r["score_panne_cloud"] = panne
        r["score_robuste"] = (1 - POIDS_PANNE) * r["score"]["moy"] + POIDS_PANNE * panne


def recommander(resultats):
    """Meilleur score robuste parmi les scénarios de conception, sous contraintes ; à 1 point près, le moins cher."""
    eligibles = []
    for sid in CONCEPTION:
        r = resultats[sid]["resume"]
        if r["cout_total_eur"]["p90"] <= 150 and r["ram_ok_part"] >= 0.95:
            eligibles.append((r["score_robuste"], -r["cout_total_eur"]["moy"], sid))
    eligibles.sort(reverse=True)
    meilleur = eligibles[0][0]
    proches = [e for e in eligibles if e[0] >= meilleur - 1.0]
    choix = max(proches, key=lambda e: (e[1], e[0]))[2]
    classement = [e[2] for e in eligibles]
    return choix, classement


CAPACITE_SC = ["S1L", "S2", "S3", "S5", "S13", "S16"]
CHARGES = [1, 3, 6, 10, 15, 25, 40]


def capacite(hyp, scenarios, tirages, jours, base, pool):
    """Rampe de charge : missions/jour soutenables = débit max tant que p90 d'attente (jour) ≤ 1 h
    et part livrée ≥ (part livrée à ×1) − 5 points."""
    par_id = {s["id"]: s for s in scenarios}
    res = {}
    for sid in CAPACITE_SC:
        points = []
        for c in CHARGES:
            runs = J.monte_carlo(dict(par_id[sid], charge=c), hyp, tirages, base, jours, pool)
            pt = {"charge": c,
                  "livrees_jour": sum(r["livrees_jour"] for r in runs) / len(runs),
                  "attente_p90_s": sum(r["attente_p90_s"] for r in runs) / len(runs),
                  "ratio": sum(r["ratio_livraison"] for r in runs) / len(runs),
                  "cpu_llm": sum(r["cpu_llm"] for r in runs) / len(runs)}
            points.append(pt)
        ref = points[0]["ratio"]
        for pt in points:
            pt["soutenable"] = pt["attente_p90_s"] <= 3600 and pt["ratio"] >= ref - 0.05
        ok = [p["livrees_jour"] for p in points if p["soutenable"]]
        res[sid] = {"points": points, "soutenable_jour": max(ok) if ok else 0.0,
                    "sature_au_dela": not points[-1]["soutenable"]}
        print(f"  capacité {sid:4} ≈ {res[sid]['soutenable_jour']:.0f} missions/jour soutenables", flush=True)
    return res


def _score_moyen(args):
    """Score robuste moyen (nominal et panne cloud) pour un jeu de surcharges."""
    sc, hyp, tirages, base, jours, surch = args
    v = variante_panne(sc)
    total = 0.0
    for i in range(tirages):
        nominal = J.simuler(sc, hyp, i, base, jours, surcharges=surch)["score"]
        panne = J.simuler(v, hyp, i, base, jours, surcharges=surch)["score"] if v else nominal
        total += (1 - POIDS_PANNE) * nominal + POIDS_PANNE * panne
    return total / tirages


def sensibilite(hyp, scenarios, candidats, tirages, jours, base, pool):
    """Tornade : chaque hypothèse fixée à son min puis à son max (les autres restent tirées au hasard)."""
    par_id = {s["id"]: s for s in scenarios}
    params = [k for k, d in sorted(hyp["parametres"].items()) if d["max"] > d["min"]]
    taches, cles = [], []
    for sid in candidats:
        taches.append((par_id[sid], hyp, tirages, base, jours, None))
        cles.append((sid, None, None))
        for p in params:
            for borne in ("min", "max"):
                taches.append((par_id[sid], hyp, tirages, base, jours, {p: hyp["parametres"][p][borne]}))
                cles.append((sid, p, borne))
    scores = pool.map(_score_moyen, taches, chunksize=2) if pool else [_score_moyen(t) for t in taches]
    table = {}
    for (sid, p, borne), s in zip(cles, scores):
        table.setdefault(p or "_base", {}).setdefault(sid, {})[borne or "base"] = s
    base_sc = {sid: table["_base"][sid]["base"] for sid in candidats}
    lignes = []
    for p in params:
        gagnant = {b: max(candidats, key=lambda sid: table[p][sid][b]) for b in ("min", "max")}
        tete = candidats[0]
        ecart = abs(table[p][tete]["max"] - table[p][tete]["min"])
        ecart_max = max(abs(table[p][sid]["max"] - table[p][sid]["min"]) for sid in candidats)
        lignes.append({"parametre": p, "gagnant_min": gagnant["min"], "gagnant_max": gagnant["max"],
                       "change_conclusion": gagnant["min"] != tete or gagnant["max"] != tete,
                       "delta_score_recommande": ecart, "delta_score_max": ecart_max,
                       "scores": table[p], "min": hyp["parametres"][p]["min"], "max": hyp["parametres"][p]["max"],
                       "unite": hyp["parametres"][p]["unite"]})
    lignes.sort(key=lambda l: (l["change_conclusion"], l["delta_score_recommande"]), reverse=True)
    return {"candidats": candidats, "tirages": tirages, "base": base_sc, "parametres": lignes}


# --------------------------------------------------------------------------- graphiques

def graphiques(resultats, ordre, jours, cap=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return graphiques_svg(resultats, ordre)
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRILLE, "axes.labelcolor": ENCRE2,
                         "xtick.color": ENCRE2, "ytick.color": ENCRE2, "text.color": ENCRE,
                         "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": FOND,
                         "axes.facecolor": FOND, "savefig.facecolor": FOND})
    noms = [f"{sid} · {resultats[sid]['scenario']['nom']}" for sid in ordre]
    y = list(range(len(ordre)))[::-1]
    fichiers = []

    def finir(fig, nom):
        fig.tight_layout()
        chemin = os.path.join(RES, nom)
        fig.savefig(chemin, dpi=130)
        plt.close(fig)
        fichiers.append(nom)

    # 1. Débit
    fig, ax = plt.subplots(figsize=(8.5, 6.5))
    for yi, sid in zip(y, ordre):
        r = resultats[sid]["resume"]["livrees_jour"]
        ax.barh(yi, r["moy"], height=0.6, color=C1)
        ax.plot([r["p10"], r["p90"]], [yi, yi], color=ENCRE, lw=1.2)
        ax.text(r["p90"] + 0.2, yi, f"{r['moy']:.1f}", va="center", fontsize=8, color=ENCRE2)
    ax.set_yticks(y, noms, fontsize=8)
    ax.set_xlabel("missions livrées par jour (moyenne, trait = p10–p90)")
    ax.set_title("Débit par scénario (30 jours × 200 tirages)", loc="left")
    ax.grid(axis="x", color=GRILLE, lw=0.6)
    finir(fig, "debit.png")

    # 2. Délais p50/p90 F2 et F3 (missions de jour)
    fig, axes = plt.subplots(1, 2, figsize=(10, 6.5), sharey=True)
    for ax, f in zip(axes, ("F2", "F3")):
        for yi, sid in zip(y, ordre):
            r = resultats[sid]["resume"]
            p50, p90 = m(r["delai_p50"], f), m(r["delai_p90"], f)
            if p50 is None:
                continue
            ax.plot([p50 / 60, p90 / 60], [yi, yi], color=GRILLE, lw=2, zorder=1)
            ax.scatter([p50 / 60], [yi], s=36, color=C1, zorder=2, label="p50" if yi == y[0] else None)
            ax.scatter([p90 / 60], [yi], s=36, color=C2, zorder=2, label="p90" if yi == y[0] else None)
        ax.set_xscale("log")
        ax.axvline(J.charger_hypotheses()["fixes"]["fonctionnement"][f]["delai_max_s"] / 60, color=ENCRE2, lw=0.8,
                   ls="--")
        ax.set_title(f"{f} — délai arrivée → livrable (min)", loc="left", fontsize=10)
        ax.grid(axis="x", color=GRILLE, lw=0.6)
    axes[0].set_yticks(y, noms, fontsize=8)
    axes[0].legend(frameon=False, loc="lower right")
    fig.suptitle("Délais de bout en bout des missions de jour (tiret = chrono max du niveau)", x=0.01, ha="left")
    finir(fig, "delais.png")

    # 3. Coût vs score
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for sid in ordre:
        r = resultats[sid]["resume"]
        couleur = C1 if sid in CONCEPTION else C2
        ax.scatter(r["cout_total_eur"]["moy"], r["score"]["moy"], s=50, color=couleur, edgecolor=FOND, lw=1.5,
                   zorder=3)
        ax.plot([r["cout_total_eur"]["moy"]] * 2, [r["score"]["p10"], r["score"]["p90"]], color=couleur, lw=1,
                alpha=0.6)
        ax.annotate(sid, (r["cout_total_eur"]["moy"], r["score"]["moy"]), xytext=(5, 3),
                    textcoords="offset points", fontsize=8, color=ENCRE2)
    ax.scatter([], [], color=C1, label="conception")
    ax.scatter([], [], color=C2, label="test de stress")
    ax.axvline(100, color=ENCRE2, lw=0.8, ls="--")
    ax.axvline(150, color=ENCRE2, lw=0.8, ls=":")
    ax.text(101, ax.get_ylim()[0] + 1, "budget 100 €", fontsize=8, color=ENCRE2)
    ax.text(151, ax.get_ylim()[0] + 1, "max 150 €", fontsize=8, color=ENCRE2)
    ax.set_xlabel("coût total €/mois (serveur + API payante)")
    ax.set_ylabel("score composite (0–100)")
    ax.set_title("Coût mensuel et score de performance", loc="left")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(color=GRILLE, lw=0.6)
    finir(fig, "cout_score.png")

    # 4. Charge du Décideur (petits multiples, pas de double axe)
    fig, axes = plt.subplots(1, 3, figsize=(11, 6.5), sharey=True)
    for ax, (cle, titre, coul) in zip(axes, (("n3_jour", "fiches N3 par jour", C1),
                                           ("decisions_expirees", "décisions expirées (30 j)", C2),
                                           ("part_au_dessus_plafond", "part au-dessus du plafond 15/j", C3))):
        for yi, sid in zip(y, ordre):
            r = resultats[sid]["resume"][cle]
            v = r["moy"] * (100 if cle.startswith("part") else 1)
            ax.barh(yi, v, height=0.6, color=coul)
            ax.text(v, yi, f" {v:.1f}" + (" %" if cle.startswith("part") else ""), va="center", fontsize=7,
                    color=ENCRE2)
        ax.set_title(titre, loc="left", fontsize=10)
        ax.grid(axis="x", color=GRILLE, lw=0.6)
    axes[0].set_yticks(y, noms, fontsize=8)
    fig.suptitle("Charge du Décideur (sessions 12:30 et 19:00, expiration 24 h)", x=0.01, ha="left")
    finir(fig, "decideur.png")

    # 5. File d'attente heure par heure sur 7 jours
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for sid, coul in zip(TRACES, (C1, C2, C3)):
        tr = resultats[sid]["resume"].get("trace_file")
        if not tr:
            continue
        x = list(range(len(tr["moy"])))
        ax.fill_between(x, tr["p10"], tr["p90"], color=coul, alpha=0.15, lw=0)
        ax.plot(x, tr["moy"], color=coul, lw=2, label=f"{sid} · {resultats[sid]['scenario']['nom']}")
    jours_noms = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    ax.set_xticks([24 * i for i in range(7)], jours_noms)
    ax.set_xlabel("heure (semaine 1, début lundi 00:00)")
    ax.set_ylabel("missions en attente de place")
    ax.set_title("File d'attente heure par heure (moyenne, bande p10–p90)", loc="left")
    ax.legend(frameon=False)
    ax.grid(color=GRILLE, lw=0.6)
    finir(fig, "file_7j.png")

    # 6. Capacité : livrées/jour vs p90 d'attente selon la charge
    if cap:
        fig, ax = plt.subplots(figsize=(9, 5))
        couleurs = [C1, C2, C3, "#eda100", "#e87ba4", "#008300"]
        for (sid, c), coul in zip(cap.items(), couleurs):
            xs = [p["livrees_jour"] for p in c["points"]]
            ys = [max(1.0, p["attente_p90_s"]) / 60 for p in c["points"]]
            ax.plot(xs, ys, color=coul, lw=2, marker="o", ms=5, label=f"{sid} · {resultats[sid]['scenario']['nom']}")
        ax.axhline(60, color=ENCRE2, lw=0.8, ls="--")
        ax.text(ax.get_xlim()[0] + 1, 66, "seuil soutenable : 1 h", fontsize=8, color=ENCRE2)
        ax.set_yscale("log")
        ax.set_xlabel("missions livrées par jour (charge manuelle ×1 à ×40)")
        ax.set_ylabel("p90 attente en file, missions de jour (min)")
        ax.set_title("Capacité : quand la file explose", loc="left")
        ax.legend(frameon=False, fontsize=8)
        ax.grid(color=GRILLE, lw=0.6)
        finir(fig, "capacite.png")
    return fichiers


def graphiques_svg(resultats, ordre):
    """Repli sans matplotlib : graphique de débit en SVG écrit à la main."""
    h = 24 * len(ordre) + 60
    vmax = max(resultats[s]["resume"]["livrees_jour"]["p90"] for s in ordre) * 1.1
    parties = [f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{h}" font-family="sans-serif" '
               f'font-size="11"><rect width="100%" height="100%" fill="{FOND}"/>'
               f'<text x="10" y="20" fill="{ENCRE}">Débit par scénario (missions livrées/jour)</text>']
    for i, sid in enumerate(ordre):
        r = resultats[sid]["resume"]["livrees_jour"]
        yv, w = 40 + 24 * i, 480 * r["moy"] / vmax
        parties.append(f'<text x="10" y="{yv + 12}" fill="{ENCRE2}">{sid}</text>'
                       f'<rect x="200" y="{yv}" width="{w:.1f}" height="16" rx="3" fill="{C1}"/>'
                       f'<text x="{205 + w:.1f}" y="{yv + 12}" fill="{ENCRE2}">{r["moy"]:.1f}</text>')
    parties.append("</svg>")
    with open(os.path.join(RES, "debit.svg"), "w", encoding="utf-8") as f:
        f.write("".join(parties))
    return ["debit.svg"]


# --------------------------------------------------------------------------- rapport

def rapport(hyp, resultats, ordre, choix, classement, sens, calage, args, fichiers, cap=None):
    L = []
    L.append("# Jumeau numérique SYFER V2 — rapport de simulation\n")
    L.append(f"{len(ordre)} scénarios × {args.tirages} tirages Monte Carlo × {args.jours} jours simulés, "
             f"graine {args.graine}. Toutes les valeurs : moyenne [p10 – p90] sur les tirages. "
             "Les délais concernent les missions de jour (manuelles et pilote) : les missions de nuit attendent "
             "volontairement leur fenêtre.\n")
    L.append("## Calage sur les mesures réelles (KVM 2, qwen2.5:3b, 1,1 vCPU)\n")
    L.append("| Mission | Durée simulée | Mesurée | Tokens simulés | Mesurés |")
    L.append("|---|---|---|---|---|")
    for c in calage:
        L.append(f"| {c['mission']} | {c['duree_s']:.0f} s ({c['ecart_duree']:+.0%}) | {c['mesure_s']} s | "
                 f"{c['tokens']} ({c['ecart_tokens']:+.0%}) | {c['mesure_tokens']} |")
    L.append("\n## Tableau des scénarios\n")
    L.append("| Scénario | Livrées/j | p50 F2 | p90 F2 | p90 F3 | Attente file moy. | CPU LLM | RAM pic / P1 | "
             "Plafond atteint | N3/j | Expirées | Tokens/mois local · cloud · payant | Coût €/mois | €/mission | "
             "Qualité | Score | Score panne cloud · robuste |")
    L.append("|" + "---|" * 17)
    for sid in ordre:
        r = resultats[sid]["resume"]
        sc = resultats[sid]["scenario"]
        tok = " · ".join(f"{r[k]['moy'] / 1e6:.2f} M" for k in ("tokens_mois_local", "tokens_mois_cloud",
                                                              "tokens_mois_payant"))
        L.append(
            f"| **{sid}** {sc['nom']} | {r['livrees_jour']['moy']:.1f} [{r['livrees_jour']['p10']:.1f}–"
            f"{r['livrees_jour']['p90']:.1f}] | {fmt_duree(m(r['delai_p50'], 'F2'))} | "
            f"{fmt_duree(m(r['delai_p90'], 'F2'))} [{fmt_duree(m(r['delai_p90'], 'F2', 'p10'))}–"
            f"{fmt_duree(m(r['delai_p90'], 'F2', 'p90'))}] | {fmt_duree(m(r['delai_p90'], 'F3'))} | "
            f"{fmt_duree(r['attente_moy_s']['moy'])} | {r['cpu_llm']['moy']:.0%} | "
            f"{r['ram_pic_go']['moy']:.1f} / {r['ram_limite_go']:.0f} Go | {r['taux_plafond']['moy']:.1%} | "
            f"{r['n3_jour']['moy']:.1f} | {r['decisions_expirees']['moy']:.1f} | {tok} | "
            f"{r['cout_total_eur']['moy']:.0f} [{r['cout_total_eur']['p10']:.0f}–{r['cout_total_eur']['p90']:.0f}] | "
            f"{r['cout_par_mission_eur']['moy']:.2f} | {r['qualite']['moy']:.0%} | "
            f"**{r['score']['moy']:.1f}** [{r['score']['p10']:.0f}–{r['score']['p90']:.0f}] | "
            + (f"{r['score_panne_cloud']:.1f} · **{r['score_robuste']:.1f}** |" if 'score_robuste' in r else "test de stress |"))
    rc = resultats[choix]["resume"]
    L.append(f"\n## Recommandation : {choix} — {resultats[choix]['scenario']['nom']}\n")
    L.append(f"{resultats[choix]['scenario']['description']}\n")
    L.append(f"Règle : meilleur score robuste (0,75 × nominal + 0,25 × avec 10 jours de panne du cloud gratuit) parmi les scénarios de conception ({', '.join(CONCEPTION)}), avec coût p90 "
             "≤ 150 €/mois et RAM sous la limite P1 dans ≥ 95 % des tirages ; à 1 point près, le moins cher l'emporte.\n")
    L.append("Classement des scénarios éligibles : " + " > ".join(
        f"{s} ({resultats[s]['resume']['score_robuste']:.1f})" for s in classement) + "\n")
    L.append(f"Le scénario retenu livre {rc['livrees_jour']['moy']:.1f} missions/jour, p90 F2 = "
             f"{fmt_duree(m(rc['delai_p90'], 'F2'))}, qualité estimée {rc['qualite']['moy']:.0%}, "
             f"pour {rc['cout_total_eur']['moy']:.0f} €/mois.\n")
    if cap:
        L.append("## Capacité (rampe de charge des missions manuelles)\n")
        L.append("Soutenable = p90 de l'attente en file (missions de jour) ≤ 1 h et part livrée ≥ part livrée à ×1 − 5 points. Cellule : livrées/jour · p90 attente.\n")
        L.append("| Scénario | " + " | ".join(f"×{c}" for c in CHARGES) + " | Soutenable |")
        L.append("|---|" + "---|" * (len(CHARGES) + 1))
        for sid, c in cap.items():
            cel = [f"{p['livrees_jour']:.0f}/j · {fmt_duree(p['attente_p90_s'])}" + ("" if p["soutenable"] else " ✗")
                   for p in c["points"]]
            L.append(f"| {sid} | " + " | ".join(cel) + f" | **≈ {c['soutenable_jour']:.0f}/j**"
                     + (" (limite atteinte)" if c["sature_au_dela"] else " (non saturé)") + " |")
        L.append("")
    L.append("## Sensibilités (tornade)\n")
    L.append(f"Candidats comparés : {', '.join(sens['candidats'])} ; {sens['tirages']} tirages par point. "
             "Chaque hypothèse est fixée à son min puis à son max (les autres restent tirées au hasard) ; score = score "
             "robuste ; « change la conclusion » = un autre candidat obtient le meilleur score.\n")
    L.append("| Hypothèse | Plage | Δ score du 1er candidat | Gagnant au min | Gagnant au max | Conclusion changée |")
    L.append("|---|---|---|---|---|---|")
    for l in sens["parametres"][:15]:
        L.append(f"| `{l['parametre']}` | {l['min']} – {l['max']} {l['unite']} | {l['delta_score_recommande']:.1f} | "
                 f"{l['gagnant_min']} | {l['gagnant_max']} | {'oui' if l['change_conclusion'] else 'non'} |")
    L.append("\n## Score composite\n")
    L.append("score = 100 × (0,30 × Débit + 0,25 × Délai + 0,30 × Qualité + 0,15 × Coût), × 0,5 si la RAM dépasse "
             "la limite P1.\n- Débit = missions livrées / missions arrivées (hors tests fantômes).\n- Délai = 1 si le "
             "p90 F2 ≤ 10 min, 0 si ≥ 4 h, interpolation logarithmique entre les deux.\n- Qualité = part estimée "
             "de livrables « bons » parmi les livrés (modèle : bon 1er jet, détection du CHECKER, fausses alertes, "
             "révisions).\n- Coût = 1 − coût mensuel / 150 € (budget maximum).\n")
    L.append("## Graphiques\n")
    for f in fichiers:
        L.append(f"![{f}]({f})")
    L.append("\n## Limites — à mesurer en réel pour confirmer\n")
    L.append("- Vitesse réelle d'un 7–8B (prefill et génération) sur KVM 4 / KVM 8 : seules deux missions 3B sont "
             "mesurées ; l'extrapolation vCPU/taille repose sur des exposants supposés.\n"
             "- Qualité par modèle (bon 1er jet, sensibilité et fausses alertes du CHECKER) : hypothèses ordonnées "
             "par taille ; à mesurer avec le banc d'essai (noter.py) sur 3B, 7B, 8B, cloud gratuit, Haiku, Sonnet.\n"
             "- Quota, latence et pannes réelles d'Ollama Cloud gratuit (limites non publiées en chiffres).\n"
             "- Volume réel de missions manuelles et part de N3 (publication/envoi) ; prix Hostinger réels.\n"
             "- Le jumeau ne modélise ni la mémoire SQLite/PostgreSQL, ni n8n, ni la passerelle MCP (charge "
             "supposée faible, incluse dans la RAM de base).\n")
    with open(os.path.join(RES, "rapport.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# --------------------------------------------------------------------------- principal

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tirages", type=int, default=200)
    ap.add_argument("--jours", type=int, default=30)
    ap.add_argument("--graine", type=int, default=2026)
    ap.add_argument("--sensibilite", type=int, default=24, help="tirages par point de la tornade (0 = sans)")
    ap.add_argument("--candidats", type=int, default=5, help="nombre de scénarios comparés dans la tornade")
    ap.add_argument("--rapide", action="store_true", help="20 tirages, tornade 6 tirages (essai)")
    ap.add_argument("--processus", type=int, default=os.cpu_count() or 1)
    args = ap.parse_args(argv)
    if args.rapide:
        args.tirages, args.sensibilite = 20, 6
    os.makedirs(RES, exist_ok=True)
    hyp = J.charger_hypotheses()
    scenarios = J.charger_scenarios()
    ordre = [s["id"] for s in scenarios]
    calage = J.calage(J.tirer_parametres(hyp, None), hyp["fixes"])
    t0 = time.time()
    pool = mp.Pool(args.processus) if args.processus > 1 else None
    try:
        print(f"Simulation : {len(scenarios)} scénarios × {args.tirages} tirages × {args.jours} jours")
        resultats = executer_tout(hyp, scenarios, args.tirages, args.jours, args.graine, pool)
        print("Robustesse : variantes avec 10 jours de panne du cloud gratuit")
        robustesse(hyp, scenarios, args.tirages, args.jours, args.graine, pool, resultats)
        choix, classement = recommander(resultats)
        print("Capacité : rampe de charge")
        cap = capacite(hyp, scenarios, max(10, args.tirages // 10), args.jours, args.graine, pool)
        sens = {"candidats": [], "tirages": 0, "parametres": []}
        if args.sensibilite:
            candidats = [choix] + [s for s in classement if s != choix][:args.candidats - 1]
            print(f"Sensibilité : {len(candidats)} candidats × {len(hyp['parametres'])} hypothèses × 2 bornes")
            sens = sensibilite(hyp, scenarios, candidats, args.sensibilite, args.jours, args.graine, pool)
    finally:
        if pool:
            pool.close()
            pool.join()
    fichiers = graphiques(resultats, ordre, args.jours, cap)
    sortie = {"parametres_execution": vars(args), "duree_calcul_s": round(time.time() - t0, 1),
              "calage": calage, "recommandation": choix, "classement": classement,
              "capacite": cap, "sensibilite": sens, "scenarios": resultats}
    with open(os.path.join(RES, "resultats.json"), "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=1)
    rapport(hyp, resultats, ordre, choix, classement, sens, calage, args, fichiers, cap)
    print(f"Recommandation : {choix} ({resultats[choix]['scenario']['nom']}) — {time.time() - t0:.0f} s")
    print("Sensibilités principales : " + ", ".join(l["parametre"] for l in sens["parametres"][:3]))
    return sortie


if __name__ == "__main__":
    main()
