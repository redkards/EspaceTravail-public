"""Export vers le QG (Notion via n8n ou un petit relais) : un résumé court par mission terminée.

- Déclenché à chaque livrable enregistré (mission terminée, ou N3 validée).
- Charge : résumé ≤ 600 caractères, sans secret (masqué), plus quelques métadonnées.
- Envoi : POST JSON vers NEXUS_WEBHOOK_QG, signé HMAC-SHA256 avec NEXUS_WEBHOOK_SECRET
  (en-tête X-Nexus-Signature: sha256=<hex> calculé sur « horodatage.corps »). Sans secret, rien
  n'est envoyé (jamais de webhook non signé).
- File + reprise : chaque export est stocké ; échec → nouvel essai avec attente croissante
  (1, 2, 4… min, au plus 6 h), abandon après 10 tentatives (statut « echec », visible et journalisé).
"""
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from . import cyber, ledger
from .config import cfg
from .db import session_scope
from .models import ExportQG, Mission, maintenant

log = logging.getLogger("nexus.export_qg")
RESUME_MAX = 600
TENTATIVES_MAX = 10
ATTENTE_MAX_MIN = 360


def configure() -> bool:
    return bool(os.environ.get("NEXUS_WEBHOOK_QG", "").strip() and os.environ.get("NEXUS_WEBHOOK_SECRET", "").strip())


def resume(livrable: str | None) -> str:
    lignes = [l.strip(" #*-\t") for l in (livrable or "").splitlines()
              if l.strip() and not l.strip().upper().startswith("BROUILLON")]
    texte = cyber.masquer(re.sub(r"\s+", " ", " ".join(lignes)).strip())
    return texte if len(texte) <= RESUME_MAX else texte[: RESUME_MAX - 1].rstrip() + "…"


def mettre_en_file(mid: int) -> int | None:
    """Prépare l'export d'une mission (idempotent : une seule entrée par mission)."""
    if not os.environ.get("NEXUS_WEBHOOK_QG", "").strip():
        return None
    with session_scope() as s:
        if s.execute(select(ExportQG.id).where(ExportQG.mission_id == mid)).first():
            return None
        m = s.get(Mission, mid)
        hote = (cfg().nexus_host or "").strip()
        charge = {
            "evenement": "mission.terminee", "mission_id": m.id, "projet": m.projet, "service": m.service,
            "titre": cyber.masquer(m.titre)[:200], "statut": m.statut, "niveau": m.niveau,
            "fonctionnement": m.fonctionnement, "tokens": m.tokens, "cout_eur": round(m.cout_eur or 0, 4),
            "resume": resume(m.livrable_texte), "date": maintenant().isoformat(timespec="seconds") + "Z",
            "lien": f"https://{hote}/cockpit" if hote else None,
        }
        e = ExportQG(mission_id=mid, charge_json=json.dumps(charge, ensure_ascii=False), statut="en_attente",
                     tentatives=0, prochain_essai=maintenant(), cree_le=maintenant())
        s.add(e)
        s.flush()
        return e.id


def signer(corps: bytes, horodatage: str, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), horodatage.encode() + b"." + corps, hashlib.sha256).hexdigest()


def _envoyer(e: ExportQG) -> tuple[bool, str]:
    url = os.environ.get("NEXUS_WEBHOOK_QG", "").strip()
    secret = os.environ.get("NEXUS_WEBHOOK_SECRET", "").strip()
    if not secret:
        return False, "NEXUS_WEBHOOK_SECRET absent : envoi non signé refusé"
    corps = e.charge_json.encode("utf-8")
    horodatage = str(int(time.time()))
    try:
        r = httpx.post(url, content=corps, timeout=10, headers={
            "Content-Type": "application/json", "X-Nexus-Evenement": "mission.terminee",
            "X-Nexus-Horodatage": horodatage, "X-Nexus-Signature": signer(corps, horodatage, secret),
            "X-Nexus-Livraison": str(e.id)})
        if 200 <= r.status_code < 300:
            return True, ""
        return False, f"HTTP {r.status_code}"
    except Exception as ex:  # réseau, délai…
        return False, type(ex).__name__


def envoyer_en_attente(limite: int = 20) -> dict:
    """Envoie les exports dus (appelé chaque minute). Renvoie {envoyes, echecs, abandonnes}."""
    stats = {"envoyes": 0, "echecs": 0, "abandonnes": 0}
    if not os.environ.get("NEXUS_WEBHOOK_QG", "").strip():
        return stats
    with session_scope() as s:
        dus = s.execute(select(ExportQG).where(ExportQG.statut == "en_attente")
                        .where(ExportQG.prochain_essai <= maintenant())
                        .order_by(ExportQG.id).limit(limite)).scalars().all()
    for e in dus:
        ok, erreur = _envoyer(e)
        with session_scope() as s:
            x = s.get(ExportQG, e.id)
            x.tentatives += 1
            if ok:
                x.statut, x.envoye_le, x.derniere_erreur = "envoye", maintenant(), None
                stats["envoyes"] += 1
            else:
                x.derniere_erreur = erreur[:200]
                if x.tentatives >= TENTATIVES_MAX:
                    x.statut = "echec"
                    stats["abandonnes"] += 1
                else:
                    attente = min(ATTENTE_MAX_MIN, 2 ** (x.tentatives - 1))
                    x.prochain_essai = maintenant() + timedelta(minutes=attente)
                    stats["echecs"] += 1
            mid, statut, tentatives = x.mission_id, x.statut, x.tentatives
        if ok:
            ledger.journaliser("NEXUS-PRIME", "export_qg_envoye", mid, tentatives=tentatives)
        elif statut == "echec":
            ledger.journaliser("NEXUS-PRIME", "export_qg_abandonne", mid, tentatives=tentatives, erreur=erreur)
    return stats


def etat() -> dict:
    from sqlalchemy import func
    with session_scope() as s:
        par_statut = dict(s.execute(select(ExportQG.statut, func.count(ExportQG.id)).group_by(ExportQG.statut)).all())
    return {"configure": configure(), "par_statut": par_statut}
