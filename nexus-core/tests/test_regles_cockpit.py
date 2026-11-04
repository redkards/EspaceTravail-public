"""Règle « ce qui change le comportement ou relance : cockpit uniquement » + profil matériel."""
import pytest

from app import file_missions, fantome, pipeline, profil, sentinel
from app.llm import FournisseurFactice
from tests.conftest import creer_mission

PROPRE = ("BROUILLON — à valider\n## Leçon : la position\nJouer en dernière position donne de l'information. "
          "Le jeu comporte des risques : appelez le 09 74 75 13 13. Réservé aux majeurs.\n")


@pytest.fixture
def api_stricte(monkeypatch):
    monkeypatch.setenv("NEXUS_API_PEUT_DECIDER", "0")


def _terminee():
    FournisseurFactice.script["analyst"].append(PROPRE)
    mid = creer_mission(titre="Leçon", consigne="Rédige une leçon", service="CONTENT-ARENA/redaction",
                        projet="poker-winners")
    pipeline.traiter(mid)
    return mid


def test_exemples_reserves_au_cockpit(client, entetes, cockpit, api_stricte):
    mid = _terminee()
    assert client.post(f"/api/missions/{mid}/exemple", headers=entetes).status_code == 403
    r = client.post(f"/api/missions/{mid}/note", headers=entetes, json={"note": 5}).json()
    assert r["note"] == 5 and r["exemple"] is None  # note gardée, aucune promotion par la clé API
    eid = client.post(f"/cockpit/api/missions/{mid}/exemple", headers=cockpit, json={}).json()["id"]
    assert client.post(f"/api/exemples/{eid}/retirer", headers=entetes).status_code == 403
    assert client.post(f"/cockpit/api/exemples/{eid}/retirer", headers=cockpit, json={}).json()["actif"] is False


def test_arret_par_api_levee_par_cockpit_avec_code(client, entetes, cockpit, api_stricte, monkeypatch):
    monkeypatch.setenv("COCKPIT_CODE_DECIDEUR", "482913")
    assert client.post("/api/killswitch", headers=entetes, json={"portee": "grille", "actif": True}).status_code == 200
    assert sentinel.actifs().get("kill:grille")
    r = client.post("/api/killswitch", headers=entetes, json={"portee": "grille", "actif": False})
    assert r.status_code == 403 and "cockpit" in r.json()["detail"]
    assert client.post("/cockpit/api/killswitch", headers=cockpit, json={"portee": "grille", "actif": False}).status_code == 403
    assert client.post("/cockpit/api/killswitch", headers=cockpit,
                       json={"portee": "grille", "actif": False, "code": "000000"}).status_code in (403, 423)
    r = client.post("/cockpit/api/killswitch", headers=cockpit, json={"portee": "grille", "actif": False, "code": "482913"})
    assert r.status_code == 200 and not sentinel.actifs().get("kill:grille")


def test_levee_sans_code_configure_tracee(client, cockpit):
    client.post("/cockpit/api/killswitch", headers=cockpit, json={"portee": "grille", "actif": True})
    assert client.post("/cockpit/api/killswitch", headers=cockpit, json={"portee": "grille", "actif": False}).status_code == 200
    from app import ledger
    assert "levee_arret_sans_code_configure" in [e["action"] for e in ledger.lister(50)]


@pytest.mark.parametrize("nom,local,k", [("kvm2", 1, 5), ("kvm4", 2, 8), ("kvm8", 3, 10), ("inconnu", 1, 5)])
def test_profil_materiel(monkeypatch, nom, local, k):
    monkeypatch.setenv("NEXUS_PROFIL_MATERIEL", nom)
    assert file_missions.capacite() == local and fantome.k() == k
    monkeypatch.setenv("NEXUS_MAX_MISSIONS", "7")
    monkeypatch.setenv("NEXUS_FANTOME_K", "2")
    assert file_missions.capacite() == 7 and fantome.k() == 2  # une valeur explicite l'emporte


def test_sante_expose_le_profil(client):
    assert client.get("/api/sante").json()["profil_materiel"] == "kvm2"
