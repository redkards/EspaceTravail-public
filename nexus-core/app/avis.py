"""Note du Décideur en un geste : 👍 / 👎 + motif, sur un échantillon des missions terminées.

- Échantillon : NEXUS_ECHANTILLON_NOTE (défaut 0.2), tirage stable par mission (empreinte de l'id),
  sur les missions terminées ou validées des 14 derniers jours, pas encore notées.
- 👎 → signal transmis à la mémoire collective (leçons) ; 👍 → livrable candidat exemple (B4).
- Statistiques de satisfaction par service, projet, modèle (ANALYST) et niveau F.
"""
import hashlib
import json
import os
from datetime import timedelta

from sqlalchemy import select

from . import cyber, exemples, lecons, ledger
from .db import session_scope
from .models import Avis, Mission, maintenant

MOTIFS = {"faux": "information fausse ou inventée", "incomplet": "incomplet", "hors_ton": "hors ton",
          "mauvaise_marque": "mauvaise marque ou mélange de projets", "trop_long": "trop long", "autre": "autre"}
FENETRE_JOURS = 14


def taux() -> float:
    try:
        return min(1.0, max(0.0, float(os.environ.get("NEXUS_ECHANTILLON_NOTE", "") or 0.2)))
    except ValueError:
        return 0.2


def tiree(mid: int) -> bool:
    """Tirage pseudo-aléatoire stable : la même mission reste (ou non) dans l'échantillon."""
    return int(hashlib.sha256(f"echantillon:{mid}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < taux()


def a_noter(limite: int = 5) -> list[dict]:
    debut = maintenant() - timedelta(days=FENETRE_JOURS)
    with session_scope() as s:
        notees = set(s.execute(select(Avis.mission_id)).scalars())
        ms = s.execute(select(Mission).where(Mission.statut.in_(("terminee", "validee")))
                       .where(Mission.maj_le >= debut).order_by(Mission.id.desc())).scalars().all()
        return [{"mission_id": m.id, "titre": m.titre, "projet": m.projet, "service": m.service,
                 "fonctionnement": m.fonctionnement, "extrait": (m.livrable_texte or "")[:400]}
                for m in ms if m.id not in notees and tiree(m.id)][:limite]


def _modele_analyste(m: Mission) -> str | None:
    return (json.loads(m.modeles_json) if m.modeles_json else {}).get("analyst")


def enregistrer(mid: int, valeur: str, motif: str | None, texte: str | None, utilisateur: str) -> dict:
    if valeur not in ("positif", "negatif"):
        raise ValueError("valeur : positif ou negatif")
    if valeur == "negatif" and motif not in MOTIFS:
        raise ValueError("motif obligatoire pour un avis négatif : " + ", ".join(MOTIFS))
    texte = cyber.masquer((texte or "").strip())[:120] or None
    with session_scope() as s:
        m = s.get(Mission, mid)
        if m is None:
            raise LookupError("Mission introuvable.")
        if m.statut not in ("terminee", "validee"):
            raise PermissionError("Seules les missions terminées ou validées se notent.")
        if s.execute(select(Avis.id).where(Avis.mission_id == mid)).first():
            raise PermissionError("Mission déjà notée.")
        s.add(Avis(mission_id=mid, valeur=valeur, motif=motif if valeur == "negatif" else None, texte=texte,
                   utilisateur=utilisateur, service=m.service, projet=m.projet, modele=_modele_analyste(m),
                   fonctionnement=m.fonctionnement, cree_le=maintenant()))
    ledger.journaliser("DECIDEUR", f"avis_{valeur}", mid, motif=motif, utilisateur=utilisateur,
                       source="decideur_mobile")
    res = {"mission_id": mid, "valeur": valeur}
    if valeur == "negatif":
        res["lecons"] = lecons.enregistrer_signaux(mid)  # signal pour la mémoire collective
    else:
        res["exemple"] = exemples.proposer(mid, "avis_positif")  # candidat exemple (B4)
    return res


def statistiques(jours: int = 30) -> dict:
    debut = maintenant() - timedelta(days=jours)
    with session_scope() as s:
        tous = s.execute(select(Avis).where(Avis.cree_le >= debut)).scalars().all()

    def grouper(cle):
        g = {}
        for a in tous:
            k = getattr(a, cle) or "?"
            d = g.setdefault(k, {"positifs": 0, "negatifs": 0})
            d["positifs" if a.valeur == "positif" else "negatifs"] += 1
        for d in g.values():
            d["satisfaction"] = round(100 * d["positifs"] / (d["positifs"] + d["negatifs"]))
        return g
    motifs = {}
    for a in tous:
        if a.motif:
            motifs[a.motif] = motifs.get(a.motif, 0) + 1
    return {"avis": len(tous), "par_service": grouper("service"), "par_projet": grouper("projet"),
            "par_modele": grouper("modele"), "par_fonctionnement": grouper("fonctionnement"),
            "motifs_negatifs": motifs}
