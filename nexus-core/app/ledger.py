"""LEDGER : journal append-only chaîné par SHA-256.

Chaque entrée contient le hash de la précédente ; toute modification
d'une ligne casse la chaîne et est détectée par `verifier()`.
"""
import hashlib
import json
import threading

from sqlalchemy import select

from .db import session_scope
from .models import Ledger, maintenant

GENESE = "0" * 64
_verrou = threading.Lock()  # sérialise les écritures (1 seul worker)


def _calcul(horodatage, acteur, action, mission_id, details_json, hash_prec) -> str:
    charge = json.dumps(
        [horodatage, acteur, action, mission_id, details_json, hash_prec],
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(charge.encode("utf-8")).hexdigest()


def journaliser(acteur: str, action: str, mission_id: int | None = None, **details) -> str:
    """Ajoute une entrée dans sa propre transaction et renvoie son hash."""
    details_json = json.dumps(details, ensure_ascii=False, sort_keys=True, default=str)
    with _verrou, session_scope() as s:
        dernier = s.execute(select(Ledger).order_by(Ledger.id.desc()).limit(1)).scalar_one_or_none()
        hash_prec = dernier.hash if dernier else GENESE
        horodatage = maintenant().isoformat(timespec="microseconds")
        h = _calcul(horodatage, acteur, action, mission_id, details_json, hash_prec)
        s.add(Ledger(horodatage=horodatage, acteur=acteur, action=action, mission_id=mission_id,
                     details_json=details_json, hash_prec=hash_prec, hash=h))
        return h


def verifier() -> dict:
    """Recalcule toute la chaîne. Renvoie {valide, entrees, premiere_erreur}."""
    prec = GENESE
    n = 0
    with session_scope() as s:
        for e in s.execute(select(Ledger).order_by(Ledger.id)).scalars():
            n += 1
            attendu = _calcul(e.horodatage, e.acteur, e.action, e.mission_id, e.details_json, prec)
            if e.hash_prec != prec or e.hash != attendu:
                return {"valide": False, "entrees": n, "premiere_erreur": e.id}
            prec = e.hash
    return {"valide": True, "entrees": n, "premiere_erreur": None}


def lister(limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    with session_scope() as s:
        rows = s.execute(select(Ledger).order_by(Ledger.id.desc()).limit(limit)).scalars().all()
        return [
            {"id": e.id, "horodatage": e.horodatage, "acteur": e.acteur, "action": e.action,
             "mission_id": e.mission_id, "details": json.loads(e.details_json or "{}"),
             "hash_prec": e.hash_prec, "hash": e.hash}
            for e in rows
        ]
