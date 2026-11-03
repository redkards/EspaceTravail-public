"""Porte de qualité : VERT / ROUGE avec raisons (critères dans config/porte.json)."""
from __future__ import annotations

from . import commun as C

VERT, ROUGE = "VERT", "ROUGE"


def _exec(s):
    return bool(s) and s.get("statut") in ("reussi", "echoue")


def _crit(nom, conf, ok, mesure, absent=False, raison=""):
    if absent:
        etat = "NON ÉVALUÉ"
        bloque = conf.get("bloquant", True) and conf.get("si_absent", "bloquant") == "bloquant"
    else:
        etat = "OK" if ok else "KO"
        bloque = (not ok) and conf.get("bloquant", True)
    return {"critere": nom, "libelle": conf.get("libelle", nom), "etat": etat, "bloque": bloque,
            "mesure": mesure, "raison": raison}


def evaluer(suites: dict, indice_banc: float | None, indice_banc_precedent: float | None,
            conf: dict | None = None) -> dict:
    conf = conf or C.lire_json(C.CONFIG / "porte.json")
    cr = conf["criteres"]
    g = suites.get
    res = []

    def actif(n):
        return cr.get(n, {}).get("actif", False)

    if actif("tests_verts"):
        t = g("tests")
        if not _exec(t):
            res.append(_crit("tests_verts", cr["tests_verts"], False, None, True, "tests non exécutés"))
        else:
            m = t["mesures"]
            ko = m["echoues"] + m["erreurs"]
            dossiers_ko = [d for d, v in m["par_dossier"].items() if v["statut"] in ("echoue", "erreur", "delai")]
            res.append(_crit("tests_verts", cr["tests_verts"], ko == 0 and not dossiers_ko,
                             f"{m['reussis']}/{m['total'] - m['sautes']} verts",
                             "" if ko == 0 and not dossiers_ko else f"{ko} test(s) rouge(s) : {', '.join(dossiers_ko)}"))
    if actif("simulations"):
        s = g("simulations")
        c = cr["simulations"]
        if not _exec(s):
            res.append(_crit("simulations", c, False, None, True, "simulations non exécutées"))
        else:
            tx = s["mesures"]["taux_reussite"]
            res.append(_crit("simulations", c, tx >= c.get("seuil_pct", 99), f"{tx} %",
                             "" if tx >= c.get("seuil_pct", 99) else
                             f"{s['mesures']['echoues']} scénario(s) en échec : {', '.join(s['mesures']['echoues_ids'][:6])}"))
    if actif("iterations_critiques"):
        s = g("iterations")
        c = cr["iterations_critiques"]
        if not _exec(s):
            res.append(_crit("iterations_critiques", c, False, None, True,
                             (s or {}).get("motif") or "itérations non exécutées"))
        else:
            n = s["mesures"].get("critiques_ouverts") or 0
            res.append(_crit("iterations_critiques", c, n <= c.get("max", 0), f"{n} critique(s) ouvert(s)",
                             "" if n <= c.get("max", 0) else f"{n} défaut(s) critique(s) ouvert(s)"))
    if actif("attaque"):
        s = g("attaque")
        c = cr["attaque"]
        if not _exec(s):
            res.append(_crit("attaque", c, False, None, True, "attaque non exécutée"))
        else:
            m = s["mesures"]
            ok = m["taux_blocage_pct"] >= c.get("seuil_pct", 95) and m["faux_positifs_bloquants"] <= c.get("fp_bloquants_max", 0)
            res.append(_crit("attaque", c, ok, f"{m['taux_blocage_pct']} % bloquées, {m['faux_positifs_bloquants']} FP bloquant(s)",
                             "" if ok else "taux de blocage insuffisant ou faux positif bloquant"))
    if actif("secrets"):
        s = g("statiques")
        c = cr["secrets"]
        if not _exec(s) or "secrets" not in s["mesures"].get("controles", {}):
            res.append(_crit("secrets", c, False, None, True, "recherche de secrets non exécutée"))
        else:
            n = s["mesures"]["secrets_suspects"]
            res.append(_crit("secrets", c, n <= c.get("max", 0), f"{n} suspect(s)",
                             "" if n == 0 else f"{n} secret(s) possible(s) dans le dépôt"))
    if actif("banc_regression"):
        c = cr["banc_regression"]
        if indice_banc is None:
            res.append(_crit("banc_regression", c, False, None, True, "banc non exécuté"))
        elif indice_banc_precedent is None:
            res.append(_crit("banc_regression", c, True, f"{indice_banc} (premier passage)", raison="aucun passage précédent"))
        else:
            baisse = round(indice_banc_precedent - indice_banc, 1)
            ok = baisse <= c.get("baisse_max_points", 5)
            res.append(_crit("banc_regression", c, ok, f"{indice_banc} vs {indice_banc_precedent} (Δ {-baisse:+.1f})",
                             "" if ok else f"baisse de {baisse} points"))
    if actif("charge_sans_perte"):
        s = g("charge")
        c = cr["charge_sans_perte"]
        if not _exec(s):
            res.append(_crit("charge_sans_perte", c, False, None, True, (s or {}).get("motif") or "charge non exécutée"))
        else:
            p = s["mesures"]["pertes_donnees"]
            res.append(_crit("charge_sans_perte", c, not p, f"{len(p)} critère(s) d'intégrité KO",
                             "" if not p else "perte/duplication/corruption : " + ", ".join(p[:5])))
    verdict = ROUGE if any(r["bloque"] for r in res) else VERT
    raisons = [f"{r['libelle']} : {r['raison'] or r['etat']}" for r in res if r["bloque"]]
    return {"verdict": verdict, "criteres": res, "raisons": raisons,
            "deploiement_autorise": verdict == VERT}
