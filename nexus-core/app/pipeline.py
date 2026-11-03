"""Pipeline d'une mission : SENTINEL → PRIME → COLLECTOR → ANALYST ⇄ CHECKER → GATE → N3 / EXECUTOR.

Chaque étape est enregistrée (table etapes) et journalisée (LEDGER).
L'EXECUTOR n'effectue AUCUNE action externe : il enregistre le livrable et
prépare l'action pour un humain ou un workflow n8n.
"""
import json
import logging
import re
from datetime import timedelta

import httpx
from sqlalchemy import func, select

from . import agents as reg
from . import budget, gate, ledger, sentinel
from .config import cfg
from .db import session_scope
from .llm import ErreurLLM, fournisseur, parser_niveau, parser_verdict
from .models import Decision, Etape, Mission, maintenant

log = logging.getLogger("nexus.pipeline")

MAX_BOUCLES_CHECKER = 2   # refus → retour ANALYST, 2 boucles au plus (3 verdicts)
MAX_REVISIONS = 2         # « Demander une révision » : 2 fois au plus par mission
MARQUE = "\n[… tronqué …]\n"

# Classement PRIME par mots-clés (texte normalisé, sans accents).
MOTS_SERVICES = {
    "LEX-GUARD/conformite": ["rgpd", "ai act", "conformite", "cgv", "cgu", "mentions legales", "juridique"],
    "REVENUE-CORE/propositions": ["devis", "proposition commerciale", "offre", "tarif", "prospect", "client"],
    "CONTENT-ARENA/redaction": ["article", "post", "newsletter", "redige un texte", "blog", "linkedin"],
    "CODE-CORE/revue": ["code", "python", "javascript", "bug", "spec", "api", "revue de code"],
    "OPS-CORE/projets": ["plan de projet", "checklist", "planning", "etapes", "organisation", "demarrage"],
    "R&D-PARADOX/veille": ["veille", "synthese", "tendance", "etat de l'art", "resume"],
    "AGENT-FACTORY/evaluation": ["evalue", "evaluation", "qualite de la sortie", "agent"],
    # Nouveaux services (mots entiers, sans accents).
    "CODE-CORE/conception": ["architecture", "conception", "concevoir", "specification", "specifications",
                             "stack", "pseudo-code", "pseudo code", "decoupage en taches", "choix technique"],
    "DESIGN-SYSTEM/ui": ["design", "maquette", "maquettes", "wireframe", "wireframes", "parcours utilisateur",
                         "ux", "ui", "charte graphique", "accessibilite", "rgaa", "wcag", "ergonomie"],
    "LEX-GUARD/droit-france": ["droit francais", "loi francaise", "code civil", "code du commerce",
                               "code de commerce", "code de la consommation", "code du travail", "cnil", "anj",
                               "dgccrf", "micro-entreprise", "micro entreprise", "sasu", "statut juridique",
                               "droit des societes", "jeux d'argent"],
    "LEX-GUARD/droit-europe": ["droit europeen", "droit de l'ue", "union europeenne", "reglement europeen",
                               "directive europeenne", "dsa", "dma", "digital services act", "cjue"],
    "LEX-GUARD/droit-international": ["droit international", "export", "exporter", "conflit de lois",
                                      "conflits de lois", "convention internationale", "juridictions",
                                      "a l'etranger", "hors ue", "loi applicable"],
    "PILOT-CORE/etudes": ["etude de marche", "concurrence", "concurrents", "business plan", "previsionnel",
                          "rentabilite", "seuil de rentabilite", "chiffre d'affaires"],
    "PILOT-CORE/pilotage": ["tableau de bord", "tableaux de bord", "indicateur", "indicateurs", "kpi", "okr",
                            "plan d'action", "revue mensuelle", "pilotage"],
    "GREEN-CORE/environnement": ["environnement", "environnemental", "environnementale", "empreinte carbone",
                                 "bilan carbone", "sobriete numerique", "ecologie", "ecologique", "energie"],
    "GREEN-CORE/rse": ["rse", "responsabilite societale", "eco-conception", "ecoconception", "greenwashing",
                       "communication responsable", "developpement durable"],
}
MENTION_AVOCAT = "Information générale, ne remplace pas l'avis d'un avocat"


def garantir_mention_juridique(service: str | None, livrable: str) -> str:
    """Services LEX-GUARD/droit-* : la mention finale est ajoutée si le modèle l'a oubliée."""
    if not (service or "").startswith("LEX-GUARD/droit-"):
        return livrable
    if gate.normaliser(MENTION_AVOCAT) in gate.normaliser(livrable):
        return livrable
    return f"{livrable.rstrip()}\n\n{MENTION_AVOCAT}."


# --- Assemblage des messages (limite LLM_MAX_CHARS) ---------------------------------

def _couper(texte: str, n: int, mode: str) -> str:
    """Réduit un texte à n caractères : début seul, ou début + fin (« tete_queue »)."""
    if len(texte) <= n:
        return texte
    if n <= len(MARQUE) + 20:
        return texte[:max(0, n)]
    if mode == "tete_queue":
        reste = n - len(MARQUE)
        tete = reste // 3
        return texte[:tete] + MARQUE + texte[len(texte) - (reste - tete):]
    return texte[:n - len(MARQUE)] + MARQUE


def assembler(sections: list[tuple[str, str, int, str]], limite: int | None = None) -> str:
    """Construit le message utilisateur sans dépasser `limite` caractères.

    sections : (intitulé, texte, priorité, mode). La place est attribuée par priorité
    décroissante : les sections les moins prioritaires (ex. la consigne pour le CHECKER)
    sont tronquées en premier ; le livrable, prioritaire, reste entier tant qu'il tient.
    """
    limite = limite or cfg().llm_max_chars
    entetes = [f"{t} :\n" if t else "" for t, _, _, _ in sections]
    dispo = limite - sum(len(e) for e in entetes) - 2 * max(0, len(sections) - 1)
    tailles = [0] * len(sections)
    for i in sorted(range(len(sections)), key=lambda k: -sections[k][2]):
        tailles[i] = max(0, min(len(sections[i][1]), dispo))
        dispo -= tailles[i]
    blocs = []
    for (titre, texte, _, mode), e, n in zip(sections, entetes, tailles):
        if n == 0 and texte:
            continue  # plus de place : section omise
        blocs.append(e + _couper(texte, n, mode))
    return "\n\n".join(blocs)[:limite]


class MissionArretee(Exception):
    """Arrêt contrôlé du pipeline (kill switch, budget…) avec statut final."""

    def __init__(self, statut: str, message: str):
        super().__init__(message)
        self.statut = statut
        self.message = message


# --- Utilitaires -----------------------------------------------------------------

def _maj_mission(mid: int, **champs) -> None:
    with session_scope() as s:
        m = s.get(Mission, mid)
        for k, v in champs.items():
            setattr(m, k, v)


def _etape(mid: int, agent_id: str, role: str, entree: str, sortie: str, verdict: str | None,
           tokens: int) -> None:
    with session_scope() as s:
        s.add(Etape(mission_id=mid, agent_id=agent_id, role=role, entree=entree[:8000],
                    sortie=(sortie or "")[:16000], verdict=verdict, tokens=tokens))


class Contexte:
    """État d'exécution d'une mission (compteur de tokens, directeur…)."""

    def __init__(self, mission: Mission):
        self.mid = mission.id
        self.titre = mission.titre
        self.consigne = mission.consigne
        self.service = mission.service
        self.montant = mission.montant_eur or 0.0
        self.action = mission.action
        self.directeur: str | None = None
        self.tokens = 0
        self.cout = 0.0
        self.llm = fournisseur()

    def appel(self, agent_id: str, entree: str, temperature: float = 0.3) -> str:
        """Appelle le LLM au nom d'un agent, avec contrôles SENTINEL et BUDGET."""
        a = reg.agent(agent_id)
        cle = sentinel.bloque(self.directeur, agent_id)
        if cle:
            raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
        try:
            budget.verifier_mois(self.llm.nom)
        except budget.BudgetDepasse as e:
            raise MissionArretee("echouee", str(e))
        try:
            # L'entrée est déjà assemblée sous la limite ; garde-fou au cas où.
            r = self.llm.appeler(a["consignes"], entree[:cfg().llm_max_chars], role=a["role"],
                                 temperature=temperature, modele=a.get("modele"))
        except ErreurLLM as e:
            # Étape marquée en erreur, puis arrêt de la mission.
            _etape(self.mid, agent_id, a["role"], entree, str(e), "erreur", 0)
            ledger.journaliser(agent_id, "erreur_llm", self.mid, fournisseur=self.llm.nom, motif=str(e))
            raise MissionArretee("echouee", str(e))
        if r.bascule:
            ledger.journaliser("NEXUS-BUDGET", "bascule_llm", self.mid, agent=agent_id,
                               de=self.llm.nom, vers=r.fournisseur, modele=r.modele, motif=r.bascule)
        cout = budget.enregistrer(r.tokens, r.fournisseur)
        self.tokens += r.tokens
        self.cout += cout
        _maj_mission(self.mid, tokens=self.tokens, cout_eur=round(self.cout, 6))
        _etape(self.mid, agent_id, a["role"], entree, r.texte, None, r.tokens)
        ledger.journaliser(agent_id, f"appel_{a['role']}", self.mid, tokens=r.tokens, cout_eur=cout,
                           fournisseur=r.fournisseur, modele=r.modele)
        try:
            budget.verifier_mission(self.tokens)
        except budget.BudgetDepasse as e:
            raise MissionArretee("echouee", str(e))
        return r.texte


# --- Étapes ----------------------------------------------------------------------

def choisir_service(ctx: Contexte) -> str:
    """PRIME : paramètre explicite, sinon mots-clés, sinon avis du LLM."""
    services = reg.services()
    if ctx.service in services:
        return ctx.service
    texte = gate.normaliser(f"{ctx.titre} {ctx.consigne}")
    # Mots entiers uniquement (« argent » ne contient pas « agent », « rapide » pas « api »).
    scores = {s: sum(1 for m in mots if gate.contient_mot(texte, re.escape(m)))
              for s, mots in MOTS_SERVICES.items()}
    meilleur = max(scores, key=scores.get)
    if scores[meilleur] > 0:
        return meilleur
    prime = reg.par_role("prime")["id"]
    liste = "\n".join(f"- {s}" for s in services)
    rep = ctx.appel(prime, assembler([("Services possibles", liste, 3, "debut"),
                                      ("Mission", ctx.titre, 3, "debut"),
                                      ("Consigne", ctx.consigne, 1, "debut")]))
    for s in services:
        if s.lower() in rep.lower():
            return s
    return "OPS-CORE/projets"


def traiter(mid: int) -> None:
    """Exécute le pipeline complet d'une mission (appelé en tâche de fond)."""
    with session_scope() as s:
        m = s.get(Mission, mid)
        if m is None:
            return
        ctx = Contexte(m)
    try:
        _executer(ctx)
    except MissionArretee as e:
        _maj_mission(mid, statut=e.statut, message=e.message)
        ledger.journaliser("NEXUS-SENTINEL" if e.statut == "suspendue" else "NEXUS-BUDGET"
                           if "Budget" in e.message else "NEXUS-PRIME",
                           f"mission_{e.statut}", mid, motif=e.message)
    except Exception as e:  # filet de sécurité : jamais de mission bloquée « en_cours »
        log.exception("Erreur inattendue mission %s", mid)
        _maj_mission(mid, statut="echouee", message=f"Erreur interne : {e}")
        ledger.journaliser("NEXUS-PRIME", "mission_echouee", mid, motif=str(e))


def _executer(ctx: Contexte) -> None:
    mid = ctx.mid
    # 1. SENTINEL
    cle = sentinel.bloque()
    if cle:
        raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
    _maj_mission(mid, statut="en_cours")
    ledger.journaliser("NEXUS-SENTINEL", "controle_ok", mid)

    # 2. PRIME : service et directeur
    ctx.service = choisir_service(ctx)
    srv = reg.services()[ctx.service]
    ctx.directeur = srv["directeur"]
    _maj_mission(mid, service=ctx.service, directeur=ctx.directeur)
    ledger.journaliser("NEXUS-PRIME", "routage", mid, service=ctx.service, directeur=ctx.directeur)
    cle = sentinel.bloque(ctx.directeur)
    if cle:
        raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")

    # 3. COLLECTOR
    elements = ctx.appel(srv["collector"], assembler([("Mission", ctx.titre, 3, "debut"),
                                                      ("Consigne", ctx.consigne, 2, "debut")]))

    # 4-5. ANALYST ⇄ CHECKER, puis 6-8. GATE et suite
    livrable = ctx.appel(srv["analyst"], _message_analyst(ctx, elements))
    _boucle_qualite(ctx, srv, livrable, elements)


def _message_analyst(ctx: Contexte, elements: str, precedent: str | None = None,
                     problemes: str | None = None, commentaire: str | None = None) -> str:
    sections = [("Mission", ctx.titre, 5, "debut"), ("Consigne", ctx.consigne, 2, "debut"),
                ("Éléments", elements, 1, "debut")]
    if precedent is not None:
        sections.append(("Version précédente", precedent, 3, "tete_queue"))
    if commentaire:
        sections.append(("Révision demandée par le propriétaire (prioritaire)", commentaire, 4, "debut"))
    if problemes:
        sections.append(("Corrige ces problèmes", problemes, 4, "debut"))
    return assembler(sections)


def _boucle_qualite(ctx: Contexte, srv: dict, livrable: str, elements: str) -> None:
    """CHECKER (2 boucles de correction au plus), escalade au directeur, GATE, N3 ou EXECUTOR."""
    mid = ctx.mid
    verdict = {"ok": False, "problemes": []}
    for boucle in range(MAX_BOUCLES_CHECKER + 1):
        livrable = garantir_mention_juridique(ctx.service, livrable)
        # Le CHECKER reçoit toujours le livrable complet ; la consigne est tronquée en premier.
        rep = ctx.appel(srv["checker"], assembler([("Consigne", ctx.consigne, 1, "debut"),
                                                   ("Livrable à vérifier", livrable, 3, "tete_queue")]),
                        temperature=0.0)
        verdict = parser_verdict(rep)
        _etape(mid, srv["checker"], "checker", "verdict", json.dumps(verdict, ensure_ascii=False),
               "ok" if verdict["ok"] else "refus", 0)
        ledger.journaliser(srv["checker"], "verdict", mid, ok=verdict["ok"], problemes=verdict["problemes"])
        if verdict["ok"]:
            break
        if boucle == MAX_BOUCLES_CHECKER:
            escalader(ctx, srv, livrable, verdict)
            return
        probs = "\n".join(f"- {p}" for p in verdict["problemes"]) or "- livrable insuffisant"
        livrable = ctx.appel(srv["analyst"], _message_analyst(ctx, elements, livrable, probs))
    _maj_mission(mid, livrable_texte=livrable)

    # 6. GATE : règles déterministes sur la consigne ET le livrable ; l'avis LLM ne peut que monter
    gate_id = reg.par_role("gate")["id"]
    avis = ctx.appel(gate_id, assembler([
        ("Mission", ctx.titre, 5, "debut"),
        ("Montant et action", f"{ctx.montant} € ; action : {ctx.action or 'aucune'}", 5, "debut"),
        ("Consigne", ctx.consigne, 2, "debut"),
        ("Livrable final", livrable, 3, "tete_queue")]), temperature=0.0)
    niveau, motif = gate.classer(ctx.titre, ctx.consigne, ctx.service, ctx.montant, ctx.action,
                                 parser_niveau(avis), livrable=livrable)
    _maj_mission(mid, niveau=niveau)
    ledger.journaliser(gate_id, "classement", mid, niveau=niveau, motif=motif)

    # 7. N3 → décision humaine ; sinon 8. EXECUTOR
    if niveau == "N3":
        _maj_mission(mid, statut="en_attente_n3", message=motif)
        creer_decision_si_possible(mid, verdict, motif)
    else:
        executer_livrable(mid, srv["executor"])


def escalader(ctx: Contexte, srv: dict, livrable: str, verdict: dict) -> None:
    """3 refus du CHECKER : le directeur de la direction donne son avis, puis la mission échoue."""
    mid = ctx.mid
    directeur = srv["directeur"]
    probs = "\n".join(f"- {p}" for p in verdict["problemes"]) or "- livrable jugé insuffisant"
    avis = ctx.appel(directeur, assembler([
        ("Mission", ctx.titre, 5, "debut"), ("Service", ctx.service or "", 5, "debut"),
        ("Problèmes relevés par le contrôle qualité (3 refus)", probs, 4, "debut"),
        ("Consigne", ctx.consigne, 2, "debut"), ("Dernier livrable", livrable, 3, "tete_queue")]))
    m = re.search(r"DECISION\s*:\s*([A-ZÉ]+)", avis or "", re.I)
    decision = (m.group(1).upper() if m else "REFORMULER")
    c = re.search(r"CONSIGNE\s*:\s*(.+)", avis or "", re.I)
    recommandation = f"{decision}" + (f" — {c.group(1).strip()}" if c else "")
    _maj_mission(mid, statut="echouee", niveau="N2", livrable_texte=livrable,
                 message=(f"Refusé 3 fois par le CHECKER, escalade N2 à {directeur}. "
                          f"Recommandation : {recommandation}")[:1000])
    ledger.journaliser(directeur, "escalade_n2", mid, problemes=verdict["problemes"],
                       recommandation=recommandation)


def relancer_revision(mid: int, commentaire: str | None) -> None:
    """Révision demandée : nouvel ANALYST avec le commentaire, puis CHECKER et GATE."""
    with session_scope() as s:
        m = s.get(Mission, mid)
        if m is None:
            return
        ctx = Contexte(m)
        precedent = m.livrable_texte or ""
    try:
        cle = sentinel.bloque()
        if cle:
            raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
        ctx.service = ctx.service if ctx.service in reg.services() else choisir_service(ctx)
        srv = reg.services()[ctx.service]
        ctx.directeur = srv["directeur"]
        _maj_mission(mid, statut="en_cours", message=f"Révision en cours : {commentaire or '(sans commentaire)'}")
        ledger.journaliser("NEXUS-PRIME", "revision_lancee", mid, commentaire=commentaire)
        livrable = ctx.appel(srv["analyst"], _message_analyst(
            ctx, "", precedent, None, commentaire or "Améliore le livrable."))
        _boucle_qualite(ctx, srv, livrable, "")
    except MissionArretee as e:
        _maj_mission(mid, statut=e.statut, message=e.message)
        ledger.journaliser("NEXUS-PRIME", f"mission_{e.statut}", mid, motif=e.message)
    except Exception as e:
        log.exception("Erreur inattendue pendant la révision de la mission %s", mid)
        _maj_mission(mid, statut="echouee", message=f"Erreur interne : {e}")
        ledger.journaliser("NEXUS-PRIME", "mission_echouee", mid, motif=str(e))


# --- Décisions N3 ------------------------------------------------------------------

def _risque(montant: float, action: str | None, motif: str) -> str:
    if montant >= 1000 or action in ("signer", "supprimer", "donnees_sensibles", "depense"):
        return "eleve"
    if montant > 0 or action or "sensible" in motif:
        return "moyen"
    return "faible"


def decisions_du_jour() -> int:
    debut = maintenant().replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as s:
        return s.execute(select(func.count(Decision.id)).where(Decision.cree_le >= debut)).scalar_one()


def creer_decision_si_possible(mid: int, verdict: dict | None = None, motif: str = "") -> int | None:
    """Crée la fiche N3, ou met la mission en file si le plafond du jour est atteint."""
    c = cfg()
    if decisions_du_jour() >= c.n3_daily_cap:
        msg = (f"Plafond de {c.n3_daily_cap} décisions N3 par jour atteint : mission mise en file, "
               f"la fiche sera créée automatiquement dès que possible.")
        _maj_mission(mid, message=msg)
        ledger.journaliser("NEXUS-GATE", "n3_mise_en_file", mid)
        return None
    with session_scope() as s:
        m = s.get(Mission, mid)
        livrable = (m.livrable_texte or "").strip()
        lignes = [l.strip(" #-*") for l in livrable.splitlines() if l.strip(" #-*")]
        resume = "\n".join([m.titre] + lignes[:2])
        verdict = verdict or {"ok": True, "problemes": []}
        avis = "Conforme" if verdict.get("ok") else "Réserves"
        if verdict.get("problemes"):
            avis += " : " + "; ".join(verdict["problemes"])
        d = Decision(
            mission_id=mid, niveau="N3", resume=resume[:600],
            recommandation=(f"Relire le brouillon puis réaliser l'action manuellement ou via n8n. "
                            f"Motif du classement : {motif or m.message or 'N3'}"),
            cout_estime_eur=float(m.montant_eur or 0) + float(m.cout_eur or 0),
            risque=_risque(m.montant_eur or 0, m.action, motif),
            sources="Éléments fournis dans la consigne (pas d'accès web en mini-version).",
            avis_checker=avis,
        )
        s.add(d)
        s.flush()
        did = d.id
        titre = m.titre
    ledger.journaliser("NEXUS-GATE", "decision_n3_creee", mid, decision_id=did)
    notifier(f"Décision N3 en attente : {titre}", f"Mission #{mid} — à valider dans le cockpit.", mid)
    return did


def traiter_file_n3() -> int:
    """Crée les fiches des missions N3 mises en file, dans la limite du plafond."""
    with session_scope() as s:
        sans_fiche = s.execute(
            select(Mission.id).where(Mission.statut == "en_attente_n3")
            .where(~Mission.id.in_(select(Decision.mission_id))).order_by(Mission.id)
        ).scalars().all()
    n = 0
    for mid in sans_fiche:
        if creer_decision_si_possible(mid) is None:
            break
        n += 1
    return n


def expirer_decisions() -> int:
    """Décisions en attente depuis plus de N3_TIMEOUT_HOURS → expirée = refus par défaut."""
    limite = maintenant() - timedelta(hours=cfg().n3_timeout_hours)
    expirees: list[tuple[int, int]] = []
    with session_scope() as s:
        for d in s.execute(select(Decision).where(Decision.statut == "en_attente")
                           .where(Decision.cree_le < limite)).scalars().all():
            d.statut = "expiree"
            d.decide_le = maintenant()
            d.commentaire = "Expirée sans réponse : refus par défaut."
            m = s.get(Mission, d.mission_id)
            m.statut = "refusee"
            m.message = "Décision N3 expirée : refus par défaut."
            expirees.append((d.id, d.mission_id))
    # Journalisation après validation de la transaction.
    for did, mid in expirees:
        ledger.journaliser("NEXUS-GATE", "decision_expiree", mid, decision_id=did)
    return len(expirees)


def decider(did: int, choix: str, commentaire: str | None) -> dict:
    """Valider / refuser / réviser une décision N3 (action humaine)."""
    statuts = {"valider": "validee", "refuser": "refusee", "reviser": "revision"}
    if choix not in statuts:
        raise ValueError("choix inconnu")
    with session_scope() as s:
        d = s.get(Decision, did)
        if d is None:
            raise LookupError("décision introuvable")
        if d.statut != "en_attente":
            raise PermissionError(f"décision déjà traitée ({d.statut})")
        if choix == "reviser":
            deja = s.execute(select(func.count(Decision.id)).where(Decision.mission_id == d.mission_id)
                             .where(Decision.statut == "revision")).scalar_one()
            if deja >= MAX_REVISIONS:
                raise PermissionError(f"Limite de {MAX_REVISIONS} révisions atteinte pour cette mission : "
                                      "valider ou refuser.")
        d.statut = statuts[choix]
        d.decide_le = maintenant()
        d.commentaire = commentaire
        mid = d.mission_id
        m = s.get(Mission, mid)
        m.statut = statuts[choix]
        if choix == "reviser":
            m.message = f"Révision demandée : {commentaire or '(sans commentaire)'}"
        service = m.service
    ledger.journaliser("DECIDEUR", f"decision_{statuts[choix]}", mid, decision_id=did,
                       commentaire=commentaire)
    if choix == "valider":
        executor = reg.services().get(service, {}).get("executor", "NEXUS-PRIME")
        executer_livrable(mid, executor, statut_final="validee")
    # La relance d'une révision est lancée par l'appelant (tâche de fond) : relancer_revision().
    return {"decision_id": did, "mission_id": mid, "statut": statuts[choix],
            "relance": choix == "reviser"}


# --- EXECUTOR (aucune action externe) -------------------------------------------

def executer_livrable(mid: int, executor_id: str, statut_final: str = "terminee") -> None:
    """Enregistre le livrable final et prépare l'action ; n'exécute rien à l'extérieur."""
    with session_scope() as s:
        m = s.get(Mission, mid)
        projet = m.projet
        contenu = (f"# {m.titre}\n\n- Mission : #{m.id}\n- Projet : {m.projet}\n- Service : {m.service}\n"
                   f"- Niveau : {m.niveau}\n- Action préparée : {m.action or 'aucune'} "
                   f"(à réaliser par un humain ou un workflow n8n)\n\n---\n\n{m.livrable_texte or ''}\n")
    chemin = cfg().data_dir / "livrables" / (projet or "divers") / f"{mid}.md"
    fichier = None
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
        fichier = str(chemin)
    except OSError as e:
        log.warning("Écriture du livrable impossible (%s) : conservé en base uniquement.", e)
    _etape(mid, executor_id, "executor", "livrable final", fichier or "(base uniquement)", "prepare", 0)
    _maj_mission(mid, statut=statut_final,
                 message=f"Livrable enregistré{' : ' + fichier if fichier else ' en base'}. "
                         "Aucune action externe exécutée.")
    ledger.journaliser(executor_id, "livrable_enregistre", mid, fichier=fichier, action_externe=False)


# --- Notification ntfy (best effort) --------------------------------------------

def notifier(titre: str, message: str, mission_id: int | None = None) -> bool:
    """Notification ntfy optionnelle : un échec est journalisé, jamais bloquant."""
    c = cfg()
    if not c.ntfy_url or not c.ntfy_topic:
        ledger.journaliser("NEXUS-GATE", "notification_non_envoyee", mission_id,
                           motif="NTFY_URL ou NTFY_TOPIC vide")
        return False
    try:
        # Titre en ASCII pour l'en-tête HTTP ; le corps reste en UTF-8.
        r = httpx.post(f"{c.ntfy_url}/{c.ntfy_topic}", content=message.encode("utf-8"),
                       headers={"Title": re.sub(r"[^\x20-\x7e]", "", gate.normaliser(titre))[:120],
                                "Priority": "high", "Tags": "warning"}, timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("Notification ntfy impossible : %s", e)
        ledger.journaliser("NEXUS-GATE", "notification_echec", mission_id, erreur=str(e)[:300])
        return False
