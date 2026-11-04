import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
SYSTEME = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEME))


def _suite(nom, statut="reussi", mesures=None, defauts=None):
    return {"nom": nom, "titre": nom, "statut": statut, "motif": None, "duree_s": 1.0, "commandes": [],
            "mesures": mesures or {}, "defauts": defauts or []}


@pytest.fixture
def suites_vertes():
    """Résultats synthétiques d'un passage entièrement vert."""
    pm = {m: {"executes": 10, "reussis": 10} for m in ("securite_ia", "cybersecurite", "gate_decision", "decideur",
                                                       "charte_qualite", "continuite")}
    return {
        "tests": _suite("tests", mesures={"total": 100, "reussis": 100, "echoues": 0, "erreurs": 0, "sautes": 0,
                                          "taux_reussite": 100.0, "par_dossier": {"nexus-core": {"statut": "reussi"}},
                                          "dossiers_sautes": []}),
        "protocole": _suite("protocole", mesures={"taux_conformite": 100.0}),
        "simulations": _suite("simulations", mesures={"taux_reussite": 100.0, "executes": 60, "reussis": 60,
                                                      "echoues": 0, "echoues_ids": [], "par_methode": pm}),
        "iterations": _suite("iterations", mesures={"taux_reussite": 100.0, "critiques_ouverts": 0, "defauts_ouverts": 0}),
        "attaque": _suite("attaque", mesures={"taux_blocage_pct": 100.0, "faux_positifs": 0, "faux_positifs_bloquants": 0}),
        "statiques": _suite("statiques", mesures={"controles": {"secrets": {"statut": "reussi"}}, "secrets_suspects": 0}),
        "banc": _suite("banc", mesures={"note_systeme_moy": 100.0, "pieges_reussis_pct": 100.0, "note_livrable_moy": 10.0}),
        "charge": _suite("charge", mesures={"taux_criteres": 100.0, "pertes_donnees": [], "integrite_ok": 4,
                                            "integrite_total": 4, "par_famille": {"fautes": {"total": 2, "reussis": 2}}}),
        "jumeau": _suite("jumeau", mesures={"version": {
            "nominal": {"score": 90.0, "ratio_livraison": 0.9, "cout_total_eur": 15.0, "n3_jour": 2.0,
                        "decisions_expirees": 0.0, "delai_decision_p50_h": 5.0},
            "panne_cloud": {"ratio_livraison": 0.9}, "absence_decideur": {"ratio_livraison": 0.81}}}),
    }


@pytest.fixture
def fabrique():
    return _suite
