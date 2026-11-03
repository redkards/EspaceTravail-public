"""Note du Décideur en un geste : échantillon, 👍 → exemple, 👎 → leçon, statistiques, anti-CSRF."""
import pytest

from app import avis, exemples, lecons, pipeline
from app.llm import FournisseurFactice

from .conftest import creer_mission

BON = "BROUILLON\n## Plan\n- Étape 1 : relire\n- Étape 2 : trier"


def _terminee(titre="Checklist", projet="nexus"):
    FournisseurFactice.script["analyst"].append(BON)
    mid = creer_mission(titre=titre, consigne="Liste les étapes", service="OPS-CORE/projets", projet=projet)
    pipeline.traiter(mid)
    return mid


def test_echantillon_stable(monkeypatch):
    monkeypatch.setenv("NEXUS_ECHANTILLON_NOTE", "0.2")
    tirage = [avis.tiree(i) for i in range(1, 501)]
    assert 60 <= sum(tirage) <= 140 and tirage == [avis.tiree(i) for i in range(1, 501)]
    monkeypatch.setenv("NEXUS_ECHANTILLON_NOTE", "1")
    ids = [_terminee(f"C{i}") for i in range(3)]
    assert {m["mission_id"] for m in avis.a_noter()} == set(ids)
    monkeypatch.setenv("NEXUS_ECHANTILLON_NOTE", "0")
    assert avis.a_noter() == []


def test_pouce_haut_candidat_exemple(monkeypatch, client, cockpit):
    monkeypatch.setenv("NEXUS_ECHANTILLON_NOTE", "1")
    mid = _terminee()
    assert client.get("/cockpit/api/decideur/etat", headers=cockpit).json()["a_noter"][0]["mission_id"] == mid
    r = client.post(f"/cockpit/api/decideur/avis/{mid}", headers=cockpit, json={"valeur": "positif"})
    assert r.status_code == 200 and r.json()["exemple"]["service"] == "OPS-CORE/projets"
    assert exemples.lister("OPS-CORE/projets")[0]["mission_id"] == mid
    assert client.get("/cockpit/api/decideur/etat", headers=cockpit).json()["a_noter"] == []
    assert client.post(f"/cockpit/api/decideur/avis/{mid}", headers=cockpit,
                       json={"valeur": "positif"}).status_code == 409  # une seule note par mission


def test_pouce_bas_signal_pour_les_lecons(monkeypatch, client, cockpit):
    monkeypatch.setenv("NEXUS_LECONS_SEUIL", "2")
    for i in range(2):
        mid = _terminee(f"C{i}")
        r = client.post(f"/cockpit/api/decideur/avis/{mid}", headers=cockpit,
                        json={"valeur": "negatif", "motif": "mauvaise_marque"})
        assert r.status_code == 200
    l = lecons.lister("proposee")
    assert l and "mauvaise marque" in l[0]["texte"] and l[0]["type"] == "interdit" and l[0]["occurrences"] == 2


def test_motif_obligatoire_et_mission_terminee(client, cockpit):
    mid = _terminee()
    assert client.post(f"/cockpit/api/decideur/avis/{mid}", headers=cockpit,
                       json={"valeur": "negatif"}).status_code == 422
    creer = creer_mission(titre="En cours", consigne="x")
    assert client.post(f"/cockpit/api/decideur/avis/{creer}", headers=cockpit,
                       json={"valeur": "positif"}).status_code == 409


def test_anti_csrf_et_pas_de_cle_api(client, entetes, cockpit):
    mid = _terminee()
    assert client.post(f"/cockpit/api/decideur/avis/{mid}", json={"valeur": "positif"},
                       headers={"X-Cockpit-Auth": cockpit["X-Cockpit-Auth"]}).status_code == 403
    assert client.post(f"/api/decideur/avis/{mid}", headers=entetes, json={"valeur": "positif"}).status_code == 404


def test_statistiques_dans_le_rapport(client, entetes, cockpit):
    a, b = _terminee("A", "nexus"), _terminee("B", "turf")
    client.post(f"/cockpit/api/decideur/avis/{a}", headers=cockpit, json={"valeur": "positif"})
    client.post(f"/cockpit/api/decideur/avis/{b}", headers=cockpit,
                json={"valeur": "negatif", "motif": "trop_long", "texte": "deux fois trop long"})
    s = client.get("/api/memoire/rapport", headers=entetes).json()["satisfaction"]
    assert s["avis"] == 2 and s["par_service"]["OPS-CORE/projets"]["satisfaction"] == 50
    assert s["par_projet"]["nexus"]["positifs"] == 1 and s["par_projet"]["turf"]["negatifs"] == 1
    assert s["par_fonctionnement"]["F2"]["satisfaction"] == 50 and s["motifs_negatifs"] == {"trop_long": 1}
    assert any(k.startswith("fake:") for k in s["par_modele"])
