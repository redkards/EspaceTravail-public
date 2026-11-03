"""Archive brute immuable de la mémoire collective.

- Un enregistrement JSON complet par événement de mission (fin d'exécution, décision humaine) :
  consigne, projet, service, niveau F, modèles par rôle, étapes (sorties tronquées), livrable,
  verdicts du CHECKER, violations de charte, décisions N3 et motifs, révisions, tokens, durée, note.
- Stockage : NEXUS_ARCHIVE_DIR (défaut <NEXUS_DATA_DIR>/archive), un fichier JSONL compressé par
  mois (AAAA-MM.jsonl.gz, ajout de membres gzip ; aucune réécriture).
- Chaînage : chaque ligne porte l'empreinte de la précédente ; empreinte = HMAC-SHA256 avec
  LEDGER_HMAC_KEY (SHA-256 si la clé est absente, comme le LEDGER) sur
  « seq | précédente | empreinte du contenu | référence LEDGER ». L'empreinte du contenu est
  conservée à part : un effacement (droit à l'effacement) remplace le contenu par une « pierre
  tombale » sans casser la chaîne, et l'effacement est tracé au LEDGER.
- Filtre anti-secret (cyber.masquer) sur toutes les chaînes avant écriture.
- Index en base (archive_index + FTS5) pour la recherche ; il ne contient qu'un texte court.
"""
import gzip
import hashlib
import hmac
import json
import os
import threading
from pathlib import Path

from sqlalchemy import select, text

from . import cyber, ledger
from .config import cfg
from .db import engine, session_scope
from .models import ArchiveIndex, Decision, Etape, Ledger, Mission, maintenant

GENESE = "0" * 64
SORTIE_MAX = 2000
LIVRABLE_MAX = 20000
_verrou = threading.Lock()


def dossier() -> Path:
    v = os.environ.get("NEXUS_ARCHIVE_DIR", "").strip()
    return Path(v) if v else cfg().data_dir / "archive"


def _canonique(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _masquer(obj):
    """Masque les secrets dans toutes les chaînes (récursif)."""
    if isinstance(obj, str):
        return cyber.masquer(obj)
    if isinstance(obj, list):
        return [_masquer(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _masquer(v) for k, v in obj.items()}
    return obj


def _empreinte_ligne(seq: int, prec: str, contenu: str, ledger_ref: str, algo: str) -> str:
    charge = f"{seq}|{prec}|{contenu}|{ledger_ref}".encode()
    if algo == "hmac":
        return hmac.new(ledger.cle_hmac() or b"", charge, hashlib.sha256).hexdigest()
    return hashlib.sha256(charge).hexdigest()


def initialiser_fts(eng) -> None:
    if eng.dialect.name != "sqlite":
        return
    with eng.begin() as c:
        c.execute(text("""CREATE VIRTUAL TABLE IF NOT EXISTS archive_fts USING fts5(
            texte, content='archive_index', content_rowid='id', tokenize='unicode61 remove_diacritics 2')"""))
        c.execute(text("""CREATE TRIGGER IF NOT EXISTS archive_ai AFTER INSERT ON archive_index BEGIN
            INSERT INTO archive_fts(rowid, texte) VALUES (new.id, new.texte); END"""))
        c.execute(text("""CREATE TRIGGER IF NOT EXISTS archive_au AFTER UPDATE ON archive_index BEGIN
            INSERT INTO archive_fts(archive_fts, rowid, texte) VALUES ('delete', old.id, old.texte);
            INSERT INTO archive_fts(rowid, texte) VALUES (new.id, new.texte); END"""))


# --- Construction de l'enregistrement -----------------------------------------------------

def enregistrement(mid: int, evenement: str) -> dict:
    with session_scope() as s:
        m = s.get(Mission, mid)
        etapes = s.execute(select(Etape).where(Etape.mission_id == mid).order_by(Etape.id)).scalars().all()
        decisions = s.execute(select(Decision).where(Decision.mission_id == mid).order_by(Decision.id)).scalars().all()
        verdicts, charte_violations = [], []
        for e in etapes:
            if e.role in ("checker", "checker_local") and e.verdict in ("ok", "refus"):
                try:
                    v = json.loads(e.sortie or "{}")
                except ValueError:
                    v = {"brut": (e.sortie or "")[:500]}
                (charte_violations if e.entree == "charte du projet" else verdicts).append(
                    {"source": e.entree, "verdict": e.verdict, "problemes": v.get("problemes", [])})
        return {
            "evenement": evenement, "horodatage": maintenant().isoformat(timespec="seconds") + "Z",
            "mission_id": m.id, "titre": m.titre, "consigne": m.consigne, "projet": m.projet, "service": m.service,
            "statut": m.statut, "niveau": m.niveau, "fonctionnement_demande": m.fonctionnement_demande,
            "fonctionnement": m.fonctionnement, "fonctionnement_raison": m.fonctionnement_raison,
            "modeles": json.loads(m.modeles_json) if m.modeles_json else {},
            "etapes": [{"agent": e.agent_id, "role": e.role, "verdict": e.verdict, "tokens": e.tokens,
                        "sortie": (e.sortie or "")[:SORTIE_MAX]} for e in etapes],
            "livrable": (m.livrable_texte or "")[:LIVRABLE_MAX], "verdicts_checker": verdicts,
            "charte_violations": charte_violations,
            "charte_avertissements": json.loads(m.charte_avertissements) if m.charte_avertissements else [],
            "decisions": [{"id": d.id, "objet": d.objet, "statut": d.statut, "risque": d.risque,
                           "commentaire": d.commentaire, "motif": d.recommandation} for d in decisions],
            "revisions": m.revisions, "relance_auto": m.relance_auto, "message": m.message,
            "tokens": m.tokens, "tokens_entree": m.tokens_entree, "tokens_sortie": m.tokens_sortie,
            "cout_eur": m.cout_eur, "duree_s": m.duree_s, "note": m.note, "note_banc": None,
        }


def _texte_index(e: dict) -> str:
    probs = " ".join(p for v in e.get("verdicts_checker", []) + e.get("charte_violations", [])
                     for p in v.get("problemes", []))
    return f"{e.get('titre', '')} {e.get('consigne', '')[:1500]} {e.get('livrable', '')[:1500]} {probs}"[:4000]


# --- Écriture -----------------------------------------------------------------------------

def archiver(mid: int, evenement: str = "fin_execution") -> dict:
    """Ajoute l'enregistrement (masqué) à l'archive du mois et le chaîne. Renvoie {seq, hash, fichier}."""
    e = _masquer(enregistrement(mid, evenement))
    contenu = hashlib.sha256(_canonique(e)).hexdigest()
    algo = "hmac" if ledger.cle_hmac() else "sha256"
    mois = maintenant().strftime("%Y-%m")
    with _verrou:
        with session_scope() as s:
            dernier = s.execute(select(ArchiveIndex).order_by(ArchiveIndex.seq.desc()).limit(1)).scalar_one_or_none()
            ref = s.execute(select(Ledger.hash).order_by(Ledger.id.desc()).limit(1)).scalar_one_or_none() or GENESE
        seq = (dernier.seq + 1) if dernier else 1
        prec = dernier.hash if dernier else GENESE
        h = _empreinte_ligne(seq, prec, contenu, ref, algo)
        ligne = {"seq": seq, "prec": prec, "contenu": contenu, "ledger_ref": ref, "algo": algo, "hash": h,
                 "enregistrement": e}
        d = dossier()
        d.mkdir(parents=True, exist_ok=True)
        fichier = d / f"{mois}.jsonl.gz"
        with gzip.open(fichier, "ab") as f:  # nouveau membre gzip : ajout sans réécriture
            f.write(_canonique(ligne) + b"\n")
        with session_scope() as s:
            s.add(ArchiveIndex(seq=seq, mois=mois, mission_id=mid, evenement=evenement, projet=e.get("projet"),
                               service=e.get("service"), statut=e.get("statut"), hash=h, prec=prec,
                               texte=_texte_index(e), cree_le=maintenant()))
    ledger.journaliser("NEXUS-LEDGER", "archive_ajout", mid, seq=seq, hash=h, mois=mois, evenement=evenement)
    return {"seq": seq, "hash": h, "fichier": str(fichier)}


# --- Lecture et vérification -------------------------------------------------------------------

def lignes() -> list[dict]:
    res = []
    for f in sorted(dossier().glob("*.jsonl.gz")):
        with gzip.open(f, "rb") as g:
            for brute in g:
                if brute.strip():
                    res.append(json.loads(brute))
    return sorted(res, key=lambda l: l["seq"])


def verifier() -> dict:
    """Recalcule la chaîne et les empreintes de contenu (pierres tombales : empreinte conservée)."""
    prec, n, tombes = GENESE, 0, 0
    cle = ledger.cle_hmac()
    for l in lignes():
        n += 1
        motif = None
        if l["prec"] != prec:
            motif = "chaînage rompu"
        elif l["algo"] == "hmac" and cle is None:
            motif = "LEDGER_HMAC_KEY absente : vérification impossible"
        elif not l["enregistrement"].get("efface") and \
                hashlib.sha256(_canonique(l["enregistrement"])).hexdigest() != l["contenu"]:
            motif = "contenu modifié"
        elif not hmac.compare_digest(l["hash"], _empreinte_ligne(l["seq"], l["prec"], l["contenu"],
                                                                  l["ledger_ref"], l["algo"])):
            motif = "empreinte invalide"
        if motif:
            return {"valide": False, "lignes": n, "premiere_erreur": l["seq"], "motif": motif}
        tombes += 1 if l["enregistrement"].get("efface") else 0
        prec = l["hash"]
    return {"valide": True, "lignes": n, "effacees": tombes, "premiere_erreur": None, "motif": None}


def effacer(mid: int, demandeur: str, motif: str = "droit à l'effacement") -> int:
    """Remplace les enregistrements d'une mission par une pierre tombale (seule réécriture permise)."""
    n = 0
    with _verrou:
        for f in sorted(dossier().glob("*.jsonl.gz")):
            with gzip.open(f, "rb") as g:
                contenu = [json.loads(b) for b in g if b.strip()]
            change = False
            for l in contenu:
                if l["enregistrement"].get("mission_id") == mid and not l["enregistrement"].get("efface"):
                    l["enregistrement"] = {"efface": True, "mission_id": mid,
                                           "mention": f"effacée le {maintenant().strftime('%Y-%m-%d')} "
                                                      f"à la demande de {demandeur}", "motif": motif}
                    change, n = True, n + 1
            if change:
                tmp = f.with_suffix(".tmp")
                with gzip.open(tmp, "wb") as g:
                    for l in contenu:
                        g.write(_canonique(l) + b"\n")
                os.replace(tmp, f)
        with session_scope() as s:
            for x in s.execute(select(ArchiveIndex).where(ArchiveIndex.mission_id == mid)).scalars():
                x.texte, x.efface = "", True
    if n:
        ledger.journaliser("NEXUS-LEDGER", "archive_effacement", mid, lignes=n, demandeur=demandeur, motif=motif)
    return n


def rechercher(q: str, projet: str | None = None, service: str | None = None, limite: int = 10) -> list[dict]:
    from .memoire import _requete_fts
    requete = _requete_fts(q or "")
    if not requete or engine().dialect.name != "sqlite":
        return []
    filtres, params = "", {"m": requete, "n": limite}
    if projet:
        filtres += " AND a.projet = :p"
        params["p"] = projet
    if service:
        filtres += " AND a.service = :s"
        params["s"] = service
    with session_scope() as s:
        rows = s.execute(text(f"""SELECT a.seq, a.mission_id, a.mois, a.evenement, a.projet, a.service, a.statut,
            snippet(archive_fts, 0, '[', ']', '…', 24) AS extrait
            FROM archive_fts JOIN archive_index a ON a.id = archive_fts.rowid
            WHERE archive_fts MATCH :m AND a.efface = 0 {filtres} ORDER BY bm25(archive_fts) LIMIT :n"""),
            params).all()
    return [dict(r._mapping) for r in rows]
