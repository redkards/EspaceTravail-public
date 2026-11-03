"""Fixtures : base SQLite temporaire, jetons de test, faux nexus-core (aucun réseau)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

JETONS = {
    "claude": "c" * 40 + "0123456789abcdef0123456789",
    "chatgpt": "a" * 40 + "0123456789abcdef0123456789",
    "gemini": "9" * 40 + "0123456789abcdef0123456789",
    "proprietaire": "f" * 40 + "0123456789abcdef0123456789",
}
CLE_CORE = "cle-core-de-test-" + "0" * 30


class FauxCore:
    """Simule nexus-core : enregistre les requêtes reçues."""

    def __init__(self):
        self.requetes: list[httpx.Request] = []
        self.projets_disponible = True

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requetes.append(req)
        if req.headers.get("x-nexus-key") != CLE_CORE:
            return httpx.Response(401, json={"detail": "Clé API absente ou invalide"})
        if req.method == "POST" and req.url.path == "/api/missions":
            return httpx.Response(202, json={"id": 42, "statut": "recue"})
        if req.method == "GET" and req.url.path == "/api/missions/42":
            return httpx.Response(200, json={"id": 42, "titre": "Test", "statut": "en_attente_n3", "niveau": "N3",
                                             "livrable_texte": "Brouillon", "etapes": [{"agent_id": "a", "role": "analyst"}]})
        if req.method == "GET" and req.url.path.startswith("/api/missions/"):
            return httpx.Response(404, json={"detail": "Mission introuvable"})
        if req.method == "GET" and req.url.path == "/api/decisions":
            return httpx.Response(200, json=[{"id": 7, "mission_id": 42, "niveau": "N3", "resume": "Devis",
                                              "recommandation": "valider", "cout_estime_eur": 0, "risque": "moyen"}])
        if req.method == "GET" and req.url.path == "/api/projets":
            if not self.projets_disponible:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json=[{"code": "poker-winners", "nom": "Poker Winners"}, {"code": "nexus"}])
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture
def faux_core():
    return FauxCore()


@pytest.fixture
def client(tmp_path, monkeypatch, faux_core):
    monkeypatch.setenv("BRIDGE_DB", str(tmp_path / "bridge.db"))
    for ident, jeton in JETONS.items():
        monkeypatch.setenv(f"BRIDGE_TOKEN_{ident.upper()}", jeton)
    monkeypatch.setenv("NEXUS_API_KEY", CLE_CORE)
    monkeypatch.setenv("NEXUS_CORE_URL", "http://nexus-core:8000")
    monkeypatch.setenv("NEXUS_HOST", "srv-test.example")
    monkeypatch.setenv("BRIDGE_LIMITE_PAR_MINUTE", "60")
    from app import outils
    from app.garde import limiteur
    limiteur.reinitialiser()
    monkeypatch.setattr(outils, "_transport", httpx.MockTransport(faux_core))
    from app.main import app
    with TestClient(app) as c:
        yield c
    limiteur.reinitialiser()


class Session:
    """Petit client MCP de test pour une identité donnée."""

    def __init__(self, client, ident: str, mode: str = "entete"):
        self.c, self.jeton, self.mode, self.n = client, JETONS[ident], mode, 0

    def post(self, corps, entetes=None):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-06-18", **(entetes or {})}
        if self.mode == "entete":
            return self.c.post("/mcp", content=json.dumps(corps), headers={"Authorization": f"Bearer {self.jeton}", **h})
        return self.c.post(f"/mcp/{self.jeton}", content=json.dumps(corps), headers=h)

    def rpc(self, methode, params=None):
        self.n += 1
        corps = {"jsonrpc": "2.0", "id": self.n, "method": methode}
        if params is not None:
            corps["params"] = params
        return self.post(corps)

    def outil(self, nom, **args):
        r = self.rpc("tools/call", {"name": nom, "arguments": args})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        return res, res.get("structuredContent")


@pytest.fixture
def session(client):
    return lambda ident="claude", mode="entete": Session(client, ident, mode)
