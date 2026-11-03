"""VEILLE SYFER — mode « tendances » (réseaux sociaux + médias), sans LLM, sans données personnelles.

Ce que fait ce module
- tonalite(texte) : positive / negative / neutre, calculée LOCALEMENT par un lexique simple FR/EN
  (avec négation « pas / plus / jamais / not / no » qui inverse le mot suivant). C'est une indication grossière.
- calculer_tendances(...) : agrégats par projet ou par sujet sur une période (volume, évolution par rapport
  à la période précédente, répartition des tonalités, volume par jour, mots-clés dominants, sources principales).

Règles (RGPD, social listening — voir RGPD_social.md)
- on n'agrège que des fiches déjà anonymisées (aucun identifiant de personne physique en base) ;
- les mots-clés renvoyés excluent les mots vides, les nombres et les [éléments retirés] ;
- un sujet dont le volume est inférieur à SEUIL_MIN fiches est signalé « volume trop faible » (pas d'analyse) ;
- les tendances décrivent des SUJETS, jamais des personnes, et ne sont jamais présentées comme des faits.

CLI
    python tendances.py --projet poker-winners --jours 7
    python tendances.py --sujet "intelligence artificielle" --jours 30 --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
SEUIL_MIN = 5

POSITIFS = set("""
bien bon bonne bons bonnes excellent excellente super genial génial top bravo merci réussi reussi réussite reussite
succès succes gagne gagné gagnant victoire progrès progres amélioration amelioration utile efficace fiable sûr sur
innovant innovante solide adoré adore aime aimé aimons recommande recommandé satisfait content heureux ravi fier
facile clair rapide gratuit sécurisé securise protégé protege positif positive hausse croissance record
good great excellent awesome love loved like liked best better win won winning success useful reliable secure safe
fast easy clear happy glad improved improvement growth recommend recommended amazing fantastic nice helpful
""".split())
NEGATIFS = set("""
mal mauvais mauvaise nul nulle horrible terrible catastrophe catastrophique échec echec perdu perte perd raté rate
problème probleme bug bogue panne faille vulnérabilité vulnerabilite piratage piraté pirate fuite arnaque escroquerie
fraude interdit interdiction sanction amende danger dangereux risque risqué inquiétant inquietant inquiétude
déçu decu déception deception colère colere scandale lent cher arnaque triche tricheur addiction dépendance
baisse chute crise grave critique attaque rançongiciel rancongiciel abus plainte
bad worse worst terrible awful fail failed failure lost loss bug broken breach hack hacked leak scam fraud banned
ban fine risk risky dangerous angry disappointed slow expensive cheat cheating addiction crash attack vulnerable
""".split())
NEGATIONS = {"pas", "plus", "jamais", "aucun", "aucune", "ni", "sans", "not", "no", "never", "without", "n't"}
MOTS_VIDES = set("""
a à au aux avec ce ces cet cette dans de des du elle en et eux il ils je la le les leur lui ma mais me même mes moi mon
ne nos notre nous on ou où par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous est sont
été être avoir ont fait plus très tout tous toute toutes comme si sans sous entre aussi donc car alors cela ça ici
the of and to in for on with by from at as is are be this that it or an was were will can not you your we our they
their have has had just more about what when how all new via amp rt
retiré retire pseudo lien profil e-mail téléphone telephone
""".split())


def _mots(texte: str) -> list[str]:
    return re.findall(r"[a-zàâäçéèêëîïôöùûüÿœæ'-]+", (texte or "").lower())


def tonalite(texte: str) -> str:
    """'positive', 'negative' ou 'neutre' (lexique local, négation simple)."""
    mots = _mots(texte)
    score = 0
    for i, m in enumerate(mots):
        m = m.split("'")[-1]
        val = 1 if m in POSITIFS else (-1 if m in NEGATIFS else 0)
        if val and any(x in NEGATIONS for x in mots[max(0, i - 2):i]):
            val = -val
        score += val
    return "positive" if score > 0 else ("negative" if score < 0 else "neutre")


def _sans_accents(x: str) -> str:
    return unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode()


def mots_cles_dominants(textes: list[str], n: int = 10) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for t in textes:
        t = re.sub(r"\[[^\]]*\]", " ", t or "")  # [pseudo retiré], [e-mail retiré]…
        vus = set()
        for m in _mots(t):
            m = m.strip("'-")
            if len(m) < 4 or m in MOTS_VIDES or m.isdigit():
                continue
            k = _sans_accents(m)
            if k not in vus:
                vus.add(k)
                c[m] += 1  # 1 par fiche : on compte des fiches, pas des répétitions
    return c.most_common(n)


def _ouvrir(chemin: str | None) -> sqlite3.Connection:
    sys.path.insert(0, str(ICI))
    import recherche  # lecture seule (mode=ro / immutable si montage en lecture seule)
    return recherche.ouvrir_lecture(chemin)


def calculer_tendances(projet: str | None = None, sujet: str | None = None, jours: int = 7,
                       canaux: tuple[str, ...] = ("social", "media"), chemin_db: str | None = None,
                       conn: sqlite3.Connection | None = None, maintenant: datetime | None = None) -> dict:
    """Agrégats d'un projet et/ou d'un sujet (mots) sur `jours` jours, comparés aux `jours` jours précédents."""
    propre = conn is None
    conn = conn or _ouvrir(chemin_db)
    try:
        fin = maintenant or datetime.now(timezone.utc)
        debut, debut_prec = fin - timedelta(days=jours), fin - timedelta(days=2 * jours)
        where = [f"canal IN ({','.join('?' * len(canaux))})"]
        params: list = list(canaux)
        if projet:
            where.append("projets LIKE ?")
            params.append(f"%|{projet}|%")
        if sujet:
            sys.path.insert(0, str(ICI))
            import recherche
            q = recherche.requete_fts(sujet)
            if not q:
                return {"erreur": "sujet vide"}
            where.append("id IN (SELECT rowid FROM fiches_fts WHERE fiches_fts MATCH ?)")
            params.append(q)
        sql = (f"SELECT source_id, titre, resume, tonalite, canal, COALESCE(date, collecte_le) AS d FROM fiches "
               f"WHERE {' AND '.join(where)} AND COALESCE(date, collecte_le) >= ?")
        lignes = [dict(r) for r in conn.execute(sql, [*params, debut_prec.strftime("%Y-%m-%dT%H:%M:%SZ")])]
        lim = debut.strftime("%Y-%m-%dT%H:%M:%SZ")
        courantes = [l for l in lignes if l["d"] >= lim]
        precedentes = [l for l in lignes if l["d"] < lim]
        n, n_prec = len(courantes), len(precedentes)
        ton = Counter(l["tonalite"] or "neutre" for l in courantes)
        par_jour = Counter(l["d"][:10] for l in courantes)
        res = {
            "projet": projet, "sujet": sujet, "periode_jours": jours, "canaux": list(canaux),
            "du": debut.strftime("%Y-%m-%d"), "au": fin.strftime("%Y-%m-%d"),
            "volume": n, "volume_periode_precedente": n_prec,
            "evolution_pct": (round(100.0 * (n - n_prec) / n_prec, 1) if n_prec else None),
            "par_canal": dict(Counter(l["canal"] for l in courantes)),
            "par_jour": dict(sorted(par_jour.items())),
            "avertissement": "Signaux issus des réseaux sociaux et des médias : opinions et tendances, pas des faits. "
                             "Tonalité calculée par lexique simple (indicative).",
        }
        if n < SEUIL_MIN:
            res["analyse"] = f"volume trop faible (< {SEUIL_MIN} fiches) : pas d'analyse de tonalité ni de mots-clés"
            return res
        res["tonalite"] = {k: ton.get(k, 0) for k in ("positive", "negative", "neutre")}
        res["tonalite_pct"] = {k: round(100.0 * v / n, 1) for k, v in res["tonalite"].items()}
        res["mots_cles"] = mots_cles_dominants([f"{l['titre']} {l['resume']}" for l in courantes])
        res["sources_principales"] = Counter(l["source_id"] for l in courantes).most_common(5)
        return res
    finally:
        if propre:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tendances (réseaux sociaux + médias) de la veille SYFER")
    ap.add_argument("--projet")
    ap.add_argument("--sujet")
    ap.add_argument("--jours", type=int, default=7)
    ap.add_argument("--canaux", default="social,media")
    ap.add_argument("--db", default=os.environ.get("VEILLE_DB"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = calculer_tendances(a.projet, a.sujet, a.jours, tuple(a.canaux.split(",")), a.db)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print(f"Tendances {a.projet or ''} {a.sujet or ''} — {r.get('du')} → {r.get('au')}")
    print(f"  volume : {r.get('volume')} (période précédente : {r.get('volume_periode_precedente')}, "
          f"évolution : {r.get('evolution_pct')} %)")
    if "tonalite_pct" in r:
        print(f"  tonalité : {r['tonalite_pct']}")
        print(f"  mots-clés : {', '.join(m for m, _ in r['mots_cles'])}")
        print(f"  sources : {', '.join(s for s, _ in r['sources_principales'])}")
    else:
        print(f"  {r.get('analyse', '')}")
    print(f"  ⚠ {r['avertissement']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
