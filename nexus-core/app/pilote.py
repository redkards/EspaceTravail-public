"""Pilote de projets hebdomadaire.

Chaque lundi à NEXUS_PILOTE_HEBDO (défaut 07:30, heure de Paris ; « off » pour désactiver), une mission
PILOT-CORE/pilotage (F2 demandé ; le plancher du service la relève en F3) est lancée pour chaque projet
marqué « actif » dans projets.yaml. Elle s'appuie sur la mémoire du projet, les leçons acceptées et
l'historique des 7 derniers jours, et produit : 3 priorités, 1 à 5 missions proposées, les points bloqués.

Les plans sont consolidés en UNE décision N3 « Plan de la semaine » (Décideur) : le propriétaire coche
les missions à lancer (tout est décoché par défaut). À la validation, seules les missions cochées sont
créées, avec les planchers GATE et de fonctionnement habituels. Notification générique ; résumé envoyé
au webhook QG (D1).
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import agents as reg
from . import bouclier, cyber, decideur, gate, lecons, ledger, memoire, sentinel
from . import projets as registre
from .db import session_scope
from .models import Decision, Mission, maintenant

log = logging.getLogger("nexus.pilote")
SERVICE = "PILOT-CORE/pilotage"
MAX_PAR_PROJET = 5
STATUTS_EN_COURS = ("recue", "en_attente_place", "en_cours")


def heure() -> str | None:
    v = os.environ.get("NEXUS_PILOTE_HEBDO")
    if v is None:
        return "07:30"
    v = v.strip().lower()
    if v in ("", "0", "off", "non", "desactive"):
        return None
    return v if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else "07:30"


def semaine(t_utc: datetime | None = None) -> str:
    p = (t_utc or maintenant()).replace(tzinfo=timezone.utc).astimezone(decideur.PARIS)
    a, s, _ = p.isocalendar()
    return f"{a}-W{s:02d}"


def _etat(sem: str) -> dict:
    return json.loads(sentinel.lire(f"pilote:{sem}") or "{}")


def _ecrire_etat(sem: str, d: dict) -> None:
    sentinel.ecrire(f"pilote:{sem}", json.dumps(d, ensure_ascii=False))


def consigne(projet: str) -> str:
    depuis = maintenant() - timedelta(days=7)
    with session_scope() as s:
        historique = s.execute(select(Mission).where(Mission.projet == projet, Mission.fantome.is_(False),
                                                     Mission.cree_le >= depuis).order_by(Mission.id.desc())
                               .limit(15)).scalars().all()
        lignes_h = [f"- #{m.id} {m.titre} — {m.statut} ({m.service or 'service ?'})" for m in historique]
    trouves, _ = memoire.filtrer_extraits(memoire.extraits(projet, "priorités objectifs état avancement prochaine étape", "F2"))
    extraits = memoire.formater_protege(trouves)  # bouclier : données encapsulées, rejets écartés
    apprises = lecons.actives(None, projet)
    nom = registre.charger()[projet]["nom"]
    return (f"Prépare le plan de la semaine du projet « {nom} » ({projet}).\n"
            "Réponds exactement au format suivant :\n"
            "PRIORITES:\n1. <priorité>\n2. <priorité>\n3. <priorité>\n"
            "MISSIONS:\n- <titre> | <SERVICE> | <F1, F2 ou F3> | <consigne courte et autonome>\n"
            "(1 à 5 missions ; services possibles : " + ", ".join(sorted(reg.services())) + ")\n"
            "BLOQUES:\n- <point bloqué ou « aucun »>\n"
            "N'invente aucun fait : appuie-toi seulement sur les éléments ci-dessous.\n\n"
            "Historique des 7 derniers jours :\n" + ("\n".join(lignes_h) or "- aucune mission") + "\n\n"
            "Mémoire du projet :\n" + (extraits or "- vide") + "\n\n"
            "Leçons acceptées :\n" + (apprises or "- aucune"))


def lancer(sem: str | None = None) -> dict:
    """Crée une mission de pilotage par projet actif et les met dans la file d'exécution."""
    from .file_missions import FILE
    from .pipeline import traiter
    sem = sem or semaine()
    ids = []
    for code, p in registre.charger().items():
        if not p.get("actif"):
            continue
        with session_scope() as s:
            m = Mission(titre=f"Pilote de la semaine {sem} — {p['nom']}", consigne=consigne(code), service=SERVICE,
                        projet=code, statut="recue", fonctionnement_demande="F2", fonctionnement="F2",
                        pilote_semaine=sem)
            s.add(m)
            s.flush()
            ids.append(m.id)
    _ecrire_etat(sem, {"missions": ids, "plan": None})
    ledger.journaliser("NEXUS-PRIME", "pilote_hebdo_lance", None, semaine=sem, missions=ids)
    for mid in ids:
        FILE.soumettre(mid, traiter)
    return {"semaine": sem, "missions": ids}


def tick(maintenant_utc: datetime | None = None) -> dict | None:
    h = heure()
    if not h:
        return None
    t = maintenant_utc or maintenant()
    p = t.replace(tzinfo=timezone.utc).astimezone(decideur.PARIS)
    hh, mm = map(int, h.split(":"))
    debut = p.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if p.isoweekday() != 1 or not (debut <= p < debut + timedelta(minutes=60)):
        return None
    sem = semaine(t)
    cle = f"pilote:lance:{sem}"
    if sentinel.lire(cle) == "1":
        return None
    sentinel.ecrire(cle, "1")
    return lancer(sem)


# --- Consolidation ---------------------------------------------------------------------------

def _section(texte: str, nom: str) -> list[str]:
    t = texte.replace("\r", "")
    m = re.search(rf"^\s*\**\s*{nom}\s*\**\s*:?\s*$(.*?)(?=^\s*\**\s*(?:PRIORIT[EÉ]S|MISSIONS|BLOQU[EÉ]S)\s*\**\s*:?\s*$|\Z)",
                  t, re.S | re.M | re.I)
    if not m:
        return []
    return [re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", l).strip() for l in m.group(1).splitlines()
            if l.strip() and re.match(r"^\s*(?:[-*]|\d+[.)])", l)]


def analyser(projet: str, livrable: str) -> dict:
    """Extrait priorités, missions proposées (validées) et points bloqués d'un plan."""
    services = reg.services()
    propositions = []
    for ligne in _section(livrable or "", "MISSIONS")[:MAX_PAR_PROJET]:
        parties = [x.strip() for x in ligne.split("|")]
        if len(parties) < 4 or not parties[0] or not parties[3]:
            continue
        titre, service, niveau, cons = parties[0][:200], parties[1].upper(), parties[2].upper(), " | ".join(parties[3:])
        service = next((s for s in services if s.upper() == service), None)  # inconnu → PRIME choisira
        niveau = niveau if niveau in ("F1", "F2", "F3") else "F2"  # F4 jamais proposé automatiquement
        score = bouclier.detecter_injection(f"{titre}\n{cons}").score
        if score >= bouclier.SEUIL_HAUT:  # deviendrait une consigne de confiance : écartée
            ledger.journaliser("NEXUS-BOUCLIER", "proposition_rejetee", None, projet=projet, score=score)
            continue
        propositions.append({"projet": projet, "titre": cyber.masquer(titre), "service": service,
                             "fonctionnement": niveau, "consigne": cyber.masquer(cons)[:2000],
                             "alerte": score >= bouclier.SEUIL_MOYEN})
    return {"priorites": _section(livrable or "", "PRIORIT[EÉ]S")[:3], "missions": propositions,
            "bloques": _section(livrable or "", "BLOQU[EÉ]S")[:5]}


def consolider_si_pret(sem: str) -> int | None:
    """Quand toutes les missions de pilotage de la semaine sont finies : une décision N3 « Plan de la semaine »."""
    e = _etat(sem)
    if not e.get("missions") or e.get("plan"):
        return None
    with session_scope() as s:
        ms = s.execute(select(Mission).where(Mission.id.in_(e["missions"]))).scalars().all()
        if any(m.statut in STATUTS_EN_COURS for m in ms):
            return None
        plans = [(m.projet, m.livrable_texte or "", m.statut) for m in ms]
    propositions, lignes, alertes = [], [f"# Plan de la semaine {sem}", ""], []
    for projet, livrable, statut in plans:
        a = analyser(projet, livrable)
        alertes += [f"{projet} : {m}" for m in bouclier.verifier_sortie(livrable)["motifs"]]
        alertes += [f"{projet} : proposition « {p['titre']} » suspecte d'injection" for p in a["missions"] if p["alerte"]]
        lignes.append(f"## {registre.charger()[projet]['nom']}" + ("" if livrable else f" (plan indisponible : {statut})"))
        lignes += [f"Priorité : {x}" for x in a["priorites"]] + [f"Bloqué : {x}" for x in a["bloques"]]
        for prop in a["missions"]:
            prop["id"] = len(propositions) + 1
            propositions.append(prop)
            lignes.append(f"- [{prop['id']}] {prop['titre']} ({prop['service'] or 'service choisi par PRIME'}, "
                          f"{prop['fonctionnement']})" + (" ⚠ suspecte (bouclier)" if prop["alerte"] else ""))
        lignes.append("")
    texte = "\n".join(lignes)
    with session_scope() as s:
        parent = Mission(titre=f"Plan de la semaine {sem}", consigne=f"Consolidation des plans de pilotage ({sem}).",
                         service=SERVICE, projet="divers", statut="en_attente_n3", niveau="N3", livrable_texte=texte,
                         pilote_semaine=sem, message=f"{len(propositions)} mission(s) proposée(s) : cochez celles à lancer.")
        s.add(parent)
        s.flush()
        d = Decision(mission_id=parent.id, niveau="N3", objet="plan_semaine",
                     resume=f"Plan de la semaine {sem} : {len(propositions)} mission(s) proposée(s)",
                     recommandation="Cochez les missions à lancer (aucune par défaut), puis validez.",
                     cout_estime_eur=0.0, risque="faible", risque_raisons=json.dumps(["plan interne"]),
                     sources="Missions de pilotage de la semaine",
                     avis_checker=("Alertes du bouclier anti-injection (à examiner) :\n" + bouclier.texte_alertes(alertes))
                     if alertes else "Sans objet")
        s.add(d)
        s.flush()
        pid, did = parent.id, d.id
    e.update(plan={"mission_id": pid, "decision_id": did, "propositions": propositions})
    _ecrire_etat(sem, e)
    ledger.journaliser("NEXUS-PRIME", "plan_semaine_cree", pid, semaine=sem, decision_id=did,
                       propositions=len(propositions))
    decideur.nouvelle_decision(did)  # notification générique (groupée par session)
    try:
        from . import export_qg
        export_qg.mettre_en_file(pid)  # résumé au QG (D1)
    except Exception:
        log.exception("Export QG du plan de la semaine impossible")
    return did


def propositions_de(did: int) -> list[dict]:
    with session_scope() as s:
        d = s.get(Decision, did)
        m = s.get(Mission, d.mission_id) if d else None
        sem = m.pilote_semaine if m else None
    return ((_etat(sem).get("plan") or {}).get("propositions") or []) if sem else []


def lancer_selection(did: int, selection: list[int] | None) -> list[int]:
    """Crée les missions cochées (statut « recue », planchers normaux) ; renvoie leurs ids."""
    choisies = [p for p in propositions_de(did) if p["id"] in set(selection or [])]
    ids = []
    for p in choisies:
        with session_scope() as s:
            m = Mission(titre=p["titre"], consigne=p["consigne"], service=p["service"], projet=p["projet"],
                        statut="recue", fonctionnement_demande=p["fonctionnement"], fonctionnement=p["fonctionnement"])
            s.add(m)
            s.flush()
            ids.append(m.id)
    ledger.journaliser("DECIDEUR", "plan_semaine_missions_lancees", None, decision_id=did, missions=ids,
                       cochees=[p["id"] for p in choisies])
    return ids
