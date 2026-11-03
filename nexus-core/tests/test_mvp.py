"""Mode MVP : SQLite fichier en WAL, ntfy optionnel (absent ou injoignable)."""
from .conftest import creer_mission, lire_mission
from sqlalchemy import text

from app import db, ledger, pipeline


def test_sqlite_fichier_en_wal(tmp_path, monkeypatch):
    chemin = tmp_path / "vol" / "nexus.db"  # dossier inexistant : créé automatiquement
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{chemin}")
    db.reinitialiser()
    db.init_db()
    with db.engine().connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
    assert chemin.exists()


def _actions():
    return [e["action"] for e in ledger.lister(200)]


def test_ntfy_vide_journalise_sans_planter(monkeypatch):
    # Expiration < 4 h : décision urgente → notification immédiate (sinon groupée par session).
    monkeypatch.setenv("N3_TIMEOUT_HOURS", "3")
    monkeypatch.setenv("NTFY_URL", "")
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "en_attente_n3"
    assert "notification_non_envoyee" in _actions()
    assert ledger.verifier()["valide"]


def test_ntfy_injoignable_journalise_sans_planter(monkeypatch):
    monkeypatch.setenv("N3_TIMEOUT_HOURS", "3")  # décision urgente : notification immédiate
    monkeypatch.setenv("NTFY_URL", "http://127.0.0.1:9")  # port fermé
    monkeypatch.setenv("NTFY_TOPIC", "nexus-test")
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "en_attente_n3"
    assert "notification_echec" in _actions()
