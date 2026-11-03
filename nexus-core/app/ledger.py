"""LEDGER : journal append-only chaîné.

Chaque entrée contient l'empreinte de la précédente ; toute modification d'une ligne casse la
chaîne et est détectée par `verifier()`.
- Avec LEDGER_HMAC_KEY : empreinte HMAC-SHA256 (clé hors base) — quelqu'un qui accède à la base
  ne peut pas réécrire une chaîne valide sans la clé.
- Sans clé : SHA-256 simple (ancien comportement) et avertissement dans /api/sante.
Une entrée SHA-256 placée après une entrée HMAC est refusée (pas de « déclassement »).
"""
import hashlib
import hmac
import json
import os
import threading

from sqlalchemy import select

from .db import session_scope
from .models import Ledger, maintenant

GENESE = "0" * 64
_verrou = threading.Lock()  # sérialise les écritures (1 seul worker)


def cle_hmac() -> bytes | None:
    v = os.environ.get("LEDGER_HMAC_KEY", "").strip()
    return v.encode("utf-8") if v else None


def avertissement() -> str | None:
    if cle_hmac() is None:
        return ("LEDGER_HMAC_KEY absente : journal chaîné en SHA-256 sans clé, réécriture possible par "
                "quiconque accède à la base. Définir LEDGER_HMAC_KEY (install.sh la génère).")
    return None


def _charge(horodatage, acteur, action, mission_id, details_json, hash_prec) -> bytes:
    return json.dumps([horodatage, acteur, action, mission_id, details_json, hash_prec],
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _calcul(horodatage, acteur, action, mission_id, details_json, hash_prec, algo: str = "sha256",
            cle: bytes | None = None) -> str:
    charge = _charge(horodatage, acteur, action, mission_id, details_json, hash_prec)
    if algo == "hmac":
        return hmac.new(cle or b"", charge, hashlib.sha256).hexdigest()
    return hashlib.sha256(charge).hexdigest()


def journaliser(acteur: str, action: str, mission_id: int | None = None, **details) -> str:
    """Ajoute une entrée dans sa propre transaction et renvoie son empreinte."""
    details_json = json.dumps(details, ensure_ascii=False, sort_keys=True, default=str)
    cle = cle_hmac()
    algo = "hmac" if cle else "sha256"
    with _verrou, session_scope() as s:
        dernier = s.execute(select(Ledger).order_by(Ledger.id.desc()).limit(1)).scalar_one_or_none()
        hash_prec = dernier.hash if dernier else GENESE
        horodatage = maintenant().isoformat(timespec="microseconds")
        h = _calcul(horodatage, acteur, action, mission_id, details_json, hash_prec, algo, cle)
        s.add(Ledger(horodatage=horodatage, acteur=acteur, action=action, mission_id=mission_id,
                     details_json=details_json, hash_prec=hash_prec, hash=h, algo=algo))
        return h


def verifier() -> dict:
    """Recalcule toute la chaîne.

    Renvoie {valide, entrees, premiere_erreur, motif, hmac_actif, entrees_signees, entrees_non_signees}.
    """
    cle = cle_hmac()
    prec = GENESE
    n = signees = 0
    vu_hmac = False
    res = {"hmac_actif": cle is not None}
    with session_scope() as s:
        for e in s.execute(select(Ledger).order_by(Ledger.id)).scalars():
            n += 1
            algo = e.algo or "sha256"
            motif = None
            if algo == "hmac":
                vu_hmac = True
                signees += 1
                if cle is None:
                    motif = "entrée signée HMAC mais LEDGER_HMAC_KEY absente : vérification impossible"
            elif vu_hmac:
                motif = "entrée SHA-256 après une entrée HMAC (déclassement interdit)"
            if motif is None:
                attendu = _calcul(e.horodatage, e.acteur, e.action, e.mission_id, e.details_json, prec, algo, cle)
                if e.hash_prec != prec or not hmac.compare_digest(e.hash, attendu):
                    motif = "empreinte ou chaînage invalide"
            if motif:
                return {**res, "valide": False, "entrees": n, "premiere_erreur": e.id, "motif": motif,
                        "entrees_signees": signees, "entrees_non_signees": n - signees}
            prec = e.hash
    return {**res, "valide": True, "entrees": n, "premiere_erreur": None, "motif": None,
            "entrees_signees": signees, "entrees_non_signees": n - signees}


def lister(limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    with session_scope() as s:
        rows = s.execute(select(Ledger).order_by(Ledger.id.desc()).limit(limit)).scalars().all()
        return [
            {"id": e.id, "horodatage": e.horodatage, "acteur": e.acteur, "action": e.action,
             "mission_id": e.mission_id, "details": json.loads(e.details_json or "{}"),
             "hash_prec": e.hash_prec, "hash": e.hash, "algo": e.algo or "sha256"}
            for e in rows
        ]
