"""Pipeline d'une mission : SENTINEL → PRIME → COLLECTOR → ANALYST ⇄ CHECKER → GATE → N3 / EXECUTOR.

Chaque étape est enregistrée (table etapes) et journalisée (LEDGER).
L'EXECUTOR n'effectue AUCUNE action externe : il enregistre le livrable et
prépare l'action pour un humain ou un workflow n8n.
"""
import json
import logging
import re
import time
from datetime import timedelta

import httpx
from sqlalchemy import func, select, update

from . import agents as reg
from . import budget, cyber, decideur, gate, ledger, sentinel
from . import fonctionnement as fct
from .config import cfg
from .db import session_scope
from .llm import (ErreurLLM, FournisseurAnthropic, estimer_tokens, fournisseur_controle_local,
                  fournisseur_niveau, ollama_local_joignable, parser_niveau, parser_verdict)
from .models import Decision, Etape, Mission, maintenant

log = logging.getLogger("nexus.pipeline")

# Le nombre de boucles de correction (refus CHECKER → ANALYST) dépend du niveau de
# fonctionnement (revisions_max de fonctionnement.yaml : F1 0, F2 1, F3 2, F4 3).
MAX_REVISIONS = 2         # « Demander une révision » (propriétaire) : 2 fois au plus par mission
_horloge = time.monotonic  # remplaçable dans les tests (chrono des missions)
MARQUE = "\n[… tronqué …]\n"

# Classement PRIME par mots-clés (texte normalisé, sans accents).
MOTS_SERVICES = {
    "LEX-GUARD/conformite": ["rgpd", "ai act", "conformite", "cgv", "cgu", "mentions legales", "juridique"],
    "REVENUE-CORE/propositions": ["devis", "proposition commerciale", "offre", "tarif", "prospect", "client"],
    "CONTENT-ARENA/redaction": ["article", "post", "newsletter", "redige un texte", "blog", "linkedin"],
    # « code » seul retiré (« code du travail », « code civil »…) : expressions explicites uniquement.
    "CODE-CORE/revue": ["code source", "ce code", "mon code", "le code python", "extrait de code", "python",
                        "javascript", "typescript", "bug", "spec", "api", "revue de code", "relecture de code"],
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
    # CYBER-FORTRESS (mots entiers ; « rgpd » seul reste sur LEX-GUARD/conformite).
    "CYBER-FORTRESS/audit": ["cybersecurite", "cyber securite", "securite informatique", "securite",
                             "audit de securite", "revue de securite", "securite du code", "durcissement",
                             "owasp", "asvs", "anssi", "cis", "pare-feu", "firewall", "ufw", "ssh", "fail2ban",
                             "test d'intrusion"],
    "CYBER-FORTRESS/veille": ["cve", "vulnerabilite", "vulnerabilites", "cert-fr", "faille", "failles",
                              "avis de securite", "correctif de securite", "correctifs de securite",
                              "mise a jour de securite", "mises a jour de securite"],
    "CYBER-FORTRESS/conformite": ["nis2", "nis 2", "article 32", "art. 32", "notification a la cnil",
                                  "notifier la cnil", "72 h", "72 heures", "politique de mots de passe",
                                  "politique de mot de passe", "3-2-1", "pca", "pra", "plan de continuite",
                                  "plan de reprise"],
    "CYBER-FORTRESS/incident": ["incident de securite", "intrusion", "piratage", "pirate", "phishing",
                                "hameconnage", "ransomware", "rancongiciel", "compromission", "compromis",
                                "fuite de donnees", "rotation des cles", "rotation des jetons",
                                "reponse a incident"],
}
MENTION_AVOCAT = "Information générale, ne remplace pas l'avis d'un avocat"

# Départage PRIME en cas d'égalité de score (si le LLM PRIME ne tranche pas) : du plus prudent
# (droit, sécurité, finances) au plus général. Un service absent de la liste passe après.
PRIORITE_SERVICES = [
    "LEX-GUARD/droit-france", "LEX-GUARD/droit-europe", "LEX-GUARD/droit-international", "LEX-GUARD/conformite",
    "CYBER-FORTRESS/incident", "CYBER-FORTRESS/conformite", "CYBER-FORTRESS/audit", "CYBER-FORTRESS/veille",
    "PILOT-CORE/etudes", "PILOT-CORE/pilotage", "REVENUE-CORE/propositions", "GREEN-CORE/rse",
    "GREEN-CORE/environnement", "CODE-CORE/conception", "CODE-CORE/revue", "DESIGN-SYSTEM/ui",
    "R&D-PARADOX/veille", "CONTENT-ARENA/redaction", "AGENT-FACTORY/evaluation", "OPS-CORE/projets",
]


def scores_services(titre: str, consigne: str) -> dict[str, int]:
    """Score PRIME : somme, pour chaque expression trouvée en mots entiers, de son nombre de mots."""
    texte = gate.normaliser(f"{titre} {consigne}")
    return {s: sum(len(m.split()) for m in mots if gate.contient_mot(texte, re.escape(m)))
            for s, mots in MOTS_SERVICES.items()}


def _priorite(service: str) -> int:
    return PRIORITE_SERVICES.index(service) if service in PRIORITE_SERVICES else len(PRIORITE_SERVICES)


def garantir_mention_juridique(service: str | None, livrable: str) -> str:
    """Tout service LEX-GUARD/ (conformité incluse) : la mention finale est ajoutée si le modèle l'a oubliée."""
    if not (service or "").startswith("LEX-GUARD/"):
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


class PlafondAtteint(MissionArretee):
    """Plafond du niveau de fonctionnement atteint (délai, tokens ou coût) : arrêt propre."""

    def __init__(self, nature: str, message: str):
        super().__init__("plafond_atteint", message)
        self.nature = nature


# --- Utilitaires -----------------------------------------------------------------

def _maj_mission(mid: int, **champs) -> None:
    with session_scope() as s:
        m = s.get(Mission, mid)
        for k, v in champs.items():
            setattr(m, k, v)


def transition(mid: int, depuis: tuple[str, ...], vers: str, **champs) -> bool:
    """Change le statut d'une mission seulement s'il vaut encore l'un de `depuis` (atomique).

    `UPDATE missions SET statut=… WHERE id=? AND statut IN (…)` : deux traitements concurrents
    ne peuvent pas faire la même transition ; renvoie False si la mission a déjà changé.
    """
    with session_scope() as s:
        r = s.execute(update(Mission).where(Mission.id == mid, Mission.statut.in_(depuis))
                      .values(statut=vers, maj_le=maintenant(), **champs))
        return r.rowcount == 1


def _etape(mid: int, agent_id: str, role: str, entree: str, sortie: str, verdict: str | None,
           tokens: int) -> None:
    with session_scope() as s:
        s.add(Etape(mission_id=mid, agent_id=agent_id, role=role, entree=entree[:8000],
                    sortie=(sortie or "")[:16000], verdict=verdict, tokens=tokens))


class Contexte:
    """État d'exécution d'une mission : niveau de fonctionnement, chrono, compteurs."""

    def __init__(self, mission: Mission):
        self.mid = mission.id
        self.titre = mission.titre
        self.consigne = mission.consigne
        self.service = mission.service
        self.montant = mission.montant_eur or 0.0
        self.action = mission.action
        self.repli_f3 = bool(mission.repli_f3) if mission.repli_f3 is not None else True
        self.directeur: str | None = None
        # Totaux déjà enregistrés pour la mission (cas d'une relance après révision).
        self.base = {"tokens": mission.tokens or 0, "cout": mission.cout_eur or 0.0,
                     "entree": mission.tokens_entree or 0, "sortie": mission.tokens_sortie or 0,
                     "duree": mission.duree_s or 0.0, "revisions": mission.revisions or 0}
        # Compteurs de cette exécution (plafonds appliqués par exécution).
        self.tokens = 0
        self.cout = 0.0
        self.entree = 0
        self.sortie = 0
        self.revisions = 0
        self.debut = _horloge()
        self.livrable_partiel: str | None = mission.livrable_texte
        self.relancer = False  # positionné par escalader() : relance automatique demandée
        self.f = fct.niveau(mission.fonctionnement or fct.defaut())
        self._instancier()

    def _instancier(self) -> None:
        self.llm = fournisseur_niveau(self.f.fournisseur, self.f.num_ctx)
        self.controle = fournisseur_controle_local(self.f.num_ctx) if self.f.double_controle else None

    @property
    def max_chars(self) -> int:
        return self.f.llm_max_chars

    def ecoule(self) -> float:
        return _horloge() - self.debut

    def relever(self, code: str, raison: str) -> bool:
        """Monte le niveau de fonctionnement (jamais de descente) ; trace la raison."""
        if fct.rang(code) <= fct.rang(self.f.code):
            return False
        ancien = self.f.code
        self.f = fct.niveau(code)
        self._instancier()
        with session_scope() as s:
            m = s.get(Mission, self.mid)
            m.fonctionnement = code
            m.fonctionnement_raison = "; ".join(x for x in (m.fonctionnement_raison, raison) if x)
        ledger.journaliser("NEXUS-PRIME", "fonctionnement_releve", self.mid, de=ancien, vers=code, raison=raison)
        return True

    # --- Plafonds -------------------------------------------------------------
    def _verifier_delai(self) -> None:
        if self.ecoule() > self.f.delai_max_s:
            raise PlafondAtteint("delai", f"Délai maximal du niveau {self.f.code} atteint "
                                          f"({self.f.delai_max_s:.0f} s).")

    def _cout_appel(self, modele: str | None, entree: int, sortie: int, fournisseur_nom: str) -> float:
        if self.f.code == "F4":
            return fct.cout_appel_eur(modele, entree, sortie)
        return budget.cout_eur(entree + sortie, fournisseur_nom)

    def appel(self, agent_id: str, entree: str, temperature: float = 0.3, controle_local: bool = False,
              tolerer_erreur: bool = False) -> str | None:
        """Appelle le LLM au nom d'un agent, avec SENTINEL, plafonds du niveau et BUDGET."""
        a = reg.agent(agent_id)
        if not reg.appelle_llm(a):
            raise ValueError(f"{agent_id} est un agent déterministe : il n'appelle jamais de modèle.")
        cle = sentinel.bloque(self.directeur, agent_id)
        if cle:
            raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
        self._verifier_delai()
        llm = self.controle if controle_local else self.llm
        modele = (self.f.modele_role(a["role"]) if (self.f.code == "F4" and not controle_local)
                  else a.get("modele"))
        message = entree[:self.f.llm_max_chars]  # garde-fou : l'entrée est déjà assemblée
        if self.f.cout_max_eur > 0:
            # Coût maximal possible de cet appel (entrée estimée + sortie maximale) : jamais de dépassement.
            prevu = self._cout_appel(modele, estimer_tokens(a["consignes"] + message),
                                     FournisseurAnthropic.MAX_TOKENS_SORTIE, llm.nom)
            if self.cout + prevu > self.f.cout_max_eur:
                raise PlafondAtteint("cout", f"Coût maximal du niveau {self.f.code} atteint : "
                                             f"{self.cout:.4f} € dépensés, prochain appel jusqu'à {prevu:.4f} €, "
                                             f"plafond {self.f.cout_max_eur:.2f} €.")
        try:
            budget.verifier_mois(llm.nom)
        except budget.BudgetDepasse as e:
            raise MissionArretee("echouee", str(e))
        restant = self.f.delai_max_s - self.ecoule()
        try:
            r = llm.appeler(a["consignes"], message, role=a["role"], temperature=temperature, modele=modele,
                            timeout=max(5.0, min(cfg().llm_timeout_s, restant)))
        except ErreurLLM as e:
            _etape(self.mid, agent_id, a["role"], entree, str(e), "erreur", 0)
            ledger.journaliser(agent_id, "erreur_llm", self.mid, fournisseur=llm.nom, motif=str(e))
            if tolerer_erreur:
                return None
            raise MissionArretee("echouee", str(e))
        if r.bascule:
            ledger.journaliser("NEXUS-BUDGET", "bascule_llm", self.mid, agent=agent_id,
                               de=llm.nom, vers=r.fournisseur, modele=r.modele, motif=r.bascule)
        cout = self._cout_appel(r.modele or modele, r.tokens_entree, r.tokens_sortie, r.fournisseur)
        budget.enregistrer(r.tokens, r.fournisseur, cout=cout)
        self.tokens += r.tokens
        self.entree += r.tokens_entree
        self.sortie += r.tokens_sortie
        self.cout += cout
        self.enregistrer_compteurs()
        sortie = cyber.masquer(r.texte) if cyber.concerne(self.service) else r.texte  # jamais de secret stocké
        _etape(self.mid, agent_id, a["role"] + ("_local" if controle_local else ""), entree, sortie, None,
               r.tokens)
        ledger.journaliser(agent_id, f"appel_{a['role']}", self.mid, tokens=r.tokens,
                           tokens_entree=r.tokens_entree, tokens_sortie=r.tokens_sortie, cout_eur=cout,
                           fournisseur=r.fournisseur, modele=r.modele or modele, fonctionnement=self.f.code,
                           double_controle=controle_local)
        if self.tokens > self.f.budget_tokens:
            raise PlafondAtteint("tokens", f"Budget de tokens du niveau {self.f.code} dépassé : "
                                           f"{self.tokens} > {self.f.budget_tokens}.")
        if self.f.cout_max_eur > 0 and self.cout > self.f.cout_max_eur:
            raise PlafondAtteint("cout", f"Coût maximal du niveau {self.f.code} dépassé : "
                                         f"{self.cout:.4f} € > {self.f.cout_max_eur:.2f} €.")
        self._verifier_delai()
        return r.texte

    def enregistrer_compteurs(self, final: bool = False) -> None:
        champs = dict(tokens=self.base["tokens"] + self.tokens,
                      cout_eur=round(self.base["cout"] + self.cout, 6),
                      tokens_entree=self.base["entree"] + self.entree,
                      tokens_sortie=self.base["sortie"] + self.sortie,
                      revisions=self.base["revisions"] + self.revisions)
        if final:
            champs["duree_s"] = round(self.base["duree"] + self.ecoule(), 3)
        _maj_mission(self.mid, **champs)


# --- Étapes ----------------------------------------------------------------------

def choisir_service(ctx: Contexte) -> str:
    """PRIME : paramètre explicite, sinon mots-clés, sinon avis du LLM."""
    services = reg.services()
    if ctx.service in services:
        return ctx.service
    # Mots entiers, score pondéré par le nombre de mots de l'expression (« code du travail » = 3).
    scores = scores_services(ctx.titre, ctx.consigne)
    haut = max(scores.values())
    if haut > 0:
        ex_aequo = sorted((s for s, v in scores.items() if v == haut), key=_priorite)
        if len(ex_aequo) == 1:
            return ex_aequo[0]
        return _departager(ctx, ex_aequo)
    prime = reg.par_role("prime")["id"]
    liste = "\n".join(f"- {s}" for s in services)
    rep = ctx.appel(prime, assembler([("Services possibles", liste, 3, "debut"),
                                      ("Mission", ctx.titre, 3, "debut"),
                                      ("Consigne", ctx.consigne, 1, "debut")], ctx.max_chars))
    for s in services:
        if s.lower() in rep.lower():
            return s
    return "OPS-CORE/projets"


def _proposition(ctx: Contexte) -> str:
    sup = fct.suivant(ctx.f.code)
    if sup:
        return f"Proposition : relancer la mission au niveau supérieur ({sup})."
    return "Proposition : relancer en F4 après avoir relevé le plafond dans fonctionnement.yaml."


def _terminer_arret(ctx: Contexte, e: MissionArretee) -> None:
    """Statut final d'un arrêt contrôlé ; plafond → livrable partiel conservé + proposition."""
    mid = ctx.mid
    if isinstance(e, PlafondAtteint):
        message = f"Plafond atteint — {e.message} Livrable partiel conservé. {_proposition(ctx)}"
        champs = {"statut": "plafond_atteint", "message": message[:1000]}
        if ctx.livrable_partiel:
            champs["livrable_texte"] = ctx.livrable_partiel
        _maj_mission(mid, **champs)
        ledger.journaliser("NEXUS-BUDGET", "plafond_atteint", mid, nature=e.nature, fonctionnement=ctx.f.code,
                           motif=e.message, proposition=_proposition(ctx))
        return
    _maj_mission(mid, statut=e.statut, message=e.message)
    ledger.journaliser("NEXUS-SENTINEL" if e.statut == "suspendue" else "NEXUS-BUDGET"
                       if "Budget" in e.message or "budget" in e.message else "NEXUS-PRIME",
                       f"mission_{e.statut}", mid, motif=e.message)


def _bilan(ctx: Contexte) -> None:
    """Mesures finales de l'exécution : durée, tokens, coût, révisions (mission + LEDGER)."""
    ctx.enregistrer_compteurs(final=True)
    with session_scope() as s:
        m = s.get(Mission, ctx.mid)
        bilan = dict(statut=m.statut, fonctionnement_demande=m.fonctionnement_demande,
                     fonctionnement=m.fonctionnement, raison=m.fonctionnement_raison,
                     tokens_entree=m.tokens_entree, tokens_sortie=m.tokens_sortie,
                     cout_eur=m.cout_eur, duree_s=m.duree_s, revisions=m.revisions)
    ledger.journaliser("NEXUS-BUDGET", "mission_bilan", ctx.mid, **bilan)


def _executer_protege(ctx: Contexte, fonction, *args) -> None:
    try:
        fonction(ctx, *args)
    except MissionArretee as e:
        _terminer_arret(ctx, e)
    except Exception as e:  # filet de sécurité : jamais de mission bloquée « en_cours »
        log.exception("Erreur inattendue mission %s", ctx.mid)
        _maj_mission(ctx.mid, statut="echouee", message=f"Erreur interne : {e}")
        ledger.journaliser("NEXUS-PRIME", "mission_echouee", ctx.mid, motif=str(e))
    finally:
        _bilan(ctx)


def _departager(ctx: Contexte, candidats: list[str]) -> str:
    """Égalité : avis du LLM PRIME limité aux candidats ; sinon (LLM absent ou hors liste) priorité explicite."""
    prime = reg.par_role("prime")["id"]
    rep = ctx.appel(prime, assembler([("Services possibles (à égalité)", "\n".join(f"- {s}" for s in candidats), 3,
                                       "debut"), ("Mission", ctx.titre, 3, "debut"),
                                      ("Consigne", ctx.consigne, 1, "debut")], ctx.max_chars),
                    temperature=0.0, tolerer_erreur=True)
    choisi = next((s for s in candidats if rep and s.lower() in rep.lower()), None)
    ledger.journaliser(prime, "routage_departage", ctx.mid, candidats=candidats,
                       choisi=choisi or candidats[0], par="llm" if choisi else "priorite")
    return choisi or candidats[0]


def traiter(mid: int) -> None:
    """Exécute le pipeline complet d'une mission (appelé en tâche de fond)."""
    # Prise atomique : une mission n'est traitée qu'une fois, même si elle est soumise deux fois.
    if not transition(mid, ("recue", "en_attente_place"), "en_cours", attente=None):
        ledger.journaliser("NEXUS-PRIME", "mission_deja_prise", mid)
        return
    with session_scope() as s:
        m = s.get(Mission, mid)
        ctx = Contexte(m)
    _executer_protege(ctx, _executer)
    if ctx.relancer:  # décision RELANCER du directeur : nouvelle exécution, dans la même place de file
        traiter(mid)


def _verifier_f4_au_lancement(ctx: Contexte) -> None:
    """F4 : revérifie budget et clé au démarrage (ils ont pu changer depuis l'accord)."""
    if ctx.f.code != "F4":
        return
    raison = fct.disponibilite_f4()
    if raison is None:
        return
    if not ctx.repli_f3:
        raise MissionArretee("refusee", f"F4 indisponible : {raison}. Mission non lancée (repli F3 non autorisé).")
    message = f"F4 indisponible : {raison} — mission lancée en F3"
    ctx.f = fct.niveau("F3")
    ctx._instancier()
    with session_scope() as s:
        m = s.get(Mission, ctx.mid)
        m.fonctionnement = "F3"
        m.fonctionnement_raison = message
    ledger.journaliser("NEXUS-BUDGET", "fonctionnement_repli_f3", ctx.mid, raison=raison)


def appliquer_planchers(ctx: Contexte) -> None:
    """Planchers automatiques (le niveau ne fait que monter) : service, puis pré-classement GATE."""
    srv = ctx.service or ""
    if srv.startswith("LEX-GUARD/droit-") or srv.startswith("PILOT-CORE/") or cyber.concerne(srv):
        ctx.relever("F3", f"service {srv} : niveau minimum F3")
    niveau_regles, motif = gate.classer_regles(ctx.titre, ctx.consigne, ctx.service, ctx.montant, ctx.action)
    if niveau_regles in ("N2", "N3"):
        ctx.relever("F2", f"pré-classement GATE {niveau_regles} ({motif}) : F1 relevé en F2")


def _executer(ctx: Contexte) -> None:
    mid = ctx.mid
    # 1. SENTINEL
    cle = sentinel.bloque()
    if cle:
        raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
    _verifier_f4_au_lancement(ctx)
    if ctx.f.fournisseur == "ollama_local" and cfg().llm_provider != "fake" and not ollama_local_joignable():
        # Installation sans IA locale (option --sans-repli) : F1 est impossible, on monte en F2.
        ctx.relever("F2", "IA locale injoignable : F1 relevé en F2")
    _maj_mission(mid, statut="en_cours", attente=None)
    ledger.journaliser("NEXUS-SENTINEL", "controle_ok", mid)
    ledger.journaliser("NEXUS-PRIME", "fonctionnement_applique", mid, fonctionnement=ctx.f.code,
                       budget_tokens=ctx.f.budget_tokens, revisions_max=ctx.f.revisions_max,
                       double_controle=ctx.f.double_controle, delai_max_s=ctx.f.delai_max_s,
                       cout_max_eur=ctx.f.cout_max_eur)

    # 2. PRIME : service et directeur, puis planchers de fonctionnement
    ctx.service = choisir_service(ctx)
    srv = reg.services()[ctx.service]
    ctx.directeur = srv["directeur"]
    _maj_mission(mid, service=ctx.service, directeur=ctx.directeur)
    ledger.journaliser("NEXUS-PRIME", "routage", mid, service=ctx.service, directeur=ctx.directeur)
    cle = sentinel.bloque(ctx.directeur)
    if cle:
        raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
    appliquer_planchers(ctx)

    # 3. COLLECTOR
    elements = ctx.appel(srv["collector"], assembler([("Mission", ctx.titre, 3, "debut"),
                                                      ("Consigne", ctx.consigne, 2, "debut")], ctx.max_chars))

    # 4-5. ANALYST ⇄ CHECKER, puis 6-8. GATE et suite
    livrable = ctx.appel(srv["analyst"], _message_analyst(ctx, elements))
    ctx.livrable_partiel = livrable
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
    return assembler(sections, ctx.max_chars)


def _controler(ctx: Contexte, srv: dict, livrable: str) -> dict:
    """CHECKER principal, puis (F3/F4) double contrôle par le modèle local : les deux doivent valider."""
    mid = ctx.mid
    if cyber.concerne(ctx.service):
        # CYBER-FORTRESS : secret ou action offensive → refus déterministe, sans dépendre du modèle.
        refus = cyber.verdict_garde_fou(livrable)
        if refus:
            _etape(mid, srv["checker"], "checker", "garde-fou cybersécurité",
                   json.dumps(refus, ensure_ascii=False), "refus", 0)
            ledger.journaliser(srv["checker"], "verdict", mid, ok=False, problemes=refus["problemes"],
                               source="garde_fou_cyber")
            return refus
    message = assembler([("Consigne", ctx.consigne, 1, "debut"),
                         ("Livrable à vérifier", livrable, 3, "tete_queue")], ctx.max_chars)
    verdict = parser_verdict(ctx.appel(srv["checker"], message, temperature=0.0))
    _etape(mid, srv["checker"], "checker", "verdict", json.dumps(verdict, ensure_ascii=False),
           "ok" if verdict["ok"] else "refus", 0)
    ledger.journaliser(srv["checker"], "verdict", mid, ok=verdict["ok"], problemes=verdict["problemes"])
    if not verdict["ok"] or not ctx.f.double_controle:
        return verdict
    rep = ctx.appel(srv["checker"], message, temperature=0.0, controle_local=True, tolerer_erreur=True)
    if rep is None:
        # Modèle local injoignable : le double contrôle n'a pas eu lieu ; c'est tracé, jamais silencieux.
        ledger.journaliser(srv["checker"], "double_controle_indisponible", mid, fonctionnement=ctx.f.code)
        _maj_mission(mid, message="Double contrôle indisponible (modèle local injoignable) : "
                                  "seul le CHECKER principal a validé.")
        return verdict
    second = parser_verdict(rep)
    _etape(mid, srv["checker"], "checker_local", "double contrôle", json.dumps(second, ensure_ascii=False),
           "ok" if second["ok"] else "refus", 0)
    ledger.journaliser(srv["checker"], "verdict_double_controle", mid, ok=second["ok"],
                       problemes=second["problemes"])
    if second["ok"]:
        return verdict
    return {"ok": False, "problemes": [f"[double contrôle] {p}" for p in second["problemes"]]
            or ["[double contrôle] livrable refusé par le second contrôleur"]}


def _boucle_qualite(ctx: Contexte, srv: dict, livrable: str, elements: str) -> None:
    """CHECKER (revisions_max boucles selon le niveau), escalade au directeur, GATE, N3 ou EXECUTOR."""
    mid = ctx.mid
    refus = 0
    while True:
        livrable = garantir_mention_juridique(ctx.service, livrable)
        brut = livrable
        if cyber.concerne(ctx.service):
            livrable = cyber.masquer(livrable)  # le secret n'est ni stocké ni renvoyé à l'ANALYST
        ctx.livrable_partiel = livrable
        verdict = _controler(ctx, srv, brut)
        if verdict["ok"]:
            break
        refus += 1
        if ctx.revisions >= ctx.f.revisions_max:
            escalader(ctx, srv, livrable, verdict, refus)
            return
        ctx.revisions += 1
        probs = "\n".join(f"- {p}" for p in verdict["problemes"]) or "- livrable insuffisant"
        livrable = ctx.appel(srv["analyst"], _message_analyst(ctx, elements, livrable, probs))
    _maj_mission(mid, livrable_texte=livrable)

    # 6. GATE : règles déterministes sur la consigne ET le livrable ; l'avis LLM ne peut que monter
    gate_id = reg.par_role("gate")["id"]
    avis = ctx.appel(gate_id, assembler([
        ("Mission", ctx.titre, 5, "debut"),
        ("Montant et action", f"{ctx.montant} € ; action : {ctx.action or 'aucune'}", 5, "debut"),
        ("Consigne", ctx.consigne, 2, "debut"),
        ("Livrable final", livrable, 3, "tete_queue")], ctx.max_chars), temperature=0.0)
    niveau, motif = gate.classer(ctx.titre, ctx.consigne, ctx.service, ctx.montant, ctx.action,
                                 parser_niveau(avis), livrable=livrable)
    _maj_mission(mid, niveau=niveau)
    ledger.journaliser(gate_id, "classement", mid, niveau=niveau, motif=motif)

    # Plancher F2 pour un livrable N2+ : relèvement puis nouveau passage qualité au niveau F2.
    if niveau in ("N2", "N3") and ctx.relever("F2", f"GATE {niveau} sur le livrable : F1 relevé en F2"):
        _boucle_qualite(ctx, srv, livrable, elements)
        return

    # 7. N3 → décision humaine ; sinon 8. EXECUTOR
    if niveau == "N3":
        _maj_mission(mid, statut="en_attente_n3", message=motif)
        creer_decision_si_possible(mid, verdict, motif)
    else:
        executer_livrable(mid, srv["executor"])


def escalader(ctx: Contexte, srv: dict, livrable: str, verdict: dict, refus: int = 0) -> None:
    """Refus au-delà des corrections permises : le directeur décide.

    RELANCER → une seule relance automatique (niveau de fonctionnement +1 si possible, jamais F4
    sans accord) ; REFORMULER → statut « a_reformuler » avec sa suggestion ; sinon → échouée.
    """
    mid = ctx.mid
    directeur = srv["directeur"]
    probs = "\n".join(f"- {p}" for p in verdict["problemes"]) or "- livrable jugé insuffisant"
    avis = ctx.appel(directeur, assembler([
        ("Mission", ctx.titre, 5, "debut"), ("Service", ctx.service or "", 5, "debut"),
        (f"Problèmes relevés par le contrôle qualité ({refus} refus)", probs, 4, "debut"),
        ("Consigne", ctx.consigne, 2, "debut"), ("Dernier livrable", livrable, 3, "tete_queue")], ctx.max_chars))
    m = re.search(r"DECISION\s*:\s*([A-ZÉ]+)", avis or "", re.I)
    decision = m.group(1).upper() if m else "INCONNUE"
    c = re.search(r"CONSIGNE\s*:\s*(.+)", avis or "", re.I)
    suggestion = c.group(1).strip()[:500] if c else ""
    recommandation = decision + (f" — {suggestion}" if suggestion else "")
    entete = (f"Refusé {refus} fois par le CHECKER (niveau {ctx.f.code} : {ctx.f.revisions_max} correction(s) "
              f"permise(s)), escalade N2 à {directeur}. ")
    ledger.journaliser(directeur, "escalade_n2", mid, problemes=verdict["problemes"], recommandation=recommandation)
    with session_scope() as s:
        deja_relancee = bool(s.get(Mission, mid).relance_auto)
    if decision == "RELANCER" and not deja_relancee:
        sup = fct.suivant(ctx.f.code)
        cible = sup if sup in ("F2", "F3") else ctx.f.code  # F4 payant : jamais sans accord du propriétaire
        if cible != ctx.f.code:
            ctx.relever(cible, f"relance automatique demandée par {directeur}")
        with session_scope() as s:
            mm = s.get(Mission, mid)
            if suggestion:
                mm.consigne = f"{mm.consigne}\n\nIndication du directeur pour la relance : {suggestion}"
            mm.relance_auto = 1
            mm.niveau = None
            mm.livrable_texte = livrable
        transition(mid, ("en_cours",), "recue",
                   message=(entete + f"Relance automatique unique en {cible}" +
                            (f" avec l'indication : {suggestion}" if suggestion else "") + ".")[:1000])
        ledger.journaliser(directeur, "relance_automatique", mid, fonctionnement=cible, indication=suggestion)
        ctx.relancer = True
        return
    if decision == "RELANCER":
        statut, fin = "echouee", "Relance automatique déjà effectuée : mission échouée, à reprendre manuellement."
    elif decision == "REFORMULER":
        statut, fin = "a_reformuler", ("À reformuler. Suggestion du directeur : "
                                       f"{suggestion or 'préciser la consigne et les éléments fournis'}.")
    else:
        statut, fin = "echouee", f"Décision du directeur : {recommandation}."
    _maj_mission(mid, statut=statut, niveau="N2", livrable_texte=livrable, message=(entete + fin)[:1000])


def relancer_revision(mid: int, commentaire: str | None) -> None:
    """Révision demandée : nouvel ANALYST avec le commentaire, puis CHECKER et GATE."""
    if not transition(mid, ("revision",), "en_cours"):
        ledger.journaliser("NEXUS-PRIME", "mission_deja_prise", mid)
        return
    with session_scope() as s:
        m = s.get(Mission, mid)
        if m is None:
            return
        ctx = Contexte(m)
        precedent = m.livrable_texte or ""
    _executer_protege(ctx, _reviser, precedent, commentaire)
    if ctx.relancer:
        traiter(mid)


def _reviser(ctx: Contexte, precedent: str, commentaire: str | None) -> None:
    mid = ctx.mid
    cle = sentinel.bloque()
    if cle:
        raise MissionArretee("suspendue", f"Arrêt d'urgence actif ({cle}).")
    ctx.service = ctx.service if ctx.service in reg.services() else choisir_service(ctx)
    srv = reg.services()[ctx.service]
    ctx.directeur = srv["directeur"]
    _maj_mission(mid, statut="en_cours", message=f"Révision en cours : {commentaire or '(sans commentaire)'}")
    ledger.journaliser("NEXUS-PRIME", "revision_lancee", mid, commentaire=commentaire, fonctionnement=ctx.f.code)
    livrable = ctx.appel(srv["analyst"], _message_analyst(
        ctx, "", precedent, None, commentaire or "Améliore le livrable."))
    _boucle_qualite(ctx, srv, livrable, "")


# --- Reprise au démarrage ------------------------------------------------------------

def reprendre_au_demarrage() -> dict:
    """Après un redémarrage : missions « en_cours » interrompues → échouées (relance proposée) ;
    missions « recue » / « en_attente_place » → remises dans la file, dans l'ordre d'arrivée."""
    from .file_missions import FILE
    with session_scope() as s:
        interrompues = s.execute(select(Mission.id).where(Mission.statut == "en_cours")
                                 .order_by(Mission.id)).scalars().all()
        en_file = s.execute(select(Mission.id).where(Mission.statut.in_(("recue", "en_attente_place")))
                            .order_by(Mission.id)).scalars().all()
    for mid in interrompues:
        if transition(mid, ("en_cours",), "echouee",
                      message="Échouée : interrompue par un redémarrage de nexus-core. "
                              "Proposition : relancer la mission (créer une nouvelle mission avec la même consigne)."):
            ledger.journaliser("NEXUS-PRIME", "mission_interrompue_redemarrage", mid,
                               proposition="relancer la mission")
    for mid in en_file:
        transition(mid, ("en_attente_place",), "recue")
        ledger.journaliser("NEXUS-PRIME", "mission_reprise_redemarrage", mid)
        FILE.soumettre(mid, traiter)
    return {"interrompues": list(interrompues), "relancees": list(en_file)}


# --- Décisions N3 ------------------------------------------------------------------

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
        risque, raisons = decideur.risque_mission(m)  # règles explicables (montant, tiers, production…)
        avis = "Conforme" if verdict.get("ok") else "Réserves"
        if verdict.get("problemes"):
            avis += " : " + "; ".join(verdict["problemes"])
        d = Decision(
            mission_id=mid, niveau="N3", resume=resume[:600],
            recommandation=(f"Relire le brouillon puis réaliser l'action manuellement ou via n8n. "
                            f"Motif du classement : {motif or m.message or 'N3'}"),
            cout_estime_eur=float(m.montant_eur or 0) + float(m.cout_eur or 0),
            risque=risque, risque_raisons=json.dumps(raisons, ensure_ascii=False),
            sources="Éléments fournis dans la consigne (pas d'accès web en mini-version).",
            avis_checker=avis,
        )
        s.add(d)
        s.flush()
        did = d.id
        titre = m.titre
    ledger.journaliser("NEXUS-GATE", "decision_n3_creee", mid, decision_id=did, risque=risque)
    decideur.nouvelle_decision(did)  # notification groupée par session (immédiate si urgente)
    return did


def traiter_file_n3() -> int:
    """Crée les fiches des missions N3 mises en file, dans la limite du plafond."""
    with session_scope() as s:
        sans_fiche = s.execute(
            select(Mission.id, Mission.attente).where(Mission.statut == "en_attente_n3")
            .where(~Mission.id.in_(select(Decision.mission_id).where(Decision.statut == "en_attente")))
            .order_by(Mission.id)
        ).all()
    n = 0
    for mid, attente in sans_fiche:
        cree = (creer_decision_lancement_f4(mid) if attente == "lancement_f4"
                else creer_decision_si_possible(mid))
        if cree is None:
            break
        n += 1
    return n


def creer_decision_lancement_f4(mid: int) -> int | None:
    """Décision N3 « Lancer en F4 — coût estimé X € » : la mission ne démarre qu'après accord."""
    c = cfg()
    est = fct.estimer_cout_eur("F4")
    if decisions_du_jour() >= c.n3_daily_cap:
        _maj_mission(mid, message=(f"Plafond de {c.n3_daily_cap} décisions N3 par jour atteint : la demande "
                                   "de lancement F4 sera présentée dès que possible."))
        ledger.journaliser("NEXUS-GATE", "n3_mise_en_file", mid, objet="lancement_f4")
        return None
    with session_scope() as s:
        m = s.get(Mission, mid)
        n4 = fct.niveau("F4")
        risque, raisons = decideur.risque_mission(m, "lancement_f4", est["cout_estime_eur"])
        d = Decision(
            mission_id=mid, niveau="N3", objet="lancement_f4",
            resume=(f"Lancer en F4 — coût estimé {est['cout_estime_eur']:.2f} €\n{m.titre}\n"
                    f"Plafonds : {n4.budget_tokens} tokens, {n4.cout_max_eur:.2f} €, {n4.delai_max_s:.0f} s.")[:600],
            recommandation=("Valider pour lancer la mission avec les modèles Anthropic (payant). "
                            "Refuser pour l'abandonner ; relancer en F3 (gratuit) si besoin."),
            cout_estime_eur=est["cout_estime_eur"], risque=risque,
            risque_raisons=json.dumps(raisons, ensure_ascii=False),
            sources=(f"Estimation : {est['tokens_prevus']} tokens au tarif du modèle le plus cher, "
                     f"1 $ = {est['eur_par_usd']} € (fonctionnement.yaml)."),
            avis_checker="Sans objet (mission non encore exécutée).",
        )
        s.add(d)
        s.flush()
        did, titre = d.id, m.titre
    ledger.journaliser("NEXUS-GATE", "decision_lancement_f4_creee", mid, decision_id=did,
                       cout_estime_eur=est["cout_estime_eur"])
    decideur.nouvelle_decision(did)  # notification générique, groupée par session
    return did


def expirer_decisions() -> int:
    """Décisions en attente depuis plus de N3_TIMEOUT_HOURS → expirée = refus par défaut (atomique)."""
    limite = maintenant() - timedelta(hours=cfg().n3_timeout_hours)
    with session_scope() as s:
        candidates = s.execute(select(Decision.id, Decision.mission_id).where(Decision.statut == "en_attente")
                               .where(Decision.cree_le < limite)).all()
    expirees = 0
    for did, mid in candidates:
        with session_scope() as s:
            r = s.execute(update(Decision).where(Decision.id == did, Decision.statut == "en_attente")
                          .values(statut="expiree", decide_le=maintenant(),
                                  commentaire="Expirée sans réponse : refus par défaut."))
            if r.rowcount != 1:
                continue  # décidée entre-temps par le propriétaire
            s.execute(update(Mission).where(Mission.id == mid, Mission.statut == "en_attente_n3")
                      .values(statut="refusee", attente=None, maj_le=maintenant(),
                              message="Décision N3 expirée : refus par défaut."))
        expirees += 1
        ledger.journaliser("NEXUS-GATE", "decision_expiree", mid, decision_id=did)
    return expirees


def decider(did: int, choix: str, commentaire: str | None) -> dict:
    """Valider / refuser / réviser une décision N3 (action humaine), de façon atomique.

    `UPDATE decisions … WHERE id=? AND statut='en_attente'` puis transition de la mission depuis
    `en_attente_n3`, dans la même transaction : un seul appel concurrent peut gagner (les autres → 409).
    """
    statuts = {"valider": "validee", "refuser": "refusee", "reviser": "revision"}
    if choix not in statuts:
        raise ValueError("choix inconnu")
    with session_scope() as s:
        d = s.get(Decision, did)
        if d is None:
            raise LookupError("décision introuvable")
        if d.statut != "en_attente":
            raise PermissionError(f"décision déjà traitée ({d.statut})")
        lancement = d.objet == "lancement_f4"
        mid = d.mission_id
        if lancement and choix == "reviser":
            raise PermissionError("Révision impossible pour un lancement F4 : valider ou refuser.")
        if choix == "reviser":
            deja = s.execute(select(func.count(Decision.id)).where(Decision.mission_id == mid)
                             .where(Decision.statut == "revision")).scalar_one()
            if deja >= MAX_REVISIONS:
                raise PermissionError(f"Limite de {MAX_REVISIONS} révisions atteinte pour cette mission : "
                                      "valider ou refuser.")
    with session_scope() as s:
        r = s.execute(update(Decision).where(Decision.id == did, Decision.statut == "en_attente")
                      .values(statut=statuts[choix], decide_le=maintenant(), commentaire=commentaire))
        if r.rowcount != 1:
            raise PermissionError("décision déjà traitée (décision concurrente)")
        champs = {"statut": statuts[choix], "maj_le": maintenant()}
        if lancement:
            champs["attente"] = None
            if choix == "valider":
                champs.update(statut="recue", message="Lancement F4 approuvé : mission en file d'exécution.")
            else:
                champs["message"] = "Lancement F4 refusé par le propriétaire."
        if choix == "reviser":
            champs["message"] = f"Révision demandée : {commentaire or '(sans commentaire)'}"
        r = s.execute(update(Mission).where(Mission.id == mid, Mission.statut == "en_attente_n3").values(**champs))
        if r.rowcount != 1:
            s.rollback()
            raise PermissionError("La mission n'attend plus de décision (statut modifié entre-temps).")
        service = s.get(Mission, mid).service
    ledger.journaliser("DECIDEUR", f"decision_{statuts[choix]}", mid, decision_id=did,
                       commentaire=commentaire, objet="lancement_f4" if lancement else "livrable")
    if lancement:
        # Le lancement réel est fait par l'appelant (tâche de fond) : traiter(mid).
        return {"decision_id": did, "mission_id": mid, "statut": statuts[choix], "relance": False,
                "lancer": choix == "valider"}
    if choix == "valider":
        executor = reg.services().get(service, {}).get("executor", "NEXUS-PRIME")
        executer_livrable(mid, executor, statut_final="validee")
    # La relance d'une révision est lancée par l'appelant (tâche de fond) : relancer_revision().
    return {"decision_id": did, "mission_id": mid, "statut": statuts[choix],
            "relance": choix == "reviser", "lancer": False}


# --- EXECUTOR (aucune action externe) -------------------------------------------

def executer_livrable(mid: int, executor_id: str, statut_final: str = "terminee") -> None:
    """EXECUTOR (agent déterministe, sans LLM) : enregistre le livrable final et prépare l'action ;
    n'exécute rien à l'extérieur."""
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

def notifier(titre: str, message: str, mission_id: int | None = None, clic: str | None = None) -> bool:
    """Notification ntfy optionnelle : un échec est journalisé, jamais bloquant.

    Le texte doit rester générique (aucun détail métier) ; `clic` = lien ouvert depuis la notification.
    """
    c = cfg()
    if not c.ntfy_url or not c.ntfy_topic:
        ledger.journaliser("NEXUS-GATE", "notification_non_envoyee", mission_id,
                           motif="NTFY_URL ou NTFY_TOPIC vide")
        return False
    try:
        # Titre en ASCII pour l'en-tête HTTP ; le corps reste en UTF-8.
        r = httpx.post(f"{c.ntfy_url}/{c.ntfy_topic}", content=message.encode("utf-8"),
                       headers={"Title": re.sub(r"[^\x20-\x7e]", "", gate.normaliser(titre))[:120],
                                "Priority": "high", "Tags": "warning", **({"Click": clic} if clic else {})},
                       timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("Notification ntfy impossible : %s", e)
        ledger.journaliser("NEXUS-GATE", "notification_echec", mission_id, erreur=str(e)[:300])
        return False
