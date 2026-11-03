"""Résumé quotidien ntfy (générique) à NEXUS_RESUME_QUOTIDIEN (défaut 19:00, heure de Paris).

Contenu : nombre de missions terminées dans la journée, décisions N3 en attente, alertes (missions
échouées, plafonds, à reformuler, leçons suspendues, journal non signé). Jamais de détail métier.
Désactivation : NEXUS_RESUME_QUOTIDIEN=off (ou vide après « = » explicite : « 0 », « non »).
"""
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import decideur, ledger, sentinel
from .config import cfg
from .db import session_scope
from .models import Decision, Mission, maintenant

FENETRE_MIN = 60


def heure() -> str | None:
    v = os.environ.get("NEXUS_RESUME_QUOTIDIEN")
    if v is None:
        return "19:00"
    v = v.strip().lower()
    if v in ("", "0", "off", "non", "aucun", "desactive"):
        return None
    return v if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else "19:00"


def bilan(maintenant_utc: datetime | None = None) -> dict:
    t = maintenant_utc or maintenant()
    paris = t.replace(tzinfo=timezone.utc).astimezone(decideur.PARIS)
    debut = paris.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    with session_scope() as s:
        terminees = s.execute(select(func.count(Mission.id)).where(Mission.maj_le >= debut)
                              .where(Mission.statut.in_(("terminee", "validee")))).scalar_one()
        alertes = s.execute(select(func.count(Mission.id)).where(Mission.maj_le >= debut)
                            .where(Mission.statut.in_(("echouee", "plafond_atteint", "a_reformuler",
                                                       "suspendue")))).scalar_one()
        attente = s.execute(select(func.count(Decision.id)).where(Decision.statut == "en_attente")).scalar_one()
    try:
        from .lecons import suspendues_depuis
        alertes += suspendues_depuis(debut)
    except Exception:  # module optionnel (leçons) absent ou erreur : le résumé part quand même
        pass
    if ledger.avertissement():
        alertes += 1
    return {"terminees": terminees, "n3_en_attente": attente, "alertes": alertes}


def message(b: dict) -> str:
    def p(n, s, pl):
        return f"{n} {s if n == 1 else pl}"
    return (f"Bilan du jour : {p(b['terminees'], 'mission terminee', 'missions terminees')}, "
            f"{p(b['n3_en_attente'], 'decision N3 en attente', 'decisions N3 en attente')}, "
            f"{p(b['alertes'], 'alerte', 'alertes')}.")


def tick(maintenant_utc: datetime | None = None) -> dict | None:
    """Envoie le résumé une fois par jour dans la fenêtre [heure, heure + 60 min)."""
    h = heure()
    if not h:
        return None
    t = maintenant_utc or maintenant()
    paris = t.replace(tzinfo=timezone.utc).astimezone(decideur.PARIS)
    hh, mm = map(int, h.split(":"))
    debut = paris.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if not (debut <= paris < debut + timedelta(minutes=FENETRE_MIN)):
        return None
    cle = f"resume:{paris.strftime('%Y-%m-%d')}"
    if sentinel.lire(cle) == "1":
        return None
    sentinel.ecrire(cle, "1")
    b = bilan(t)
    from .pipeline import notifier
    hote = (cfg().nexus_host or "").strip()
    envoye = notifier("NEXUS : bilan du jour", message(b), None, clic=f"https://{hote}/cockpit" if hote else None)
    ledger.journaliser("NEXUS-PRIME", "resume_quotidien", None, envoye=envoye, **b)
    return b
