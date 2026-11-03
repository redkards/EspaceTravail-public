"""VEILLE SYFER — calibration du classement de la recherche (hors ligne, sans réseau, sans LLM).

Score d'une fiche (recherche.scorer) :
    pertinence_bm25^alpha × poids_confiance[A–D] × (1 + w_type × affinité(service, type_doc))
    × (1 + w_autorite × autorité_éditeur) × fraîcheur(domaine) × poids_canal[flux|document|media|social|web]
avec fraîcheur = plancher + (1 − plancher) / (1 + âge / (demi_vie[domaine] × mult_demi_vie)),
et une expansion FR ↔ EN facultative de la requête (les normes de référence sont souvent en anglais).

Méthode
- jeu d'évaluation : requetes.yaml (60 requêtes des 20 services, dont 10 « tendances / médias » évaluées en mode
  tendances, c.-à-d. canaux social + média) et corpus_eval.py (fiches représentatives + leurres) ;
- métriques : precision@5 et nDCG@10 (gains 2^note − 1) ; objectif = moyenne des deux ;
- optimisation : montée par coordonnées sur une grille de valeurs, plusieurs passes, départ = formule d'origine ;
- anti-surapprentissage : validation croisée à 5 plis (on apprend sur 48 requêtes, on mesure sur 12 jamais vues) ;
  les poids finaux sont appris sur les 60 requêtes, mais le chiffre « après » rapporté est celui de la validation croisée.
- sortie : poids.json (versionné) + RAPPORT_CALIBRATION.md.

    python calibration/calibrer.py                 # calibre et écrit poids.json + rapport
    python calibration/calibrer.py --evaluer       # évalue seulement les poids actuels
    python calibration/calibrer.py --db veille.db  # évalue sur la base réelle (ids traduits en source + ref)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))
sys.path.insert(0, str(ICI))
import collecteur as C  # noqa: E402
import recherche as R  # noqa: E402
from corpus_eval import items  # noqa: E402

CANAUX_TENDANCES = ("social", "media")

DEMI_VIES = {  # jours ; le droit et les normes vieillissent beaucoup moins vite que l'actualité cyber
    "droit": 1825, "normes_documentation": 1460, "marches_publics": 45, "cybersecurite": 30, "ia": 120,
    "tech": 60, "entreprise": 365, "environnement": 730, "design_ux": 1095, "marketing_communication": 120,
    "poker": 180, "bd_edition": 365, "forums_experts": 365, "medias": 7, "reseaux_sociaux": 3,
    "communication_institutionnelle": 90, "defaut": 180,
}
AFFINITES = {  # 0 = inadapté … 1 = type de document idéal pour le service
    "LEX-GUARD": {"loi": 1.0, "jurisprudence": 0.9, "guide": 0.8, "norme": 0.6, "actualite": 0.5, "defaut": 0.2},
    "CYBER-FORTRESS/audit": {"norme": 1.0, "guide": 1.0, "documentation": 0.7, "loi": 0.5, "discussion": 0.3, "defaut": 0.2},
    "CYBER-FORTRESS/conformite": {"norme": 1.0, "guide": 0.9, "loi": 0.9, "documentation": 0.5, "defaut": 0.2},
    "CYBER-FORTRESS/veille": {"actualite": 1.0, "donnees": 1.0, "release": 0.9, "guide": 0.4, "defaut": 0.3},
    "CYBER-FORTRESS/incident": {"actualite": 0.9, "donnees": 0.9, "guide": 0.9, "loi": 0.7, "release": 0.8, "defaut": 0.3},
    "CODE-CORE": {"documentation": 1.0, "norme": 0.9, "guide": 0.8, "discussion": 0.6, "release": 0.5, "defaut": 0.2},
    "OPS-CORE": {"documentation": 1.0, "guide": 0.8, "release": 0.7, "discussion": 0.5, "defaut": 0.2},
    "AGENT-FACTORY": {"recherche": 1.0, "documentation": 0.9, "norme": 0.5, "actualite": 0.4, "defaut": 0.2},
    "DESIGN-SYSTEM": {"norme": 1.0, "guide": 0.9, "documentation": 0.6, "discussion": 0.4, "release": 0.4, "defaut": 0.2},
    "GREEN-CORE": {"norme": 1.0, "guide": 0.9, "actualite": 0.6, "donnees": 0.7, "cahier_des_charges": 0.5, "defaut": 0.3},
    "REVENUE-CORE": {"cahier_des_charges": 1.0, "appel_offres": 1.0, "guide": 0.7, "donnees": 0.5, "defaut": 0.2},
    "PILOT-CORE": {"guide": 0.9, "donnees": 0.9, "loi": 0.7, "cahier_des_charges": 0.8, "actualite": 0.5, "defaut": 0.3},
    "R&D-PARADOX": {"recherche": 1.0, "actualite": 0.8, "release": 0.6, "social": 0.5, "podcast": 0.6, "defaut": 0.3},
    "CONTENT-ARENA": {"actualite": 0.9, "social": 0.8, "podcast": 0.8, "guide": 0.6, "defaut": 0.3},
}
BASE = copy.deepcopy(R.POIDS_DEFAUT)
GRILLE = {
    "alpha": [0.5, 0.75, 1.0, 1.5, 2.0],
    "conf.B": [0.6, 0.7, 0.8, 0.85, 0.9, 1.0], "conf.C": [0.3, 0.4, 0.5, 0.6, 0.7], "conf.D": [0.1, 0.2, 0.3, 0.4, 0.5],
    "w_type": [0.0, 0.25, 0.5, 1.0, 1.5, 2.0], "w_autorite": [0.0, 0.25, 0.5, 1.0],
    "plancher_fraicheur": [0.3, 0.5, 0.6, 0.7, 0.8, 0.9], "mult_demi_vie": [0.25, 0.5, 1.0, 2.0, 4.0],
    "demi_vie_uniforme": [60, None], "expansion": [False, True],
    "canal.document": [0.8, 1.0, 1.2, 1.5], "canal.media": [0.4, 0.6, 0.8, 1.0], "canal.social": [0.2, 0.4, 0.6, 0.8, 1.0],
    "canal.web": [0.3, 0.6, 1.0],
}


# --------------------------------------------------------------------------------------------- données
def construire_base(its: list[dict]):
    conn = C.ouvrir(":memory:")
    maint = datetime.now(timezone.utc)
    for it in its:
        d = C._iso(maint - timedelta(days=it["age"]))
        conn.execute(
            "INSERT INTO fiches(source_id, titre, resume, url, url_canonique, empreinte, date, domaines, services, projets,"
            " confiance, type, langue, score_injection, collecte_le, type_doc, canal, ref, autorite, licence, stockage)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (it["source_id"], it["titre"], it["resume"], f"https://eval.local/{it['id']}", f"https://eval.local/{it['id']}",
             it["id"], d, it["domaine"], "", "", it["confiance"], "eval", "fr", 0, d, it["type_doc"], it["canal"],
             it["ref"], it["autorite"], "eval", "extrait"))
    conn.commit()
    return conn


def charger_requetes() -> list[dict]:
    import yaml
    return yaml.safe_load((ICI / "requetes.yaml").read_text(encoding="utf-8"))["requetes"]


class Evaluateur:
    """Pré-calcule les candidats FTS (indépendants des poids) puis reclasse en Python pour chaque jeu de poids."""

    def __init__(self, conn, requetes: list[dict], cle_id=lambda f: f["url"].rsplit("/", 1)[-1]):
        self.conn, self.requetes, self.cle_id = conn, requetes, cle_id
        self.cache: dict = {}

    def candidats(self, q: dict, expansion: bool) -> list[dict]:
        k = (q["id"], expansion)
        if k not in self.cache:
            poids = copy.deepcopy(BASE)
            poids["parametres"]["expansion"] = expansion
            canaux = CANAUX_TENDANCES if q.get("categorie") == "tendances" else None
            # limite haute : on récupère tous les candidats, le reclassement se fait ensuite
            self.cache[k] = R.rechercher(q["requete"], conn=self.conn, poids=poids, limite=400, canaux=canaux)
        return self.cache[k]

    def classer(self, q: dict, poids: dict) -> list[str]:
        cands = self.candidats(q, bool(poids["parametres"].get("expansion")))
        notes = sorted(cands, key=lambda f: R.scorer(f, f["pertinence"], poids, q["service"]), reverse=True)
        return [self.cle_id(f) for f in notes]

    def mesurer(self, poids: dict, sous_ensemble: list[dict] | None = None) -> dict:
        p5, nd, par_cat = [], [], {}
        for q in sous_ensemble or self.requetes:
            ordre = self.classer(q, poids)
            att = {str(k): int(v) for k, v in q["attendus"].items()}
            pr = sum(1 for x in ordre[:5] if att.get(x, 0) >= 1) / 5
            dcg = sum((2 ** att.get(x, 0) - 1) / math.log2(i + 2) for i, x in enumerate(ordre[:10]))
            ideal = sorted(att.values(), reverse=True)[:10]
            idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal)) or 1.0
            p5.append(pr)
            nd.append(dcg / idcg)
            c = q.get("categorie", "normale")
            par_cat.setdefault(c, []).append((pr, dcg / idcg))
        m = lambda xs: round(sum(xs) / len(xs), 4) if xs else 0.0
        return {"precision@5": m(p5), "ndcg@10": m(nd), "objectif": m([(a + b) / 2 for a, b in zip(p5, nd)]),
                "par_categorie": {c: {"precision@5": m([a for a, _ in v]), "ndcg@10": m([b for _, b in v]), "n": len(v)}
                                  for c, v in par_cat.items()}}


# --------------------------------------------------------------------------------------------- optimisation
def poser(poids: dict, cle: str, valeur) -> dict:
    p = copy.deepcopy(poids)
    prm = p["parametres"]
    if "." in cle:
        a, b = cle.split(".")
        prm[a][b] = valeur
    else:
        prm[cle] = valeur
    return p


def lire(poids: dict, cle: str):
    prm = poids["parametres"]
    if "." in cle:
        a, b = cle.split(".")
        return prm[a].get(b)
    return prm.get(cle)


def poids_initiaux() -> dict:
    p = copy.deepcopy(BASE)
    p["demi_vie_jours"] = DEMI_VIES
    p["affinites"] = AFFINITES
    return p


def monter_par_coordonnees(ev: Evaluateur, requetes: list[dict], passes: int = 3) -> tuple[dict, float]:
    meilleur = poids_initiaux()
    score = ev.mesurer(meilleur, requetes)["objectif"]
    for _ in range(passes):
        ameliore = False
        for cle, valeurs in GRILLE.items():
            for v in valeurs:
                if v == lire(meilleur, cle):
                    continue
                cand = poser(meilleur, cle, v)
                s = ev.mesurer(cand, requetes)["objectif"]
                if s > score + 1e-6:
                    meilleur, score, ameliore = cand, s, True
        if not ameliore:
            break
    return meilleur, score


def plis(requetes: list[dict], k: int = 5) -> list[list[dict]]:
    ordre = sorted(requetes, key=lambda q: hashlib.sha256(q["id"].encode()).hexdigest())  # mélange déterministe
    return [ordre[i::k] for i in range(k)]


def validation_croisee(ev: Evaluateur, requetes: list[dict], k: int = 5) -> dict:
    avant, apres = [], []
    for i, test in enumerate(plis(requetes, k)):
        entrainement = [q for q in requetes if q not in test]
        p, _ = monter_par_coordonnees(ev, entrainement)
        avant.append(ev.mesurer(poids_initiaux(), test))
        apres.append(ev.mesurer(p, test))
    moy = lambda L, cle: round(sum(x[cle] for x in L) / len(L), 4)
    return {"plis": k, "avant": {c: moy(avant, c) for c in ("precision@5", "ndcg@10", "objectif")},
            "apres": {c: moy(apres, c) for c in ("precision@5", "ndcg@10", "objectif")}}


# --------------------------------------------------------------------------------------------- sorties
def ecrire_rapport(res: dict, chemin: Path) -> None:
    a, b, cv = res["avant"], res["apres_entrainement"], res["validation_croisee"]
    prm = res["poids"]["parametres"]
    lignes = [
        "# Calibration du classement — rapport", "",
        f"Version des poids : **{res['poids']['version']}** — {res['n_requetes']} requêtes "
        f"({res['n_tendances']} « tendances / médias »), corpus de {res['n_fiches']} fiches (empreinte {res['corpus']}).", "",
        "| Mesure | Avant (formule d'origine) | Après — validation croisée 5 plis | Après — sur les 60 requêtes (entraînement) |",
        "|---|---|---|---|",
        f"| precision@5 | {a['precision@5']} | {cv['apres']['precision@5']} | {b['precision@5']} |",
        f"| nDCG@10 | {a['ndcg@10']} | {cv['apres']['ndcg@10']} | {b['ndcg@10']} |",
        f"| objectif (moyenne) | {a['objectif']} | {cv['apres']['objectif']} | {b['objectif']} |", "",
        "Le chiffre à retenir est la **validation croisée** : poids appris sans voir les requêtes mesurées.", "",
        "Par catégorie (avant → après, sur les 60 requêtes) :", "",
    ]
    for c, v in b["par_categorie"].items():
        av = a["par_categorie"].get(c, {})
        lignes.append(f"- {c} ({v['n']} requêtes) : precision@5 {av.get('precision@5')} → {v['precision@5']}, "
                      f"nDCG@10 {av.get('ndcg@10')} → {v['ndcg@10']}")
    lignes += ["", "## Poids retenus", "", "```json", json.dumps(prm, ensure_ascii=False, indent=1), "```", "",
               "## Limites", "",
               "- Corpus d'évaluation rédigé pour l'occasion (paraphrases courtes) et jugements de pertinence posés à la main : "
               "à refaire sur la base réelle après quelques semaines de collecte (`--db`).",
               "- 60 requêtes, c'est peu : les écarts de quelques centièmes ne sont pas significatifs.",
               "- La tonalité et les signaux sociaux restent des indications (confiance D), jamais des faits."]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def calibrer() -> dict:
    its, reqs = items(), charger_requetes()
    conn = construire_base(its)
    ev = Evaluateur(conn, reqs)
    avant = ev.mesurer(poids_initiaux())
    cv = validation_croisee(ev, reqs)
    final, _ = monter_par_coordonnees(ev, reqs)
    apres = ev.mesurer(final)
    corpus = hashlib.sha256(json.dumps(its, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    final["version"] = f"{datetime.now(timezone.utc):%Y-%m-%d}.1"
    final["methode"] = "montée par coordonnées sur grille, validation croisée 5 plis (calibration/calibrer.py)"
    final["evaluation"] = {"avant": avant, "apres_entrainement": apres, "validation_croisee": cv,
                           "n_requetes": len(reqs), "corpus": corpus}
    res = {"poids": final, "avant": avant, "apres_entrainement": apres, "validation_croisee": cv, "n_requetes": len(reqs),
           "n_tendances": sum(1 for q in reqs if q.get("categorie") == "tendances"), "n_fiches": len(its), "corpus": corpus}
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibration du classement de la veille")
    ap.add_argument("--evaluer", action="store_true", help="évaluer seulement les poids actuels (poids.json)")
    ap.add_argument("--db", help="évaluer sur une base réelle (ids du corpus traduits en source + ref)")
    a = ap.parse_args(argv)
    if a.evaluer or a.db:
        reqs = charger_requetes()
        if a.db:
            corr = {it["id"]: (it["source_id"], it["ref"]) for it in items()}
            conn = R.ouvrir_lecture(a.db)

            def cle(f):  # une fiche réelle « vaut » l'id du corpus de même source (et même ref si renseignée)
                for i, (src, ref) in corr.items():
                    if f["source_id"] == src and (not ref or (f.get("ref") or "").startswith(ref)):
                        return i
                return f"reel-{f['id']}"
            ev = Evaluateur(conn, reqs, cle)
        else:
            ev = Evaluateur(construire_base(items()), reqs)
        print(json.dumps({"poids_actuels": ev.mesurer(R.charger_poids()), "formule_origine": ev.mesurer(poids_initiaux())},
                         ensure_ascii=False, indent=1))
        return 0
    res = calibrer()
    (ICI / "poids.json").write_text(json.dumps(res["poids"], ensure_ascii=False, indent=1), encoding="utf-8")
    ecrire_rapport(res, ICI / "RAPPORT_CALIBRATION.md")
    cv = res["validation_croisee"]
    print(f"avant : {res['avant']['objectif']} | après (validation croisée) : {cv['apres']['objectif']} "
          f"| après (entraînement) : {res['apres_entrainement']['objectif']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
