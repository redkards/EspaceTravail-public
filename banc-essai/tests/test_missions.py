"""Cohérence des fichiers de missions, et accord avec les règles réelles de nexus-core si importables."""
import json
import re
import sys

import pytest

import noter

SERVICES = {
    "AGENT-FACTORY/evaluation", "CODE-CORE/conception", "CODE-CORE/revue", "CONTENT-ARENA/redaction",
    "CYBER-FORTRESS/audit", "CYBER-FORTRESS/conformite", "CYBER-FORTRESS/incident", "CYBER-FORTRESS/veille",
    "DESIGN-SYSTEM/ui", "GREEN-CORE/environnement", "GREEN-CORE/rse", "LEX-GUARD/conformite",
    "LEX-GUARD/droit-europe", "LEX-GUARD/droit-france", "LEX-GUARD/droit-international", "OPS-CORE/projets",
    "PILOT-CORE/etudes", "PILOT-CORE/pilotage", "R&D-PARADOX/veille", "REVENUE-CORE/propositions"}
PROJETS = {"paradoxx", "nexus", "poker-winners", "poker-feeling", "redkards", "top-solver",
           "youtube-poker-winner", "freelance-ia", "esct-boxe", "turf", "divers"}


def _verifier_definition(m):
    assert m["service_attendu"] in SERVICES
    assert m["projet"] in PROJETS
    assert m["niveau_decision_attendu"] in noter.NIVEAUX
    for r in m["interdits"]:
        if r.startswith("regle:"):
            noter.violations_regle(r, "", "")  # règle connue
    lg = m["longueur"]
    assert 0 < lg["min_mots"] < lg["max_mots"]


def test_banc_principal(banc, missions):
    d = json.loads((banc / "missions.json").read_text(encoding="utf-8"))
    ids = [m["id"] for m in d["missions"]]
    assert ids == [f"BE-{i:02d}" for i in range(1, 31)]
    assert {m["service_attendu"] for m in missions.values()} == SERVICES
    assert {"redkards", "poker-feeling", "poker-winners", "freelance-ia", "nexus"} <= {m["projet"] for m in missions.values()}
    pieges = {m["piege"]["type"] for m in missions.values() if "piege" in m}
    assert pieges == {"n3_obligatoire", "secret_refuse", "offensif_refuse"}
    assert len(d["selection_rapide"]) == 8 and set(d["selection_rapide"]) <= set(ids)
    assert all("service" not in m for m in d["missions"])  # le routage est mesuré
    for m in missions.values():
        _verifier_definition(m)


def test_audit_syfer(banc, audit):
    d = json.loads((banc / "audit-syfer" / "missions.json").read_text(encoding="utf-8"))
    assert d["fonctionnement_defaut"] == "F3" and len(audit) == 10
    attendus = {"CYBER-FORTRESS/audit", "CYBER-FORTRESS/conformite", "CYBER-FORTRESS/veille", "CODE-CORE/conception",
                "CODE-CORE/revue", "LEX-GUARD/droit-france", "LEX-GUARD/droit-europe", "PILOT-CORE/etudes",
                "PILOT-CORE/pilotage", "GREEN-CORE/environnement"}
    assert {m["service"] for m in audit.values()} == attendus
    for m in audit.values():
        _verifier_definition(m)
        assert m["projet"] == "nexus" and m["service"] == m["service_attendu"]
        dossier = m["consigne"].split("Dossier factuel :\n", 1)[1].split("\nLivrable attendu", 1)[0]
        assert len(dossier) <= 1500, m["id"]
        assert not re.search(r"srv\d|hstgr|\b\d{1,3}(\.\d{1,3}){3}\b|sk-|BEGIN .*KEY", m["consigne"])
        if m["service"].startswith("LEX-GUARD/"):
            assert "ne remplace pas l'avis d'un avocat" in m["obligatoires"]
        assert "regle:offensif" in m["interdits"]


def test_aucun_secret_hors_piege(missions, audit):
    for m in list(missions.values()) + list(audit.values()):
        if m.get("piege", {}).get("type") == "secret_refuse":
            continue
        assert not noter.violations_regle("regle:secret", m["consigne"], noter.normaliser(m["consigne"])), m["id"]


@pytest.fixture
def nexus_core(banc):
    racine = banc.parent / "nexus-core"
    if not (racine / "app" / "gate.py").exists():
        pytest.skip("nexus-core absent")
    sys.path.insert(0, str(racine))
    try:
        from app import gate, pipeline
    except Exception as e:  # dépendances (yaml, sqlalchemy…) absentes
        pytest.skip(f"nexus-core non importable : {e}")
    return gate, pipeline


def test_attendus_conformes_aux_regles_reelles(nexus_core, missions, audit):
    """Routage PRIME (mots-clés, sans égalité) et GATE (règles sur la consigne) du code actuel."""
    gate, pipeline = nexus_core
    for m in missions.values():
        sc = pipeline.scores_services(m["titre"], m["consigne"])
        haut = max(sc.values())
        gagnants = [s for s, v in sc.items() if v == haut]
        assert haut > 0 and gagnants == [m["service_attendu"]], (m["id"], gagnants)
        niveau, _ = gate.classer_regles(m["titre"], m["consigne"], m["service_attendu"])
        assert niveau == m["niveau_decision_attendu"], m["id"]
    for m in audit.values():
        niveau, _ = gate.classer_regles(m["titre"], m["consigne"], m["service"])
        assert niveau == m["niveau_decision_attendu"], m["id"]
