"""Audit 1 — CSRF et contournement N3 sur /cockpit/api/*."""
import pytest

from .conftest import COCKPIT_INTERNE


def _decision(client, entetes):
    client.post("/api/missions", headers=entetes, json={"titre": "Devis", "consigne": "Rédige un devis"})
    return client.get("/api/decisions?statut=en_attente", headers=entetes).json()[0]["id"]


def test_formulaire_sans_entete_refuse(client, entetes):
    did = _decision(client, entetes)
    # Formulaire HTML d'un site tiers : pas d'X-Cockpit, pas de JSON, le navigateur envoie le basic auth.
    r = client.post(f"/cockpit/api/decisions/{did}/valider", data={"commentaire": "ok"},
                    headers={"X-Cockpit-Auth": COCKPIT_INTERNE, "Origin": "https://pirate.exemple"})
    assert r.status_code == 403
    r = client.post(f"/cockpit/api/decisions/{did}/valider", data={"commentaire": "ok"},
                    headers={"X-Cockpit-Auth": COCKPIT_INTERNE})
    assert r.status_code == 403 and "X-Cockpit" in r.json()["detail"]
    assert client.get("/api/decisions?statut=en_attente", headers=entetes).json()[0]["id"] == did


def test_mauvaise_origine_refusee(client, entetes, cockpit):
    did = _decision(client, entetes)
    r = client.post(f"/cockpit/api/decisions/{did}/valider", json={},
                    headers={**cockpit, "Origin": "https://pirate.exemple"})
    assert r.status_code == 403 and "origine" in r.json()["detail"]


def test_sans_x_cockpit_auth_refuse(client, entetes):
    did = _decision(client, entetes)
    for h in ({"X-Cockpit": "1"}, {"X-Cockpit": "1", "X-Cockpit-Auth": "mauvaise"}):
        assert client.post(f"/cockpit/api/decisions/{did}/valider", json={}, headers=h).status_code == 403
        assert client.get("/cockpit/api/decisions", headers=h).status_code == 403  # lectures aussi


def test_corps_json_obligatoire(client, entetes, cockpit):
    did = _decision(client, entetes)
    r = client.post(f"/cockpit/api/decisions/{did}/valider", headers=cockpit)  # sans corps
    assert r.status_code == 403 and "JSON" in r.json()["detail"]
    r = client.post(f"/cockpit/api/decisions/{did}/valider", content=b"pas du json",
                    headers={**cockpit, "Content-Type": "application/json"})
    assert r.status_code == 403


def test_cas_nominal(client, entetes, cockpit):
    did = _decision(client, entetes)
    r = client.post(f"/cockpit/api/decisions/{did}/valider", json={"commentaire": "ok"},
                    headers={**cockpit, "Origin": "https://nexus.exemple.fr"})
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    r = client.post("/cockpit/api/missions", json={"titre": "t", "consigne": "Liste les étapes"}, headers=cockpit)
    assert r.status_code == 202
    assert client.get("/cockpit/api/missions", headers={"X-Cockpit-Auth": COCKPIT_INTERNE}).status_code == 200


def test_cockpit_interne_absent_verrouille(client, entetes, cockpit, monkeypatch):
    monkeypatch.setenv("COCKPIT_INTERNAL", "")
    r = client.post("/cockpit/api/missions", json={"titre": "t", "consigne": "c"}, headers=cockpit)
    assert r.status_code == 403 and "COCKPIT_INTERNAL" in r.json()["detail"]
    assert client.get("/cockpit/api/agents", headers=cockpit).status_code == 403
    assert client.get("/cockpit").status_code == 200  # la page reste servie (protégée par Caddy)


def test_cle_api_inchangee_et_passerelle_sans_validation(client, entetes):
    # L'API à clé n'est pas concernée par les en-têtes cockpit.
    did = _decision(client, entetes)
    assert client.post(f"/api/decisions/{did}/refuser", headers=entetes).status_code == 200


@pytest.mark.parametrize("methode", ["put", "patch", "delete"])
def test_autres_methodes_ecriture(client, cockpit, methode):
    r = getattr(client, methode)("/cockpit/api/missions/1", headers={"X-Cockpit-Auth": COCKPIT_INTERNE})
    assert r.status_code == 403  # refusé par la garde avant même le routage
