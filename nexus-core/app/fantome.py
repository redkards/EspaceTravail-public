"""Test fantôme avant activation : rejouer K missions passées « avant » et « après » une variante.

Variantes : leçon proposée, exemple (B4), charte modifiée (dossier de chartes candidat), modèles par
rôle (chaîne au format NEXUS_MODELES_ROLES). Les rejeux :
- partent de missions archivées du même service (et projet si précisé) — NEXUS_FANTOME_K (défaut 5) ;
- s'exécutent sans aucun effet de bord : missions marquées « fantome », ni décision, ni EXECUTOR,
  ni notification, ni archive, ni leçon, exclues des statistiques ;
- tournent la nuit (NEXUS_FENETRE_NUIT, défaut 01:00-06:00, heure de Paris), un seul à la fois.
Notation : banc-essai/noter.py (NEXUS_BANC_DIR) si la mission rejouée est une mission du banc,
sinon critères déterministes (charte du projet + verdict du CHECKER + issue de la mission).
Résultat : « +12 points sur 5 missions » ; gain < 0 → déconseillé (une leçon ne peut alors être
acceptée qu'avec confirmation explicite ; un exemple est retiré automatiquement).
"""
import json
import logging
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from . import archive, bouclier, charte, decideur, ledger, sentinel, surcharges
from .db import session_scope
from .models import ArchiveIndex, Etape, Mission, maintenant

log = logging.getLogger("nexus.fantome")
_verrou = threading.Lock()
FILE_CLE = "fantome:file"


def k() -> int:
    try:
        from . import profil
        return max(1, int(os.environ.get("NEXUS_FANTOME_K", "") or profil.valeur("fantome_k")))
    except ValueError:
        return 5


def fenetre() -> tuple[int, int]:
    v = os.environ.get("NEXUS_FENETRE_NUIT", "").strip() or "01:00-06:00"
    m = re.fullmatch(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", v)
    if not m:
        return 60, 360
    return int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])


def dans_la_fenetre(t_utc: datetime) -> bool:
    p = t_utc.replace(tzinfo=timezone.utc).astimezone(decideur.PARIS)
    debut, fin = fenetre()
    minute = p.hour * 60 + p.minute
    return debut <= minute < fin if debut < fin else (minute >= debut or minute < fin)


# --- File des tests ----------------------------------------------------------------------------

def _file() -> list[dict]:
    return json.loads(sentinel.lire(FILE_CLE) or "[]")


def planifier(type_: str, cible: str | int, variante: dict, service: str | None, projet: str | None = None) -> dict:
    """Ajoute un test à la file (dédoublonné par type + cible)."""
    if type_ not in ("lecon", "exemple", "charte", "modeles"):
        raise ValueError("type : lecon, exemple, charte ou modeles")
    for cle in ("lecon", "exemple"):  # bouclier : aucune variante textuelle suspecte d'injection
        texte = (variante or {}).get(cle)
        if texte and bouclier.detecter_injection(texte).score >= bouclier.SEUIL_MOYEN:
            ledger.journaliser("NEXUS-BOUCLIER", "fantome_refuse", None, type=type_, cible=str(cible))
            raise ValueError("Variante refusée par le bouclier : texte suspect d'injection de consignes.")
    with _verrou:
        file = [j for j in _file() if not (j["type"] == type_ and str(j["cible"]) == str(cible))]
        job = {"type": type_, "cible": str(cible), "variante": variante, "service": service, "projet": projet,
               "planifie_le": maintenant().isoformat()}
        sentinel.ecrire(FILE_CLE, json.dumps(file + [job], ensure_ascii=False))
    ledger.journaliser("NEXUS-PRIME", "fantome_planifie", None, type=type_, cible=str(cible), service=service)
    return job


def resultat(type_: str, cible: str | int) -> dict | None:
    return json.loads(sentinel.lire(f"fantome:{type_}:{cible}") or "null")


def etat() -> dict:
    return {"file": _file(), "en_cours": _verrou_execution.locked(), "fenetre": os.environ.get(
        "NEXUS_FENETRE_NUIT", "01:00-06:00"), "k": k()}


# --- Notation ----------------------------------------------------------------------------------

def _definitions_banc() -> dict:
    d = os.environ.get("NEXUS_BANC_DIR", "").strip()
    if not d:
        return {}
    try:
        missions = json.loads((Path(d) / "missions.json").read_text(encoding="utf-8"))["missions"]
        return {m["titre"]: m for m in missions}
    except (OSError, ValueError, KeyError):
        return {}


def _noter_banc(definition: dict, m: Mission) -> float | None:
    d = os.environ.get("NEXUS_BANC_DIR", "").strip()
    try:
        if d not in sys.path:
            sys.path.insert(0, d)
        import noter  # banc-essai/noter.py (Python standard)
        r = noter.noter_mission(definition, {"livrable_texte": m.livrable_texte or "", "service": m.service,
                                             "niveau": m.niveau, "statut": "terminee"})
        return float(r["note_livrable"])
    except Exception:
        return None


def noter(mid: int, definitions: dict | None = None) -> tuple[float, str]:
    """(note sur 100, méthode). Banc si possible, sinon charte + CHECKER + issue."""
    with session_scope() as s:
        m = s.get(Mission, mid)
        refus = s.execute(select(Etape).where(Etape.mission_id == mid, Etape.role == "checker")
                          .order_by(Etape.id.desc())).scalars().first()
        definition = (definitions or {}).get(m.titre)
        livrable = m.livrable_texte or ""
        # Bouclier : un rejeu dont la sortie montre une injection réussie est lourdement pénalisé.
        penalite = 40 if bouclier.verifier_sortie(livrable, {"consigne": m.consigne, "action": m.action})["suspect"] else 0
        if definition:
            note = _noter_banc(definition, m)
            if note is not None:
                return max(0.0, note - penalite), "banc"
        if not livrable.strip():
            return 0.0, "charte+checker"
        c = charte.verifier(m.projet, m.service, livrable, m.action)
        note = 100 - 30 * len(c["bloquants"]) - min(30, 10 * len(c["avertissements"])) - 10 * (m.revisions or 0)
        if refus is not None and refus.verdict == "refus":
            note -= 20
        if m.statut in ("echouee", "a_reformuler", "plafond_atteint"):
            note = min(note, 20)
        note -= penalite
        return float(max(0, min(100, note))), "charte+checker"


# --- Exécution -----------------------------------------------------------------------------------

_verrou_execution = threading.Lock()


def _missions_du_domaine(service: str | None, projet: str | None, n: int) -> list[dict]:
    with session_scope() as s:
        q = select(ArchiveIndex).where(ArchiveIndex.efface.is_(False), ArchiveIndex.evenement == "fin_execution")
        if service:
            q = q.where(ArchiveIndex.service == service)
        if projet:
            q = q.where(ArchiveIndex.projet == projet)
        seqs, vues = [], set()
        for a in s.execute(q.order_by(ArchiveIndex.seq.desc())).scalars():
            if a.mission_id not in vues:
                vues.add(a.mission_id)
                seqs.append(a.seq)
            if len(seqs) >= n:
                break
    par_seq = {l["seq"]: l["enregistrement"] for l in archive.lignes() if l["seq"] in seqs}
    return [par_seq[q] for q in seqs if q in par_seq and not par_seq[q].get("efface")]


def _rejouer(e: dict) -> int:
    from .pipeline import traiter
    with session_scope() as s:
        m = Mission(titre=e["titre"], consigne=e["consigne"], service=e.get("service"), projet=e.get("projet") or "divers",
                    montant_eur=e.get("montant_eur") or 0.0, action=e.get("action"), statut="recue", fantome=True,
                    fonctionnement=e.get("fonctionnement") or "F2", fonctionnement_demande=e.get("fonctionnement") or "F2")
        s.add(m)
        s.flush()
        mid = m.id
    traiter(mid)
    return mid


def _surcharge(job: dict) -> dict:
    v = job.get("variante") or {}
    return {"lecon": v.get("lecon"), "exemple": v.get("exemple"), "charte_dir": v.get("charte_dir"),
            "modeles_roles": v.get("modeles_roles")}


def executer(job: dict) -> dict:
    """Rejoue K missions avant puis après la variante ; enregistre et renvoie le résultat."""
    with _verrou_execution:
        cas = _missions_du_domaine(job.get("service"), job.get("projet"), k())
        definitions = _definitions_banc()
        avant, apres, ids, methodes = [], [], [], set()
        for e in cas:
            mid = _rejouer(e)
            n, meth = noter(mid, definitions)
            avant.append(n), ids.append(mid), methodes.add(meth)
        with surcharges.appliquer(**_surcharge(job)):
            for e in cas:
                mid = _rejouer(e)
                n, meth = noter(mid, definitions)
                apres.append(n), ids.append(mid), methodes.add(meth)
        with session_scope() as s:  # clôture : tous les rejeux finissent au statut « fantome »
            for m in s.execute(select(Mission).where(Mission.id.in_(ids))).scalars():
                m.statut = "fantome"
        if cas:
            gain = round(sum(apres) / len(apres) - sum(avant) / len(avant), 1)
            texte = f"{gain:+.0f} points sur {len(cas)} mission(s)" + (" → déconseillé" if gain < 0 else "")
        else:
            gain, texte = 0.0, "aucune mission archivée dans ce domaine : test impossible"
        res = {"type": job["type"], "cible": job["cible"], "gain": gain, "missions": len(cas), "texte": texte,
               "avant": avant, "apres": apres, "methode": "+".join(sorted(methodes)) or "aucune",
               "verdict": "deconseille" if gain < 0 else ("neutre" if gain == 0 else "favorable"),
               "date": maintenant().isoformat(timespec="seconds")}
        sentinel.ecrire(f"fantome:{job['type']}:{job['cible']}", json.dumps(res, ensure_ascii=False))
    ledger.journaliser("NEXUS-PRIME", "fantome_resultat", None, type=job["type"], cible=job["cible"],
                       gain=gain, missions=len(cas))
    if job["type"] == "exemple" and gain < 0:  # exemples auto-promus : retrait automatique si défavorable
        from .exemples import retirer
        retirer(int(job["cible"]))
    return res


def tick(maintenant_utc: datetime | None = None) -> dict | None:
    """Chaque minute : dans la fenêtre de nuit et si aucun test ne tourne, lance le premier de la file
    dans un fil dédié (la boucle minute n'est jamais bloquée)."""
    t = maintenant_utc or maintenant()
    if not dans_la_fenetre(t) or _verrou_execution.locked():
        return None
    with _verrou:
        file = _file()
        if not file:
            return None
        job, reste = file[0], file[1:]
        sentinel.ecrire(FILE_CLE, json.dumps(reste, ensure_ascii=False))
    threading.Thread(target=_executer_protege, args=(job,), name="fantome", daemon=True).start()
    return job


def _executer_protege(job: dict) -> None:
    try:
        executer(job)
    except Exception:
        log.exception("Test fantôme en échec : %s", job)
