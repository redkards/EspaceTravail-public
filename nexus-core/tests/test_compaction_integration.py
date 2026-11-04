"""Compaction branchée sur le noyau : archive (recherche, vérification, effacement RGPD), mémoire
(consolidation), tâche de nuit, statistiques au cockpit."""
from datetime import datetime, timedelta

import pytest

from app import archive, compaction, ledger, main, memoire, pipeline
from app.llm import FournisseurFactice
from app.models import maintenant
from tests.conftest import creer_mission


@pytest.fixture(autouse=True)
def _cle(monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", "cle-de-test-compaction-0123456789")
    compaction._defaut = None
    yield
    compaction._defaut = None


def _mission(titre="Tournoi Valdrôme", texte="# Plan du tournoi amical de Valdrôme\n- Réserver la salle"):
    FournisseurFactice.script["analyst"].append(texte)
    mid = creer_mission(titre=titre, consigne="Liste les étapes du tournoi.", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    return mid


def _compacter():
    demain = (maintenant() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    return compaction.defaut(journal=ledger.journaliser).compacter("tiede", avant_date=demain,
                                                                   dossier_archive=archive.dossier())


def test_archive_verifiee_et_recherche_avec_compaction():
    mid = _mission()
    res = _compacter()
    assert res["ajoutes"] >= 1
    v = archive.verifier()
    assert v["valide"] and v["compaction"]["valide"]
    assert compaction.defaut().lire_mission(mid)


def test_recherche_complete_par_les_paliers_compactes(monkeypatch):
    mid = _mission()
    _compacter()
    monkeypatch.setattr(archive, "_rechercher_chaud", lambda *a, **k: [])  # mois retiré : plus dans l'index chaud
    assert any(r.get("mission_id") == mid for r in archive.rechercher("valdrome"))


def test_effacement_rgpd_atteint_la_compaction():
    mid = _mission()
    _compacter()
    assert compaction.defaut().rechercher("valdrome")
    archive.effacer(mid, "proprietaire", "demande RGPD")
    assert compaction.defaut().rechercher("valdrome") == []
    assert all(e.get("efface") or "Valdr" not in str(e) for e in compaction.defaut().lire_mission(mid))
    trace = [e for e in ledger.lister(300) if e["action"] == "archive_effacement"][0]
    assert trace["details"]["compaction"] >= 1
    assert archive.verifier()["valide"]


def test_consolidation_memoire_plafond_par_projet():
    for i in range(4):
        memoire.ajouter("divers", f"livrable #{100 + i} — Note {i}", f"Résumé numéro {i} " + "texte distinct " * i
                        + f"sujet {i * 7919}", f"livrable #{100 + i}", "nexus-core", origine="auto", masquer=True)
    memoire.ajouter("divers", "Règle", "Citer la source.", "manuel-1", "api")
    res = memoire.consolider(plafond=2)
    assert res["evincees"] == 3
    restantes = memoire.rechercher("divers", limite=50)
    assert len(restantes) == 2 and any(k["origine"] == "manuel" for k in restantes)  # le manuel n'est jamais évincé


def test_tache_de_nuit_une_fois_par_jour(monkeypatch):
    _mission()
    jour = datetime(2026, 11, 5, 12, 0)   # midi à Paris : hors fenêtre
    assert main.lancer_compaction_nuit(jour) is False
    nuit = datetime(2026, 11, 5, 2, 0)    # 03:00 à Paris
    assert main.lancer_compaction_nuit(nuit) is True
    main._fil_compaction.join(60)
    assert [e for e in ledger.lister(300) if e["action"] == "compaction_nuit"]
    assert compaction.defaut()._meta("derniere_nuit") == "2026-11-05"
    assert compaction.defaut().tache_nocturne(nuit) is None  # déjà faite ce jour
    monkeypatch.setenv("NEXUS_COMPACTION", "0")
    assert main.lancer_compaction_nuit(nuit) is False


def test_statistiques_au_cockpit(client, entetes, cockpit):
    r = client.get("/cockpit/api/archive/compaction", headers=cockpit).json()
    assert r["compaction"] is None and r["fenetre_nuit"]
    _mission()
    _compacter()
    r = client.get("/api/archive/compaction", headers=entetes).json()
    assert r["compaction"]["ratio"] and r["compaction"]["avant_octets"] > 0 and r["archive_chaude_octets"] > 0
    assert client.get("/api/archive/compaction").status_code == 401
