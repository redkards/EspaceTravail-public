"""API HTTP : clé obligatoire, missions, décisions, kill switch, cockpit."""


def test_sante_sans_et_avec_cle(client, entetes):
    assert client.get("/api/sante").status_code == 200
    r = client.get("/api/sante", headers=entetes)
    assert r.status_code == 200 and r.json()["statut"] == "ok"


def test_cle_obligatoire_sur_api(client, entetes):
    assert client.get("/api/missions").status_code == 401
    assert client.get("/api/missions", headers={"X-Nexus-Key": "mauvaise"}).status_code == 401
    assert client.post("/api/missions", json={"titre": "a", "consigne": "b"}).status_code == 401
    assert client.get("/api/missions", headers=entetes).status_code == 200


def test_cockpit_sans_cle(client):
    r = client.get("/cockpit")
    assert r.status_code == 200 and "Cockpit NEXUS" in r.text
    assert client.get("/cockpit/api/agents").status_code == 200
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/cockpit"


def test_mission_complete_n1(client, entetes):
    r = client.post("/api/missions", headers=entetes,
                    json={"titre": "Checklist de démarrage", "consigne": "Rédige une checklist de démarrage",
                          "service": "OPS-CORE/projets"})
    assert r.status_code == 202
    mid = r.json()["id"]
    m = client.get(f"/api/missions/{mid}", headers=entetes).json()
    assert m["statut"] == "terminee" and m["niveau"] in ("N0", "N1")
    assert len(m["etapes"]) >= 4
    liste = client.get("/api/missions", headers=entetes).json()
    assert isinstance(liste, list) and liste[0]["id"] == mid


def test_devis_decision_valider(client, entetes):
    mid = client.post("/api/missions", headers=entetes,
                      json={"titre": "Devis", "consigne": "Rédige un devis pour un site", "montant_eur": 900}).json()["id"]
    decs = client.get("/api/decisions?statut=en_attente", headers=entetes).json()
    assert isinstance(decs, list) and len(decs) == 1 and decs[0]["mission_id"] == mid
    did = decs[0]["id"]
    r = client.post(f"/api/decisions/{did}/valider", headers=entetes, json={"commentaire": "OK"})
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    assert client.get(f"/api/missions/{mid}", headers=entetes).json()["statut"] == "validee"
    # Une décision ne peut être traitée qu'une fois.
    assert client.post(f"/api/decisions/{did}/refuser", headers=entetes).status_code == 409
    assert client.get("/api/decisions?statut=en_attente", headers=entetes).json() == []


def test_devis_decision_refuser_et_reviser(client, entetes):
    for choix, statut in (("refuser", "refusee"), ("reviser", "revision")):
        mid = client.post("/api/missions", headers=entetes,
                          json={"titre": "Contrat", "consigne": "Prépare le contrat"}).json()["id"]
        did = client.get("/api/decisions?statut=en_attente", headers=entetes).json()[0]["id"]
        r = client.post(f"/cockpit/api/decisions/{did}/{choix}", json={"commentaire": "non"})
        assert r.status_code == 200 and r.json()["statut"] == statut
        m = client.get(f"/api/missions/{mid}", headers=entetes).json()
        # Une révision relance la mission ; « contrat » la ramène en N3 avec une nouvelle fiche.
        assert m["statut"] == ("refusee" if choix == "refuser" else "en_attente_n3")
        if choix == "reviser":
            client.post(f"/api/decisions/{client.get('/api/decisions?statut=en_attente', headers=entetes).json()[0]['id']}/refuser",
                        headers=entetes)


def test_killswitch_api(client, entetes):
    r = client.post("/api/killswitch", headers=entetes, json={"portee": "grille", "actif": True})
    assert r.status_code == 200 and r.json()["cle"] == "kill:grille"
    mid = client.post("/api/missions", headers=entetes, json={"titre": "a", "consigne": "b"}).json()["id"]
    assert client.get(f"/api/missions/{mid}", headers=entetes).json()["statut"] == "suspendue"
    assert all(a["statut"] == "suspendu" for a in client.get("/api/agents", headers=entetes).json())
    client.post("/api/killswitch", headers=entetes, json={"portee": "grille", "actif": False})
    assert client.post("/api/killswitch", headers=entetes,
                       json={"portee": "agent", "cible": "INCONNU", "actif": True}).status_code == 422


def test_ledger_budget_agents(client, entetes):
    client.post("/api/missions", headers=entetes, json={"titre": "a", "consigne": "Fais une synthèse"})
    assert client.get("/api/ledger/verifier", headers=entetes).json()["valide"] is True
    assert len(client.get("/api/ledger?limit=5", headers=entetes).json()) == 5
    assert len(client.get("/api/agents", headers=entetes).json()) == 93
    b = client.get("/api/budget", headers=entetes).json()
    assert b["tokens"] > 0 and b["budget_tache_tokens"] == 20000
    # Aucune route de modification/suppression du ledger.
    assert client.delete("/api/ledger", headers=entetes).status_code == 405
