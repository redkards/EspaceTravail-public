"""Fixtures : SQLite temporaire, LLM factice, aucun réseau."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLE = "cle-de-test"
COCKPIT_INTERNE = "secret-interne-caddy-de-test"
# En-têtes posés par Caddy (X-Cockpit-Auth) et par le JavaScript du cockpit (X-Cockpit).
ENTETES_COCKPIT = {"X-Cockpit-Auth": COCKPIT_INTERNE, "X-Cockpit": "1"}


@pytest.fixture(autouse=True)
def environnement(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("NEXUS_API_KEY", CLE)
    monkeypatch.setenv("NEXUS_TACHES_FOND", "0")
    monkeypatch.setenv("COCKPIT_INTERNAL", COCKPIT_INTERNE)
    monkeypatch.setenv("NEXUS_HOST", "nexus.exemple.fr")
    monkeypatch.setenv("BUDGET_TASK_TOKENS", "20000")
    for v in ("NTFY_URL", "NTFY_TOPIC", "ANTHROPIC_API_KEY", "NEXUS_FONCTIONNEMENT_DEFAUT", "EUR_PAR_USD",
              "NEXUS_FONCTIONNEMENT_FILE", "BUDGET_MONTHLY_EUR", "LEDGER_HMAC_KEY", "NEXUS_MAX_MISSIONS",
              "NEXUS_PROJETS_FILE"):
        monkeypatch.delenv(v, raising=False)
    from app import fonctionnement
    fonctionnement.charger(recharger=True)
    from app import db
    from app.llm import FournisseurFactice
    db.reinitialiser()
    db.init_db()
    FournisseurFactice.reinitialiser()
    yield
    db.reinitialiser()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cockpit():
    return dict(ENTETES_COCKPIT)


@pytest.fixture
def entetes():
    return {"X-Nexus-Key": CLE}


def creer_mission(**champs) -> int:
    """Crée une mission directement en base (sans passer par l'API)."""
    from app.db import session_scope
    from app.models import Mission
    with session_scope() as s:
        m = Mission(titre=champs.pop("titre", "Test"), consigne=champs.pop("consigne", "Consigne"), **champs)
        s.add(m)
        s.flush()
        return m.id


def lire_mission(mid: int):
    from app.db import session_scope
    from app.models import Mission
    with session_scope() as s:
        return s.get(Mission, mid)
