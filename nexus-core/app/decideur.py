"""Décideur mobile : sessions de décision N3, risque explicable, résumé déterministe, code Décideur.

- Sessions : les décisions N3 sont présentées en NEXUS_SESSIONS_N3 (défaut « 12:30,19:00 »,
  Europe/Paris) avec UNE notification ntfy par session ; une décision qui expire dans moins de
  4 h à sa création est notifiée tout de suite ; rappel 2 h avant le refus automatique.
  Le texte ntfy est toujours générique (aucun détail métier, aucun secret) et pointe vers
  /cockpit/decideur.
- Risque faible / moyen / élevé selon des règles explicables (montant, irréversibilité, tiers,
  production, données sensibles), avec la liste des raisons.
- Valider une décision à risque « élevé » exige le code Décideur COCKPIT_CODE_DECIDEUR
  (6 chiffres, comparaison à temps constant ; 5 erreurs → verrou de 15 minutes).
- Toute action passe par une confirmation en deux temps (jeton à usage unique, 2 minutes).
"""
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from . import gate, ledger, sentinel
from .config import cfg
from .db import session_scope
from .models import Decision, Mission, maintenant

try:
    PARIS = ZoneInfo("Europe/Paris")  # base de fuseaux du système ou paquet Python « tzdata »
except ZoneInfoNotFoundError:  # pragma: no cover — image sans base de fuseaux
    PARIS = timezone(timedelta(hours=1), "Europe/Paris (UTC+1, approximatif)")
    logging.getLogger("nexus.decideur").warning("Fuseau Europe/Paris introuvable : UTC+1 utilisé (installer tzdata).")
URGENCE_H = 4          # expiration dans moins de 4 h à la création → notification immédiate
RAPPEL_H = 2           # rappel 2 h avant le refus automatique
FENETRE_SESSION_MIN = 60
ECHECS_MAX = 5
VERROU_MIN = 15
JETON_TTL_S = 120
TITRE_NTFY = "NEXUS : decisions en attente"


# --- Risque explicable -----------------------------------------------------------------

REGLES_RISQUE = {
    "irreversibilite": (["signer", "signature", "supprimer", "suppression", "resilier", "resiliation",
                         "virement", "payer", "paiement", "verser", "versement", "rembourser",
                         "remboursement", "transferer", "achat", "acheter", "commander", "effacer"], "eleve"),
    "production": (["mise en production", "mettre en production", "deployer", "deploiement", "pare-feu",
                    "firewall", "redemarrer", "redemarrage", "ouverture de port", "ouvrir le port",
                    "serveur de production"], "eleve"),
    "donnees_sensibles": (["donnees personnelles", "mot de passe", "mots de passe", "donnees de sante",
                           "coordonnees bancaires", "iban", "numero de carte"], "eleve"),
    "tiers": (["client", "clients", "partenaire", "partenaires", "fournisseur", "publier", "publication",
               "mise en ligne", "envoyer", "envoi", "diffuser", "poster", "cgv", "cgu", "contrat"], "moyen"),
}
ACTIONS_RISQUE = {"signer": "irreversibilite", "supprimer": "irreversibilite", "depense": "irreversibilite",
                  "mise_en_production": "production", "donnees_sensibles": "donnees_sensibles",
                  "envoyer_client": "tiers", "publier": "tiers"}
LIBELLES_RAISON = {"irreversibilite": "action irréversible", "production": "touche la production",
                   "donnees_sensibles": "données sensibles", "tiers": "implique un tiers ou une publication"}
_ORDRE = {"faible": 0, "moyen": 1, "eleve": 2}


def evaluer_risque(titre: str, consigne: str, livrable: str | None = None, montant_eur: float = 0.0,
                   action: str | None = None, cout_estime_eur: float = 0.0) -> tuple[str, list[str]]:
    """(niveau, raisons). Règles : montant, irréversibilité, tiers, production, données sensibles."""
    niveau, raisons = "faible", []

    def monter(n: str, raison: str):
        nonlocal niveau
        if _ORDRE[n] > _ORDRE[niveau]:
            niveau = n
        raisons.append(raison)

    if montant_eur and montant_eur >= 1000:
        monter("eleve", f"montant engagé {montant_eur:.0f} € (≥ 1 000 €)")
    elif montant_eur and montant_eur > 0:
        monter("moyen", f"montant engagé {montant_eur:.2f} €")
    m = gate.detecter_montant(f"{titre} {consigne}")
    if m and not montant_eur:
        monter("moyen", f"montant cité dans la consigne ({m})")
    if cout_estime_eur and cout_estime_eur > 0 and not montant_eur:
        monter("moyen", f"dépense IA estimée {cout_estime_eur:.2f} €")
    texte = gate.normaliser(f"{titre} {consigne} {livrable or ''}")
    for cle, (mots, n) in REGLES_RISQUE.items():
        mot = gate._contient(texte, mots)
        if mot:
            monter(n, f"{LIBELLES_RAISON[cle]} (« {mot} »)")
    if action in ACTIONS_RISQUE:
        cle = ACTIONS_RISQUE[action]
        monter(REGLES_RISQUE[cle][1], f"{LIBELLES_RAISON[cle]} (action « {action} »)")
    return niveau, raisons or ["aucun critère de risque détecté"]


def risque_mission(m: Mission, objet: str = "livrable", cout_estime_eur: float = 0.0) -> tuple[str, list[str]]:
    livrable = None if objet == "lancement_f4" else m.livrable_texte
    return evaluer_risque(m.titre, m.consigne, livrable, m.montant_eur or 0.0, m.action, cout_estime_eur)


# --- Résumé déterministe en 3 lignes ----------------------------------------------------

def _premiere_ligne_utile(texte: str | None) -> str:
    for ligne in (texte or "").splitlines():
        l = ligne.strip(" #-*>\t")
        if l and not l.upper().startswith("BROUILLON") and len(l) > 3:
            return l
    return ""


def _court(texte: str, n: int = 140) -> str:
    texte = re.sub(r"\s+", " ", texte or "").strip()
    return texte if len(texte) <= n else texte[: n - 1].rstrip() + "…"


def resume_3_lignes(m: Mission, d: Decision) -> dict:
    if d.objet == "lancement_f4":
        return {"quoi": _court(f"Lancer « {m.titre} » avec les modèles payants (F4)."),
                "pourquoi": _court(f"Niveau Expert demandé ; coût estimé {d.cout_estime_eur:.2f} €."),
                "si_refus": "La mission n'est pas lancée : aucune dépense."}
    extrait = _premiere_ligne_utile(m.livrable_texte)
    motif = (m.message or "").split(" ; relevé")[0] or "classement N3 par le GATE"
    action = {"envoyer_client": "aucun envoi au client", "publier": "aucune publication",
              "signer": "aucune signature", "depense": "aucune dépense", "supprimer": "aucune suppression",
              "mise_en_production": "aucune mise en production"}.get(m.action or "", "aucune action externe")
    return {"quoi": _court(f"{m.titre}" + (f" — {extrait}" if extrait else "")),
            "pourquoi": _court(motif[:1].upper() + motif[1:]),
            "si_refus": _court(f"Le livrable reste un brouillon : {action} ne sera réalisée.")}


# --- Cartes ------------------------------------------------------------------------------

def expiration(d: Decision) -> datetime:
    return d.cree_le + timedelta(hours=cfg().n3_timeout_hours)


def carte(d: Decision, m: Mission, maintenant_utc: datetime | None = None) -> dict:
    t = maintenant_utc or maintenant()
    restant = max(0, int((expiration(d) - t).total_seconds()))
    raisons = json.loads(d.risque_raisons) if d.risque_raisons else risque_mission(m, d.objet)[1]
    tokens = m.tokens or 0
    if d.objet == "lancement_f4":
        from .fonctionnement import estimer_cout_eur
        tokens = estimer_cout_eur("F4")["tokens_prevus"]
    afficher_tokens = d.objet == "lancement_f4" or m.fonctionnement == "F4" or (m.montant_eur or 0) > 0
    return {
        "id": d.id, "mission_id": m.id, "objet": d.objet, "titre": m.titre, "resume": resume_3_lignes(m, d),
        "risque": d.risque, "raisons": raisons, "cout_estime_eur": round(d.cout_estime_eur or 0.0, 4),
        "tokens": tokens if afficher_tokens else None, "service": m.service, "projet": m.projet,
        "fonctionnement": m.fonctionnement, "restant_s": restant, "urgent": restant < URGENCE_H * 3600,
        "expire_le": expiration(d).isoformat(), "lien_livrable": f"/cockpit/api/missions/{m.id}",
        "code_requis": d.risque == "eleve",
        "avertissements": json.loads(m.charte_avertissements) if m.charte_avertissements else [],
    }


def etat_decideur(maintenant_utc: datetime | None = None) -> dict:
    from .pipeline import decisions_du_jour
    t = maintenant_utc or maintenant()
    debut = t.replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as s:
        attente = s.execute(select(Decision, Mission).join(Mission, Mission.id == Decision.mission_id)
                            .where(Decision.statut == "en_attente").order_by(Decision.cree_le)).all()
        cartes = sorted((carte(d, m, t) for d, m in attente), key=lambda c: (c["restant_s"], c["id"]))
        historique = s.execute(select(Decision, Mission.titre, Mission.projet)
                               .join(Mission, Mission.id == Decision.mission_id)
                               .where(Decision.statut != "en_attente")
                               .order_by(Decision.decide_le.desc(), Decision.id.desc()).limit(20)).all()
        decidees = s.execute(select(func.count(Decision.id)).where(Decision.decide_le >= debut)
                             .where(Decision.statut.in_(("validee", "refusee", "revision")))).scalar_one()
    return {
        "cartes": cartes,
        "historique": [{"id": d.id, "mission_id": d.mission_id, "titre": titre, "projet": projet,
                        "statut": d.statut, "objet": d.objet, "risque": d.risque,
                        "decide_le": d.decide_le.isoformat() if d.decide_le else None,
                        "commentaire": d.commentaire} for d, titre, projet in historique],
        "compteur_jour": {"decidees": decidees, "creees": decisions_du_jour(), "plafond": cfg().n3_daily_cap},
        "sessions": sessions(), "prochaine_session": prochaine_session(t).isoformat(),
        "code_configure": code_configure(), "verrou_restant_s": verrou_restant_s(),
    }


# --- Sessions et notifications ---------------------------------------------------------

def sessions() -> list[str]:
    brut = os.environ.get("NEXUS_SESSIONS_N3", "").strip() or "12:30,19:00"
    res = []
    for h in brut.split(","):
        h = h.strip()
        if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h):
            res.append(h)
    return sorted(set(res)) or ["12:30", "19:00"]


def _paris(t_utc: datetime) -> datetime:
    return t_utc.replace(tzinfo=timezone.utc).astimezone(PARIS)


def prochaine_session(t_utc: datetime | None = None) -> datetime:
    """Prochaine session (heure de Paris, avec fuseau)."""
    p = _paris(t_utc or maintenant())
    for jour in range(0, 2):
        for h in sessions():
            hh, mm = map(int, h.split(":"))
            cand = (p + timedelta(days=jour)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if cand > p:
                return cand
    return p


def lien_decideur() -> str | None:
    hote = (cfg().nexus_host or "").strip()
    return f"https://{hote}/cockpit/decideur" if hote else None


def _notifier(message: str, mission_id: int | None = None, motif: str = "") -> bool:
    from .pipeline import notifier
    ok = notifier(TITRE_NTFY, message, mission_id, clic=lien_decideur())
    ledger.journaliser("NEXUS-GATE", "notification_decideur", mission_id, motif=motif, envoyee=ok,
                       texte=message)
    return ok


def _pluriel(n: int, singulier: str, pluriel: str) -> str:
    return singulier if n == 1 else pluriel


def nouvelle_decision(did: int, maintenant_utc: datetime | None = None) -> str:
    """Appelé à la création d'une décision : notification immédiate si urgente, sinon session."""
    t = maintenant_utc or maintenant()
    with session_scope() as s:
        d = s.get(Decision, did)
        restant = (expiration(d) - t).total_seconds()
        mid = d.mission_id
    if restant < URGENCE_H * 3600:
        sentinel.ecrire(f"n3:urgent:{did}", "1")
        _notifier("Une decision N3 urgente vous attend (refus automatique dans moins de 4 h).", mid, "urgence")
        return "immediate"
    ledger.journaliser("NEXUS-GATE", "decision_en_attente_session", mid, decision_id=did,
                       session=prochaine_session(t).strftime("%Y-%m-%d %H:%M"))
    return "session"


def tick(maintenant_utc: datetime | None = None) -> dict:
    """Appelé chaque minute : notification de session (une seule) et rappels avant expiration."""
    t = maintenant_utc or maintenant()
    p = _paris(t)
    res = {"session": None, "rappels": 0}
    for h in sessions():
        hh, mm = map(int, h.split(":"))
        debut = p.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if debut <= p < debut + timedelta(minutes=FENETRE_SESSION_MIN):
            cle = f"n3:session:{debut.strftime('%Y-%m-%d')}:{h}"
            if sentinel.lire(cle) == "1":
                continue
            sentinel.ecrire(cle, "1")
            with session_scope() as s:
                n = s.execute(select(func.count(Decision.id)).where(Decision.statut == "en_attente")).scalar_one()
            if n:
                _notifier(f"{n} {_pluriel(n, 'decision N3 vous attend', 'decisions N3 vous attendent')}.",
                          None, f"session {h}")
            res["session"] = {"heure": h, "decisions": n}
    with session_scope() as s:
        attente = s.execute(select(Decision.id, Decision.cree_le).where(Decision.statut == "en_attente")).all()
    limite_h = cfg().n3_timeout_hours
    a_rappeler = [did for did, cree in attente
                  if 0 < (cree + timedelta(hours=limite_h) - t).total_seconds() <= RAPPEL_H * 3600
                  and sentinel.lire(f"n3:rappel:{did}") != "1"]
    for did in a_rappeler:
        sentinel.ecrire(f"n3:rappel:{did}", "1")
    if a_rappeler:
        n = len(a_rappeler)
        _notifier(f"Rappel : {n} {_pluriel(n, 'decision N3 sera refusee', 'decisions N3 seront refusees')} "
                  f"automatiquement dans moins de 2 h.", None, "rappel")
        res["rappels"] = n
    return res


# --- Code Décideur et verrou -------------------------------------------------------------

class CodeRefuse(Exception):
    def __init__(self, message: str, statut: int = 403):
        super().__init__(message)
        self.statut = statut


def code_configure() -> bool:
    return re.fullmatch(r"\d{6}", os.environ.get("COCKPIT_CODE_DECIDEUR", "").strip()) is not None


def verrou_restant_s() -> int:
    v = sentinel.lire("decideur:verrou")
    if not v:
        return 0
    try:
        fin = datetime.fromisoformat(v)
    except ValueError:
        return 0
    return max(0, int((fin - maintenant()).total_seconds()))


def verifier_code(code: str | None, utilisateur: str = "decideur") -> None:
    """Lève CodeRefuse si le code est absent, faux, non configuré ou verrouillé."""
    attendu = os.environ.get("COCKPIT_CODE_DECIDEUR", "").strip()
    if not code_configure():
        raise CodeRefuse("Code Décideur non configuré (COCKPIT_CODE_DECIDEUR) : validation à risque élevé "
                         "impossible.", 403)
    restant = verrou_restant_s()
    if restant:
        raise CodeRefuse(f"Trop d'erreurs de code : validation verrouillée encore {restant // 60 + 1} min.", 423)
    fourni = (code or "").strip()
    if fourni and hmac.compare_digest(fourni.encode(), attendu.encode()):
        sentinel.ecrire("decideur:echecs", "0")
        return
    echecs = int(sentinel.incrementer("decideur:echecs", 1))
    if echecs >= ECHECS_MAX:
        sentinel.ecrire("decideur:verrou", (maintenant() + timedelta(minutes=VERROU_MIN)).isoformat())
        sentinel.ecrire("decideur:echecs", "0")
        ledger.journaliser("DECIDEUR", "code_decideur_verrou", None, utilisateur=utilisateur,
                           duree_min=VERROU_MIN)
        raise CodeRefuse(f"Code Décideur incorrect ({ECHECS_MAX} erreurs) : validation verrouillée "
                         f"{VERROU_MIN} min.", 423)
    ledger.journaliser("DECIDEUR", "code_decideur_errone", None, utilisateur=utilisateur, echecs=echecs)
    raise CodeRefuse(f"Code Décideur incorrect ({ECHECS_MAX - echecs} essai(s) restant(s)).", 403)


# --- Confirmation en deux temps (jetons à usage unique) ---------------------------------

_jetons: dict[str, tuple[int, str, float]] = {}
_verrou_jetons = threading.Lock()


def preparer(did: int, choix: str) -> str:
    jeton = secrets.token_urlsafe(18)
    with _verrou_jetons:
        t = time.monotonic()
        for k in [k for k, (_, _, fin) in _jetons.items() if fin < t]:
            _jetons.pop(k, None)
        _jetons[jeton] = (did, choix, t + JETON_TTL_S)
    return jeton


def jeton_valide(jeton: str | None, did: int, choix: str) -> bool:
    """Vérifie sans consommer (le jeton reste utilisable après une erreur de code)."""
    with _verrou_jetons:
        v = _jetons.get(jeton or "")
    return bool(v and v[0] == did and v[1] == choix and v[2] >= time.monotonic())


def consommer(jeton: str | None, did: int, choix: str) -> bool:
    with _verrou_jetons:
        v = _jetons.pop(jeton or "", None)
    return bool(v and v[0] == did and v[1] == choix and v[2] >= time.monotonic())
