#!/usr/bin/env python3
"""Banc de mesure de la compaction SYFER (Python 3.12, bibliothèque standard ; matplotlib facultatif).

Génère un corpus synthétique réaliste (missions avec étapes et livrables FR, fiches de veille,
connaissances avec quasi-doublons), reproduit le format d'archive actuel (archive.py : un membre
gzip par ligne dans AAAA-MM.jsonl.gz + archive_index/FTS5 dans SQLite) puis mesure chaque méthode :
ratio, temps de compaction, lecture d'un enregistrement, recherche ; et projette l'espace disque.

Usage :  python3 compaction/mesure.py                 (10 000 missions, ~3-6 min)
         python3 compaction/mesure.py --missions 2000 (rapide)
Produit : compaction/resultats.md, compaction/resultats.json, compaction/resultats.png (si matplotlib).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import lzma
import os
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
import zlib
from datetime import datetime, timedelta
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(RACINE / "nexus-core"))
from app import compaction as C  # noqa: E402  (module autonome : n'importe pas le reste de app)

CLE = b"cle-de-mesure"
MAINTENANT = datetime(2026, 11, 4, 3, 0, 0)

# --------------------------------------------------------------------------------- corpus
PROJETS = ["poker-vitrine", "solver", "studio-master", "siteesctboxe", "freelance-ia", "youtube-poker"]
SERVICES = ["REDACTION/article", "REDACTION/fiche-produit", "CYBER-FORTRESS/audit", "DEV/code", "DEV/revue",
            "MARKETING/post", "MARKETING/campagne", "JURIDIQUE/contrat", "FINANCE/budget", "VEILLE/synthese",
            "POKER/analyse", "SUPPORT/reponse"]
OUVERTURES = ["Dans ce contexte,", "Concrètement,", "Par ailleurs,", "En pratique,", "Pour commencer,", "Ensuite,",
              "De plus,", "À court terme,", "Sur le plan technique,", "Du point de vue du client,", "En résumé,",
              "Il convient de noter que", "Selon les données disponibles,", "Pour la suite,", "À l'inverse,",
              "Afin de limiter les risques,", "Compte tenu du budget,", "Sur les trois derniers mois,", "D'abord,",
              "Enfin,", "Néanmoins,", "Autrement dit,", "En parallèle,", "Pour mémoire,", "Dans l'immédiat,"]
SUJETS = ["l'équipe", "le serveur VPS", "la page d'accueil", "le tableau de bord", "la campagne", "le contrat",
          "le solveur", "la base de données", "le budget mensuel", "la sauvegarde", "le parcours utilisateur",
          "l'outil d'analyse de main", "la chaîne YouTube", "le module de paiement", "la charte graphique",
          "le prestataire", "le client", "la stratégie de contenu", "le pare-feu", "la documentation",
          "l'API interne", "le planning éditorial", "le formulaire de contact", "la newsletter", "le dépôt Git",
          "la file des missions", "le processus de validation", "l'agent CHECKER", "la mémoire du projet",
          "le référencement naturel", "la vidéo de présentation", "le livre Poker Feeling", "la bêta privée"]
VERBES = ["doit renforcer", "permet d'améliorer", "nécessite de revoir", "devrait simplifier", "va accélérer",
          "risque de compliquer", "peut sécuriser", "doit documenter", "aide à mesurer", "impose de tester",
          "facilite", "réduit", "augmente", "consolide", "clarifie", "remplace progressivement", "complète",
          "fiabilise", "ralentit", "structure", "automatise", "met en évidence", "contredit", "confirme"]
OBJETS = ["la conversion des visiteurs", "le temps de chargement", "la rétention des abonnés", "les coûts d'hébergement",
          "la qualité des livrables", "le taux d'erreur", "la sécurité des accès", "la lisibilité du code",
          "la cohérence des messages", "le suivi des dépenses", "la conformité au RGPD", "les délais de réponse",
          "l'expérience mobile", "la couverture des tests", "les sauvegardes quotidiennes", "le respect de la charte",
          "la précision des ranges", "l'engagement sur les réseaux", "la marge brute", "le nombre de relances",
          "la mise à jour des dépendances", "la journalisation des actions", "le tunnel d'inscription",
          "les clauses de résiliation", "les fréquences de mise", "la gestion des mots de passe"]
COMPLEMENTS = ["d'ici la fin du mois", "sans dépense supplémentaire", "avec un suivi hebdomadaire",
               "selon la règle 3-2-1", "en priorité sur mobile", "avant la mise en production", "pour la bêta",
               "en lien avec le prestataire", "à budget constant", "sur l'ensemble des projets", "dès la semaine {n}",
               "avec un objectif de {p} %", "pour {n} utilisateurs actifs", "sur un échantillon de {n} mains",
               "dans un délai de {n} jours", "avec une marge d'erreur de {p} %", "sous réserve de validation",
               "conformément au contrat signé le {d}", "en version {n}.{m}", "pour un coût estimé à {n} €"]
PROBLEMES = ["Le livrable ne cite pas ses sources.", "La conclusion contredit l'analyse.",
             "Le ton est trop familier pour le client.", "Des chiffres ne sont pas justifiés.",
             "La consigne demandait un tableau comparatif.", "Le texte dépasse la longueur demandée.",
             "Une recommandation n'est pas réalisable avec le budget.", "Mention d'un outil interdit par la charte.",
             "Le livrable contient un brouillon non terminé.", "Absence de prochaines étapes datées.",
             "Le code proposé n'est pas testé.", "Les clauses RGPD sont incomplètes.",
             "Les ranges proposées sont incohérentes avec la position.", "Promesse de gain interdite (jeu d'argent).",
             "Le titre ne reprend pas le mot-clé principal.", "Données personnelles visibles dans l'exemple."]
CONSIGNES = ["Rédige un article de blog de {n} mots sur {o} pour {pj}.",
             "Fais l'audit de sécurité de {s} et liste les correctifs prioritaires.",
             "Propose un plan de campagne pour améliorer {o}.", "Analyse la main suivante et explique la décision GTO : {main}.",
             "Écris une fiche produit pour {s}, ton professionnel, {n} mots maximum.",
             "Révise le code de {s} : lisibilité, tests, sécurité.", "Prépare un budget prévisionnel sur {n} mois pour {pj}.",
             "Rédige une réponse au client à propos de {o}.", "Fais une synthèse de veille sur {o}.",
             "Rédige les clauses de résiliation du contrat avec {s}.", "Prépare {n} publications pour les réseaux sociaux sur {o}.",
             "Compare trois options pour {o} et recommande la meilleure.", "Explique à un débutant comment {v} {o}.",
             "Liste les risques liés à {s} et les mesures de réduction.", "Écris le script d'une vidéo de {n} minutes sur {o}."]
SUFFIXE_CONSIGNE = ("\nRespecte la charte du projet. Réponds en français, de façon claire et structurée, "
                    "avec des titres et une liste de prochaines étapes.")
SECTIONS = ["Contexte", "Analyse", "Recommandations", "Plan d'action", "Risques", "Budget", "Prochaines étapes",
            "Synthèse", "Détails techniques", "Points d'attention", "Comparatif", "Conclusion"]
NOMS = ["Kevin", "Thomas", "Léa", "Nadia", "Hugo", "Inès", "Paul", "Sarah", "Yanis", "Chloé"]
MAINS = ["AhKd", "QsQh", "7c7d", "AsJs", "KcQc", "9h8h", "Ad5d", "JhTh", "6s6c", "AcKc"]


class Gen:
    def __init__(self, graine: int = 42):
        self.r = random.Random(graine)
        self.connaissances_projet = {p: [self.paragraphe(2, 3) for _ in range(60)] for p in PROJETS}

    def remplir(self, t: str) -> str:
        r = self.r
        return t.format(n=r.randint(2, 900), m=r.randint(0, 9), p=r.randint(1, 60),
                        d=f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/2026")

    def phrase(self) -> str:
        r = self.r
        p = f"{r.choice(OUVERTURES)} {r.choice(SUJETS)} {r.choice(VERBES)} {r.choice(OBJETS)} {self.remplir(r.choice(COMPLEMENTS))}."
        if r.random() < 0.25:
            p += f" {r.choice(NOMS)} suit ce point (réf. {r.randint(100, 9999)})."
        return p

    def paragraphe(self, a: int = 2, b: int = 5) -> str:
        return " ".join(self.phrase() for _ in range(self.r.randint(a, b)))

    def livrable(self, titre: str) -> str:
        r = self.r
        cible = r.randint(1000, 4000)
        parties = [f"# {titre}", ""]
        if r.random() < 0.15:
            parties.insert(0, "BROUILLON — à valider par le Décideur")
        while sum(len(x) for x in parties) < cible:
            parties += [f"## {r.choice(SECTIONS)}", self.paragraphe()]
            if r.random() < 0.5:
                parties += [f"- {self.phrase()}" for _ in range(r.randint(2, 5))]
            parties.append("")
        parties += ["## Prochaines étapes", f"1. Valider ce document avant le {self.remplir('{d}')}.",
                    "2. Planifier la mise en œuvre avec l'équipe.", "", "_Livrable produit par NEXUS — à relire avant diffusion._"]
        return "\n".join(parties)[:4096]

    def consigne(self) -> str:
        r = self.r
        return r.choice(CONSIGNES).format(n=r.randint(3, 1500), o=r.choice(OBJETS), s=r.choice(SUJETS),
                                          pj=r.choice(PROJETS), main=r.choice(MAINS) + " au bouton",
                                          v=r.choice(VERBES)) + SUFFIXE_CONSIGNE

    def mission(self, mid: int, quand: datetime) -> dict:
        r = self.r
        projet, service = r.choice(PROJETS), r.choice(SERVICES)
        titre = f"{service.split('/')[1].capitalize()} — {r.choice(OBJETS)}"
        consigne, livrable = self.consigne(), self.livrable(titre)
        refus = r.random() < 0.25
        probs = r.sample(PROBLEMES, r.randint(1, 3)) if refus else []
        extraits = r.sample(self.connaissances_projet[projet], 3)
        etapes = [
            {"agent": "NEXUS-COLLECTOR", "role": "collector", "verdict": None, "tokens": r.randint(300, 1500),
             "sortie": "\n".join(f"- [{projet}.md#{r.randint(1, 40)}] {e}" for e in extraits)[:2000]},
            {"agent": "NEXUS-ANALYST", "role": "analyst", "verdict": None, "tokens": r.randint(500, 2500),
             "sortie": "Plan proposé :\n" + "\n".join(f"{i}. {self.phrase()}" for i in range(1, r.randint(4, 9)))},
            {"agent": "NEXUS-WRITER", "role": "writer", "verdict": None, "tokens": r.randint(800, 4000),
             "sortie": livrable[:2000]},
            {"agent": "NEXUS-CHECKER", "role": "checker", "verdict": "refus" if refus else "ok",
             "tokens": r.randint(200, 900), "sortie": json.dumps({"verdict": "refus" if refus else "ok",
                                                                  "problemes": probs, "commentaire": self.phrase()},
                                                                 ensure_ascii=False)}]
        if refus:
            etapes += [{"agent": "NEXUS-WRITER", "role": "writer", "verdict": None, "tokens": r.randint(800, 4000),
                        "sortie": livrable[:2000]},
                       {"agent": "NEXUS-CHECKER", "role": "checker", "verdict": "ok", "tokens": r.randint(200, 900),
                        "sortie": json.dumps({"verdict": "ok", "problemes": []})}]
        decisions = []
        if r.random() < 0.2:
            st = r.choice(["validee", "validee", "refusee", "revision"])
            decisions.append({"id": mid, "objet": "livrable", "statut": st, "risque": r.choice(["faible", "moyen"]),
                              "commentaire": self.phrase() if st != "validee" else None, "motif": self.phrase()})
        tok = sum(e["tokens"] for e in etapes)
        return {"evenement": "fin_execution", "horodatage": quand.isoformat(timespec="seconds") + "Z",
                "mission_id": mid, "titre": titre, "consigne": consigne, "projet": projet, "service": service,
                "statut": r.choice(["terminee"] * 8 + ["validee", "plafond_atteint"]),
                "niveau": r.choice(["N1", "N2", "N3"]), "fonctionnement_demande": "F2",
                "fonctionnement": r.choice(["F1", "F2", "F3"]), "fonctionnement_raison": None,
                "modeles": {"collector": "local/qwen2.5-7b", "analyst": "claude-haiku", "writer": "claude-sonnet",
                            "checker": "claude-haiku"},
                "etapes": etapes, "livrable": livrable,
                "verdicts_checker": [{"source": "contrôle", "verdict": "refus", "problemes": probs}] if refus else [],
                "charte_violations": [], "charte_avertissements": [], "decisions": decisions, "montant_eur": None,
                "action": None, "revisions": 1 if refus else 0, "relance_auto": 0, "message": None, "tokens": tok,
                "tokens_entree": tok // 3, "tokens_sortie": tok - tok // 3, "cout_eur": round(tok * 0.000004, 5),
                "duree_s": round(r.uniform(8, 240), 1), "note": r.choice([None, None, 3, 4, 5]), "note_banc": None}

    def fiche(self, i: int, quand: datetime) -> dict:
        r = self.r
        titre = f"{r.choice(SUJETS).capitalize()} : {r.choice(OBJETS)} ({r.randint(1, 999)})"
        resume = self.paragraphe(2, 4)[:700]
        url = f"https://source{r.randint(1, 80)}.exemple.fr/article/{i}-{r.randint(1000, 99999)}"
        return {"source_id": f"src-{r.randint(1, 80)}", "titre": titre, "resume": resume, "url": url,
                "url_canonique": url, "empreinte": hashlib.sha256(f"{titre}{resume}".encode()).hexdigest(),
                "date": quand.strftime("%Y-%m-%d"), "domaines": "|" + r.choice(["cyber", "poker", "ia", "web", "seo"]) + "|",
                "services": "", "projets": "|" + r.choice(PROJETS) + "|", "confiance": r.choice(["A", "B", "C"]),
                "type": "article", "langue": "fr", "score_injection": 0,
                "collecte_le": quand.strftime("%Y-%m-%dT%H:%M:%SZ")}


def lignes_archive(gen: Gen, n: int, jours: int) -> list[dict]:
    """Lignes au format exact d'archive.py (chaîne HMAC, contenu = SHA-256 du JSON canonique)."""
    res, prec = [], C.GENESE
    debut = MAINTENANT - timedelta(days=jours)
    for i in range(1, n + 1):
        quand = debut + timedelta(seconds=(jours * 86400) * (i - 1) / n)
        e = gen.mission(i, quand)
        contenu = hashlib.sha256(C.canonique(e)).hexdigest()
        ref = hashlib.sha256(f"ledger{i}".encode()).hexdigest()
        h = hmac.new(CLE, f"{i}|{prec}|{contenu}|{ref}".encode(), hashlib.sha256).hexdigest()
        res.append({"seq": i, "prec": prec, "contenu": contenu, "ledger_ref": ref, "algo": "hmac", "hash": h,
                    "enregistrement": e})
        prec = h
    return res


# --------------------------------------------------------------------------------- format actuel
def ecrire_actuel(lignes: list[dict], dossier: Path) -> dict:
    """archive.archiver : gzip.open(fichier, 'ab') par ligne -> un membre gzip par ligne."""
    dossier.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    fichiers: dict[str, list[bytes]] = {}
    for l in lignes:
        mois = l["enregistrement"]["horodatage"][:7]
        fichiers.setdefault(mois, []).append(gzip.compress(C.canonique(l) + b"\n", compresslevel=9))
    for mois, membres in fichiers.items():
        (dossier / f"{mois}.jsonl.gz").write_bytes(b"".join(membres))
    t = time.perf_counter() - t0
    return {"octets": sum(f.stat().st_size for f in dossier.glob("*.jsonl.gz")), "temps_s": t}


def texte_index_actuel(e: dict) -> str:
    probs = " ".join(p for v in e.get("verdicts_checker", []) + e.get("charte_violations", [])
                     for p in v.get("problemes", []))
    return f"{e.get('titre', '')} {e.get('consigne', '')[:1500]} {e.get('livrable', '')[:1500]} {probs}"[:4000]


def index_actuel(lignes: list[dict], chemin: Path) -> dict:
    """archive_index + archive_fts (contenu externe) comme dans archive.py / models.py."""
    c = sqlite3.connect(str(chemin))
    c.executescript("""
        CREATE TABLE archive_index (id INTEGER PRIMARY KEY, seq INTEGER UNIQUE, mois VARCHAR(7), mission_id INTEGER,
          evenement VARCHAR(30), projet VARCHAR(40), service VARCHAR(80), statut VARCHAR(20), hash VARCHAR(64),
          prec VARCHAR(64), texte TEXT, efface BOOLEAN, cree_le DATETIME);
        CREATE INDEX ix_archive_index_seq ON archive_index(seq);
        CREATE INDEX ix_archive_index_mission_id ON archive_index(mission_id);
        CREATE VIRTUAL TABLE archive_fts USING fts5(texte, content='archive_index', content_rowid='id',
          tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER archive_ai AFTER INSERT ON archive_index BEGIN
          INSERT INTO archive_fts(rowid, texte) VALUES (new.id, new.texte); END;""")
    for l in lignes:
        e = l["enregistrement"]
        c.execute("INSERT INTO archive_index(seq, mois, mission_id, evenement, projet, service, statut, hash, prec,"
                  " texte, efface, cree_le) VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
                  (l["seq"], e["horodatage"][:7], e["mission_id"], e["evenement"], e["projet"], e["service"],
                   e["statut"], l["hash"], l["prec"], texte_index_actuel(e), e["horodatage"]))
    c.commit()
    c.execute("VACUUM")
    c.close()
    return {"octets": chemin.stat().st_size}


# --------------------------------------------------------------------------------- méthodes
def blocs(lignes_b: list[bytes], n: int = 256, octets: int = 1_000_000) -> list[list[bytes]]:
    res, lot, t = [], [], 0
    for l in lignes_b:
        if lot and (len(lot) >= n or t + len(l) > octets):
            res.append(lot)
            lot, t = [], 0
        lot.append(l)
        t += len(l) + 1
    return res + ([lot] if lot else [])


def dedup(enregs: list[dict], zd: bytes | None) -> tuple[list[bytes], int, int]:
    """Même règle que Compacteur._dedupliquer (segments ≥ 64 car. vus ≥ 2 fois) ; fragments
    compressés individuellement (zlib brut + dictionnaire)."""
    from collections import Counter
    compte = Counter()
    for e in enregs:  # fréquence documentaire (comme le module)
        compte.update({C.sha(p.encode()) for s in C._chaines(e) for p in C._segments_longs(s)})
    frag: dict[str, int] = {}
    taille = 0

    def choix(p):
        nonlocal taille
        h = C.sha(p.encode())
        if not C.rentable(len(p), compte[h]):
            return None
        if h not in frag:
            frag[h] = len(frag) + 1
            taille += len(C.z_compresser(p.encode(), zd)) + 40  # + ligne SQLite (empreinte, compteur)
        return frag[h]

    return [C.canonique(C._remplacer(e, choix)) for e in enregs], len(frag), taille


def chrono(f, *a, **k):
    t0 = time.perf_counter()
    r = f(*a, **k)
    return r, time.perf_counter() - t0


def mesurer_methodes(lignes: list[dict], brut: int, rng: random.Random) -> list[dict]:
    lb = [C.canonique(l) for l in lignes]
    echant = rng.sample(range(len(lb)), min(200, len(lb)))
    zd, t_dict = chrono(C.entrainer_dictionnaire, lb[:2000])
    res = []

    def ajouter(nom, octets, t_comp, lecture_ms, note=""):
        res.append({"methode": nom, "octets": octets, "ratio": round(brut / octets, 2), "compaction_s": round(t_comp, 2),
                    "lecture_ms": round(lecture_ms, 3), "note": note})

    # par ligne
    for nom, d in (("zlib ligne", None), ("zlib ligne + dict", zd)):
        comp, t = chrono(lambda: [C.z_compresser(l, d) for l in lb])
        t0 = time.perf_counter()
        for i in echant:
            json.loads(C.z_decompresser(comp[i], d))
        ajouter(nom, sum(len(x) for x in comp) + (len(zd) if d else 0), t + (t_dict if d else 0),
                (time.perf_counter() - t0) * 1000 / len(echant), "accès direct si l'offset est indexé")
    # par bloc
    for nom, f_c, f_d, src in (
            ("zlib bloc", lambda b: C.z_compresser(b), lambda b: C.z_decompresser(b), "plein"),
            ("zlib bloc + dict", lambda b: C.z_compresser(b, zd), lambda b: C.z_decompresser(b, zd), "plein"),
            ("lzma bloc", C.x_compresser, C.x_decompresser, "plein"),
            ("zlib bloc + dict + dédup", lambda b: C.z_compresser(b, zd), lambda b: C.z_decompresser(b, zd), "dedup"),
            ("lzma bloc + dédup", C.x_compresser, C.x_decompresser, "dedup")):
        t0 = time.perf_counter()
        extra, nfrag = 0, 0
        if src == "dedup":
            entrees, nfrag, extra = dedup(lignes, zd)
        else:
            entrees = lb
        lots = blocs(entrees)
        comp = [f_c(b"\n".join(l)) for l in lots]
        t = time.perf_counter() - t0 + t_dict
        pos = []
        for bi, l in enumerate(lots):
            pos += [(bi, j) for j in range(len(l))]
        t0 = time.perf_counter()
        for i in echant:
            bi, j = pos[i]
            json.loads(f_d(comp[bi]).split(b"\n")[j])
        ajouter(nom, sum(len(x) for x in comp) + extra + len(zd), t, (time.perf_counter() - t0) * 1000 / len(echant),
                f"{len(lots)} blocs" + (f", {nfrag} fragments dédupliqués" if nfrag else ""))
    return res


# --------------------------------------------------------------------------------- pipeline complet
def taille_dossier(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def pipeline_paliers(lignes: list[dict], travail: Path, actuel_dir: Path, rng: random.Random,
                     env: dict | None = None) -> dict:
    """Pipeline réel du module : chaud (≤ 30 j) laissé au format actuel ; tiède / froid compactés."""
    os.environ["LEDGER_HMAC_KEY"] = CLE.decode()
    for k in ("COMPACTION_ALGO_TIEDE", "COMPACTION_FTS_DETAIL"):
        os.environ.pop(k, None)
    os.environ.update(env or {})
    d = travail / "compact"
    shutil.rmtree(d, ignore_errors=True)
    c = C.Compacteur(d, horloge=lambda: MAINTENANT)
    t0 = time.perf_counter()
    r_t = c.compacter("tiede", dossier_archive=actuel_dir)
    t_tiede = time.perf_counter() - t0
    t0 = time.perf_counter()
    r_f = c.compacter("froid")
    t_froid = time.perf_counter() - t0
    st = c.statistiques()
    t0 = time.perf_counter()
    v = c.verifier()
    t_verif = time.perf_counter() - t0
    ids = [r[0] for r in c.db.execute("SELECT id FROM enregs")]
    par_palier = dict(c.db.execute("SELECT e.id, b.palier FROM enregs e JOIN blocs b ON b.id=e.bloc"))
    lect = {"tiede": [], "froid": []}
    for i in rng.sample(ids, min(300, len(ids))):
        c._cache.clear()
        c._frag_cache.clear()
        t0 = time.perf_counter()
        c.lire(i)
        lect[par_palier[i]].append((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    for i in rng.sample(ids, min(50, len(ids))):
        c.verifier_enregistrement(i)
    t_v1 = (time.perf_counter() - t0) * 1000 / min(50, len(ids))
    requetes = ["sauvegardes serveur", "clauses résiliation contrat", "ranges position solveur", "conversion mobile",
                "RGPD conformité", "budget hébergement", "newsletter engagement", "pare-feu sécurité accès"]
    t0 = time.perf_counter()
    for q in requetes:
        c.rechercher(q, limite=10, avec_extrait=False)
    t_rech = (time.perf_counter() - t0) * 1000 / len(requetes)
    t0 = time.perf_counter()
    for q in requetes:
        c.rechercher(q, limite=10)
    t_rech_ex = (time.perf_counter() - t0) * 1000 / len(requetes)
    # composition de l'index
    try:
        compo = dict(c.db.execute("SELECT name, sum(pgsize) FROM dbstat GROUP BY name"))
    except sqlite3.Error:
        compo = {}
    fts = sum(v for k, v in compo.items() if k.startswith("cfts"))
    # effacement RGPD (temps)
    t0 = time.perf_counter()
    c.effacer(ids[len(ids) // 2], "mesure", "banc")
    t_eff = (time.perf_counter() - t0) * 1000
    v2 = c.verifier()
    c.fermer()
    ent = C.entretenir(d / "compaction.db", "oui")
    return {"stats": st, "tiede_s": round(t_tiede, 2), "froid_s": round(t_froid, 2), "verifier_s": round(t_verif, 2),
            "verifier_valide": v["valide"] and v2["valide"], "verifier_un_ms": round(t_v1, 2),
            "lecture_ms": {k: round(statistics.mean(x), 3) if x else None for k, x in lect.items()},
            "lecture_p95_ms": {k: round(sorted(x)[int(len(x) * .95)], 3) if x else None for k, x in lect.items()},
            "recherche_ms": round(t_rech, 2), "recherche_extrait_ms": round(t_rech_ex, 2),
            "effacement_ms": round(t_eff, 1), "index_fts_octets": fts, "index_composition": compo,
            "entretien": ent, "dossier_octets": taille_dossier(d), "ajoutes": r_t["ajoutes"], "migres": r_f["migres"]}


def recherche_actuelle(chemin: Path) -> float:
    c = sqlite3.connect(str(chemin))
    requetes = ["sauvegardes serveur", "clauses résiliation contrat", "ranges position solveur", "conversion mobile",
                "RGPD conformité", "budget hébergement", "newsletter engagement", "pare-feu sécurité accès"]
    t0 = time.perf_counter()
    for q in requetes:
        c.execute("""SELECT a.seq, snippet(archive_fts, 0, '[', ']', '…', 24) FROM archive_fts
                     JOIN archive_index a ON a.id = archive_fts.rowid WHERE archive_fts MATCH ? AND a.efface = 0
                     ORDER BY bm25(archive_fts) LIMIT 10""", (C.requete_fts(q),)).fetchall()
    c.close()
    return (time.perf_counter() - t0) * 1000 / len(requetes)


def lecture_actuelle(dossier: Path, lignes: list[dict], rng: random.Random) -> float:
    """archive.lignes() : un enregistrement = décompresser et parcourir le fichier du mois."""
    ech = rng.sample(lignes, 30)
    t0 = time.perf_counter()
    for l in ech:
        f = dossier / f"{l['enregistrement']['horodatage'][:7]}.jsonl.gz"
        with gzip.open(f, "rb") as g:
            for b in g:
                if json.loads(b)["seq"] == l["seq"]:
                    break
    return (time.perf_counter() - t0) * 1000 / len(ech)


# --------------------------------------------------------------------------------- veille / connaissances
def mesurer_veille(gen: Gen, n: int, travail: Path) -> dict:
    try:
        sys.path.insert(0, str(RACINE / "veille"))
        import collecteur
        schema = collecteur.SCHEMA
    except Exception:
        schema = None
    chemin = travail / "veille.db"
    c = sqlite3.connect(str(chemin))
    if schema:
        c.executescript(schema)
    debut = MAINTENANT - timedelta(days=360)
    for i in range(n):
        f = gen.fiche(i, debut + timedelta(seconds=360 * 86400 * i / n))
        c.execute(f"INSERT INTO fiches({','.join(f)}) VALUES ({','.join('?' * len(f))})", list(f.values()))
    c.commit()
    c.execute("VACUUM")
    c.close()
    avant = chemin.stat().st_size
    d = travail / "compact-veille"
    shutil.rmtree(d, ignore_errors=True)
    cp = C.Compacteur(d, horloge=lambda: MAINTENANT)
    t0 = time.perf_counter()
    r = cp.archiver_veille(chemin, 180)
    t = time.perf_counter() - t0
    st = cp.statistiques()
    cp.fermer()
    ent = C.entretenir(chemin, "oui")
    return {"fiches": n, "base_avant_octets": avant, "archivees": r["archivees"],
            "base_apres_octets": ent["apres"], "froid_fichiers_octets": st["fichiers_octets"],
            "froid_avant_octets": st["avant_octets"], "froid_ratio_hors_index": st["ratio_hors_index"],
            "froid_total_octets": taille_dossier(d), "temps_s": round(t, 2)}


def mesurer_connaissances(gen: Gen, n: int, travail: Path) -> dict:
    chemin = travail / "nexus.db"
    c = sqlite3.connect(str(chemin))
    c.executescript("""
        CREATE TABLE connaissances (id INTEGER PRIMARY KEY, projet VARCHAR(40), titre VARCHAR(200), contenu TEXT,
          source VARCHAR(300), date DATETIME, auteur VARCHAR(60), version INTEGER, origine VARCHAR(10),
          empreinte VARCHAR(64), suspect BOOLEAN, UNIQUE(projet, source));
        CREATE VIRTUAL TABLE connaissances_fts USING fts5(titre, contenu, content='connaissances', content_rowid='id',
          tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER connaissances_ai AFTER INSERT ON connaissances BEGIN
          INSERT INTO connaissances_fts(rowid, titre, contenu) VALUES (new.id, new.titre, new.contenu); END;
        CREATE TRIGGER connaissances_ad AFTER DELETE ON connaissances BEGIN
          INSERT INTO connaissances_fts(connaissances_fts, rowid, titre, contenu)
          VALUES ('delete', old.id, old.titre, old.contenu); END;""")
    r = gen.r
    bases = []
    nb_dup = int(n * 0.2)
    for i in range(n - nb_dup):
        projet = r.choice(PROJETS)
        origine = r.choice(["auto"] * 6 + ["import"] * 3 + ["manuel"])
        contenu = gen.paragraphe(4, 9)[:800]
        bases.append((projet, origine, contenu))
        c.execute("INSERT INTO connaissances(projet, titre, contenu, source, date, auteur, version, origine, empreinte,"
                  " suspect) VALUES (?,?,?,?,?,?,1,?,?,0)",
                  (projet, f"livrable #{i} — note", contenu, f"livrable #{i}" if origine == "auto" else f"doc{i}.md#1",
                   (MAINTENANT - timedelta(days=r.randint(0, 400))).isoformat(sep=" "), "nexus-core", origine,
                   hashlib.sha256(contenu.encode()).hexdigest()))
    for j in range(nb_dup):  # quasi-doublons : une phrase modifiée ou ajoutée
        projet, _, contenu = r.choice(bases)
        phrases = contenu.split(". ")
        phrases[r.randrange(len(phrases))] = gen.phrase().rstrip(".")
        v = ". ".join(phrases) if r.random() < 0.5 else contenu + " " + gen.phrase()
        k = n + j
        c.execute("INSERT INTO connaissances(projet, titre, contenu, source, date, auteur, version, origine, empreinte,"
                  " suspect) VALUES (?,?,?,?,?,?,1,'auto',?,0)",
                  (projet, f"livrable #{k} — note", v, f"livrable #{k}",
                   (MAINTENANT - timedelta(days=r.randint(0, 400))).isoformat(sep=" "), "nexus-core",
                   hashlib.sha256(v.encode()).hexdigest()))
    c.commit()
    c.execute("VACUUM")
    avant = chemin.stat().st_size
    d = travail / "compact-k"
    shutil.rmtree(d, ignore_errors=True)
    cp = C.Compacteur(d, horloge=lambda: MAINTENANT)
    t0 = time.perf_counter()
    res = cp.consolider_connaissances(c, plafond=250, seuil=0.7)
    t = time.perf_counter() - t0
    c.close()
    ent = C.entretenir(chemin, "oui")
    v = cp.verifier()["valide"]
    cp.fermer()
    return {"connaissances": n, "quasi_doublons_injectes": nb_dup, "fusionnees": res["fusionnees"],
            "evincees_plafond_250": res["evincees"], "base_avant_octets": avant, "base_apres_octets": ent["apres"],
            "archive_octets": taille_dossier(d), "temps_s": round(t, 2), "verification": v}


# --------------------------------------------------------------------------------- projection
def projection(par_mission: dict, veille_par_fiche: dict, rythme: float) -> dict:
    res = {}
    for annees in (1, 3):
        h = 365 * annees
        chaud = rythme * min(h, 30)
        tiede = rythme * max(0, min(h, 180) - 30)
        froid = rythme * max(0, h - 180)
        avec = chaud * par_mission["chaud"] + tiede * par_mission["tiede"] + froid * par_mission["froid"]
        sans = rythme * h * par_mission["chaud"]
        fiches = 28 * (rythme / 40)
        v_actuel = fiches * min(h, 180) * veille_par_fiche["actuel"]   # purge à 180 j (perte)
        v_avec = v_actuel + fiches * max(0, h - 180) * veille_par_fiche["froid"]  # rien de perdu
        res[f"{annees}an"] = {"missions": int(rythme * h), "sans_compaction_mo": round(sans / 1e6, 1),
                              "avec_compaction_mo": round(avec / 1e6, 1), "gain_x": round(sans / avec, 1),
                              "veille_actuel_mo": round(v_actuel / 1e6, 1), "veille_avec_archivage_mo": round(v_avec / 1e6, 1)}
    return res


# --------------------------------------------------------------------------------- rapport
def mo(x: float) -> str:
    return f"{x / 1e6:,.2f} Mo".replace(",", " ")


def rapport(R: dict) -> str:
    L = ["# Compaction SYFER — résultats du banc de mesure", "",
         f"_Généré par `compaction/mesure.py` le {datetime.now():%Y-%m-%d %H:%M} — Python {sys.version.split()[0]}, "
         f"SQLite {sqlite3.sqlite_version}. Corpus synthétique : {R['corpus']['missions']} missions sur "
         f"{R['corpus']['jours']} jours, {R['veille']['fiches']} fiches de veille, "
         f"{R['connaissances']['connaissances']} connaissances (20 % de quasi-doublons)._", "",
         "## 1. Missions : comparaison des méthodes (corpus complet, enregistrements intégraux)", "",
         f"Taille brute (JSON canonique des lignes d'archive) : **{mo(R['brut_octets'])}**, "
         f"soit {R['brut_octets'] / R['corpus']['missions'] / 1000:.1f} Ko par mission.", "",
         "| Méthode | Taille | Ratio | Compaction | Lecture d'un enregistrement | Remarque |",
         "|---|---:|---:|---:|---:|---|",
         f"| **Format actuel** (gzip par ligne, AAAA-MM.jsonl.gz) | {mo(R['actuel']['octets'])} | "
         f"{R['brut_octets'] / R['actuel']['octets']:.2f} | {R['actuel']['temps_s']:.1f} s | "
         f"{R['actuel']['lecture_ms']:.1f} ms | lecture = décompresser et parcourir le mois |",
         f"| + index actuel archive_index/FTS (texte ≤ 4000) | {mo(R['actuel']['index_octets'])} | — | — | — | "
         f"recherche {R['actuel']['recherche_ms']:.2f} ms |"]
    for m in R["methodes"]:
        L.append(f"| {m['methode']} | {mo(m['octets'])} | {m['ratio']:.2f} | {m['compaction_s']:.1f} s | "
                 f"{m['lecture_ms']:.2f} ms | {m['note']} |")
    P = R["paliers"]
    st = P["stats"]
    L += ["", "## 2. Pipeline complet à paliers (module `app/compaction.py`)", "",
          f"Chaud ≤ 30 j laissé au format actuel ; tiède 31–180 j ; froid > 180 j. Enregistrements compactés : "
          f"{st['paliers'].get('tiede', {}).get('enregistrements', 0)} tièdes, "
          f"{st['paliers'].get('froid', {}).get('enregistrements', 0)} froids.", "",
          "| Palier | Avant (brut) | Fichiers de blocs | Ratio fichiers |", "|---|---:|---:|---:|"]
    for pal, p in st["paliers"].items():
        L.append(f"| {pal} | {mo(p['avant_octets'])} | {mo(p['fichiers_octets'])} | {p['ratio']} |")
    L += ["", f"- Fragments dédupliqués : {st['dedup']['fragments']} ({mo(st['dedup']['fragments_octets'])} stockés, "
              f"{mo(st['dedup']['octets_evites'])} de texte non répété).",
          f"- Index SQLite (blocs, enregistrements, feuilles de Merkle, FTS5, agrégats) : {mo(st['index_octets'])} "
          f"dont FTS5 {mo(P['index_fts_octets'])} ; après entretien (VACUUM) : {mo(P['entretien']['apres'])}.",
          f"- Total dossier compact/ : **{mo(P['dossier_octets'])}** pour {mo(st['avant_octets'])} brut → "
          f"ratio global **{st['avant_octets'] / P['dossier_octets']:.1f}** (index compris) ; "
          f"{st['ratio_hors_index']} hors index.",
          f"- Temps : compaction tiède {P['tiede_s']} s, migration froid {P['froid_s']} s, vérification complète "
          f"{P['verifier_s']} s (valide : {P['verifier_valide']}), vérification d'un enregistrement {P['verifier_un_ms']} ms.",
          f"- Lecture d'un enregistrement (cache vide) : tiède {P['lecture_ms']['tiede']} ms (p95 "
          f"{P['lecture_p95_ms']['tiede']} ms), froid {P['lecture_ms']['froid']} ms (p95 {P['lecture_p95_ms']['froid']} ms).",
          f"- Recherche FTS5 : {P['recherche_ms']} ms par requête ({P['recherche_extrait_ms']} ms avec extraits) ; "
          f"format actuel : {R['actuel']['recherche_ms']:.2f} ms.",
          f"- Effacement RGPD d'un enregistrement dans un bloc : {P['effacement_ms']} ms (bloc réécrit, racine recalculée).",
          "", "Variantes (même corpus) :", "",
          "| Variante | Dossier compact/ | Fichiers de blocs | Index après VACUUM | Compaction tiède | Lecture tiède | Recherche |",
          "|---|---:|---:|---:|---:|---:|---:|",
          f"| **défaut** (tiède zlib + dict, FTS5 detail=none) | {mo(P['dossier_octets'])} | {mo(st['fichiers_octets'])} | "
          f"{mo(P['entretien']['apres'])} | {P['tiede_s']} s | {P['lecture_ms']['tiede']} ms | {P['recherche_ms']} ms |"]
    for nom, v in R.get("variantes", {}).items():
        L.append(f"| {nom} | {mo(v['dossier_octets'])} | {mo(v['fichiers'])} | {mo(v['index_apres'])} | "
                 f"{v['tiede_s']} s | {v['lecture_tiede_ms']} ms | {v['recherche_ms']} ms |")
    L += [
          "", "## 3. Veille et mémoire de travail", "",
          f"- Veille : {R['veille']['fiches']} fiches sur 360 j ; base {mo(R['veille']['base_avant_octets'])} → "
          f"{mo(R['veille']['base_apres_octets'])} après archivage des {R['veille']['archivees']} fiches expirées "
          f"(> 180 j) en palier froid : {mo(R['veille']['froid_total_octets'])} au lieu de la suppression actuelle "
          f"(ratio fichiers {R['veille']['froid_ratio_hors_index']}).",
          f"- Connaissances : {R['connaissances']['connaissances']} dont {R['connaissances']['quasi_doublons_injectes']} "
          f"quasi-doublons injectés ; {R['connaissances']['fusionnees']} fusionnées, "
          f"{R['connaissances']['evincees_plafond_250']} évincées (plafond 250/projet) vers l'archive ; base "
          f"{mo(R['connaissances']['base_avant_octets'])} → {mo(R['connaissances']['base_apres_octets'])} en "
          f"{R['connaissances']['temps_s']} s (archive {mo(R['connaissances']['archive_octets'])}, vérification "
          f"{R['connaissances']['verification']}).", "",
          "## 4. Projection d'espace disque (archive des missions + index)", "",
          f"Coût par mission mesuré : chaud {R['par_mission']['chaud'] / 1000:.1f} Ko (format actuel + index), "
          f"tiède {R['par_mission']['tiede'] / 1000:.2f} Ko, froid {R['par_mission']['froid'] / 1000:.2f} Ko (index compris).", "",
          "| Rythme | Horizon | Missions | Sans compaction | Avec compaction | Gain | Veille actuelle (purge) | Veille archivée (sans perte) |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for nom, pr in R["projection"].items():
        for h, v in pr.items():
            L.append(f"| {nom} | {h.replace('an', ' an')} | {v['missions']} | {v['sans_compaction_mo']} Mo | "
                     f"{v['avec_compaction_mo']} Mo | ×{v['gain_x']} | {v['veille_actuel_mo']} Mo | "
                     f"{v['veille_avec_archivage_mo']} Mo |")
    M = {m["methode"]: m for m in R["methodes"]}
    V = R.get("variantes", {})
    vl = next((v for k, v in V.items() if "lzma" in k), None)
    vf = next((v for k, v in V.items() if "full" in k), None)
    L += ["", "## 5. Choix retenus et justification (d'après ces mesures)", "",
          f"- **Blocs plutôt que lignes** : le format actuel (un membre gzip par ligne) plafonne à un ratio de "
          f"{R['brut_octets'] / R['actuel']['octets']:.1f} ; la concaténation en blocs atteint "
          f"{M['zlib bloc']['ratio']} en zlib et {M['lzma bloc']['ratio']} en lzma, et l'index (bloc, offset) ramène "
          f"la lecture d'un enregistrement de {R['actuel']['lecture_ms']:.0f} ms (parcours du mois) à quelques ms.",
          f"- **Dictionnaire zlib** : ×{M['zlib ligne + dict']['ratio'] / M['zlib ligne']['ratio']:.2f} sur des objets "
          f"isolés (fragments), mais seulement ×{M['zlib bloc + dict']['ratio'] / M['zlib bloc']['ratio']:.2f} sur des "
          "blocs de 1 Mo (la fenêtre zlib de 32 Ko limite sa portée). Conservé car gratuit à la lecture ; versionné.",
          f"- **lzma pour le froid** (×{M['lzma bloc']['ratio'] / M['zlib bloc + dict']['ratio']:.2f} par rapport à "
          "zlib) : lecture plus lente mais rare. **zlib pour le tiède** : lecture et recherche avec extraits ~4× plus "
          "rapides" + (f" ; passer le tiède en lzma (COMPACTION_ALGO_TIEDE=lzma) gagnerait encore "
          f"{(1 - vl['dossier_octets'] / P['dossier_octets']) * 100:.0f} % pour une lecture à {vl['lecture_tiede_ms']} ms."
          if vl else "."),
          f"- **Déduplication : gain faible, à ne pas surestimer.** Sur les enregistrements intégraux elle DÉGRADE le "
          f"ratio (zlib bloc {M['zlib bloc + dict']['ratio']} → {M['zlib bloc + dict + dédup']['ratio']}, lzma "
          f"{M['lzma bloc']['ratio']} → {M['lzma bloc + dédup']['ratio']}) : un fragment compressé seul perd le "
          "contexte du bloc. Dans le pipeline à paliers, avec le critère `rentable` (segments longs et fréquents "
          f"seulement), elle reste légèrement positive : {P['stats']['dedup']['fragments']} fragments, "
          f"{mo(P['stats']['dedup']['octets_evites'])} de texte non répété, ≈ 0,3 % sur le total mesuré à part. "
          "Gardée pour les consignes types et gabarits réels (plus longs que dans ce corpus).",
          f"- **Paliers** : le plus gros gain vient de la réduction du contenu (tiède ×"
          f"{P['stats']['paliers'].get('tiede', {}).get('ratio')}, froid ×{P['stats']['paliers'].get('froid', {}).get('ratio')}"
          " en fichiers), en gardant ce qui alimente la mémoire collective (problèmes du CHECKER, décisions, métriques, "
          "extrait d'exemple) et la chaîne d'empreintes de l'archive.",
          f"- **Index FTS5 detail=none** : " + (f"{mo(vf['index_apres'])} → {mo(P['entretien']['apres'])} d'index "
          f"(−{(1 - P['dossier_octets'] / vf['dossier_octets']) * 100:.0f} % au total) ; le classement bm25 est "
          "remplacé par « nombre de termes trouvés, puis le plus récent » (COMPACTION_FTS_DETAIL=full pour bm25)."
          if vf else "index ~3× plus petit, classement par termes trouvés puis date."),
          "- **Limites** : le chaud (≤ 30 j) et les tables `missions`/`etapes` de nexus.db ne sont pas compactés "
          "(hors périmètre) ; le tiède/froid est une réduction volontaire (les sorties intermédiaires des agents "
          "disparaissent après 30 j, leur empreinte reste) ; l'effacement RGPD coûte un 'optimize' FTS (~0,5 s).", ""]
    if R.get("graphique"):
        L += [f"![Résultats]({R['graphique']})", ""]
    return "\n".join(L)


def graphique(R: dict, chemin: Path) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 5))
    noms = ["actuel"] + [m["methode"] for m in R["methodes"]] + ["paliers (tout compris)"]
    ratios = [R["brut_octets"] / R["actuel"]["octets"]] + [m["ratio"] for m in R["methodes"]] + \
             [R["paliers"]["stats"]["avant_octets"] / R["paliers"]["dossier_octets"]]
    a.barh(noms, ratios, color=["#888"] + ["#3b6ea8"] * len(R["methodes"]) + ["#2a8a4a"])
    a.set_xlabel("ratio de compression (brut / stocké)")
    a.invert_yaxis()
    a.set_title("Missions : ratio par méthode")
    for nom, couleur in (("nominal (40/j)", "#3b6ea8"), ("200 % (80/j)", "#c0612b")):
        p = R["projection"][nom]
        b.plot([0, 1, 3], [0, p["1an"]["sans_compaction_mo"], p["3an"]["sans_compaction_mo"]], "--", color=couleur,
               label=f"sans compaction, {nom}")
        b.plot([0, 1, 3], [0, p["1an"]["avec_compaction_mo"], p["3an"]["avec_compaction_mo"]], "-", color=couleur,
               label=f"avec compaction, {nom}")
    b.set_xlabel("années")
    b.set_ylabel("Mo (archive + index)")
    b.set_title("Projection d'espace disque")
    b.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(chemin, dpi=110)
    return chemin.name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--missions", type=int, default=10000)
    ap.add_argument("--fiches", type=int, default=5000)
    ap.add_argument("--connaissances", type=int, default=2000)
    ap.add_argument("--sortie", default=str(ICI))
    args = ap.parse_args(argv)
    for v in ("COMPACTION_TIEDE_JOURS", "COMPACTION_FROID_JOURS", "COMPACTION_BLOC_N", "COMPACTION_BLOC_OCTETS"):
        os.environ.pop(v, None)
    os.environ["LEDGER_HMAC_KEY"] = CLE.decode()
    rng = random.Random(7)
    gen = Gen(42)
    jours = max(1, round(args.missions / 40))
    sortie = Path(args.sortie)
    R = {"corpus": {"missions": args.missions, "jours": jours}}
    with tempfile.TemporaryDirectory(prefix="syfer-mesure-") as tmp:
        travail = Path(tmp)
        print(f"[1/6] corpus : {args.missions} missions sur {jours} jours…", flush=True)
        lignes = lignes_archive(gen, args.missions, jours)
        R["brut_octets"] = sum(len(C.canonique(l)) + 1 for l in lignes)
        print("[2/6] format actuel…", flush=True)
        actuel_dir = travail / "archive"
        R["actuel"] = ecrire_actuel(lignes, actuel_dir)
        R["actuel"]["index_octets"] = index_actuel(lignes, travail / "index_actuel.db")["octets"]
        R["actuel"]["recherche_ms"] = recherche_actuelle(travail / "index_actuel.db")
        R["actuel"]["lecture_ms"] = lecture_actuelle(actuel_dir, lignes, rng)
        print("[3/6] méthodes (ligne, bloc, dictionnaire, lzma, dédup)…", flush=True)
        R["methodes"] = mesurer_methodes(lignes, R["brut_octets"], rng)
        print("[4/6] pipeline à paliers…", flush=True)
        R["paliers"] = pipeline_paliers(lignes, travail, actuel_dir, rng)
        R["variantes"] = {}
        for nom, env in (("tiède en lzma (COMPACTION_ALGO_TIEDE=lzma)", {"COMPACTION_ALGO_TIEDE": "lzma"}),
                         ("FTS5 detail=full, classement bm25 (COMPACTION_FTS_DETAIL=full)", {"COMPACTION_FTS_DETAIL": "full"})):
            v = pipeline_paliers(lignes, travail, actuel_dir, random.Random(7), env)
            R["variantes"][nom] = {"dossier_octets": v["dossier_octets"], "index_apres": v["entretien"]["apres"],
                                   "fichiers": v["stats"]["fichiers_octets"], "tiede_s": v["tiede_s"],
                                   "lecture_tiede_ms": v["lecture_ms"]["tiede"], "recherche_ms": v["recherche_ms"]}
        for k in ("COMPACTION_ALGO_TIEDE", "COMPACTION_FTS_DETAIL"):
            os.environ.pop(k, None)
        print("[5/6] veille et connaissances…", flush=True)
        R["veille"] = mesurer_veille(Gen(43), args.fiches, travail)
        R["connaissances"] = mesurer_connaissances(Gen(44), args.connaissances, travail)
    # coûts par mission
    st, P = R["paliers"]["stats"], R["paliers"]
    n_chaud = args.missions - st["paliers"].get("tiede", {}).get("enregistrements", 0) - \
        st["paliers"].get("froid", {}).get("enregistrements", 0)
    nb = max(1, st["paliers"].get("tiede", {}).get("enregistrements", 0) + st["paliers"].get("froid", {}).get("enregistrements", 0))
    index_par = P["entretien"]["apres"] / nb
    R["par_mission"] = {
        "chaud": (R["actuel"]["octets"] + R["actuel"]["index_octets"]) / args.missions,
        "tiede": st["paliers"]["tiede"]["fichiers_octets"] / st["paliers"]["tiede"]["enregistrements"] + index_par
        if "tiede" in st["paliers"] else 0,
        "froid": st["paliers"]["froid"]["fichiers_octets"] / st["paliers"]["froid"]["enregistrements"] + index_par
        if "froid" in st["paliers"] else 0}
    R["par_mission"]["tiede"] = R["par_mission"]["tiede"] or R["par_mission"]["froid"]
    R["missions_chaudes_non_compactees"] = n_chaud
    v = R["veille"]
    veille_par = {"actuel": v["base_avant_octets"] / v["fiches"],
                  "froid": v["froid_total_octets"] / max(1, v["archivees"])}
    R["projection"] = {"nominal (40/j)": projection(R["par_mission"], veille_par, 40),
                       "200 % (80/j)": projection(R["par_mission"], veille_par, 80)}
    print("[6/6] rapport…", flush=True)
    R["graphique"] = graphique(R, sortie / "resultats.png")
    (sortie / "resultats.json").write_text(json.dumps(R, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (sortie / "resultats.md").write_text(rapport(R), encoding="utf-8")
    print(f"OK : {sortie / 'resultats.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
