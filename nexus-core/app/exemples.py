"""Exemples modèles par service (few-shot court injecté dans l'ANALYST).

Sources : livrable N3 validé, livrable noté ≥ NEXUS_EXEMPLES_SEUIL (défaut 4/5), ou marquage manuel
« garder comme exemple » depuis le cockpit. Au plus 3 exemples actifs par service (les mieux notés,
puis les plus récents). Filtres : anti-secret (cyber) et charte du projet (un exemple qui viole sa
charte n'est jamais retenu). Un exemple peut être retiré à tout moment.
"""
import os

from sqlalchemy import select

from . import bouclier, charte, cyber, ledger
from .db import session_scope
from .models import Exemple, Mission, maintenant

MAX_PAR_SERVICE = 3
TAILLE_EXEMPLE = 1500
TAILLE_INJECTION = 1500


class ExempleRefuse(ValueError):
    pass


def seuil() -> int:
    try:
        return int(os.environ.get("NEXUS_EXEMPLES_SEUIL", "") or 4)
    except ValueError:
        return 4


def _extrait(livrable: str) -> str:
    lignes = [l for l in (livrable or "").splitlines() if not l.strip().upper().startswith("BROUILLON")]
    texte = "\n".join(lignes).strip()
    return texte if len(texte) <= TAILLE_EXEMPLE else texte[: TAILLE_EXEMPLE - 1].rstrip() + "…"


def _suspect(texte: str) -> bool:
    """Bouclier : signes d'injection réussie (hors secrets, traités à part) ou consignes injectées."""
    if any(not m.startswith("secret") for m in bouclier.verifier_sortie(texte or "")["motifs"]):
        return True
    return bouclier.detecter_injection(texte or "").score >= bouclier.SEUIL_MOYEN


def proposer(mid: int, origine: str, manuel: bool = False) -> dict | None:
    """Fait d'un livrable un exemple de son service. `manuel=True` : erreurs remontées (ExempleRefuse)."""
    with session_scope() as s:
        m = s.get(Mission, mid)
        if m is None:
            raise ExempleRefuse("Mission introuvable.")
        service, projet, titre, livrable, note, statut = (m.service, m.projet, m.titre, m.livrable_texte,
                                                          m.note, m.statut)
    motif = None
    if not service or not (livrable or "").strip():
        motif = "mission sans service ou sans livrable"
    elif statut not in ("terminee", "validee"):
        motif = f"mission non validée (statut {statut})"
    elif cyber.detecter_secrets(livrable):
        motif = "le livrable contient un secret"
    elif charte.verifier(projet, service, livrable)["bloquants"]:
        motif = "le livrable ne respecte pas la charte du projet"
    elif _suspect(livrable):
        motif = "le livrable est suspect d'injection de consignes (bouclier)"
    if motif:
        ledger.journaliser("NEXUS-PRIME", "exemple_ecarte", mid, motif=motif, origine=origine)
        if manuel:
            raise ExempleRefuse(f"Exemple refusé : {motif}.")
        return None
    with session_scope() as s:
        e = s.execute(select(Exemple).where(Exemple.mission_id == mid)).scalar_one_or_none()
        if e is None:
            e = Exemple(mission_id=mid, service=service, projet=projet, titre=titre[:200], extrait=_extrait(livrable),
                        note=note, origine=origine, actif=True, cree_le=maintenant())
            s.add(e)
        else:
            e.actif, e.note, e.origine, e.extrait = True, note, origine, _extrait(livrable)
            e.cree_le = maintenant()
        s.flush()
        eid = e.id
    ledger.journaliser("NEXUS-PRIME", "exemple_retenu", mid, exemple_id=eid, service=service, origine=origine)
    from . import fantome  # exemple actif tout de suite (faible risque), vérifié la nuit, retiré si défavorable
    fantome.planifier("exemple", eid, {"exemple": f"[exemple #{eid} — {titre}]\n{_extrait(livrable)}"}, service)
    _limiter(service)
    return {"id": eid, "service": service}


def _limiter(service: str) -> None:
    """Garde les MAX_PAR_SERVICE meilleurs exemples actifs (note puis date) ; désactive les autres."""
    with session_scope() as s:
        actifs = s.execute(select(Exemple).where(Exemple.service == service, Exemple.actif.is_(True))).scalars().all()
        actifs.sort(key=lambda e: (e.note or 0, e.cree_le, e.id), reverse=True)
        for e in actifs[MAX_PAR_SERVICE:]:
            e.actif = False


def retirer(eid: int) -> bool:
    with session_scope() as s:
        e = s.get(Exemple, eid)
        if e is None:
            return False
        e.actif = False
        mid = e.mission_id
    ledger.journaliser("DECIDEUR", "exemple_retire", mid, exemple_id=eid)
    return True


def lister(service: str | None = None, tous: bool = False) -> list[dict]:
    with session_scope() as s:
        q = select(Exemple).order_by(Exemple.service, Exemple.cree_le.desc())
        if service:
            q = q.where(Exemple.service == service)
        if not tous:
            q = q.where(Exemple.actif.is_(True))
        return [{"id": e.id, "mission_id": e.mission_id, "service": e.service, "projet": e.projet, "titre": e.titre,
                 "extrait": e.extrait, "note": e.note, "origine": e.origine, "actif": e.actif,
                 "cree_le": e.cree_le.isoformat()} for e in s.execute(q).scalars()]


def pour_analyst(service: str | None, projet: str | None, maxi: int = TAILLE_INJECTION) -> str:
    """Few-shot ≤ maxi caractères : exemples du même service, même projet d'abord ; un exemple d'un autre
    projet n'est retenu que s'il respecte la charte du projet courant (pas de mélange de marques)."""
    if not service:
        return ""
    candidats = [e for e in lister(service) if e["projet"] == projet and not _suspect(e["extrait"])] + \
                [e for e in lister(service) if e["projet"] != projet
                 and not charte.verifier(projet, service, e["extrait"])["bloquants"] and not _suspect(e["extrait"])]
    blocs, total = [], 0
    for e in candidats:
        reste = maxi - total - 40
        if reste < 200:
            break
        extrait = e["extrait"] if len(e["extrait"]) <= reste else e["extrait"][: reste - 1] + "…"
        bloc = f"[exemple #{e['id']} — {e['titre']}]\n{extrait}"
        blocs.append(bloc)
        total += len(bloc) + 2
    return "\n\n".join(blocs)[:maxi]
