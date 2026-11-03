"""Chargement des agents, GATE et parseurs tolérants."""
from app import agents as reg
from app import gate
from app.llm import parser_niveau, parser_verdict


def test_chargement_93_agents():
    tous = reg.charger()
    assert len(tous) == 93
    roles = [a["role"] for a in tous.values()]
    for r in ("prime", "gate", "sentinel", "ledger", "budget"):
        assert roles.count(r) == 1
    assert roles.count("directeur") == 8  # 7 + DIR-IMPACT
    for r in ("collector", "analyst", "checker", "executor"):
        assert roles.count(r) == 20  # 7 + 9 + 4 CYBER-FORTRESS
    for a in tous.values():
        assert a["consignes"].strip() and isinstance(a["outils_autorises"], list)


def test_vingt_services_complets():
    s = reg.services()
    assert len(s) == 20
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


def test_agents_deterministes():
    tous = reg.charger()
    deterministes = {i for i, a in tous.items() if not reg.appelle_llm(a)}
    attendus = {i for i, a in tous.items() if a["role"] == "executor"} | {"NEXUS-SENTINEL", "NEXUS-LEDGER",
                                                                          "NEXUS-BUDGET"}
    assert deterministes == attendus and len(deterministes) == 23
    assert all(a["type"] == "llm" for a in tous.values() if a["role"] in ("analyst", "checker", "collector"))


def test_api_agents_expose_appelle_llm(client, entetes):
    agents = {a["id"]: a for a in client.get("/api/agents", headers=entetes).json()}
    assert agents["NEXUS-LEDGER"]["appelle_llm"] is False and agents["NEXUS-LEDGER"]["type"] == "deterministe"
    assert agents["OPS-CORE-EXECUTOR"]["appelle_llm"] is False
    assert agents["OPS-CORE-ANALYST"]["appelle_llm"] is True and agents["NEXUS-GATE"]["appelle_llm"] is True


def test_agent_deterministe_jamais_appele():
    import pytest
    from app import pipeline
    from app.db import session_scope
    from app.models import Mission
    from .conftest import creer_mission
    mid = creer_mission(titre="t", consigne="c")
    with session_scope() as s:
        ctx = pipeline.Contexte(s.get(Mission, mid))
    with pytest.raises(ValueError, match="déterministe"):
        ctx.appel("NEXUS-LEDGER", "x")


def test_defauts_fournisseur(monkeypatch):
    from app.config import cfg
    for v in ("LLM_PROVIDER", "LLM_FALLBACK"):
        monkeypatch.delenv(v, raising=False)
    assert cfg().llm_provider == "ollama" and cfg().llm_fallback == "ollama"
