"""Pipeline : boucle CHECKER, kill switch, budget, N3, expiration, ledger."""
import json
from datetime import timedelta

from .conftest import creer_mission, lire_mission
from sqlalchemy import select

from app import ledger, pipeline, sentinel
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Decision, Etape, Ledger, maintenant

REFUS = json.dumps({"ok": False, "problemes": ["total HT faux"]})
ACCEPTE = json.dumps({"ok": True, "problemes": []})


def test_checker_refus_puis_acceptation(tmp_path):
    FournisseurFactice.script["checker"].extend([REFUS, ACCEPTE])
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "terminee"
    assert FournisseurFactice.appels.count("analyst") == 2  # 1 brouillon + 1 correction
    assert FournisseurFactice.appels.count("checker") == 2
    assert (tmp_path / "data" / "livrables" / "divers" / f"{mid}.md").exists()


def test_trois_refus_echouee():
    FournisseurFactice.script["checker"].extend([REFUS, REFUS, REFUS])
    # F3 : 2 boucles de correction permises → 3 refus avant l'escalade.
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "a_reformuler"  # directeur (factice) : REFORMULER
    assert m.niveau == "N2"  # escalade N2
    assert FournisseurFactice.appels.count("checker") == 3
    assert "gate" not in FournisseurFactice.appels


def test_kill_switch_grille_suspend():
    sentinel.basculer("grille", None, True)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "suspendue"
    assert FournisseurFactice.appels == []


def test_kill_switch_direction_suspend():
    sentinel.basculer("direction", "operations", True)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "suspendue"


def test_budget_tokens_depasse_arret(monkeypatch):
    monkeypatch.setenv("BUDGET_TASK_TOKENS", "100")
    FournisseurFactice.tokens_par_appel = 80
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "plafond_atteint"  # arrêt propre (niveaux de fonctionnement)
    assert "Budget" in m.message
    assert len(FournisseurFactice.appels) == 2  # arrêt juste après le dépassement


def test_budget_mensuel_payant_refuse(monkeypatch):
    from app import budget
    monkeypatch.setenv("BUDGET_MONTHLY_EUR", "0")
    try:
        budget.verifier_mois("anthropic")
        assert False, "aurait dû refuser"
    except budget.BudgetDepasse:
        pass
    budget.verifier_mois("ollama")  # local : jamais bloqué


def test_devis_n3_cree_decision():
    mid = creer_mission(titre="Devis site vitrine", consigne="Rédige un devis", montant_eur=1500,
                        service="REVENUE-CORE/propositions")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "en_attente_n3" and m.niveau == "N3"
    with session_scope() as s:
        d = s.execute(select(Decision).where(Decision.mission_id == mid)).scalar_one()
        assert d.statut == "en_attente" and d.risque == "eleve"
        assert "executor" not in [e.role for e in s.execute(select(Etape)).scalars()]


def test_plafond_n3_mise_en_file(monkeypatch):
    monkeypatch.setenv("N3_DAILY_CAP", "1")
    a = creer_mission(titre="Devis A", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    b = creer_mission(titre="Devis B", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(a)
    pipeline.traiter(b)
    assert lire_mission(b).statut == "en_attente_n3"
    assert "Plafond" in lire_mission(b).message
    with session_scope() as s:
        assert len(s.execute(select(Decision)).scalars().all()) == 1


def test_expiration_n3_refus():
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid)
    with session_scope() as s:
        d = s.execute(select(Decision)).scalar_one()
        d.cree_le = maintenant() - timedelta(hours=25)
    assert pipeline.expirer_decisions() == 1
    with session_scope() as s:
        assert s.execute(select(Decision)).scalar_one().statut == "expiree"
    assert lire_mission(mid).statut == "refusee"


def test_ledger_chaine_et_alteration():
    ledger.journaliser("TEST", "a", None, x=1)
    ledger.journaliser("TEST", "b", None, x=2)
    ledger.journaliser("TEST", "c", None, x=3)
    v = ledger.verifier()
    assert v["valide"] and v["entrees"] == 3
    with session_scope() as s:
        e = s.execute(select(Ledger).where(Ledger.action == "b")).scalar_one()
        e.details_json = json.dumps({"x": 999})
        alteree = e.id
    v = ledger.verifier()
    assert v["valide"] is False and v["premiere_erreur"] == alteree


def test_executor_aucune_action_externe(monkeypatch):
    """L'EXECUTOR ne fait aucun appel réseau : httpx.post interdit pendant le pipeline."""
    import httpx

    def interdit(*a, **k):
        raise AssertionError("appel réseau interdit")
    monkeypatch.setattr(httpx, "post", interdit)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "terminee"
