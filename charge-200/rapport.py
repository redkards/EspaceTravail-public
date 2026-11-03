#!/usr/bin/env python3
"""Rapport de la campagne « SYFER à 200 % » : rapport.md + graphiques (matplotlib, sinon SVG minimal).

Usage : python3 rapport.py [resultats/AAAA-MM-JJ_HHMM.json]   (défaut : le plus récent)
L'analyse experte rédigée (analyse.md, à côté de ce fichier) est insérée en tête si elle existe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # palette de référence validée (ordre fixe)
SURFACE, ENCRE, ENCRE2 = "#fcfcfb", "#0b0b0b", "#52514e"


def _r(res, sid):
    return next((r for r in res if r.get("id") == sid), None)


def _fmt(x, n=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{n}f}"
    return str(x)


# ------------------------------------------------------------------ graphiques
def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": "#c9c8c2",
                             "axes.labelcolor": ENCRE2, "xtick.color": ENCRE2, "ytick.color": ENCRE2,
                             "text.color": ENCRE, "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                             "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
                             "lines.linewidth": 2})
        return plt
    except ImportError:
        return None


def _svg_lignes(chemin: Path, titre: str, series: list[tuple[str, list, list]], xl: str, yl: str):
    """Repli sans matplotlib : courbes SVG simples."""
    xs = [x for _, X, _ in series for x in X] or [0, 1]
    ys = [y for _, _, Y in series for y in Y if y is not None] or [0, 1]
    x0, x1, y1 = min(xs), max(xs) or 1, max(ys) or 1
    W, H, m = 640, 360, 50
    sx = lambda x: m + (x - x0) / ((x1 - x0) or 1) * (W - 2 * m)
    sy = lambda y: H - m - y / y1 * (H - 2 * m)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" style="background:{SURFACE}">',
           f'<text x="{m}" y="20" font-size="14" fill="{ENCRE}">{titre}</text>',
           f'<text x="{W/2}" y="{H-10}" font-size="11" fill="{ENCRE2}">{xl}</text>',
           f'<text x="10" y="{H/2}" font-size="11" fill="{ENCRE2}">{yl}</text>']
    for k, (nom, X, Y) in enumerate(series):
        pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(X, Y) if y is not None)
        out.append(f'<polyline fill="none" stroke="{SERIES[k % 4]}" stroke-width="2" points="{pts}"/>')
        out.append(f'<text x="{W-m-150}" y="{40+15*k}" font-size="11" fill="{ENCRE}">■ {nom}</text>'
                   .replace("■", f'<tspan fill="{SERIES[k % 4]}">■</tspan>'))
    out.append("</svg>")
    chemin.write_text("\n".join(out), encoding="utf-8")


def graphiques(doc: dict, dossier: Path) -> list[str]:
    res, faits = doc["resultats"], []
    plt = _plt()
    ext = "png" if plt else "svg"
    rampes = [(sid, _r(res, sid)) for sid in ("S02", "S03")]
    rampes = [(s, r) for s, r in rampes if r and r.get("paliers")]
    # 1. Débit vs charge
    if rampes:
        nom = f"debit_vs_charge.{ext}"
        if plt:
            fig, ax = plt.subplots(figsize=(7, 4))
            mx = 0
            for k, (sid, r) in enumerate(rampes):
                P = r["paliers"]
                X = [p["pct"] for p in P]
                Y = [p["pct_tenu"] * p["pct"] / 100 if p.get("pct_tenu") is not None else None for p in P]
                mx = max(mx, max(X))
                lib = "1 mission à la fois (défaut)" if sid == "S02" else "4 missions simultanées"
                ax.plot(X, Y, marker="o", ms=5, color=SERIES[k], label=f"{sid} — {lib}")
                rup = next((p for p in P if not p.get("tenu")), None)
                if rup:
                    ax.annotate(f"rupture {rup['pct']} %", (rup["pct"], rup["pct_tenu"] * rup["pct"] / 100),
                                textcoords="offset points", xytext=(6, -14), fontsize=8, color=ENCRE2)
            ax.plot([0, mx], [0, mx], color="#a9a8a2", lw=1, ls="--", label="idéal (tout écoulé)")
            ax.set_xlabel("charge offerte (% du pic nominal 15 missions/h)")
            ax.set_ylabel("charge écoulée (% du pic)")
            ax.set_title("Débit écoulé selon la charge offerte", loc="left")
            ax.legend(frameon=False, fontsize=8)
            fig.tight_layout()
            fig.savefig(dossier / nom, dpi=130)
            plt.close(fig)
        else:
            _svg_lignes(dossier / nom, "Débit écoulé selon la charge offerte",
                        [(sid, [p["pct"] for p in r["paliers"]],
                          [(p.get("pct_tenu") or 0) * p["pct"] / 100 for p in r["paliers"]]) for sid, r in rampes],
                        "charge offerte (%)", "écoulée (%)")
        faits.append(nom)
        # 2. Latence vs charge (deux graphiques séparés : pas de double axe)
        nom = f"latence_vs_charge.{ext}"
        if plt:
            fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.6))
            for k, (sid, r) in enumerate(rampes):
                P = r["paliers"]
                X = [p["pct"] for p in P]
                C = r.get("compression") or 1
                a1.plot(X, [(p["e2e_s"]["p95"] or 0) * C / 60 for p in P], marker="o", ms=5, color=SERIES[k],
                        label=sid)
                a2.plot(X, [p["creation_ms"]["p95"] for p in P], marker="o", ms=5, color=SERIES[k], label=sid)
            a1.set_title("p95 bout en bout (min simulées)", loc="left")
            a2.set_title("p95 création POST /api/missions (ms réelles)", loc="left")
            for a in (a1, a2):
                a.set_xlabel("charge offerte (% du pic)")
                a.legend(frameon=False, fontsize=8)
            a1.set_yscale("log")
            fig.tight_layout()
            fig.savefig(dossier / nom, dpi=130)
            plt.close(fig)
        else:
            _svg_lignes(dossier / nom, "p95 création (ms)", [(sid, [p["pct"] for p in r["paliers"]],
                                                            [p["creation_ms"]["p95"] for p in r["paliers"]])
                                                           for sid, r in rampes], "charge (%)", "ms")
        faits.append(nom)
    # 3. Stockage par mission
    cand = [r for r in res if r.get("octets_par_mission") and r.get("id") in ("S04", "S07", "S10", "S12")]
    if cand:
        nom = f"stockage_par_mission.{ext}"
        comp = ["base_octets", "archive_octets", "livrables_octets", "journal_octets"]
        lib = ["base SQLite", "archive gz", "livrables .md", "journal applicatif"]
        if plt:
            fig, ax = plt.subplots(figsize=(7, 3.6))
            larg = 0.8 / len(comp)
            for k, c in enumerate(comp[:3]):
                X = [i + k * larg for i in range(len(cand))]
                ax.bar(X, [r["octets_par_mission"][c] / 1024 for r in cand], width=larg - 0.02,
                       color=SERIES[k], label=lib[k])
            ax.set_xticks([i + larg for i in range(len(cand))], [r["id"] for r in cand])
            ax.set_ylabel("Ko par mission")
            ax.set_title("Stockage consommé par mission (après checkpoint WAL)", loc="left")
            ax.legend(frameon=False, fontsize=8)
            fig.tight_layout()
            fig.savefig(dossier / nom, dpi=130)
            plt.close(fig)
            faits.append(nom)
    # 4. Série temporelle des rafales (file d'attente, pool de fils, disponibilité)
    for sid in ("S05", "S06"):
        r = _r(res, sid)
        if not (r and r.get("serie") and plt):
            continue
        nom = f"serie_{sid}.{ext}"
        S = r["serie"]
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 4.6), sharex=True)
        T = [p["t"] for p in S]
        a1.plot(T, [p.get("file_en_attente") for p in S], color=SERIES[0], label="missions en file")
        a1.plot(T, [p.get("file_pool_occupe") for p in S], color=SERIES[1], label="fils du pool occupés (max 40)")
        a1.axhline(40, color="#a9a8a2", lw=1, ls="--")
        a1.legend(frameon=False, fontsize=8)
        a1.set_title(f"{sid} — {r['nom']}", loc="left", fontsize=9)
        a2.plot(T, [p.get("rss_mo") for p in S], color=SERIES[2], label="RSS nexus-core (Mo)")
        a2.legend(frameon=False, fontsize=8)
        a2.set_xlabel("temps (s réelles)")
        fig.tight_layout()
        fig.savefig(dossier / nom, dpi=130)
        plt.close(fig)
        faits.append(nom)
    return faits


# ------------------------------------------------------------------ Markdown
def rapport_md(doc: dict, images: list[str]) -> str:
    res = doc["resultats"]
    L = []
    analyse = ICI / "analyse.md"
    L.append("# Campagne « SYFER à 200 % » — rapport de charge\n")
    m = doc.get("machine", {})
    L.append(f"Campagne du **{doc['date']}** · durée {doc['duree_totale_s'] / 60:.1f} min · machine de test "
             f"{m.get('cpu')} vCPU / {m.get('ram_go')} Go (≈ VPS KVM 2) · Python {m.get('python')} · SQLite "
             f"{m.get('sqlite')} · LLM **factice** (le temps LLM réel vient du jumeau numérique)"
             + (" · mode rapide (durées ÷3)" if doc.get("rapide") else "") + ".\n")
    if analyse.exists():
        L.append(analyse.read_text(encoding="utf-8").strip() + "\n")
    L.append("## Tableau de bord des 25 scénarios\n")
    L.append("| Scénario | Charge | Missions | Débit tenu | p95 création | p95 bout en bout (s réelles) | 5xx | timeouts "
             "| locks | perdues | bloquées | LEDGER | archive | secrets | Résultat |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|")
    for r in res:
        if r.get("saute") or r.get("erreur"):
            L.append(f"| {r['id']} {r['nom']} | | | | | | | | | | | | | | "
                     f"{'SAUTÉ : ' + r['saute'] if r.get('saute') else 'ERREUR : ' + r['erreur'][:80]} |")
            continue
        me, ig = r["mesures"], r["integrite"]
        echecs = [c["critere"] for c in r["criteres"] if c["ok"] is False]
        L.append(f"| {r['id']} {r['nom']} | {r['paliers'][-1].get('pct') or '—'} % | {ig['missions_total']} | "
                 f"{_fmt(me.get('debit_pct_offert'))} % | {_fmt(me.get('p95_creation_ms'), 0)} ms | "
                 f"{_fmt(r['e2e_s']['p95'], 2)} | {me['erreurs_5xx']} | {me['timeouts']} | {me['db_locked']} | "
                 f"{me['missions_perdues']} | {me['bloquees']} | {'✔' if me['ledger_valide'] else '✘'} | "
                 f"{'✔' if me['archive_valide'] else '✘'} | {me['secrets_stockes']} | "
                 f"{'réussi' if r['reussi'] else 'ÉCHEC : ' + ', '.join(echecs)} |")
    L.append("")
    for im in images:
        L.append(f"![{im}]({im})\n")
    # Paliers des montées
    for sid in ("S02", "S03"):
        r = _r(res, sid)
        if not r or not r.get("paliers"):
            continue
        C = r.get("compression") or 1
        L.append(f"### {sid} — {r['nom']}\n")
        L.append("| Palier | Offertes | Écoulées dans le palier | Débit simulé (missions/h) | p95 création (ms) | "
                 "p95 bout en bout (min simulées) | File max | Dispo. /api/sante | Tenu |")
        L.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for p in r["paliers"]:
            e = p["e2e_s"]["p95"]
            L.append(f"| {p['pct']} % | {p['offert']} | {_fmt(p['pct_tenu'])} % | {_fmt(p['debit_sim_h'])} | "
                     f"{_fmt(p['creation_ms']['p95'], 0)} | {_fmt(e * C / 60 if e else None)} | {_fmt(p['file_max'])} | "
                     f"{_fmt(p['disponibilite'], 3)} | {'oui' if p['tenu'] else '**non**'} |")
        L.append("")
    # Détails par scénario
    L.append("## Détails par scénario\n")
    for r in res:
        if r.get("saute") or r.get("erreur"):
            continue
        me, ig = r["mesures"], r["integrite"]
        L.append(f"### {r['id']} — {r['nom']}\n")
        L.append(f"- Compression ×{r['compression']:g} · LLM factice {r['llm']['latence_s'] * 1000:.0f} ms/appel "
                 f"(×{r['llm']['multiplicateur']}, échecs {r['llm']['taux_echec']:.0%}) · durée {r['duree_reelle_s']} s · "
                 f"démarrage {r['demarrage_s']} s · vidange {r['vidange']['apres_charge_s']} s")
        L.append(f"- Missions : {ig['missions_total']} (statuts {ig['statuts']}) · envoyées {ig['missions_envoyees']}, "
                 f"acceptées 202 {ig['missions_acceptees_202']}, créées sans accusé {ig['creees_sans_accuse']}, "
                 f"doublons double clic {ig.get('doublons_double_clic', 0)}")
        L.append(f"- Bout en bout (s réelles) : p50 {_fmt(r['e2e_s']['p50'], 2)} · p95 {_fmt(r['e2e_s']['p95'], 2)} · "
                 f"p99 {_fmt(r['e2e_s']['p99'], 2)} ; attente en file p95 {_fmt(r['attente_file_s']['p95'], 2)} ; "
                 f"service p95 {_fmt(r['service_s']['p95'], 2)}")
        if r.get("e2e_par_f_s"):
            L.append("- Par niveau F (p50/p95 s réelles) : " + " · ".join(
                f"{k} {_fmt(v['p50'], 2)}/{_fmt(v['p95'], 2)} (n={v['n']})" for k, v in r["e2e_par_f_s"].items()))
        L.append(f"- Erreurs : {me['erreurs_par_type'] or 'aucune'} · « database is locked » {me['db_locked']} · "
                 f"traces Python au journal {me['traces_log']} · disponibilité {_fmt(me.get('disponibilite'), 4)}")
        L.append(f"- Ressources : RSS {_fmt(me.get('rss_debut_mo'))} → {_fmt(me.get('rss_max_mo'))} Mo · CPU moy. "
                 f"{_fmt(me.get('cpu_moy_pct'))} % / max {_fmt(me.get('cpu_max_pct'))} % · fils max {me.get('fils_max')} · "
                 f"pool occupé max {me.get('pool_occupe_max')}/40 · file max {me.get('file_max')}")
        st, opm = r["stockage"], r["octets_par_mission"]
        L.append(f"- Stockage : base {st['base_octets'] / 1024:.0f} Ko (WAL avant checkpoint "
                 f"{ig.get('wal_avant_checkpoint_octets', 0) / 1024:.0f} Ko), archive {st['archive_octets'] / 1024:.0f} Ko, "
                 f"livrables {st['livrables_octets'] / 1024:.0f} Ko, journal {st['journal_octets'] / 1024:.0f} Ko · par "
                 f"mission : base {opm['base_octets'] / 1024:.1f} Ko, archive {opm['archive_octets'] / 1024:.1f} Ko")
        L.append(f"- Intégrité : LEDGER {ig['ledger_entrees']} entrées {'valide' if ig['ledger_valide'] else 'INVALIDE'} "
                 f"(API : {_fmt(me.get('ledger_verif_api_s'), 2)} s) · archive {ig['archive_lignes_fichier']} lignes / "
                 f"{ig['archive_index']} index, {'valide' if ig['archive_valide'] else 'INVALIDE'} · compteurs tokens "
                 f"{'exacts' if ig['compteurs_exacts'] else 'ÉCART'} ({ig['tokens_missions']} / {ig['tokens_etapes']} / "
                 f"{ig['tokens_compteur']:.0f}) · décisions/jour {ig['decisions_par_jour']} · N3 en file sans fiche "
                 f"{ig['n3_en_file_sans_fiche']} · secrets {ig['secrets_detail'] or 0}")
        spec = {k: me[k] for k in ("double_clic_ok", "missions_double_clic_creees", "double_clic_mission_doublons",
                                   "sauvegardes", "sauvegarde_duree_max_s", "sauvegarde_valide", "veille_insertions",
                                   "veille_indisponible_log", "effacements", "effacements_ok", "redemarrage_s",
                                   "reprise_ok", "pieges_signales") if k in me and me[k] is not None}
        if spec:
            L.append(f"- Spécifique : {spec}")
        if r.get("extra", {}).get("double_clic"):
            L.append(f"- Double clic décisions : {r['extra']['double_clic']}")
        lentes = sorted(((k, v) for k, v in r["par_route"].items() if v["n"] >= 5), key=lambda kv: -(kv[1]["p95"] or 0))[:6]
        if lentes:
            L.append("- Routes (p50/p95/p99 ms, n) : " + " · ".join(
                f"`{k}` {_fmt(v['p50'], 0)}/{_fmt(v['p95'], 0)}/{_fmt(v['p99'], 0)} ({v['n']})" for k, v in lentes))
        if r.get("notes"):
            L.append(f"- Notes : {'; '.join(r['notes'])}")
        echecs = [c for c in r["criteres"] if c["ok"] is False]
        txt = "; ".join(f"{c['critere']} attendu {c['attendu']} obtenu {c['obtenu']}" for c in echecs)
        L.append(f"- Critères : {txt or 'tous respectés'}\n")
    return "\n".join(L)


def produire(doc: dict, dossier: Path) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    images = graphiques(doc, dossier)
    f = dossier / "rapport.md"
    f.write_text(rapport_md(doc, images), encoding="utf-8")
    return f


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted((ICI / "resultats").glob("*.json"))[-1]
    print(produire(json.loads(src.read_text(encoding="utf-8")), src.parent))
