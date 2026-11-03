"""Contrôles du jeu de simulations : schéma, identifiants, répartition (10 par méthode, 13 pour le Décideur), exécution d'un sous-ensemble.

Lancer : cd simulations && python3 -m pytest -q tests
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ICI))

import simuler  # noqa: E402

DOC = json.loads((ICI / "scenarios.json").read_text(encoding="utf-8"))
SCENARIOS = DOC["scenarios"]


def test_schema_valide():
    assert simuler.valider_schema(DOC) == []


def test_exactement_103_scenarios_ids_uniques_et_continus():
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == 103
    assert len(set(ids)) == 103
    assert ids == [f"SIM-{i:03d}" for i in range(1, 104)]


def test_repartition_10_par_methode_et_13_decideur():
    """10 scénarios par méthode ; le Décideur en a 13 (SIM-101 à SIM-103 : non-régression des décisions)."""
    c = Counter(s["methode"] for s in SCENARIOS)
    assert set(c) == set(simuler.METHODES)
    attendu = {m: (13 if m == "decideur" else 10) for m in simuler.METHODES}
    assert dict(c) == attendu, c


def test_champs_et_valeurs():
    for s in SCENARIOS:
        assert s["mode"] in ("hors_ligne", "api_factice", "vps")
        assert s["criticite"] in ("critique", "haute", "moyenne", "basse")
        assert s["attendus"], s["id"]
        for p in s["prerequis"]:
            assert p in simuler.PREREQUIS, (s["id"], p)


def test_aucun_secret_ni_donnee_personnelle():
    """Valeurs factices seulement : pas de vraie clé Anthropic/GitHub longue, pas d'adresse e-mail réelle."""
    texte = json.dumps(DOC, ensure_ascii=False)
    import re
    assert not re.search(r"[\w.+-]+@(?!exemple\.invalid)[\w-]+\.(?:com|fr|net|org)\b", texte)
    for m in re.findall(r"sk-ant-[A-Za-z0-9_-]{16,}", texte):
        assert "SIMULATION" in m
    for m in re.findall(r"ghp_[A-Za-z0-9]+", texte):
        assert m.startswith("ghp_ABCDEFGH")


def test_operateurs_et_chemins():
    assert simuler.verifier("contient", "Élevé", "eleve")
    assert simuler.verifier("aucun_contient", ["memoire_lire"], ["valider"])
    ctx = {"r": {"json": [{"code": "a", "n": 1}, {"code": "b", "n": 2}]}, "l": ["x", "yy"]}
    assert simuler.resoudre(ctx, "r.json[code=b].n") == 2
    assert simuler.resoudre(ctx, "l#len") == 2
    assert simuler.rendre("${r.json.0.n}", ctx) == 1


# Sous-ensemble représentatif (une ou deux par méthode, les deux modes exécutables).
SOUS_ENSEMBLE = ["SIM-003", "SIM-012", "SIM-014", "SIM-023", "SIM-027", "SIM-033", "SIM-038", "SIM-041",
                 "SIM-051", "SIM-060", "SIM-062", "SIM-076", "SIM-078", "SIM-083", "SIM-087", "SIM-090", "SIM-091",
                 "SIM-101", "SIM-102", "SIM-103"]


@pytest.mark.parametrize("sid", SOUS_ENSEMBLE)
def test_sous_ensemble_reussi(sid):
    sc = next(s for s in SCENARIOS if s["id"] == sid)
    r = simuler.executer_scenario(sc)
    if r["statut"] == "saute":
        pytest.skip(r["motif"])
    assert r["statut"] == "reussi", json.dumps(r["echecs"], ensure_ascii=False, indent=1)


def test_scenario_vps_toujours_saute():
    sc = dict(SCENARIOS[0], mode="vps")
    assert simuler.executer_scenario(sc)["statut"] == "saute"


def test_prerequis_absent_saute_proprement():
    sc = dict(SCENARIOS[0], prerequis=["module_inexistant_simulation"])
    r = simuler.executer_scenario(sc)
    assert r["statut"] == "saute" and "module_inexistant_simulation" in r["motif"]
    sc2 = dict(SCENARIOS[0], preparation={"description": "x", "fonctions_requises": ["app.gate.fonction_inexistante"]})
    r2 = simuler.executer_scenario(sc2)
    assert r2["statut"] == "saute" and "fonction_inexistante" in r2["motif"]


def test_une_assertion_fausse_est_detectee():
    """Garde-fou du moteur : une attente volontairement fausse doit échouer (pas de réussite à vide)."""
    sc = json.loads(json.dumps(next(s for s in SCENARIOS if s["id"] == "SIM-014")))
    sc["attendus"] = [{"chemin": "r.0", "op": "egal", "valeur": "N0", "libelle": "faux exprès"}]
    r = simuler.executer_scenario(sc)
    assert r["statut"] == "echoue" and r["echecs"][0]["obtenu"] == "N3"
