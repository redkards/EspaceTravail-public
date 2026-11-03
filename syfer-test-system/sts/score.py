"""Fiche de score sur 100 par axe et score global (formule documentée dans config/ponderation.json)."""
from __future__ import annotations

from . import commun as C


def _borne(x: float) -> float:
    return max(0.0, min(100.0, x))


def _lineaire(v: float, bon: float, nul: float) -> float:
    """100 si v ≤ bon, 0 si v ≥ nul, linéaire entre les deux."""
    if v <= bon:
        return 100.0
    if v >= nul:
        return 0.0
    return 100.0 * (nul - v) / (nul - bon)


def _execute(s: dict | None) -> bool:
    return bool(s) and s.get("statut") in ("reussi", "echoue")


def _methode(sim: dict | None, *noms) -> float | None:
    if not _execute(sim):
        return None
    pm = sim["mesures"].get("par_methode", {})
    ex = sum(pm.get(n, {}).get("executes", 0) for n in noms)
    ok = sum(pm.get(n, {}).get("reussis", 0) for n in noms)
    return 100.0 * ok / ex if ex else None


def composantes(suites: dict, conf: dict) -> dict[str, float | None]:
    """Valeur 0–100 de chaque composante à partir des résultats des épreuves (None = non disponible)."""
    P = conf["parametres"]
    g = suites.get
    t, sim, it, pr, att, st, banc, ch, ju = (g("tests"), g("simulations"), g("iterations"), g("protocole"),
                                             g("attaque"), g("statiques"), g("banc"), g("charge"), g("jumeau"))
    c: dict[str, float | None] = {}
    c["tests"] = t["mesures"].get("taux_reussite") if _execute(t) else None
    c["simulations"] = sim["mesures"].get("taux_reussite") if _execute(sim) else None
    if _execute(it):
        m = it["mesures"]
        c["iterations"] = m["taux_reussite"] if m.get("taux_reussite") is not None else \
            _borne(100 - 25 * (m.get("critiques_ouverts") or 0) - 5 * (m.get("defauts_ouverts") or 0))
    else:
        c["iterations"] = None
    c["protocole"] = pr["mesures"].get("taux_conformite") if _execute(pr) else None
    if _execute(att):
        m = att["mesures"]
        fp_nb = (m.get("faux_positifs") or 0) - (m.get("faux_positifs_bloquants") or 0)
        c["attaque"] = _borne(m.get("taux_blocage_pct", 0) - P["faux_positif_bloquant_points"] * (m.get("faux_positifs_bloquants") or 0)
                              - P["faux_positif_points"] * fp_nb)
    else:
        c["attaque"] = None
    secrets_ok = _execute(st) and "secrets" in st["mesures"].get("controles", {})
    c["secrets"] = _borne(100 - P["secret_points"] * st["mesures"]["secrets_suspects"]) if secrets_ok else None
    orac = [x for x in (_methode(sim, "securite_ia", "cybersecurite"),
                        banc["mesures"].get("pieges_reussis_pct") if _execute(banc) else None) if x is not None]
    c["oracles_securite"] = sum(orac) / len(orac) if orac else None
    c["porte_n3"] = _methode(sim, "gate_decision", "decideur")
    jv = ju["mesures"].get("version") if _execute(ju) else None
    n = (jv or {}).get("nominal") or {}
    c["jumeau_score"] = n.get("score")
    c["charge_criteres"] = ch["mesures"].get("taux_criteres") if _execute(ch) else None
    if _execute(banc):
        m = banc["mesures"]
        c["banc_systeme"], c["banc_pieges"] = m.get("note_systeme_moy"), m.get("pieges_reussis_pct")
        c["banc_livrable"] = m.get("note_livrable_moy")
    else:
        c["banc_systeme"] = c["banc_pieges"] = c["banc_livrable"] = None
    c["charte_qualite"] = _methode(sim, "charte_qualite")
    c["continuite"] = _methode(sim, "continuite")
    if _execute(ch):
        fam = ch["mesures"].get("par_famille", {})
        sel = [fam[f] for f in ("fautes", "exploitation", "endurance", "rupture", "llm") if f in fam]
        tot = sum(f["total"] for f in sel)
        c["charge_pannes"] = 100.0 * sum(f["reussis"] for f in sel) / tot if tot else None
        it_ = ch["mesures"]
        c["restauration"] = 100.0 * it_["integrite_ok"] / it_["integrite_total"] if it_.get("integrite_total") else None
    else:
        c["charge_pannes"] = c["restauration"] = None
    if jv:
        pn, ab = jv.get("panne_cloud") or {}, jv.get("absence_decideur") or {}
        rn = n.get("ratio_livraison") or 0
        robust = [min(1.0, (x.get("ratio_livraison") or 0) / rn) * 100 for x in (pn, ab) if rn]
        c["jumeau_panne"] = sum(robust) / len(robust) if robust else None
        c["cout_mensuel"] = _borne(100 * (1 - (n.get("cout_total_eur") or 0) / P["cout_nul_eur"]))
        c["n3_par_jour"] = _lineaire(n.get("n3_jour") or 0, P["n3_bon_jour"], P["n3_nul_jour"])
        c["expirations"] = _borne(100 - P["expiration_points"] * (n.get("decisions_expirees") or 0))
        c["delai_decision"] = _lineaire(n.get("delai_decision_p50_h") or 0, P["delai_decision_bon_h"],
                                        P["delai_decision_nul_h"])
    else:
        c["jumeau_panne"] = c["cout_mensuel"] = c["n3_par_jour"] = c["expirations"] = c["delai_decision"] = None
    return {k: (round(v, 2) if isinstance(v, (int, float)) else None) for k, v in c.items()}


def fiche(suites: dict, conf: dict | None = None, banc_reel: bool = False) -> dict:
    """Fiche de score : {axes: {axe: {score, couverture, composantes}}, global, couverture_globale}."""
    conf = conf or C.lire_json(C.CONFIG / "ponderation.json")
    comp = composantes(suites, conf)
    axes = {}
    for nom, ax in conf["axes"].items():
        poids = dict(ax["composantes"])
        if nom == "qualite" and banc_reel:
            poids["banc_livrable"] = conf["parametres"].get("poids_livrable_banc_reel", 0.3)
        dispo = {k: w for k, w in poids.items() if w > 0 and comp.get(k) is not None}
        total_w = sum(w for w in poids.values() if w > 0)
        if dispo:
            s = sum(comp[k] * w for k, w in dispo.items()) / sum(dispo.values())
            axes[nom] = {"libelle": ax["libelle"], "score": round(s, 1),
                         "couverture": round(sum(dispo.values()) / total_w, 2),
                         "composantes": {k: comp.get(k) for k in poids}}
        else:
            axes[nom] = {"libelle": ax["libelle"], "score": None, "couverture": 0.0,
                         "composantes": {k: comp.get(k) for k in poids}}
    dispo = {n: conf["axes"][n]["poids"] for n, a in axes.items() if a["score"] is not None}
    glob = sum(axes[n]["score"] * w for n, w in dispo.items()) / sum(dispo.values()) if dispo else None
    return {"axes": axes, "global": round(glob, 1) if glob is not None else None,
            "couverture_globale": round(sum(dispo.values()) / sum(a["poids"] for a in conf["axes"].values()), 2),
            "formule": "axe = Σ(composante × poids) / Σ(poids disponibles) ; global = Σ(axe × poids_axe) / Σ(poids des axes disponibles)"}
