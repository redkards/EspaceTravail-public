"""Compaction de la mémoire et des archives de SYFER (concaténation en blocs, dédup, paliers).

=====================================================================================================
INTÉGRATION (à faire par l'agent noyau ; ce module ne modifie aucun fichier existant)
=====================================================================================================
Module autonome (Python 3.12, bibliothèque standard). Instance par défaut : `defaut()` ;
dossier NEXUS_COMPACTION_DIR (défaut <NEXUS_ARCHIVE_DIR ou NEXUS_DATA_DIR/archive>/compact),
clé = LEDGER_HMAC_KEY (la même que le LEDGER ; SHA-256 si absente, comme ledger.py).

1. app/archive.py
   - effacer(mid, …) : appeler aussi `compaction.defaut(journal=ledger.journaliser)
     .effacer_mission(mid, motif, demandeur)` (tombstone dans le bloc + journal chaîné).
   - verifier() : quand des mois ont été retirés (`retirer_mois`), démarrer la chaîne avec
     `compaction.defaut().point_de_reprise()` -> {"seq", "hash"} au lieu de GENESE ; ajouter
     `compaction.defaut().verifier()` au résultat.
   - rechercher() : compléter par `compaction.defaut().rechercher(q, projet, service, limite)`
     (mêmes clés : mission_id, projet, service, statut, extrait ; + palier).
   - lignes() : les mois retirés ne sont plus lus ; `compaction.defaut().lire_mission(mid)`
     renvoie les enregistrements compactés d'une mission.
2. app/memoire.py : consolidation hebdomadaire ou nocturne :
   `defaut().consolider_connaissances(sqlite3.connect(<nexus.db>), plafond=…, acces=…)`
   (fusion des quasi-doublons « auto », éviction vers l'archive au-delà du plafond ; les
   connaissances « import » et « manuel » ne sont jamais supprimées). Après l'appel, rien à
   resynchroniser : les déclencheurs FTS de `connaissances` suivent les DELETE.
   La cascade RGPD (archive._effacer_cascade) doit aussi appeler effacer_mission (point 1) : les
   connaissances « livrable #mid » évincées sont indexées par mission_id.
3. Veille (veille/collecteur.py, avant `purger`) : `defaut().archiver_veille(<veille.db>, jours)`
   met les fiches expirées en palier FROID puis les supprime de la base de veille.
4. Fenêtre de nuit : dans la boucle de fond de main.py (celle qui appelle fantome chaque minute),
   appeler `compaction.tache_nocturne(nexus_db=cfg().data_dir/'nexus.db', veille_db=…,
   journal=ledger.journaliser)` : ne fait rien hors NEXUS_FENETRE_NUIT (01:00-06:00 Paris) ni
   plus d'une fois par jour (méta « derniere_nuit ») ; verrou fichier non bloquant.
   Variables : COMPACTION_TIEDE_JOURS (30), COMPACTION_FROID_JOURS (180), COMPACTION_BLOC_N (256),
   COMPACTION_BLOC_OCTETS (1000000), COMPACTION_PLAFOND_CONNAISSANCES (0 = pas de plafond),
   COMPACTION_RETIRER_SOURCES (0 : les fichiers AAAA-MM.jsonl.gz compactés sont gardés),
   COMPACTION_VACUUM_JOUR (6 = dimanche ; VACUUM complet hebdomadaire, sinon incrémental).
5. backup.sh : sauvegarder le dossier compact/ ENTIER (blocs/, dictionnaires/, compaction.db) ;
   copie cohérente de compaction.db par `sqlite3 compaction.db ".backup …"` comme nexus.db.
   restore.sh : restaurer puis appeler `defaut().reprendre()` et `defaut().verifier()`.
=====================================================================================================

Conception (voir compaction/README.md et compaction/resultats.md) :
- Paliers : CHAUD (≤ 30 j) = système actuel (missions SQLite + archive AAAA-MM.jsonl.gz + FTS),
  non touché ; TIÈDE (31-180 j) = livrable complet, étapes réduites (agent, rôle, verdict, tokens,
  avis du CHECKER tronqué), blocs zlib + dictionnaire entraîné ; FROID (> 180 j) = résumé
  ≤ 600 caractères + métriques + empreintes + signaux de mémoire collective, blocs lzma.
- Blocs : ≤ N enregistrements ou ≤ ~1 Mo non compressé, sérialisation JSON canonique, un fichier
  par bloc (réécriture atomique : indispensable à un effacement RGPD réel). Index SQLite
  (id -> bloc, position, offset, longueur, feuille Merkle) : lecture d'un enregistrement = 1 bloc.
- Déduplication : segments de texte (lignes ≥ 64 car.) vus ≥ 2 fois stockés une fois
  (empreinte SHA-256, compteur de références), remplacés par {"$f": [...]} dans l'enregistrement.
- Intégrité : feuille = SHA-256(0x00‖JSON canonique de l'enregistrement LOGIQUE développé), racine
  de Merkle par bloc ; journal append-only chaîné HMAC-SHA256 (clé du LEDGER) : création, retrait,
  effacement (ancienne/nouvelle racine), dictionnaires. La chaîne d'origine de l'archive
  (seq, prec, contenu, ledger_ref, hash) est conservée dans chaque enregistrement compacté et
  reste vérifiable avec archive._empreinte_ligne.
- RGPD : effacer() réécrit le bloc avec une pierre tombale (feuille d'avant conservée), retire le
  texte de l'index plein texte, libère les fragments orphelins (PRAGMA secure_delete), trace au
  journal chaîné et (option) au LEDGER.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import lzma
import os
import re
import sqlite3
import struct
import threading
import time
import unicodedata
import zlib
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover - base de fuseaux absente
    PARIS = timezone(timedelta(hours=1), "Europe/Paris (UTC+1, approximatif)")

GENESE = "0" * 64
MAGIC = b"SYFB"
FORMAT = 1
PALIERS = ("chaud", "tiede", "froid")
SEG_MIN = 64            # longueur minimale d'un segment dédupliqué
DICT_TAILLE = 32768     # fenêtre zlib : un dictionnaire plus grand est inutile
AVIS_MAX = 300          # avis du CHECKER conservé au palier tiède
RESUME_MAX = 600        # résumé du palier froid
EXEMPLE_MAX = 1500      # = exemples.TAILLE_EXEMPLE (extrait conservé pour les exemples few-shot)
TEXTE_MAX = 300         # commentaires / messages conservés au palier froid
INDEX_TIEDE = 1500      # texte indexé (FTS) par enregistrement tiède
_COUPE = re.compile(r"(\n+)")
MOTS_VIDES = set("""le la les un une des du de d l et ou en au aux a pour par sur dans avec sans ce cette ces
cet son sa ses leur leurs mon ma mes ton ta tes nos vos qui que quoi dont est sont etre fait faire fais
redige redigez donne liste plus moins tres tout tous toute toutes comme mais pas ne se s y il elle on nous
vous ils elles je tu me te lui eux the and for with""".split())


# --- Configuration ----------------------------------------------------------------------------

def _env_int(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, "") or defaut)
    except ValueError:
        return defaut


def config() -> dict:
    return {"tiede_jours": _env_int("COMPACTION_TIEDE_JOURS", 30),
            "froid_jours": _env_int("COMPACTION_FROID_JOURS", 180),
            "bloc_n": _env_int("COMPACTION_BLOC_N", 256),
            "bloc_n_froid": _env_int("COMPACTION_BLOC_N_FROID", 1024),
            "bloc_octets": _env_int("COMPACTION_BLOC_OCTETS", 1_000_000),
            "plafond_connaissances": _env_int("COMPACTION_PLAFOND_CONNAISSANCES", 0),
            "retirer_sources": os.environ.get("COMPACTION_RETIRER_SOURCES", "0").strip() == "1",
            "vacuum_jour": _env_int("COMPACTION_VACUUM_JOUR", 6),
            "algo_tiede": "lzma" if os.environ.get("COMPACTION_ALGO_TIEDE", "").strip() == "lzma" else "zlib",
            "fts_detail": "full" if os.environ.get("COMPACTION_FTS_DETAIL", "").strip() == "full" else "none",
            "jours_agregats_jour": _env_int("COMPACTION_AGREGATS_JOURS", 90)}


def cle_hmac() -> bytes | None:
    """Même clé et même règle que ledger.cle_hmac()."""
    v = os.environ.get("LEDGER_HMAC_KEY", "").strip()
    return v.encode("utf-8") if v else None


def dossier_defaut() -> Path:
    v = os.environ.get("NEXUS_COMPACTION_DIR", "").strip()
    if v:
        return Path(v)
    a = os.environ.get("NEXUS_ARCHIVE_DIR", "").strip()
    base = Path(a) if a else Path(os.environ.get("NEXUS_DATA_DIR", "/data")) / "archive"
    return base / "compact"


# --- Utilitaires ------------------------------------------------------------------------------

def canonique(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower())


def requete_fts(q: str) -> str | None:
    """Même construction que memoire._requete_fts (OR de préfixes, mots vides retirés)."""
    mots = []
    for m in re.findall(r"[a-z0-9]+", normaliser(q)):
        if len(m) >= 3 and m not in MOTS_VIDES and m not in mots:
            mots.append(m)
    return " OR ".join(f'"{m}"*' for m in mots[:16]) or None


def _date(v) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v or "").strip().rstrip("Z")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return datetime(1970, 1, 1)


def _iso(d: datetime) -> str:
    return d.replace(tzinfo=None).isoformat(timespec="seconds")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _tronquer(t: str | None, n: int) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# --- Dictionnaire zlib ------------------------------------------------------------------------

_SEG_DICT = re.compile(rb'"[A-Za-z_]{2,30}":\[?\{?"?|[^"\\\n]{8,240}')
_PHRASE = re.compile(rb"(?<=[.!?;:])\s+")


def entrainer_dictionnaire(echantillons: Iterable[bytes], taille: int = DICT_TAILLE) -> bytes:
    """Dictionnaire prédéfini zlib (zdict) : segments fréquents (clés JSON, formulations
    récurrentes des agents), classés par fréquence documentaire × longueur ; les plus utiles en fin
    de dictionnaire (distance de référence la plus courte)."""
    df: Counter = Counter()
    n = 0
    for e in echantillons:
        n += 1
        vus = set()
        for m in _SEG_DICT.findall(e):
            for p in _PHRASE.split(m):
                if 6 <= len(p) <= 240:
                    vus.add(p)
        df.update(vus)
    seuil = max(2, n // 50)
    cands = sorted(((c * len(s), s) for s, c in df.items() if c >= seuil), reverse=True)
    choisis, total = [], 0
    for _, s in cands:
        if total + len(s) <= taille:
            choisis.append(s)
            total += len(s)
    return b"".join(reversed(choisis))


def z_compresser(donnees: bytes, zdict: bytes | None = None, niveau: int = 9) -> bytes:
    c = zlib.compressobj(niveau, zlib.DEFLATED, -15, 9, zlib.Z_DEFAULT_STRATEGY,
                         **({"zdict": zdict} if zdict else {}))
    return c.compress(donnees) + c.flush()


def z_decompresser(donnees: bytes, zdict: bytes | None = None) -> bytes:
    d = zlib.decompressobj(-15, **({"zdict": zdict} if zdict else {}))
    return d.decompress(donnees) + d.flush()


_FILTRES_LZMA = [{"id": lzma.FILTER_LZMA2, "preset": 9, "dict_size": 1 << 21}]  # 2 Mo : ~25 Mo de RAM


def x_compresser(donnees: bytes) -> bytes:
    return lzma.compress(donnees, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, filters=_FILTRES_LZMA)


def x_decompresser(donnees: bytes) -> bytes:
    return lzma.decompress(donnees)


# --- Merkle -----------------------------------------------------------------------------------

def feuille(enreg: dict) -> bytes:
    return hashlib.sha256(b"\x00" + canonique(enreg)).digest()


def racine(feuilles: list[bytes]) -> bytes:
    if not feuilles:
        return hashlib.sha256(b"").digest()
    niv = list(feuilles)
    while len(niv) > 1:
        suiv = [hashlib.sha256(b"\x01" + niv[i] + niv[i + 1]).digest() for i in range(0, len(niv) - 1, 2)]
        if len(niv) % 2:
            suiv.append(niv[-1])  # nœud impair promu tel quel
        niv = suiv
    return niv[0]


def preuve(feuilles: list[bytes], i: int) -> list[tuple[str, bytes]]:
    """Chemin d'audit [(côté du frère, frère)] de la feuille i jusqu'à la racine."""
    chemin, niv = [], list(feuilles)
    while len(niv) > 1:
        frere = i ^ 1
        if frere < len(niv):
            chemin.append(("g" if frere < i else "d", niv[frere]))
        suiv = [hashlib.sha256(b"\x01" + niv[k] + niv[k + 1]).digest() for k in range(0, len(niv) - 1, 2)]
        if len(niv) % 2:
            suiv.append(niv[-1])
        niv, i = suiv, i // 2
    return chemin


def verifier_preuve(f: bytes, chemin: list[tuple[str, bytes]], r: bytes) -> bool:
    h = f
    for cote, frere in chemin:
        h = hashlib.sha256(b"\x01" + (frere + h if cote == "g" else h + frere)).digest()
    return hmac.compare_digest(h, r)


# --- Transformations par palier ---------------------------------------------------------------

def _problemes(d: dict) -> list[dict]:
    res = []
    for cle in ("verdicts_checker", "charte_violations"):
        for v in d.get(cle) or []:
            res.append({"type": cle, "source": v.get("source"), "verdict": v.get("verdict"),
                        "problemes": [p[:TEXTE_MAX] for p in v.get("problemes", []) if isinstance(p, str)]})
    return res


def reduire_tiede(enreg: dict) -> dict:
    """Palier TIÈDE : livrable complet ; étapes réduites à l'essentiel."""
    if enreg.get("efface") or enreg.get("type") != "mission":
        return enreg
    d = dict(enreg.get("donnees") or {})
    if d.get("efface"):
        return enreg
    etapes = []
    for e in d.get("etapes") or []:
        r = {"agent": e.get("agent"), "role": e.get("role"), "verdict": e.get("verdict"), "tokens": e.get("tokens")}
        if (e.get("role") or "").startswith("checker"):
            r["avis"] = _tronquer(e.get("sortie"), AVIS_MAX)
        etapes.append(r)
    d["etapes"] = etapes
    return {**enreg, "donnees": d, "forme": "reduit"}


def _exemple_eligible(d: dict) -> bool:
    note = d.get("note")
    return (isinstance(note, (int, float)) and note >= _env_int("NEXUS_EXEMPLES_SEUIL", 4)) or \
        any(x.get("statut") == "validee" for x in d.get("decisions") or [])


def resumer_froid(enreg: dict) -> dict:
    """Palier FROID : résumé ≤ 600 car. + métriques + empreintes + signaux de mémoire collective."""
    if enreg.get("efface"):
        return enreg
    t = enreg.get("type")
    d = enreg.get("donnees") or {}
    if d.get("efface"):
        return {**enreg, "forme": "resume"}
    if t == "mission":
        livrable = d.get("livrable") or ""
        resume = _tronquer(f"{d.get('titre', '')} — {_tronquer(d.get('consigne'), 160)} → {livrable}", RESUME_MAX)
        memoire = {"problemes": _problemes(d),
                   "decisions": [{"statut": x.get("statut"), "objet": x.get("objet"), "risque": x.get("risque"),
                                  "commentaire": _tronquer(x.get("commentaire"), TEXTE_MAX) or None,
                                  "motif": _tronquer(x.get("motif"), TEXTE_MAX) or None}
                                 for x in d.get("decisions") or []],
                   "message": _tronquer(d.get("message"), TEXTE_MAX) or None,
                   "relance_auto": d.get("relance_auto")}
        if _exemple_eligible(d) and livrable:
            memoire["exemple"] = livrable[:EXEMPLE_MAX]
        roles = Counter(e.get("role") for e in d.get("etapes") or [])
        nd = {k: d.get(k) for k in ("evenement", "horodatage", "mission_id", "titre", "projet", "service", "statut",
                                    "niveau", "fonctionnement_demande", "fonctionnement", "modeles", "montant_eur",
                                    "action", "revisions", "tokens", "tokens_entree", "tokens_sortie", "cout_eur",
                                    "duree_s", "note", "note_banc")}
        nd.update({"resume": resume, "memoire": memoire, "roles": dict(sorted(roles.items(), key=lambda x: str(x[0]))),
                   "etapes_tokens": sum(int(e.get("tokens") or 0) for e in d.get("etapes") or []),
                   "empreintes": {"livrable": sha(livrable.encode()), "consigne": sha((d.get("consigne") or "").encode()),
                                  "tiede": feuille(enreg).hex()}})
        return {**enreg, "donnees": nd, "forme": "resume"}
    if t in ("veille", "connaissance"):
        cle = "resume" if t == "veille" else "contenu"
        texte = d.get(cle) or ""
        nd = {**d, cle: _tronquer(texte, RESUME_MAX), "empreinte_texte": sha(texte.encode())}
        return {**enreg, "donnees": nd, "forme": "resume"}
    return {**enreg, "forme": "resume"}


def texte_index(enreg: dict) -> str:
    """Texte court indexé (FTS5 sans contenu stocké) ; recalculable pour l'effacement."""
    if enreg.get("efface"):
        return ""
    d = enreg.get("donnees") or {}
    t = enreg.get("type")
    if t == "mission":
        probs = " ".join(p for v in _problemes(d) for p in v["problemes"]) if "verdicts_checker" in d else \
            " ".join(p for v in (d.get("memoire") or {}).get("problemes", []) for p in v.get("problemes", []))
        corps = d.get("resume") if "resume" in d else f"{(d.get('consigne') or '')[:600]} {(d.get('livrable') or '')[:900]}"
        return f"{d.get('titre', '')} {corps} {probs}"[:INDEX_TIEDE]
    if t == "veille":
        return f"{d.get('titre', '')} {d.get('resume', '')} {d.get('domaines', '')}"[:INDEX_TIEDE]
    if t == "connaissance":
        return f"{d.get('titre', '')} {d.get('contenu', '')}"[:INDEX_TIEDE]
    return json.dumps(d, ensure_ascii=False)[:INDEX_TIEDE]


def depuis_ligne_archive(ligne: dict) -> dict:
    """Ligne d'archive (archive.py) -> enregistrement logique compactable (chaîne conservée)."""
    e = ligne["enregistrement"]
    chaine = {k: ligne[k] for k in ("seq", "prec", "contenu", "ledger_ref", "algo", "hash")}
    r = {"id": f"m:{ligne['seq']}", "type": "mission", "date": (e.get("horodatage") or "").rstrip("Z"),
         "mission_id": e.get("mission_id"), "projet": e.get("projet"), "service": e.get("service"),
         "statut": e.get("statut"), "chaine": chaine, "forme": "integral", "donnees": e}
    if e.get("efface"):
        r["efface"] = True
    return r


# --- Déduplication ----------------------------------------------------------------------------

def rentable(longueur: int, df: int) -> bool:
    """Externaliser un segment vu dans `df` enregistrements n'est rentable que si le texte évité
    (≈ 50 % après compression) dépasse le coût d'un fragment (~64 o : ligne SQLite, empreinte) et des
    références (~4 o chacune). Mesuré : sans ce critère, la dédup de petits segments AGRANDIT
    l'archive (fragments compressés isolément, hors du contexte du bloc)."""
    return df >= 2 and (df - 1) * longueur * 0.5 > 64 + 4 * df


def _echapper(obj):
    if isinstance(obj, dict):
        return {("$" + k if k.startswith("$") else k): _echapper(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_echapper(x) for x in obj]
    return obj


def _segments_longs(s: str) -> Iterator[str]:
    for p in _COUPE.split(s):
        if len(p) >= SEG_MIN and not p.startswith("\n"):
            yield p


def _chaines(obj) -> Iterator[str]:
    if isinstance(obj, str):
        if len(obj) >= SEG_MIN:
            yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _chaines(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _chaines(v)


def _remplacer(obj, choix: Callable[[str], int | None]):
    if isinstance(obj, str):
        if len(obj) < SEG_MIN:
            return obj
        parts, change = [], False
        for p in _COUPE.split(obj):
            fid = choix(p) if len(p) >= SEG_MIN and not p.startswith("\n") else None
            if fid is not None:
                parts.append(fid)
                change = True
            elif p:
                if parts and isinstance(parts[-1], str):
                    parts[-1] += p
                else:
                    parts.append(p)
        return {"$f": parts} if change else obj
    if isinstance(obj, dict):
        return {k: _remplacer(v, choix) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remplacer(v, choix) for v in obj]
    return obj


def _references(obj, acc: list) -> list:
    if isinstance(obj, dict):
        if set(obj) == {"$f"}:
            acc.extend(p for p in obj["$f"] if isinstance(p, int))
        else:
            for v in obj.values():
                _references(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _references(v, acc)
    return acc


def _developper(obj, fragment: Callable[[int], str]):
    if isinstance(obj, dict):
        if set(obj) == {"$f"}:
            return "".join(fragment(p) if isinstance(p, int) else p for p in obj["$f"])
        return {(k[1:] if k.startswith("$") else k): _developper(v, fragment) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_developper(v, fragment) for v in obj]
    return obj


# --- Quasi-doublons (MinHash + LSH, bibliothèque standard) ------------------------------------

def shingles(texte: str, k: int = 5) -> set[int]:
    mots = re.findall(r"[a-z0-9]+", normaliser(texte))
    if len(mots) < k:
        return {hash_64(" ".join(mots))} if mots else set()
    return {hash_64(" ".join(mots[i:i + k])) for i in range(len(mots) - k + 1)}


def hash_64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


_MERSENNE = (1 << 61) - 1
_PERMS = [((hash_64(f"a{i}") % (_MERSENNE - 1)) + 1, hash_64(f"b{i}") % _MERSENNE) for i in range(64)]


def minhash(sh: set[int]) -> tuple[int, ...]:
    if not sh:
        return tuple([0] * len(_PERMS))
    return tuple(min((a * x + b) % _MERSENNE for x in sh) for a, b in _PERMS)


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def quasi_doublons(textes: dict, seuil: float = 0.85, bandes: int = 16) -> list[list]:
    """Groupes de clés dont les textes ont une similarité de Jaccard (shingles de 5 mots) ≥ seuil.
    Candidats par LSH (16 bandes × 4 lignes), confirmation exacte, regroupement union-find."""
    sh = {k: shingles(t) for k, t in textes.items()}
    sig = {k: minhash(s) for k, s in sh.items()}
    r = len(_PERMS) // bandes
    parent = {k: k for k in textes}

    def trouver(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    vus = set()
    for b in range(bandes):
        seaux: dict = {}
        for k, s in sig.items():
            seaux.setdefault(s[b * r:(b + 1) * r], []).append(k)
        for membres in seaux.values():
            for i in range(len(membres)):
                for j in range(i + 1, len(membres)):
                    a, c = membres[i], membres[j]
                    if (a, c) in vus:
                        continue
                    vus.add((a, c))
                    if jaccard(sh[a], sh[c]) >= seuil:
                        parent[trouver(a)] = trouver(c)
    groupes: dict = {}
    for k in textes:
        groupes.setdefault(trouver(k), []).append(k)
    return [sorted(g, key=str) for g in groupes.values() if len(g) > 1]


# --- Fenêtre de nuit --------------------------------------------------------------------------

def fenetre_nuit() -> tuple[int, int]:
    v = os.environ.get("NEXUS_FENETRE_NUIT", "").strip() or "01:00-06:00"
    m = re.fullmatch(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", v)
    if not m:
        return 60, 360
    return int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])


def heure_paris(t_utc: datetime) -> datetime:
    return t_utc.replace(tzinfo=timezone.utc).astimezone(PARIS)


def dans_la_fenetre(t_utc: datetime) -> bool:
    p = heure_paris(t_utc)
    debut, fin = fenetre_nuit()
    minute = p.hour * 60 + p.minute
    return debut <= minute < fin if debut < fin else (minute >= debut or minute < fin)


# --- Entretien SQLite -------------------------------------------------------------------------

def _taille_db(chemin: Path) -> int:
    return sum(p.stat().st_size for p in (chemin, Path(f"{chemin}-wal"), Path(f"{chemin}-journal")) if p.exists())


def entretenir(chemin: str | Path, vacuum: str = "auto", seuil_libre: float = 0.25) -> dict:
    """Entretien d'une base SQLite : auto_vacuum incrémental (conversion par un VACUUM unique),
    VACUUM complet si `vacuum="oui"` ou (auto) si > 25 % de pages libres, sinon incremental_vacuum ;
    'optimize' de chaque table FTS5 ; ANALYZE ; checkpoint WAL. À lancer hors charge."""
    chemin = Path(chemin)
    if not chemin.is_file():
        return {"base": str(chemin), "absente": True}
    avant = _taille_db(chemin)
    res = {"base": str(chemin), "avant": avant, "vacuum": False, "fts": [], "erreur": None}
    c = sqlite3.connect(str(chemin), timeout=30, isolation_level=None)
    try:
        c.execute("PRAGMA busy_timeout=30000")
        av = c.execute("PRAGMA auto_vacuum").fetchone()[0]
        libres = c.execute("PRAGMA freelist_count").fetchone()[0]
        pages = max(1, c.execute("PRAGMA page_count").fetchone()[0])
        complet = vacuum == "oui" or (vacuum == "auto" and libres / pages > seuil_libre)
        if av != 2 and vacuum != "non":
            c.execute("PRAGMA auto_vacuum=INCREMENTAL")
            complet = True  # la conversion n'est effective qu'après un VACUUM
        for (nom,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND "
                                "sql LIKE 'CREATE VIRTUAL TABLE%USING fts5%'").fetchall():
            c.execute(f'INSERT INTO "{nom}"("{nom}") VALUES (\'optimize\')')
            res["fts"].append(nom)
        if complet:
            c.execute("VACUUM")
            res["vacuum"] = True
        else:
            c.execute("PRAGMA incremental_vacuum")
        c.execute("ANALYZE")
        c.execute("PRAGMA optimize")
        with contextlib.suppress(sqlite3.Error):
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as e:
        res["erreur"] = str(e)
    finally:
        c.close()
    res["apres"] = _taille_db(chemin)
    return res


# --- Magasin compacté -------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT);
CREATE TABLE IF NOT EXISTS dictionnaires (version INTEGER PRIMARY KEY, empreinte TEXT NOT NULL,
    taille INTEGER NOT NULL, cree_le TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS blocs (id INTEGER PRIMARY KEY, palier TEXT NOT NULL, algo TEXT NOT NULL,
    dict_version INTEGER NOT NULL DEFAULT 0, n INTEGER NOT NULL, brut INTEGER NOT NULL, taille INTEGER NOT NULL,
    racine TEXT NOT NULL, date_min TEXT, date_max TEXT, journal_id INTEGER, cree_le TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS enregs (rid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, bloc INTEGER NOT NULL,
    position INTEGER NOT NULL, offset INTEGER NOT NULL, longueur INTEGER NOT NULL, feuille BLOB NOT NULL,
    type TEXT NOT NULL, date TEXT, projet TEXT, service TEXT, statut TEXT, mission_id INTEGER,
    seq INTEGER, efface INTEGER NOT NULL DEFAULT 0, taille_brute INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS enregs_bloc ON enregs(bloc, position);
CREATE INDEX IF NOT EXISTS enregs_mission ON enregs(mission_id);
CREATE TABLE IF NOT EXISTS fragments (id INTEGER PRIMARY KEY, h TEXT NOT NULL UNIQUE, donnees BLOB NOT NULL,
    taille INTEGER NOT NULL, refs INTEGER NOT NULL DEFAULT 0, dv INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, type TEXT NOT NULL,
    bloc INTEGER, details TEXT NOT NULL, prec TEXT NOT NULL, mac TEXT NOT NULL, algo TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agregats (periode TEXT NOT NULL, service TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
    termines INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0, cout REAL NOT NULL DEFAULT 0,
    duree REAL NOT NULL DEFAULT 0, notes_somme REAL NOT NULL DEFAULT 0, notes_n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (periode, service));
"""
FTS = ("CREATE VIRTUAL TABLE IF NOT EXISTS cfts USING fts5(texte, content='', detail={detail}, "
       "tokenize='unicode61 remove_diacritics 2')")


class ErreurCompaction(RuntimeError):
    pass


class Compacteur:
    def __init__(self, dossier: str | Path | None = None, cle: bytes | None | str = "env",
                 journal: Callable | None = None, horloge: Callable[[], datetime] = _maintenant):
        self.dossier = Path(dossier) if dossier else dossier_defaut()
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / "blocs" / "tiede").mkdir(parents=True, exist_ok=True)
        (self.dossier / "blocs" / "froid").mkdir(parents=True, exist_ok=True)
        (self.dossier / "dictionnaires").mkdir(exist_ok=True)
        self.cle = cle_hmac() if cle == "env" else (cle.encode() if isinstance(cle, str) else cle)
        self.ledger = journal
        self.horloge = horloge
        self.cfg = config()
        self._verrou = threading.RLock()
        self._profondeur = 0
        self._cache: OrderedDict = OrderedDict()
        self._frag_cache: OrderedDict = OrderedDict()
        self._dicts: dict[int, bytes] = {}
        self.db = sqlite3.connect(str(self.dossier / "compaction.db"), isolation_level=None,
                                  check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA busy_timeout=30000")
        if self.db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0:
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA secure_delete=ON")  # RGPD : pages libérées écrasées
        self.db.executescript(SCHEMA)
        # detail=none (défaut) : index ~3× plus petit, pas de bm25 -> classement par nombre de termes
        # trouvés puis date ; detail=full : bm25. Fixé à la création (méta), modifiable par reconstruction.
        self.fts_detail = self._meta("fts_detail") or self._meta("fts_detail", self.cfg["fts_detail"])
        self.db.execute(FTS.format(detail=self.fts_detail))

    def fermer(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fermer()

    # --- verrous et transactions -------------------------------------------------------------
    @contextlib.contextmanager
    def verrou(self, bloquant: bool = True):
        """Verrou de processus (fichier, flock) + verrou de fil. Lève BlockingIOError si non bloquant."""
        if not self._verrou.acquire(blocking=bloquant):
            raise BlockingIOError("compaction déjà en cours")
        try:
            if self._profondeur:  # réentrant dans le même fil
                self._profondeur += 1
                try:
                    yield
                finally:
                    self._profondeur -= 1
                return
            f = open(self.dossier / "compaction.verrou", "a+")
            try:
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_EX | (0 if bloquant else fcntl.LOCK_NB))
                self._profondeur = 1
                yield
            finally:
                self._profondeur = 0
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
        finally:
            self._verrou.release()

    @contextlib.contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _meta(self, cle: str, valeur: str | None = None) -> str | None:
        if valeur is None:
            r = self.db.execute("SELECT valeur FROM meta WHERE cle=?", (cle,)).fetchone()
            return r[0] if r else None
        self.db.execute("INSERT OR REPLACE INTO meta(cle, valeur) VALUES (?, ?)", (cle, valeur))
        return valeur

    # --- journal chaîné ------------------------------------------------------------------------
    def _mac(self, id_, horodatage, type_, bloc, details, prec, algo) -> str:
        charge = canonique([id_, horodatage, type_, bloc, details, prec])
        if algo == "hmac":
            return hmac.new(self.cle or b"", charge, hashlib.sha256).hexdigest()
        return sha(charge)

    def _journaliser(self, type_: str, bloc: int | None = None, **details) -> int:
        """À appeler DANS une transaction. Refuse le déclassement HMAC -> SHA-256."""
        algo = "hmac" if self.cle else "sha256"
        dernier = self.db.execute("SELECT id, mac, algo FROM journal ORDER BY id DESC LIMIT 1").fetchone()
        if dernier and dernier[2] == "hmac" and algo != "hmac":
            raise ErreurCompaction("LEDGER_HMAC_KEY absente : journal déjà signé HMAC, écriture refusée.")
        id_ = (dernier[0] + 1) if dernier else 1
        prec = dernier[1] if dernier else GENESE
        h = _iso(self.horloge())
        d = canonique(details).decode()
        self.db.execute("INSERT INTO journal(id, horodatage, type, bloc, details, prec, mac, algo) "
                        "VALUES (?,?,?,?,?,?,?,?)", (id_, h, type_, bloc, d, prec,
                                                     self._mac(id_, h, type_, bloc, d, prec, algo), algo))
        return id_

    # --- dictionnaires -------------------------------------------------------------------------
    def dictionnaire(self, version: int) -> bytes | None:
        if version == 0:
            return None
        if version not in self._dicts:
            self._dicts[version] = (self.dossier / "dictionnaires" / f"v{version}.zdict").read_bytes()
        return self._dicts[version]

    def version_dictionnaire(self) -> int:
        r = self.db.execute("SELECT max(version) FROM dictionnaires").fetchone()[0]
        return r or 0

    def entrainer(self, echantillons: list[bytes]) -> int:
        """Entraîne et enregistre une nouvelle version du dictionnaire (les anciennes restent lisibles)."""
        d = entrainer_dictionnaire(echantillons)
        if len(d) < 256:
            return self.version_dictionnaire()
        with self._transaction():
            v = self.version_dictionnaire() + 1
            f = self.dossier / "dictionnaires" / f"v{v}.zdict"
            _ecrire_atomique(f, d)
            self.db.execute("INSERT INTO dictionnaires VALUES (?,?,?,?)", (v, sha(d), len(d), _iso(self.horloge())))
            self._journaliser("dictionnaire", None, version=v, empreinte=sha(d), taille=len(d))
        self._dicts[v] = d
        return v

    # --- fragments -----------------------------------------------------------------------------
    def _fragment(self, fid: int) -> str:
        if fid in self._frag_cache:
            self._frag_cache.move_to_end(fid)
            return self._frag_cache[fid]
        r = self.db.execute("SELECT donnees, h, dv FROM fragments WHERE id=?", (fid,)).fetchone()
        if r is None:
            raise ErreurCompaction(f"fragment {fid} introuvable")
        try:
            t = z_decompresser(r[0], self.dictionnaire(r[2])).decode()
        except (zlib.error, UnicodeDecodeError):
            raise ErreurCompaction(f"fragment {fid} altéré") from None
        if sha(t.encode()) != r[1]:
            raise ErreurCompaction(f"fragment {fid} altéré")
        self._frag_cache[fid] = t
        if len(self._frag_cache) > 2048:
            self._frag_cache.popitem(last=False)
        return t

    def _dedupliquer(self, enregs: list[dict]) -> list[dict]:
        """Remplace les segments répétés (dans le lot ou déjà connus) par des références."""
        compte: Counter = Counter()  # fréquence DOCUMENTAIRE : les répétitions internes à un
        for e in enregs:             # enregistrement sont déjà absorbées par la compression du bloc
            compte.update({sha(p.encode()) for s in _chaines(e.get("donnees")) for p in _segments_longs(s)})
        connus: dict[str, int] = {}
        hs = list(compte)
        for i in range(0, len(hs), 500):
            part = hs[i:i + 500]
            q = f"SELECT h, id FROM fragments WHERE h IN ({','.join('?' * len(part))})"
            connus.update(dict(self.db.execute(q, part).fetchall()))
        dv = self.version_dictionnaire()
        zd = self.dictionnaire(dv)

        def choix(p: str) -> int | None:
            h = sha(p.encode())
            if h in connus:
                fid = connus[h]
            elif rentable(len(p), compte[h]):
                cur = self.db.execute("INSERT INTO fragments(h, donnees, taille, refs, dv) VALUES (?,?,?,0,?)",
                                      (h, z_compresser(p.encode(), zd), len(p.encode()), dv))
                fid = connus[h] = cur.lastrowid
            else:
                return None
            self.db.execute("UPDATE fragments SET refs = refs + 1 WHERE id=?", (fid,))
            return fid

        return [{**e, "donnees": _remplacer(e["donnees"], choix)} if "donnees" in e else e for e in enregs]

    def _liberer_fragments(self, stocke: dict) -> int:
        refs = Counter(_references(stocke, []))
        for fid, n in refs.items():
            self.db.execute("UPDATE fragments SET refs = refs - ? WHERE id=?", (n, fid))
            self._frag_cache.pop(fid, None)
        return self.db.execute("DELETE FROM fragments WHERE refs <= 0").rowcount if refs else 0

    # --- blocs ---------------------------------------------------------------------------------
    def _chemin(self, palier: str, bid: int) -> Path:
        return self.dossier / "blocs" / palier / f"{bid:08d}.blk"

    def _encoder(self, palier: str, entete: dict, lignes: list[bytes]) -> tuple[bytes, list[tuple[int, int]]]:
        tete = canonique(entete) + b"\n"
        pos, offsets = len(tete), []
        for l in lignes:
            offsets.append((pos, len(l)))
            pos += len(l) + 1
        charge = tete + b"\n".join(lignes)
        if palier == "froid" or self.cfg["algo_tiede"] == "lzma":
            corps, algo, dv = x_compresser(charge), b"x", 0
        else:
            dv = entete.get("dict", 0)
            corps, algo = z_compresser(charge, self.dictionnaire(dv)), b"z"
        return MAGIC + bytes([FORMAT]) + algo + struct.pack(">H", dv) + corps, offsets

    def _decoder(self, octets: bytes) -> bytes:
        if octets[:4] != MAGIC:
            raise ErreurCompaction("fichier de bloc invalide")
        algo, dv = octets[5:6], struct.unpack(">H", octets[6:8])[0]
        corps = octets[8:]
        return x_decompresser(corps) if algo == b"x" else z_decompresser(corps, self.dictionnaire(dv))

    def _charge(self, bid: int) -> bytes:
        if bid in self._cache:
            self._cache.move_to_end(bid)
            return self._cache[bid]
        r = self.db.execute("SELECT palier FROM blocs WHERE id=?", (bid,)).fetchone()
        if r is None:
            raise ErreurCompaction(f"bloc {bid} absent de l'index")
        charge = self._decoder(self._chemin(r[0], bid).read_bytes())
        self._cache[bid] = charge
        if len(self._cache) > 8:
            self._cache.popitem(last=False)
        return charge

    def _lignes_bloc(self, bid: int) -> tuple[dict, list[dict]]:
        charge = self._charge(bid)
        tete, _, reste = charge.partition(b"\n")
        return json.loads(tete), [json.loads(l) for l in reste.split(b"\n")] if reste else []

    def _ecrire_blocs(self, palier: str, logiques: list[dict], tailles: dict[str, int],
                      retirer: list[int] = (), journal_extra: dict | None = None, agreger: bool = False) -> list[int]:
        """Écrit un ou plusieurs blocs (découpe N / octets) et retire `retirer`, en UNE transaction.
        Fichiers écrits avant le COMMIT ; un arrêt brutal laisse au pire des fichiers orphelins
        supprimés par reprendre()."""
        nmax = self.cfg["bloc_n_froid"] if palier == "froid" else self.cfg["bloc_n"]
        omax = self.cfg["bloc_octets"]
        lz = palier == "froid" or self.cfg["algo_tiede"] == "lzma"
        dv = 0 if lz else self.version_dictionnaire()
        cree, a_supprimer = [], []
        with self._transaction():
            for bid in retirer:  # d'abord : les ids passent dans les nouveaux blocs
                palier_r = self.db.execute("SELECT palier FROM blocs WHERE id=?", (bid,)).fetchone()[0]
                _, stk = self._lignes_bloc(bid)
                for rid, lg in self._logiques_avec_rid(bid, stk):
                    t = texte_index(lg)
                    if t:
                        self.db.execute("INSERT INTO cfts(cfts, rowid, texte) VALUES ('delete', ?, ?)", (rid, t))
                for st in stk:
                    self._liberer_fragments(st)
                self.db.execute("DELETE FROM enregs WHERE bloc=?", (bid,))
                self.db.execute("DELETE FROM blocs WHERE id=?", (bid,))
                self._journaliser("bloc_retire", bid, vers=palier)
                a_supprimer.append(self._chemin(palier_r, bid))
            if agreger:
                self._agreger(logiques)
            echappes = [_echapper(e) for e in logiques]
            stockes = self._dedupliquer(echappes) if palier == "tiede" else echappes
            lots, lot, octets = [], [], 0
            for lg, st in zip(logiques, stockes):
                ligne = canonique(st)
                if lot and (len(lot) >= nmax or octets + len(ligne) > omax):
                    lots.append(lot)
                    lot, octets = [], 0
                lot.append((lg, ligne))
                octets += len(ligne) + 1
            if lot:
                lots.append(lot)
            for lot in lots:
                feuilles = [feuille(lg) for lg, _ in lot]
                rac = racine(feuilles).hex()
                dates = [lg.get("date") or "" for lg, _ in lot]
                cur = self.db.execute(
                    "INSERT INTO blocs(palier, algo, dict_version, n, brut, taille, racine, date_min, date_max, cree_le)"
                    " VALUES (?,?,?,?,?,0,?,?,?,?)", (palier, "lzma" if lz else "zlib", dv, len(lot),
                                                      sum(len(l) for _, l in lot), rac, min(dates), max(dates),
                                                      _iso(self.horloge())))
                bid = cur.lastrowid
                entete = {"bloc": bid, "palier": palier, "dict": dv, "racine": rac, "ids": [lg["id"] for lg, _ in lot]}
                octets_f, offsets = self._encoder(palier, entete, [l for _, l in lot])
                _ecrire_atomique(self._chemin(palier, bid), octets_f)
                for pos, ((lg, _), f, (off, lon)) in enumerate(zip(lot, feuilles, offsets)):
                    seq = (lg.get("chaine") or {}).get("seq")
                    cur = self.db.execute(
                        "INSERT INTO enregs(id, bloc, position, offset, longueur, feuille, type, date, projet, service,"
                        " statut, mission_id, seq, efface, taille_brute) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (lg["id"], bid, pos, off, lon, f, lg.get("type"), lg.get("date"), lg.get("projet"),
                         lg.get("service"), lg.get("statut"), lg.get("mission_id"), seq, 1 if lg.get("efface") else 0,
                         tailles.get(lg["id"], 0)))
                    t = texte_index(lg)
                    if t:
                        self.db.execute("INSERT INTO cfts(rowid, texte) VALUES (?, ?)", (cur.lastrowid, t))
                jid = self._journaliser("bloc_cree", bid, palier=palier, n=len(lot), racine=rac, dict=dv,
                                        taille=len(octets_f), **(journal_extra or {}))
                self.db.execute("UPDATE blocs SET taille=?, journal_id=? WHERE id=?", (len(octets_f), jid, bid))
                cree.append(bid)
        for f in a_supprimer:  # après COMMIT ; sinon reprendre() supprimera l'orphelin
            with contextlib.suppress(OSError):
                f.unlink()
            self._cache.pop(int(f.stem), None)
        return cree

    def _logiques_avec_rid(self, bid: int, stockes: list[dict]):
        rids = [r[0] for r in self.db.execute("SELECT rid FROM enregs WHERE bloc=? ORDER BY position", (bid,))]
        for rid, st in zip(rids, stockes):
            yield rid, _developper(st, self._fragment)

    # --- ingestion -----------------------------------------------------------------------------
    def _deja(self, ids: list[str]) -> set[str]:
        res = set()
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            res.update(r[0] for r in self.db.execute(
                f"SELECT id FROM enregs WHERE id IN ({','.join('?' * len(part))})", part))
        return res

    def ingerer(self, enregs: Iterable[dict], tailles: dict[str, int] | None = None,
                agreger: bool = True, palier: str | None = None) -> dict:
        """Ajoute des enregistrements logiques ({id, type, date, donnees, …}) au bon palier selon
        leur date. Idempotent : un id déjà présent est ignoré."""
        maintenant = self.horloge()
        lim_froid = maintenant - timedelta(days=self.cfg["froid_jours"])
        lot = list(enregs)
        deja = self._deja([e["id"] for e in lot])
        nouveaux, vus = [], set(deja)
        for e in lot:  # ids déjà compactés ou en double dans le lot : ignorés
            if e["id"] not in vus:
                vus.add(e["id"])
                nouveaux.append(e)
        tailles = tailles or {e["id"]: len(canonique(e)) for e in nouveaux}
        vers_froid = (lambda e: palier == "froid") if palier else (lambda e: _date(e.get("date")) < lim_froid)
        froid = [resumer_froid(reduire_tiede(e)) for e in nouveaux if vers_froid(e)]
        tiede = [reduire_tiede(e) for e in nouveaux if not vers_froid(e)]
        if tiede and self.version_dictionnaire() == 0 and len(tiede) >= 50:
            self.entrainer([canonique(e) for e in tiede[:2000]])
        blocs = []
        for pal, liste in (("tiede", tiede), ("froid", froid)):
            for i in range(0, len(liste), 4096):
                part = sorted(liste[i:i + 4096], key=lambda e: (e.get("date") or "", e["id"]))
                blocs += self._ecrire_blocs(pal, part, tailles, agreger=agreger)
        return {"ajoutes": len(nouveaux), "ignores": len(lot) - len(nouveaux), "tiede": len(tiede),
                "froid": len(froid), "blocs": blocs}

    def lignes_archive(self, dossier_archive: str | Path) -> Iterator[dict]:
        """Lignes des fichiers AAAA-MM.jsonl.gz de archive.py (membres gzip concaténés)."""
        import gzip
        for f in sorted(Path(dossier_archive).glob("*.jsonl.gz")):
            with gzip.open(f, "rb") as g:
                for brute in g:
                    if brute.strip():
                        yield json.loads(brute)

    def compacter(self, palier: str = "tiede", avant_date: datetime | str | None = None,
                  dossier_archive: str | Path | None = None, source: Iterable[dict] | None = None) -> dict:
        """compacter("tiede") : lignes d'archive plus vieilles que COMPACTION_TIEDE_JOURS -> blocs
        (celles qui dépassent déjà le seuil froid vont directement au palier froid).
        compacter("froid") : en plus, blocs tièdes entièrement plus vieux que le seuil froid ->
        résumés en blocs lzma. « chaud » : rien à faire (système actuel). Idempotent, verrouillé."""
        if palier not in PALIERS:
            raise ValueError("palier : chaud, tiede ou froid")
        if palier == "chaud":
            return {"palier": "chaud", "message": "palier chaud = archive actuelle, non compactée"}
        t0 = time.perf_counter()
        maintenant = self.horloge()
        jours = self.cfg["tiede_jours"] if palier == "tiede" else self.cfg["froid_jours"]
        avant = _date(avant_date) if avant_date else maintenant - timedelta(days=jours)
        res = {"palier": palier, "avant": _iso(avant), "ajoutes": 0, "migres": 0, "blocs": []}
        with self.verrou():
            res["reprise"] = self.reprendre()
            if source is None and dossier_archive is not None:
                source = (depuis_ligne_archive(l) | {"_brut": len(canonique(l))} for l in self.lignes_archive(dossier_archive))
            if source is not None:
                lot, tailles = [], {}
                lim = avant if palier == "tiede" else maintenant - timedelta(days=self.cfg["tiede_jours"])
                derniere = ""
                for e in source:
                    if not e.get("date"):  # pierre tombale d'archive : date de la ligne précédente
                        e["date"] = derniere
                    derniere = e["date"]
                    if _date(e.get("date")) >= lim:
                        continue
                    tailles[e["id"]] = e.pop("_brut", 0) or len(canonique(e))
                    lot.append(e)
                    if len(lot) >= 4096:
                        r = self.ingerer(lot, tailles)
                        res["ajoutes"] += r["ajoutes"]
                        res["blocs"] += r["blocs"]
                        lot, tailles = [], {}
                if lot:
                    r = self.ingerer(lot, tailles)
                    res["ajoutes"] += r["ajoutes"]
                    res["blocs"] += r["blocs"]
            if palier == "froid":
                r = self._migrer_froid(avant)
                res["migres"], res["blocs"] = r["migres"], res["blocs"] + r["blocs"]
        res["duree_s"] = round(time.perf_counter() - t0, 3)
        if self.ledger and (res["ajoutes"] or res["migres"]):
            self.ledger("NEXUS-ARCHIVE", "compaction", None, palier=palier, ajoutes=res["ajoutes"],
                        migres=res["migres"], blocs=len(res["blocs"]))
        return res

    def _migrer_froid(self, avant: datetime) -> dict:
        res = {"migres": 0, "blocs": []}
        cands = [r[0] for r in self.db.execute(
            "SELECT id FROM blocs WHERE palier='tiede' AND date_max < ? ORDER BY id", (_iso(avant),))]
        groupe, logiques, tailles = [], [], {}
        for bid in cands + [None]:
            if bid is not None:
                _, stk = self._lignes_bloc(bid)
                for rid, lg in self._logiques_avec_rid(bid, stk):
                    logiques.append(resumer_froid(lg))
                tailles.update(dict(self.db.execute("SELECT id, taille_brute FROM enregs WHERE bloc=?", (bid,))))
                groupe.append(bid)
            if groupe and (bid is None or len(logiques) >= self.cfg["bloc_n_froid"]):
                res["blocs"] += self._ecrire_blocs("froid", logiques, tailles, retirer=groupe,
                                                   journal_extra={"depuis": groupe})
                res["migres"] += len(logiques)
                groupe, logiques, tailles = [], [], {}
        return res

    # --- agrégats (tableau de bord) ------------------------------------------------------------
    def _agreger(self, enregs: list[dict]) -> None:
        for e in enregs:
            if e.get("type") != "mission" or e.get("efface"):
                continue
            d = e.get("donnees") or {}
            if d.get("efface"):
                continue
            dt = _date(e.get("date"))
            iso = dt.isocalendar()
            note = d.get("note")
            for periode in (f"j:{dt:%Y-%m-%d}", f"s:{iso[0]}-W{iso[1]:02d}", f"m:{dt:%Y-%m}"):
                for service in ("*", d.get("service") or "?"):
                    self.db.execute(
                        "INSERT INTO agregats(periode, service, n, termines, tokens, cout, duree, notes_somme, notes_n)"
                        " VALUES (?,?,1,?,?,?,?,?,?) ON CONFLICT(periode, service) DO UPDATE SET n=n+1,"
                        " termines=termines+excluded.termines, tokens=tokens+excluded.tokens, cout=cout+excluded.cout,"
                        " duree=duree+excluded.duree, notes_somme=notes_somme+excluded.notes_somme,"
                        " notes_n=notes_n+excluded.notes_n",
                        (periode, service, 1 if d.get("statut") in ("terminee", "validee") else 0,
                         int(d.get("tokens") or 0), float(d.get("cout_eur") or 0), float(d.get("duree_s") or 0),
                         float(note) if isinstance(note, (int, float)) else 0, 1 if isinstance(note, (int, float)) else 0))

    def agregats(self, granularite: str = "m", service: str = "*") -> list[dict]:
        rows = self.db.execute("SELECT periode, n, termines, tokens, cout, duree, notes_somme, notes_n FROM agregats "
                               "WHERE periode LIKE ? AND service=? ORDER BY periode", (f"{granularite}:%", service))
        return [{"periode": p[2:], "missions": n, "terminees": t, "tokens": tk, "cout_eur": round(c, 4),
                 "duree_s": round(du, 1), "note_moyenne": round(ns / nn, 2) if nn else None}
                for p, n, t, tk, c, du, ns, nn in rows]

    def elaguer_agregats(self) -> int:
        """Les agrégats journaliers de plus de COMPACTION_AGREGATS_JOURS sont retirés (semaines et
        mois conservés)."""
        lim = (self.horloge() - timedelta(days=self.cfg["jours_agregats_jour"])).strftime("j:%Y-%m-%d")
        return self.db.execute("DELETE FROM agregats WHERE periode LIKE 'j:%' AND periode < ?", (lim,)).rowcount

    # --- lecture et recherche ------------------------------------------------------------------
    def _ligne_index(self, id_: str):
        return self.db.execute("SELECT rid, bloc, position, offset, longueur, feuille, efface FROM enregs WHERE id=?",
                               (id_,)).fetchone()

    def lire(self, id_: str) -> dict | None:
        """Enregistrement logique (développé) ; un seul bloc décompressé (cache LRU de 8 blocs)."""
        r = self._ligne_index(id_)
        if r is None:
            return None
        _, bid, _, off, lon, _, _ = r
        stocke = json.loads(self._charge(bid)[off:off + lon])
        return _developper(stocke, self._fragment) | {"palier": self._palier(bid)}

    def _palier(self, bid: int) -> str:
        return self.db.execute("SELECT palier FROM blocs WHERE id=?", (bid,)).fetchone()[0]

    def lire_mission(self, mid: int) -> list[dict]:
        ids = [r[0] for r in self.db.execute("SELECT id FROM enregs WHERE mission_id=? AND type='mission' "
                                             "ORDER BY seq", (mid,))]
        return [self.lire(i) for i in ids]

    def rechercher(self, q: str, projet: str | None = None, service: str | None = None, type_: str | None = None,
                   limite: int = 10, avec_extrait: bool = True) -> list[dict]:
        requete = requete_fts(q or "")
        if not requete:
            return []
        mots = [m.strip('"*') for m in requete.split(" OR ")]
        filtres, params = "", []
        for col, v in (("projet", projet), ("service", service), ("type", type_)):
            if v:
                filtres += f" AND e.{col} = ?"
                params.append(v)
        limite = max(1, min(int(limite), 100))
        if self.fts_detail == "full":
            rows = self.db.execute(
                f"SELECT e.id, e.type, e.mission_id, e.date, e.projet, e.service, e.statut, b.palier, bm25(cfts) AS score"
                f" FROM cfts JOIN enregs e ON e.rid = cfts.rowid JOIN blocs b ON b.id = e.bloc"
                f" WHERE cfts MATCH ? AND e.efface = 0 {filtres} ORDER BY score LIMIT ?",
                [requete, *params, limite]).fetchall()
            rows = [(*r[:8], -r[8]) for r in rows]
        else:  # coordination : nombre de termes distincts trouvés, puis le plus récent
            score: Counter = Counter()
            for m in mots:
                score.update(r[0] for r in self.db.execute("SELECT rowid FROM cfts WHERE cfts MATCH ?", (f'"{m}"*',)))
            self.db.execute("CREATE TEMP TABLE IF NOT EXISTS _cand(rid INTEGER PRIMARY KEY, score INTEGER)")
            self.db.execute("DELETE FROM _cand")
            self.db.executemany("INSERT INTO _cand VALUES (?, ?)", score.items())
            rows = self.db.execute(
                f"SELECT e.id, e.type, e.mission_id, e.date, e.projet, e.service, e.statut, b.palier, c.score"
                f" FROM _cand c JOIN enregs e ON e.rid = c.rid JOIN blocs b ON b.id = e.bloc"
                f" WHERE e.efface = 0 {filtres} ORDER BY c.score DESC, e.date DESC LIMIT ?", [*params, limite]).fetchall()
            self.db.execute("DELETE FROM _cand")
        res = []
        for id_, t, mid, date, pj, sv, st, pal, sc in rows:
            r = {"id": id_, "type": t, "mission_id": mid, "date": date, "projet": pj, "service": sv, "statut": st,
                 "palier": pal, "score": round(sc, 4)}
            if avec_extrait:
                r["extrait"] = _extrait(texte_index(self.lire(id_) or {}), mots)
            res.append(r)
        return res

    # --- vérification --------------------------------------------------------------------------
    def _rejouer_journal(self) -> tuple[dict, dict]:
        etat: dict = {}
        prec, n, vu_hmac = GENESE, 0, False
        for id_, h, t, bloc, d, p, mac, algo in self.db.execute(
                "SELECT id, horodatage, type, bloc, details, prec, mac, algo FROM journal ORDER BY id"):
            n += 1
            motif = None
            if algo == "hmac":
                vu_hmac = True
                if self.cle is None:
                    motif = "journal signé HMAC mais LEDGER_HMAC_KEY absente"
            elif vu_hmac:
                motif = "entrée SHA-256 après une entrée HMAC (déclassement interdit)"
            if motif is None and (p != prec or not hmac.compare_digest(mac, self._mac(id_, h, t, bloc, d, p, algo))):
                motif = "journal : empreinte ou chaînage invalide"
            if motif:
                return etat, {"valide": False, "motif": motif, "premiere_erreur": f"journal #{id_}"}
            det = json.loads(d)
            if t == "bloc_cree":
                etat[bloc] = {"racine": det["racine"], "origine": det["racine"], "palier": det["palier"],
                              "n": det["n"], "effaces": {}}
            elif t == "bloc_retire":
                etat.pop(bloc, None)
            elif t == "effacement":
                if bloc not in etat or etat[bloc]["racine"] != det["ancienne_racine"]:
                    return etat, {"valide": False, "motif": "effacement sur une racine inattendue",
                                  "premiere_erreur": f"journal #{id_}"}
                etat[bloc]["racine"] = det["nouvelle_racine"]
                etat[bloc]["effaces"][det["position"]] = det["feuille_avant"]
            elif t == "dictionnaire":
                etat.setdefault("_dicts", {})[det["version"]] = det["empreinte"]
            prec = mac
        return etat, {"valide": True, "entrees": n}

    def verifier(self, chaine_archive: bool = True) -> dict:
        """Vérification complète : journal chaîné, chaque bloc (racine Merkle recalculée depuis les
        enregistrements développés = fragments compris ; racine d'origine via les feuilles d'avant
        des pierres tombales), cohérence de l'index, dictionnaires, chaîne d'origine de l'archive."""
        with self._verrou:
            self._cache.clear()
            self._frag_cache.clear()
            etat, j = self._rejouer_journal()
            res = {"valide": False, "journal": j.get("entrees", 0), "blocs": 0, "enregistrements": 0,
                   "effaces": 0, "motif": None, "premiere_erreur": None, "hmac_actif": self.cle is not None}
            if not j["valide"]:
                return res | {"motif": j["motif"], "premiere_erreur": j["premiere_erreur"]}
            dicts = etat.pop("_dicts", {})
            for v, emp in dicts.items():
                f = self.dossier / "dictionnaires" / f"v{v}.zdict"
                if not f.is_file() or sha(f.read_bytes()) != emp:
                    return res | {"motif": "dictionnaire altéré ou manquant", "premiere_erreur": f"dictionnaire v{v}"}
            blocs = {b: (pal, rac, n) for b, pal, rac, n in self.db.execute("SELECT id, palier, racine, n FROM blocs")}
            if set(blocs) != set(etat):
                diff = sorted(set(blocs) ^ set(etat))
                return res | {"motif": "index des blocs différent du journal", "premiere_erreur": f"bloc {diff[0]}"}
            chaine = []
            for bid in sorted(blocs):
                pal, rac, n = blocs[bid]
                e = etat[bid]
                if rac != e["racine"] or pal != e["palier"] or n != e["n"]:
                    return res | {"motif": "bloc : métadonnées modifiées", "premiere_erreur": f"bloc {bid}"}
                try:
                    tete, stk = self._lignes_bloc(bid)
                except Exception as ex:  # fichier absent, illisible, compressé altéré
                    return res | {"motif": f"bloc illisible ({type(ex).__name__})", "premiere_erreur": f"bloc {bid}"}
                idx = self.db.execute("SELECT id, feuille, efface FROM enregs WHERE bloc=? ORDER BY position",
                                      (bid,)).fetchall()
                if len(stk) != n or [i for i, _, _ in idx] != tete.get("ids"):
                    return res | {"motif": "bloc : contenu et index incohérents", "premiere_erreur": f"bloc {bid}"}
                feuilles, origine = [], []
                for pos, (st, (id_, f_idx, eff)) in enumerate(zip(stk, idx)):
                    try:
                        lg = _developper(st, self._fragment)
                    except ErreurCompaction as ex:
                        return res | {"motif": str(ex), "premiere_erreur": id_}
                    f = feuille(lg)
                    if lg.get("id") != id_ or f != f_idx or bool(lg.get("efface")) != bool(eff):
                        return res | {"motif": "enregistrement modifié", "premiere_erreur": id_}
                    feuilles.append(f)
                    av = e["effaces"].get(pos) or e["effaces"].get(str(pos))
                    origine.append(bytes.fromhex(av) if av else f)
                    if lg.get("efface"):
                        res["effaces"] += 1
                    if lg.get("chaine"):
                        chaine.append(lg)
                if racine(feuilles).hex() != rac:
                    return res | {"motif": "racine de Merkle invalide", "premiere_erreur": f"bloc {bid}"}
                if racine(origine).hex() != e["origine"]:
                    return res | {"motif": "racine d'origine invalide (pierre tombale)", "premiere_erreur": f"bloc {bid}"}
                res["blocs"] += 1
                res["enregistrements"] += n
            if chaine_archive and chaine:
                ca = self._verifier_chaine(chaine)
                res["chaine_archive"] = ca
                if not ca["valide"]:
                    return res | {"motif": ca["motif"], "premiere_erreur": ca["premiere_erreur"]}
            return res | {"valide": True}

    def _verifier_chaine(self, enregs: list[dict]) -> dict:
        """Chaîne de l'archive d'origine (archive._empreinte_ligne) sur les enregistrements compactés."""
        enregs = sorted(enregs, key=lambda e: e["chaine"]["seq"])
        prec, attendu, contenus = GENESE, 1, 0
        for e in enregs:
            c = e["chaine"]
            if c["seq"] != attendu:
                return {"valide": False, "motif": "chaîne d'archive : séquence manquante",
                        "premiere_erreur": f"seq {attendu}"}
            charge = f"{c['seq']}|{c['prec']}|{c['contenu']}|{c['ledger_ref']}".encode()
            if c["algo"] == "hmac":
                if self.cle is None:
                    return {"valide": False, "motif": "LEDGER_HMAC_KEY absente : vérification impossible",
                            "premiere_erreur": f"seq {c['seq']}"}
                h = hmac.new(self.cle, charge, hashlib.sha256).hexdigest()
            else:
                h = sha(charge)
            if c["prec"] != prec or not hmac.compare_digest(h, c["hash"]):
                return {"valide": False, "motif": "chaîne d'archive : empreinte invalide",
                        "premiere_erreur": f"seq {c['seq']}"}
            if e.get("forme") == "integral" and not e.get("efface") and not (e.get("donnees") or {}).get("efface"):
                if sha(canonique(e["donnees"])) != c["contenu"]:
                    return {"valide": False, "motif": "chaîne d'archive : contenu modifié",
                            "premiere_erreur": f"seq {c['seq']}"}
                contenus += 1
            prec, attendu = c["hash"], attendu + 1
        return {"valide": True, "lignes": len(enregs), "contenus_verifies": contenus, "dernier": prec,
                "motif": None, "premiere_erreur": None}

    def verifier_enregistrement(self, id_: str) -> dict:
        """Vérification d'UN enregistrement : feuille recalculée, preuve de Merkle depuis les feuilles
        de l'index, racine comparée à la dernière entrée du journal pour ce bloc (MAC recalculé)."""
        r = self._ligne_index(id_)
        if r is None:
            return {"valide": False, "motif": "inconnu"}
        rid, bid, pos, *_ = r
        try:
            lg = self.lire(id_)
            lg.pop("palier", None)
        except Exception as ex:  # bloc illisible ou décalé : falsification ou corruption
            return {"valide": False, "bloc": bid, "position": pos, "motif": f"illisible ({type(ex).__name__})"}
        f = feuille(lg)
        feuilles = [x[0] for x in self.db.execute("SELECT feuille FROM enregs WHERE bloc=? ORDER BY position", (bid,))]
        rac_bloc, jid = self.db.execute("SELECT racine, journal_id FROM blocs WHERE id=?", (bid,)).fetchone()
        j = self.db.execute("SELECT id, horodatage, type, bloc, details, prec, mac, algo FROM journal WHERE id=?",
                            (jid,)).fetchone()
        if j is None or (j[7] == "hmac" and self.cle is None) or \
                not hmac.compare_digest(j[6], self._mac(*j[:6], j[7])) or j[3] != bid:
            return {"valide": False, "motif": "entrée de journal du bloc invalide"}
        det = json.loads(j[4])
        rac_j = det.get("nouvelle_racine") or det.get("racine")
        ok = f == feuilles[pos] and verifier_preuve(f, preuve(feuilles, pos), bytes.fromhex(rac_j)) and rac_j == rac_bloc
        return {"valide": ok, "bloc": bid, "position": pos, "racine": rac_j, "motif": None if ok else "falsification"}

    # --- effacement RGPD -----------------------------------------------------------------------
    def effacer(self, id_: str, motif: str = "droit à l'effacement", demandeur: str = "proprietaire") -> bool:
        """Remplace l'enregistrement par une pierre tombale : bloc réécrit, texte retiré de l'index,
        fragments orphelins supprimés (secure_delete), journal chaîné (ancienne -> nouvelle racine)."""
        with self.verrou():
            r = self._ligne_index(id_)
            if r is None or r[6]:
                return False
            rid, bid, pos = r[0], r[1], r[2]
            tete, stk = self._lignes_bloc(bid)
            palier = tete["palier"]
            lg = _developper(stk[pos], self._fragment)
            f_avant = feuille(lg)
            tombe = {"id": id_, "type": lg.get("type"), "date": lg.get("date"), "mission_id": lg.get("mission_id"),
                     "efface": True, "feuille_avant": f_avant.hex(),
                     "mention": f"effacé le {self.horloge():%Y-%m-%d} à la demande de {demandeur}"}
            if lg.get("chaine"):
                tombe["chaine"] = lg["chaine"]  # empreintes seules : la chaîne d'archive reste vérifiable
            feuilles = [x[0] for x in self.db.execute("SELECT feuille FROM enregs WHERE bloc=? ORDER BY position", (bid,))]
            ancienne = racine(feuilles).hex()
            feuilles[pos] = feuille(tombe)
            nouvelle = racine(feuilles).hex()
            stk_nv = list(stk)
            stk_nv[pos] = tombe
            tete["racine"] = nouvelle
            stk_nv[pos] = _echapper(tombe)
            octets_f, offsets = self._encoder(palier, tete, [canonique(s) for s in stk_nv])
            final = self._chemin(palier, bid)
            tmp = final.with_suffix(".blk.tmp")
            _ecrire_atomique(tmp, octets_f)
            with self._transaction():
                t = texte_index(lg)
                if t:
                    self.db.execute("INSERT INTO cfts(cfts, rowid, texte) VALUES ('delete', ?, ?)", (rid, t))
                self._liberer_fragments(stk[pos])
                for p, (off, lon) in enumerate(offsets):
                    self.db.execute("UPDATE enregs SET offset=?, longueur=? WHERE bloc=? AND position=?",
                                    (off, lon, bid, p))
                self.db.execute("UPDATE enregs SET feuille=?, efface=1, statut=NULL WHERE rid=?", (feuilles[pos], rid))
                jid = self._journaliser("effacement", bid, id=id_, position=pos, feuille_avant=f_avant.hex(),
                                        ancienne_racine=ancienne, nouvelle_racine=nouvelle,
                                        motif=motif, demandeur=demandeur)
                self.db.execute("UPDATE blocs SET racine=?, taille=?, journal_id=? WHERE id=?",
                                (nouvelle, len(octets_f), jid, bid))
            self._cache.pop(bid, None)
            self._finaliser_fichier(tmp, final)
            with contextlib.suppress(sqlite3.Error):
                self.db.execute("INSERT INTO cfts(cfts) VALUES ('optimize')")  # purge physique des jetons
        if self.ledger:
            self.ledger("NEXUS-ARCHIVE", "compaction_effacement", lg.get("mission_id"), id=id_, bloc=bid,
                        motif=motif, demandeur=demandeur, nouvelle_racine=nouvelle)
        return True

    def _finaliser_fichier(self, tmp: Path, final: Path) -> None:
        os.replace(tmp, final)

    def effacer_mission(self, mid: int, motif: str = "droit à l'effacement", demandeur: str = "proprietaire") -> int:
        ids = [r[0] for r in self.db.execute("SELECT id FROM enregs WHERE mission_id=? AND efface=0", (mid,))]
        return sum(1 for i in ids if self.effacer(i, motif, demandeur))

    def journal_effacements(self) -> list[dict]:
        return [{"id": i, "horodatage": h, "bloc": b, **json.loads(d)} for i, h, b, d in self.db.execute(
            "SELECT id, horodatage, bloc, details FROM journal WHERE type='effacement' ORDER BY id")]

    # --- reprise après interruption -----------------------------------------------------------
    def reprendre(self) -> dict:
        """Finalise ou annule ce qu'un arrêt brutal a laissé : fichiers .tmp d'effacement (remplacés
        si l'index porte déjà la nouvelle racine, sinon supprimés) et fichiers de blocs orphelins."""
        res = {"orphelins": 0, "finalises": 0, "annules": 0, "manquants": []}
        index = {b: (p, r) for b, p, r in self.db.execute("SELECT id, palier, racine FROM blocs")}
        for palier in ("tiede", "froid"):
            for f in (self.dossier / "blocs" / palier).glob("*.ecriture"):
                f.unlink()
                res["annules"] += 1
            for f in sorted((self.dossier / "blocs" / palier).glob("*.blk.tmp")):
                bid = int(f.name.split(".")[0])
                try:
                    rac = json.loads(self._decoder(f.read_bytes()).partition(b"\n")[0])["racine"]
                except Exception:
                    rac = None
                if bid in index and index[bid][1] == rac:
                    os.replace(f, self._chemin(palier, bid))
                    res["finalises"] += 1
                else:
                    f.unlink()
                    res["annules"] += 1
                self._cache.pop(bid, None)
            for f in sorted((self.dossier / "blocs" / palier).glob("*.blk")):
                bid = int(f.stem)
                if bid not in index or index[bid][0] != palier:
                    f.unlink()
                    res["orphelins"] += 1
        for bid, (palier, _) in index.items():
            if not self._chemin(palier, bid).is_file():
                res["manquants"].append(bid)
        return res

    # --- sources : retrait des mois compactés, veille -----------------------------------------
    def point_de_reprise(self) -> dict:
        r = self.db.execute("SELECT max(seq) FROM enregs WHERE seq IS NOT NULL").fetchone()[0]
        if not r:
            return {"seq": 0, "hash": GENESE}
        lg = self.lire(f"m:{r}")
        return {"seq": r, "hash": lg["chaine"]["hash"]}

    def retirer_mois(self, dossier_archive: str | Path) -> dict:
        """Supprime les fichiers AAAA-MM.jsonl.gz dont TOUTES les lignes sont compactées avec la même
        empreinte de chaîne, après une vérification complète réussie. Tracé au journal."""
        import gzip
        res = {"retires": [], "gardes": []}
        with self.verrou():
            v = self.verifier()
            if not v["valide"]:
                raise ErreurCompaction(f"vérification échouée, aucun retrait : {v['motif']}")
            limite = (self.horloge() - timedelta(days=self.cfg["tiede_jours"])).strftime("%Y-%m")
            for f in sorted(Path(dossier_archive).glob("*.jsonl.gz")):
                mois = f.name[:7]
                if mois >= limite:
                    res["gardes"].append(mois)
                    continue
                with gzip.open(f, "rb") as g:
                    lignes = [json.loads(b) for b in g if b.strip()]
                ok = bool(lignes)
                for l in lignes:
                    lg = self.lire(f"m:{l['seq']}")
                    if lg is None or lg.get("chaine", {}).get("hash") != l["hash"]:
                        ok = False
                        break
                if not ok:
                    res["gardes"].append(mois)
                    continue
                with self._transaction():
                    self._journaliser("retrait_source", None, fichier=f.name, lignes=len(lignes),
                                      empreinte=sha(f.read_bytes()))
                f.unlink()
                res["retires"].append(mois)
        return res

    def archiver_veille(self, chemin_veille: str | Path, jours: int | None = None) -> dict:
        """Fiches de veille plus vieilles que la rétention -> palier froid, puis supprimées de la base
        de veille (même effet que collecteur.purger, sans perte)."""
        jours = jours if jours is not None else _env_int("VEILLE_RETENTION_JOURS", 180)
        chemin = Path(chemin_veille)
        if not chemin.is_file():
            return {"absente": True}
        lim = (self.horloge() - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        c = sqlite3.connect(str(chemin), timeout=30)
        c.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in c.execute("SELECT * FROM fiches WHERE collecte_le < ?", (lim,))]
            enregs = [{"id": f"v:{r['empreinte']}", "type": "veille", "date": r["collecte_le"].rstrip("Z"),
                       "projet": None, "service": None, "statut": None,
                       "donnees": {k: v for k, v in r.items() if k != "id"}, "forme": "integral"} for r in rows]
            with self.verrou():
                tailles = {e["id"]: len(canonique(e)) for e in enregs}
                r = self.ingerer(enregs, tailles, agreger=False, palier="froid")  # fiches publiques, courtes
            ids = [x["id"] for x in rows]
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                c.execute(f"DELETE FROM fiches WHERE id IN ({','.join('?' * len(part))})", part)
            c.commit()
        finally:
            c.close()
        return {"archivees": r["ajoutes"], "supprimees": len(rows)}

    # --- consolidation de la mémoire de travail ------------------------------------------------
    def consolider_connaissances(self, conn: sqlite3.Connection, plafond: int | None = None, seuil: float = 0.85,
                                 acces: dict | None = None, notes: dict | None = None,
                                 citations: dict | None = None, appliquer: bool = True) -> dict:
        """Table `connaissances` (nexus.db) : fusion des quasi-doublons (Jaccard ≥ seuil) et
        plafond par projet selon un score d'utilité. Seules les connaissances « auto » (résumés de
        livrables) sont supprimées, après archivage complet ici (aucune perte) ; « manuel » et
        « import » sont conservées (l'import les recréerait)."""
        acces, notes, citations = acces or {}, notes or {}, citations or {}
        plafond = plafond if plafond is not None else self.cfg["plafond_connaissances"]
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT id, projet, titre, contenu, source, date, auteur, version, origine, empreinte, suspect FROM connaissances")]
        maintenant = self.horloge()
        rang = {"manuel": 3, "import": 2, "auto": 1}

        def utilite(k: dict) -> float:
            age = max(0.0, (maintenant - _date(k["date"])).days)
            recence = 0.5 ** (age / 90)
            return round(0.4 * recence + 0.25 * min(1.0, acces.get(k["id"], 0) / 10) + 0.2 * (notes.get(k["id"], 3) / 5)
                         + 0.15 * min(1.0, citations.get(k["id"], 0) / 5) - (0.3 if k["suspect"] else 0), 4)

        fusions, evictions = [], []
        par_projet: dict = {}
        for k in rows:
            par_projet.setdefault(k["projet"], []).append(k)
        for projet, ks in par_projet.items():
            par_id = {k["id"]: k for k in ks}
            for g in quasi_doublons({k["id"]: f"{k['titre']}\n{k['contenu']}" for k in ks}, seuil):
                membres = [par_id[i] for i in g]
                garde = max(membres, key=lambda k: (rang.get(k["origine"], 0), k["date"] or "", len(k["contenu"])))
                retires = [k for k in membres if k is not garde and k["origine"] == "auto"]
                if retires:
                    fusions.append({"garde": garde["id"], "retires": [k["id"] for k in retires], "projet": projet})
            retires_ids = {i for f in fusions if f["projet"] == projet for i in f["retires"]}
            restants = [k for k in ks if k["id"] not in retires_ids]
            if plafond and len(restants) > plafond:
                auto = sorted((k for k in restants if k["origine"] == "auto"), key=utilite)
                for k in auto[: len(restants) - plafond]:
                    evictions.append({"id": k["id"], "projet": projet, "utilite": utilite(k)})
        res = {"connaissances": len(rows), "fusions": len(fusions), "fusionnees": sum(len(f["retires"]) for f in fusions),
               "evincees": len(evictions), "plan": {"fusions": fusions, "evictions": evictions}}
        if not appliquer:
            return res
        par_id = {k["id"]: k for k in rows}
        a_archiver = [(i, "fusion", f["garde"]) for f in fusions for i in f["retires"]] + \
                     [(e["id"], "eviction", None) for e in evictions]
        enregs = []
        for i, raison, garde in a_archiver:
            k = par_id[i]
            m = re.match(r"livrable #(\d+)", k["source"] or "")
            enregs.append({"id": f"k:{k['projet']}:{k['id']}:{k['empreinte'][:12]}", "type": "connaissance",
                           "date": str(k["date"] or _iso(maintenant)).replace(" ", "T")[:19], "projet": k["projet"],
                           "mission_id": int(m.group(1)) if m else None, "service": None, "statut": raison,
                           "donnees": {**{c: (str(v) if c == "date" else v) for c, v in k.items()},
                                       "raison": raison, "fusionnee_dans": garde}, "forme": "integral"})
        if enregs:
            with self.verrou():
                self.ingerer(enregs, agreger=False)
            ids = [i for i, _, _ in a_archiver]
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                conn.execute(f"DELETE FROM connaissances WHERE id IN ({','.join('?' * len(part))})", part)
            conn.commit()
            if self.ledger:
                self.ledger("NEXUS-PRIME", "connaissances_consolidees", None, fusionnees=res["fusionnees"],
                            evincees=res["evincees"])
        return res

    # --- statistiques --------------------------------------------------------------------------
    def statistiques(self) -> dict:
        par = {}
        for pal, nb, n, brut_c, taille in self.db.execute(
                "SELECT palier, count(*), sum(n), sum(brut), sum(taille) FROM blocs GROUP BY palier"):
            avant = self.db.execute("SELECT coalesce(sum(e.taille_brute),0) FROM enregs e JOIN blocs b ON b.id=e.bloc "
                                    "WHERE b.palier=?", (pal,)).fetchone()[0]
            par[pal] = {"blocs": nb, "enregistrements": n, "avant_octets": avant, "serialise_octets": brut_c,
                        "fichiers_octets": taille, "ratio": round(avant / taille, 2) if taille else None}
        nf, tf, ref, eco = self.db.execute(
            "SELECT count(*), coalesce(sum(length(donnees)),0), coalesce(sum(refs),0),"
            " coalesce(sum((refs-1)*taille),0) FROM fragments").fetchone()
        dicts = sum(f.stat().st_size for f in (self.dossier / "dictionnaires").glob("*.zdict"))
        idx = _taille_db(self.dossier / "compaction.db")
        avant = sum(p["avant_octets"] for p in par.values())
        fichiers = sum(p["fichiers_octets"] for p in par.values())
        apres = fichiers + idx + dicts
        return {"paliers": par, "avant_octets": avant, "fichiers_octets": fichiers, "index_octets": idx,
                "dictionnaires_octets": dicts, "apres_octets": apres,
                "ratio": round(avant / apres, 2) if apres else None,
                "ratio_hors_index": round(avant / (fichiers + tf), 2) if fichiers else None,
                "dedup": {"fragments": nf, "fragments_octets": tf, "references": ref, "octets_evites": eco},
                "effaces": self.db.execute("SELECT count(*) FROM enregs WHERE efface=1").fetchone()[0],
                "dictionnaire_version": self.version_dictionnaire()}

    # --- tâche de nuit -------------------------------------------------------------------------
    def tache_nocturne(self, maintenant_utc: datetime | None = None, dossier_archive: str | Path | None = None,
                       nexus_db: str | Path | None = None, veille_db: str | Path | None = None,
                       forcer: bool = False) -> dict | None:
        """Une fois par jour dans la fenêtre de nuit : compaction tiède + froid, consolidation,
        archivage de la veille expirée, entretien SQLite. Renvoie None si rien à faire."""
        t = maintenant_utc or self.horloge()
        jour = heure_paris(t).strftime("%Y-%m-%d")
        if not forcer and (not dans_la_fenetre(t) or self._meta("derniere_nuit") == jour):
            return None
        try:
            with self.verrou(bloquant=False):
                with self._transaction():
                    self._meta("derniere_nuit", jour)  # marqué d'abord : pas de double passage en cas d'échec
        except BlockingIOError:
            return None
        res = {"jour": jour}
        da = dossier_archive or (Path(os.environ["NEXUS_ARCHIVE_DIR"]) if os.environ.get("NEXUS_ARCHIVE_DIR")
                                 else Path(os.environ.get("NEXUS_DATA_DIR", "/data")) / "archive")
        try:
            res["tiede"] = self.compacter("tiede", dossier_archive=da if Path(da).is_dir() else None)
            res["froid"] = self.compacter("froid")
            if self.cfg["retirer_sources"] and Path(da).is_dir():
                res["retrait"] = self.retirer_mois(da)
            if nexus_db and Path(nexus_db).is_file() and self.cfg["plafond_connaissances"]:
                c = sqlite3.connect(str(nexus_db), timeout=30)
                try:
                    res["consolidation"] = {k: v for k, v in self.consolider_connaissances(c).items() if k != "plan"}
                finally:
                    c.close()
            if veille_db:
                res["veille"] = self.archiver_veille(veille_db)
            with self._transaction():
                res["agregats_elagues"] = self.elaguer_agregats()
            vac = "oui" if heure_paris(t).weekday() == self.cfg["vacuum_jour"] else "auto"
            res["entretien"] = [entretenir(p, vac) for p in (nexus_db, veille_db) if p]
            res["entretien"].append(self._entretenir_soi(vac))
        except Exception as e:  # la nuit suivante réessaiera ; l'erreur est remontée au journal
            res["erreur"] = f"{type(e).__name__}: {e}"
        if self.ledger:
            self.ledger("NEXUS-ARCHIVE", "compaction_nuit", None, **{k: v for k, v in res.items()
                                                                     if k in ("jour", "erreur")})
        return res

    def _entretenir_soi(self, vacuum: str) -> dict:
        with self.verrou():
            self.db.close()
            try:
                return entretenir(self.dossier / "compaction.db", vacuum)
            finally:
                self.db = sqlite3.connect(str(self.dossier / "compaction.db"), isolation_level=None,
                                          check_same_thread=False, timeout=30)
                self.db.execute("PRAGMA busy_timeout=30000")
                self.db.execute("PRAGMA secure_delete=ON")


# --- helpers ----------------------------------------------------------------------------------

def _ecrire_atomique(chemin: Path, octets: bytes) -> None:
    tmp = chemin.with_name(chemin.name + ".ecriture")
    with open(tmp, "wb") as f:
        f.write(octets)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)


def _extrait(texte: str, mots: list[str], largeur: int = 160) -> str:
    n = normaliser(texte)
    pos = min((p for p in (n.find(m) for m in mots) if p >= 0), default=0)
    debut = max(0, pos - largeur // 3)
    return ("…" if debut else "") + texte[debut:debut + largeur].strip() + ("…" if debut + largeur < len(texte) else "")


# --- API du module (instance par défaut) ------------------------------------------------------

_defaut: Compacteur | None = None
_verrou_defaut = threading.Lock()


def defaut(journal: Callable | None = None) -> Compacteur:
    global _defaut
    with _verrou_defaut:
        if _defaut is None or _defaut.dossier != dossier_defaut():
            _defaut = Compacteur(dossier_defaut(), journal=journal)
        elif journal is not None:
            _defaut.ledger = journal
        return _defaut


def compacter(palier: str = "tiede", avant_date=None, dossier_archive=None) -> dict:
    return defaut().compacter(palier, avant_date, dossier_archive)


def lire(id_: str) -> dict | None:
    return defaut().lire(id_)


def rechercher(q: str, **kw) -> list[dict]:
    return defaut().rechercher(q, **kw)


def verifier() -> dict:
    return defaut().verifier()


def effacer(id_: str, motif: str = "droit à l'effacement", demandeur: str = "proprietaire") -> bool:
    return defaut().effacer(id_, motif, demandeur)


def statistiques() -> dict:
    return defaut().statistiques()


def tache_nocturne(maintenant_utc: datetime | None = None, journal: Callable | None = None, **kw) -> dict | None:
    return defaut(journal).tache_nocturne(maintenant_utc, **kw)
