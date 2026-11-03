"""Corrections de la fiche technique : troncature, budget, PRIME, GATE, révision, escalade."""
import json

import pytest
from sqlalchemy import select

from app import gate, ledger, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Decision, Etape

from .conftest import creer_mission, lire_mission

REFUS = json.dumps({"ok": False, "problemes": ["exemple de défaut"]})
ACCEPTE = json.dumps({"ok": True, "problemes": []})


def _entrees(role):
    return [e for r, e in FournisseurFactice.entrees if r == role]


# --- 1) Troncature ----------------------------------------------------------------

def test_checker_recoit_livrable_complet_malgre_longue_consigne():
    code = "\n".join(f"def fonction_{i}(x):\n    return x * {i}  # ligne {i}" for i in range(120))
    livrable = "BROUILLON — à valider\n```python\n" + code + "\n```\nFIN-DU-LIVRABLE"
    assert len(livrable) > 3000
    consigne = ("Relis ce code et signale les défauts. " * 100)[:3500]
    assert len(consigne) == 3500
    FournisseurFactice.script["analyst"].append(livrable)
    mid = creer_mission(titre="Revue", consigne=consigne, service="CODE-CORE/revue")
    pipeline.traiter(mid)
    recu = _entrees("checker")[0]
    assert livrable in recu  # livrable entier, y compris la fin
    assert len(recu) <= 12000


def test_limite_atteinte_consigne_tronquee_en_premier(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CHARS", "4000")
    livrable = "X" * 3000 + "FIN-DU-LIVRABLE"
    FournisseurFactice.script["analyst"].append(livrable)
    mid = creer_mission(titre="Revue", consigne="C" * 3500, service="CODE-CORE/revue")
    pipeline.traiter(mid)
    recu = _entrees("checker")[0]
    assert livrable in recu and len(recu) <= 4000
    assert "C" * 3500 not in recu  # c'est la consigne qui a été réduite
    assert all(len(e) <= 4000 for _, e in FournisseurFactice.entrees)


def test_livrable_trop_long_garde_la_fin(monkeypatch):
    monkeypatch.setenv("LLM_MAX_CHARS", "2000")
    livrable = "DEBUT " + "y" * 5000 + " FIN-DU-LIVRABLE"
    msg = pipeline.assembler([("Consigne", "c" * 500, 1, "debut"),
                              ("Livrable à vérifier", livrable, 3, "tete_queue")])
    assert len(msg) <= 2000 and "DEBUT" in msg and "FIN-DU-LIVRABLE" in msg and "tronqué" in msg


# --- 2) Budget ----------------------------------------------------------------------

def test_deux_refus_tiennent_dans_budget_par_defaut(monkeypatch):
    monkeypatch.delenv("BUDGET_TASK_TOKENS", raising=False)
    FournisseurFactice.tokens_par_appel = 2000  # appels réalistes pour un petit modèle
    FournisseurFactice.script["checker"].extend([REFUS, REFUS, ACCEPTE])
    # 2 refus suivis d'une correction acceptée exigent F3 (2 corrections permises).
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "terminee", m.message
    assert m.tokens <= 20000


# --- 3) PRIME : mots entiers ------------------------------------------------------

def _service(titre, consigne):
    mid = creer_mission(titre=titre, consigne=consigne)
    with session_scope() as s:
        from app.models import Mission
        ctx = pipeline.Contexte(s.get(Mission, mid))
    return pipeline.choisir_service(ctx)


def test_prime_mots_entiers():
    assert _service("Budget", "Combien d'argent faut-il prévoir ?") != "AGENT-FACTORY/evaluation"
    assert _service("Note", "Une réponse rapide suffit") != "CODE-CORE/revue"
    assert _service("Revue", "Relis ce code PYTHON") == "CODE-CORE/revue"
    assert _service("Qualité", "Évalue la sortie de cet agent") == "AGENT-FACTORY/evaluation"
    assert _service("Conformité", "Vérifie la CONFORMITÉ RGPD") == "LEX-GUARD/conformite"


# --- 4) GATE --------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "Prépare la publication", "Il faut publier le texte", "Mise en ligne prévue", "Mettre en ligne la page",
    "Poster sur Instagram", "Diffuser la vidéo", "Envoyer au client", "Préparer l'envoi aux abonnés",
    "Faire le virement", "Enregistrer le paiement", "Payer le prestataire", "Établir la facture",
    "Rédiger le devis", "Relire le contrat", "Préparer la signature", "Signer le bon",
    "Valider l'achat", "Résilier l'abonnement", "Passer la commande", "Changer le mot de passe",
    "Traiter les données personnelles", "Supprimer le compte", "Suppression des fichiers",
    "Mise en production lundi", "Déployer la version 2",
])
def test_gate_declencheurs_n3(phrase):
    assert gate.classer("Tâche", phrase)[0] == "N3", phrase


@pytest.mark.parametrize("phrase", [
    "Envoyez-moi un résumé de la réunion", "Envoie-moi la synthèse", "Envoyer à moi le résumé",
    "Envoie-nous une synthèse interne", "Peux-tu m'envoyer le résumé ?", "Nous envoyer la synthèse",
])
def test_gate_envoi_au_proprietaire_pas_n3(phrase):
    assert gate.classer("Synthèse", phrase)[0] != "N3", phrase


def test_gate_envoi_a_moi_puis_au_client_reste_n3():
    assert gate.classer("Synthèse", "Envoie-moi le résumé puis envoie-le au client")[0] == "N3"


def test_gate_mots_entiers_sans_faux_positif():
    # « commandement », « contrats » OK ; « décontracté », « postérieur », « payernes » ne déclenchent rien.
    assert gate.classer("Note", "Une tenue décontractée, à l'étape postérieure")[0] != "N3"
    assert gate.classer("Note", "Rédige les CONTRATS types")[0] == "N3"


def test_gate_analyse_le_livrable_et_ne_peut_que_monter():
    niveau, motif = gate.classer("Checklist", "Liste les étapes",
                                 livrable="Étape 3 : effectuer le virement au fournisseur")
    assert niveau == "N3" and "livrable" in motif
    # Le LLM ne peut pas descendre un N3 issu du livrable.
    assert gate.classer("Checklist", "Liste les étapes", niveau_llm="N0",
                        livrable="Signer le contrat")[0] == "N3"


def test_gate_livrable_dans_le_pipeline():
    FournisseurFactice.script["analyst"].append("BROUILLON\n- Étape 1 : déployer en production\n")
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.niveau == "N3" and m.statut == "en_attente_n3"


# --- 5) Révision ------------------------------------------------------------------

def test_revision_relance_la_mission_et_limite():
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid)
    for n in range(2):
        with session_scope() as s:
            did = s.execute(select(Decision.id).where(Decision.statut == "en_attente")).scalar_one()
        FournisseurFactice.entrees.clear()
        res = pipeline.decider(did, "reviser", f"Ajoute la TVA (révision {n + 1})")
        assert res["statut"] == "revision" and res["relance"]
        pipeline.relancer_revision(mid, f"Ajoute la TVA (révision {n + 1})")
        roles = [r for r, _ in FournisseurFactice.entrees]
        assert roles[:3] == ["analyst", "checker", "gate"]
        assert f"Ajoute la TVA (révision {n + 1})" in _entrees("analyst")[0]
        assert lire_mission(mid).statut == "en_attente_n3"
    with session_scope() as s:
        statuts = [d.statut for d in s.execute(select(Decision).order_by(Decision.id)).scalars()]
        did = s.execute(select(Decision.id).where(Decision.statut == "en_attente")).scalar_one()
    assert statuts == ["revision", "revision", "en_attente"]
    with pytest.raises(PermissionError, match="Limite de 2 révisions"):
        pipeline.decider(did, "reviser", "encore")
    assert "revision_lancee" in [e["action"] for e in ledger.lister(200)]


def test_revision_par_api(client, entetes):
    mid = client.post("/api/missions", headers=entetes,
                      json={"titre": "Devis", "consigne": "Rédige un devis"}).json()["id"]
    did = client.get("/api/decisions?statut=en_attente", headers=entetes).json()[0]["id"]
    r = client.post(f"/api/decisions/{did}/reviser", headers=entetes, json={"commentaire": "Plus court"})
    assert r.status_code == 200 and r.json()["statut"] == "revision"
    assert client.get(f"/api/missions/{mid}", headers=entetes).json()["statut"] == "en_attente_n3"
    nouvelle = client.get("/api/decisions?statut=en_attente", headers=entetes).json()
    assert len(nouvelle) == 1 and nouvelle[0]["id"] != did


# --- 6) Escalade au directeur -------------------------------------------------------

def test_trois_refus_appel_reel_du_directeur():
    FournisseurFactice.script["checker"].extend([REFUS, REFUS, REFUS])
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "echouee" and m.niveau == "N2"
    assert "directeur" in FournisseurFactice.appels
    assert "exemple de défaut" in _entrees("directeur")[0]
    with session_scope() as s:
        etapes = s.execute(select(Etape).where(Etape.mission_id == mid).order_by(Etape.id)).scalars().all()
        dir_etape = [e for e in etapes if e.role == "directeur"]
        assert len(dir_etape) == 1 and dir_etape[0].agent_id == "DIR-OPERATIONS"
        assert "DECISION" in dir_etape[0].sortie
    assert "REFORMULER" in m.message and "DIR-OPERATIONS" in m.message
    esc = [e for e in ledger.lister(100) if e["action"] == "escalade_n2"]
    assert esc and esc[0]["acteur"] == "DIR-OPERATIONS" and esc[0]["details"]["recommandation"]
