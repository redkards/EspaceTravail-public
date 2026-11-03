"""Chargement des agents, GATE et parseurs tolérants."""
from app import agents as reg
from app import gate
from app.llm import parser_niveau, parser_verdict


def test_chargement_77_agents():
    tous = reg.charger()
    assert len(tous) == 77
    roles = [a["role"] for a in tous.values()]
    for r in ("prime", "gate", "sentinel", "ledger", "budget"):
        assert roles.count(r) == 1
    assert roles.count("directeur") == 8  # 7 + DIR-IMPACT
    for r in ("collector", "analyst", "checker", "executor"):
        assert roles.count(r) == 16  # 7 + 9 nouveaux services
    for a in tous.values():
        assert a["consignes"].strip() and isinstance(a["outils_autorises"], list)


def test_seize_services_complets():
    s = reg.services()
    assert len(s) == 16
    assert "R&D-PARADOX/veille" in s
    for v in s.values():
        assert {"collector", "analyst", "checker", "executor", "directeur"} <= set(v)
        assert v["directeur"].startswith("DIR-")


def test_devis_avec_montant_est_n3():
    niveau, _ = gate.classer("Préparer une offre", "Offre pour la société X", montant_eur=1200)
    assert niveau == "N3"
    assert gate.classer("Devis client", "Rédige un devis pour un site vitrine")[0] == "N3"
    assert gate.classer("Envoi", "Préparer le message", action="envoyer_client")[0] == "N3"
    assert gate.classer("Accès", "Change le mot de passe du serveur")[0] == "N3"


def test_simple_synthese_n0_ou_n1():
    assert gate.classer("Synthèse", "Fais une synthèse interne de ces notes")[0] in ("N0", "N1")
    assert gate.classer("Checklist", "Liste les étapes de démarrage")[0] in ("N0", "N1")


def test_n2_code_et_publication_charte():
    assert gate.classer("Revue", "Relis ce code Python")[0] == "N2"
    assert gate.classer("Texte", "Rédige un texte", service="CONTENT-ARENA/redaction")[0] == "N2"


def test_llm_ne_peut_pas_descendre():
    assert gate.classer("Devis", "Rédige un devis", niveau_llm="N0")[0] == "N3"
    assert gate.classer("Synthèse", "Fais une synthèse", niveau_llm="N1")[0] == "N1"
    assert gate.classer("Synthèse", "Fais une synthèse", niveau_llm="N3")[0] == "N3"
    assert gate.classer("Synthèse", "Fais une synthèse", niveau_llm="n'importe quoi")[0] == "N0"


def test_parseur_verdict_tolerant():
    assert parser_verdict('{"ok": true, "problemes": []}') == {"ok": True, "problemes": []}
    v = parser_verdict('Voici :\n```json\n{"ok": false, "problemes": ["total faux"]}\n```')
    assert v == {"ok": False, "problemes": ["total faux"]}
    assert parser_verdict("{'ok': 'vrai', 'problemes': 'aucun'}")["ok"] is True
    assert parser_verdict("ok: false, il manque la TVA")["ok"] is False
    assert parser_verdict("je ne sais pas")["ok"] is False  # illisible → refus prudent
    assert parser_niveau("NIVEAU: N2") == "N2"
