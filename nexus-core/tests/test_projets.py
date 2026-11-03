"""Registre des projets : création, validation, filtres, livrables par projet, migration."""
import sqlite3

from sqlalchemy import inspect

from app import db, projets


def _mission(client, entetes, **champs):
    corps = {"titre": "Checklist", "consigne": "Liste les étapes", "service": "OPS-CORE/projets", **champs}
    return client.post("/api/missions", headers=entetes, json=corps)


def test_registre_charge():
    reg = projets.charger(recharger=True)
    attendus = {"paradoxx", "nexus", "poker-winners", "poker-feeling", "redkards", "top-solver",
                "youtube-poker-winner", "freelance-ia", "esct-boxe", "turf", "divers"}
    assert attendus <= set(reg)
    assert projets.resoudre("poker-vitrine") == "poker-winners"  # alias
    assert projets.resoudre(None) == "divers"


def test_creation_sans_et_avec_projet(client, entetes):
    r = _mission(client, entetes)
    assert r.status_code == 202 and r.json()["projet"] == "divers"
    r = _mission(client, entetes, projet="top-solver")
    assert r.json()["projet"] == "top-solver"
    detail = client.get(f"/api/missions/{r.json()['id']}", headers=entetes).json()
    assert detail["projet"] == "top-solver"
    assert {m["projet"] for m in client.get("/api/missions", headers=entetes).json()} == {"divers", "top-solver"}
    # Alias accepté, rangé sous le code canonique.
    assert _mission(client, entetes, projet="Poker-Vitrine").json()["projet"] == "poker-winners"


def test_projet_inconnu_422(client, entetes):
    r = _mission(client, entetes, projet="inexistant")
    assert r.status_code == 422 and "Projet inconnu" in r.json()["detail"]
    assert client.get("/api/missions?projet=inexistant", headers=entetes).status_code == 422


def test_filtres_missions_et_decisions(client, entetes, cockpit):
    _mission(client, entetes, projet="turf")
    _mission(client, entetes, projet="nexus")
    client.post("/api/missions", headers=entetes,
                json={"titre": "Devis", "consigne": "Rédige un devis", "projet": "freelance-ia"})
    client.post("/api/missions", headers=entetes,
                json={"titre": "Contrat", "consigne": "Prépare le contrat", "projet": "redkards"})
    turf = client.get("/api/missions?projet=turf", headers=entetes).json()
    assert len(turf) == 1 and turf[0]["projet"] == "turf"
    decs = client.get("/api/decisions?statut=en_attente&projet=freelance-ia", headers=entetes).json()
    assert len(decs) == 1 and decs[0]["projet"] == "freelance-ia"
    assert len(client.get("/cockpit/api/decisions?statut=en_attente", headers=cockpit).json()) == 2
    # Compteurs par projet.
    liste = {p["code"]: p for p in client.get("/api/projets", headers=entetes).json()}
    assert liste["freelance-ia"]["decisions_en_attente"] == 1
    assert liste["turf"]["missions"] == 1 and liste["paradoxx"]["missions"] == 0
    assert client.get("/cockpit/api/projets", headers=cockpit).status_code == 200
    assert client.get("/api/projets").status_code == 401  # clé obligatoire


def test_livrable_range_par_projet(client, entetes, tmp_path):
    mid = _mission(client, entetes, projet="esct-boxe").json()["id"]
    assert (tmp_path / "data" / "livrables" / "esct-boxe" / f"{mid}.md").exists()
    mid2 = _mission(client, entetes).json()["id"]
    assert (tmp_path / "data" / "livrables" / "divers" / f"{mid2}.md").exists()


def test_rechargement_sans_redemarrage(client, entetes, tmp_path, monkeypatch):
    fichier = tmp_path / "projets.yaml"
    fichier.write_text("projets:\n  - {code: divers, nom: Divers}\n  - {code: nouveau, nom: Nouveau}\n",
                       encoding="utf-8")
    monkeypatch.setenv("NEXUS_PROJETS_FILE", str(fichier))
    assert _mission(client, entetes, projet="nouveau").status_code == 422  # pas encore rechargé
    r = client.get("/api/projets?recharger=1", headers=entetes)
    assert r.status_code == 200 and {p["code"] for p in r.json()} == {"divers", "nouveau"}
    assert _mission(client, entetes, projet="nouveau").status_code == 202
    # Fichier invalide : erreur claire, ancien registre conservé.
    fichier.write_text("projets:\n  - {code: sans-divers, nom: X}\n", encoding="utf-8")
    assert client.get("/api/projets?recharger=1", headers=entetes).status_code == 500
    assert "nouveau" in projets.charger()
    monkeypatch.delenv("NEXUS_PROJETS_FILE")
    projets.charger(recharger=True)


def test_migration_colonne_projet(tmp_path, monkeypatch):
    """Base existante créée sans la colonne « projet » : ajoutée au démarrage, données gardées."""
    chemin = tmp_path / "ancienne.db"
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE missions (id INTEGER PRIMARY KEY, titre VARCHAR(200), consigne TEXT,
                 service VARCHAR(80), statut VARCHAR(20), niveau VARCHAR(2), cree_le DATETIME,
                 maj_le DATETIME, livrable_texte TEXT, tokens INTEGER, cout_eur FLOAT,
                 montant_eur FLOAT, action VARCHAR(40), directeur VARCHAR(40), message TEXT)""")
    c.execute("INSERT INTO missions (id, titre, consigne, statut, cree_le, maj_le, tokens, cout_eur, montant_eur) "
              "VALUES (1, 'Ancienne', 'x', 'terminee', '2026-01-01', '2026-01-01', 0, 0, 0)")
    c.commit()
    c.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{chemin}")
    db.reinitialiser()
    db.init_db()
    colonnes = {col["name"] for col in inspect(db.engine()).get_columns("missions")}
    assert "projet" in colonnes
    from app.models import Mission
    with db.session_scope() as s:
        assert s.get(Mission, 1).projet == "divers"
    assert db.migrer(db.engine()) == []  # idempotent


def test_projets_surcharge_par_config_montee(tmp_path, monkeypatch, client, entetes):
    assert projets.chemin() == projets.EMBARQUE  # aucun montage
    monte = tmp_path / "config" / "projets.yaml"
    monte.parent.mkdir()
    monte.write_text("projets:\n  - {code: divers, nom: Divers}\n  - {code: monte, nom: Projet monté}\n",
                     encoding="utf-8")
    monkeypatch.setattr(projets, "CONFIG_MONTEE", monte)
    assert projets.chemin() == monte
    codes = {p["code"] for p in client.get("/api/projets?recharger=1", headers=entetes).json()}
    assert codes == {"divers", "monte"}
    # NEXUS_PROJETS_FILE reste prioritaire.
    autre = tmp_path / "autre.yaml"
    autre.write_text("projets:\n  - {code: divers, nom: Divers}\n", encoding="utf-8")
    monkeypatch.setenv("NEXUS_PROJETS_FILE", str(autre))
    assert projets.chemin() == autre
    monkeypatch.delenv("NEXUS_PROJETS_FILE")
    monkeypatch.setattr(projets, "CONFIG_MONTEE", tmp_path / "absent.yaml")
    projets.charger(recharger=True)
