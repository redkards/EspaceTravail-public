"""Audit 7 — décision du directeur après escalade : RELANCER / REFORMULER / autre."""
import json

from app import ledger, pipeline
from app.llm import FournisseurFactice

from .conftest import creer_mission, lire_mission

REFUS = json.dumps({"ok": False, "problemes": ["livrable incomplet"]})
ACCEPTE = json.dumps({"ok": True, "problemes": []})


def _mission(f="F1"):
    return creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                         fonctionnement=f)


def test_relancer_une_fois_au_niveau_superieur():
    FournisseurFactice.script["checker"].extend([REFUS, ACCEPTE])  # F1 : refus → escalade ; relance F2 : OK
    FournisseurFactice.script["directeur"].append("DIAGNOSTIC: x\nDECISION: RELANCER\nCONSIGNE: détailler chaque étape")
    mid = _mission("F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "terminee" and m.fonctionnement == "F2" and m.relance_auto == 1
    assert "relance automatique" in m.fonctionnement_raison
    assert "Indication du directeur pour la relance : détailler chaque étape" in m.consigne
    assert [e["action"] for e in ledger.lister(300) if e["mission_id"] == mid].count("relance_automatique") == 1


def test_relance_unique_puis_echec():
    FournisseurFactice.script["checker"].extend([REFUS, REFUS, REFUS, REFUS])
    FournisseurFactice.script["directeur"].extend(["DECISION: RELANCER"] * 2)
    mid = _mission("F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "echouee" and "déjà effectuée" in m.message
    assert FournisseurFactice.appels.count("directeur") == 2  # 2 escalades, 1 seule relance


def test_relance_ne_monte_jamais_en_f4():
    FournisseurFactice.script["checker"].extend([REFUS] * 3 + [ACCEPTE, ACCEPTE])
    FournisseurFactice.script["directeur"].append("DECISION: RELANCER")
    mid = _mission("F3")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.fonctionnement == "F3" and m.relance_auto == 1 and m.statut == "terminee"


def test_reformuler_statut_a_reformuler():
    FournisseurFactice.script["checker"].append(REFUS)
    FournisseurFactice.script["directeur"].append("DECISION: REFORMULER\nCONSIGNE: préciser le public visé")
    mid = _mission("F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "a_reformuler" and "préciser le public visé" in m.message and m.relance_auto == 0


def test_abandonner_ou_illisible_echouee():
    for avis in ("DECISION: ABANDONNER", "réponse sans format"):
        FournisseurFactice.script["checker"].append(REFUS)
        FournisseurFactice.script["directeur"].append(avis)
        mid = _mission("F1")
        pipeline.traiter(mid)
        assert lire_mission(mid).statut == "echouee"
