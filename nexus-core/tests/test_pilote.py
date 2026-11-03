"""Pilote de projets hebdomadaire : lancement le lundi, consolidation en UNE décision N3, cases à cocher."""
import json
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select

from app import ledger, pilote, projets
from app.db import session_scope
from app.file_missions import FILE
from app.llm import FournisseurFactice
from app.models import Decision, Mission

PLAN = """PRIORITES:
1. Finir la relecture
2. Préparer la checklist de bêta
3. Trier les anomalies
MISSIONS:
- Checklist de bêta 0.9 | OPS-CORE/projets | F2 | Établis la checklist de test de la version 0.9.
- Note de veille | R&D-PARADOX/veille | F4 | Synthétise les textes fournis sur le sujet.
- Ligne invalide sans séparateurs
BLOQUES:
- Prix Premium non fixés
"""


def test_projets_actifs_par_defaut():
    actifs = {c for c, p in projets.charger().items() if p["actif"]}
    assert actifs == {"poker-feeling", "poker-winners", "redkards", "top-solver", "nexus"}


def test_tick_le_lundi_une_fois(monkeypatch):
    lances = []
    monkeypatch.setattr(pilote, "lancer", lambda sem=None: lances.append(sem) or {"semaine": sem})
    assert pilote.tick(datetime(2026, 11, 10, 6, 35)) is None  # mardi
    assert pilote.tick(datetime(2026, 11, 9, 6, 0)) is None  # lundi 07:00 Paris : trop tôt
    assert pilote.tick(datetime(2026, 11, 9, 6, 35))["semaine"] == "2026-W46"  # lundi 07:35 Paris
    assert pilote.tick(datetime(2026, 11, 9, 6, 50)) is None and lances == ["2026-W46"]
    monkeypatch.setenv("NEXUS_PILOTE_HEBDO", "off")
    assert pilote.tick(datetime(2026, 11, 16, 6, 35)) is None


def test_analyse_du_plan():
    a = pilote.analyser("poker-winners", PLAN)
    assert a["priorites"] == ["Finir la relecture", "Préparer la checklist de bêta", "Trier les anomalies"]
    assert [m["titre"] for m in a["missions"]] == ["Checklist de bêta 0.9", "Note de veille"]
    assert a["missions"][1]["fonctionnement"] == "F2"  # F4 jamais proposé automatiquement
    assert a["bloques"] == ["Prix Premium non fixés"]


def _semaine_complete(monkeypatch):
    monkeypatch.setenv("NEXUS_WEBHOOK_QG", "http://qg.test/hook")
    FournisseurFactice.script["analyst"].extend([PLAN] * 5)
    r = pilote.lancer("2026-W46")
    assert FILE.attendre_vide(30) and len(r["missions"]) == 5
    with session_scope() as s:
        return s.execute(select(Decision).where(Decision.objet == "plan_semaine")).scalars().all()


def test_consolidation_une_seule_decision(monkeypatch):
    decisions = _semaine_complete(monkeypatch)
    assert len(decisions) == 1 and decisions[0].niveau == "N3"
    props = pilote.propositions_de(decisions[0].id)
    assert len(props) == 10 and {p["projet"] for p in props} == {"poker-feeling", "poker-winners", "redkards",
                                                                "top-solver", "nexus"}
    with session_scope() as s:  # aucune autre décision (les missions de pilotage n'en créent pas)
        assert s.execute(select(func.count(Decision.id))).scalar_one() == 1
        enfants = s.execute(select(Mission).where(Mission.pilote_semaine == "2026-W46",
                                                  Mission.titre.like("Pilote%"))).scalars().all()
        assert all(m.service == "PILOT-CORE/pilotage" and m.fonctionnement == "F3" for m in enfants)
        consigne = enfants[0].consigne
    assert "PRIORITES:" in consigne and "Historique des 7 derniers jours" in consigne
    assert "plan_semaine_cree" in [e["action"] for e in ledger.lister(500)]
    from app import export_qg
    assert export_qg.etat()["par_statut"].get("en_attente", 0) >= 1  # résumé envoyé au QG


def test_validation_lance_seulement_les_missions_cochees(monkeypatch, client, cockpit):
    did = _semaine_complete(monkeypatch)[0].id
    carte = [c for c in client.get("/cockpit/api/decideur/etat", headers=cockpit).json()["cartes"]
             if c["objet"] == "plan_semaine"][0]
    assert len(carte["propositions"]) == 10 and "Pilote hebdomadaire" in carte["resume"]["pourquoi"]
    p = client.post(f"/cockpit/api/decideur/decisions/{did}/preparer", headers=cockpit, json={"choix": "valider"}).json()
    r = client.post(f"/cockpit/api/decideur/decisions/{did}/confirmer", headers=cockpit,
                    json={"choix": "valider", "jeton": p["jeton"], "missions": [1, 4]}).json()
    assert len(r["missions_creees"]) == 2
    with session_scope() as s:
        crees = s.execute(select(Mission).where(Mission.id.in_(r["missions_creees"]))).scalars().all()
        assert {m.titre for m in crees} == {"Checklist de bêta 0.9"} | {props["titre"] for props in
                                                                       pilote.propositions_de(did) if props["id"] == 4}
        assert all(m.statut != "recue" for m in crees)  # lancées par la file


def test_tout_decoche_par_defaut(monkeypatch, client, entetes):
    did = _semaine_complete(monkeypatch)[0].id
    r = client.post(f"/api/decisions/{did}/valider", headers=entetes, json={}).json()
    assert r["missions_creees"] == []


def test_revision_impossible(monkeypatch, client, cockpit):
    did = _semaine_complete(monkeypatch)[0].id
    r = client.post(f"/cockpit/api/decideur/decisions/{did}/preparer", headers=cockpit,
                    json={"choix": "reviser", "commentaire": "autre plan"})
    assert r.status_code == 409
