"""Amélioration 3a — mémoire par projet (FTS5, import idempotent, extraits, mémorisation, anti-secret)."""
from pathlib import Path

import pytest

from app import ledger, memoire, pipeline
from app.llm import FournisseurFactice

from .conftest import creer_mission, lire_mission

RACINE = Path(__file__).resolve().parents[2]
SECRET = "sk-" + "Zx9" * 10


def test_ajout_et_recherche_api(client, entetes):
    r = client.post("/api/projets/redkards/connaissances", headers=entetes,
                    json={"titre": "Personnage Red", "contenu": "Red est un joueur de poker impulsif et tenace.",
                          "source": "bible V2"})
    assert r.status_code == 201 and r.json()["etat"] == "ajoutee"
    client.post("/api/projets/redkards/connaissances", headers=entetes,
                json={"titre": "Lieu", "contenu": "Le casino des docks sert de décor principal.", "source": "bible lieux"})
    res = client.get("/api/projets/redkards/connaissances?q=joueur impulsif", headers=entetes).json()
    assert res[0]["titre"] == "Personnage Red" and res[0]["source"] == "bible V2" and res[0]["auteur"] == "api"
    assert client.get("/api/projets/redkards/connaissances", headers=entetes).json()[0]["titre"] == "Lieu"
    assert client.get("/api/projets/turf/connaissances?q=joueur", headers=entetes).json() == []  # cloisonné
    assert client.get("/api/projets/inconnu/connaissances", headers=entetes).status_code == 404
    assert client.get("/api/projets/redkards/connaissances").status_code == 401  # clé obligatoire


def test_recherche_sans_accents_et_alias(client, entetes):
    memoire.ajouter("poker-winners", "Équipe", "L'équipe bêta réunit trois testeurs.", "note", "api")
    assert memoire.rechercher("poker-vitrine", "equipe beta")[0]["titre"] == "Équipe"


def test_cockpit_lecture_et_ajout_manuel(client, cockpit):
    r = client.post("/cockpit/api/projets/turf/connaissances", headers=cockpit,
                    json={"titre": "Méthode", "contenu": "Analyse des courses à partir des cotes fournies."})
    assert r.status_code == 201
    res = client.get("/cockpit/api/projets/turf/connaissances?q=cotes", headers=cockpit).json()
    assert res[0]["auteur"] == "proprietaire"
    assert client.post("/cockpit/api/projets/turf/connaissances", json={"titre": "t", "contenu": "c"},
                       headers={"X-Cockpit-Auth": cockpit["X-Cockpit-Auth"]}).status_code == 403  # anti-CSRF


def test_idempotence_et_version(entetes, client):
    corps = {"titre": "Règle", "contenu": "Toujours citer la source.", "source": "charte"}
    assert client.post("/api/projets/nexus/connaissances", headers=entetes, json=corps).json()["etat"] == "ajoutee"
    assert client.post("/api/projets/nexus/connaissances", headers=entetes, json=corps).json()["etat"] == "inchangee"
    r = client.post("/api/projets/nexus/connaissances", headers=entetes, json={**corps, "contenu": "Citer la source."})
    assert r.json() == {"id": r.json()["id"], "etat": "mise_a_jour", "version": 2}


def test_anti_secret(client, entetes):
    r = client.post("/api/projets/nexus/connaissances", headers=entetes,
                    json={"titre": "Accès", "contenu": f"La clé est {SECRET}"})
    assert r.status_code == 422 and "secret" in r.json()["detail"]
    assert client.get("/api/projets/nexus/connaissances", headers=entetes).json() == []


def _ecrire(dossier: Path, nom: str, texte: str):
    f = dossier / nom
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(texte, encoding="utf-8")
    return f


def test_import_idempotent(tmp_path):
    d = tmp_path / "connaissances"
    _ecrire(d, "projets/poker-winners.md", "# Poker Winners\n\n## Principe\nSite éducatif en bêta privée.\n\n"
                                           "## Garde-fous\nAucune promesse de gain.\n")
    _ecrire(d, "notes/divers-notes.md", "projet: redkards\n\n# Notes\nRed perd souvent au river.\n")
    _ecrire(d, "projets/tous-les-projets.md", "# Tous\nTableau général.\n")  # aucun projet désigné
    _ecrire(d, "projets/secret.md", f"projet: nexus\n# Accès\nToken = {SECRET}\n")
    s1 = memoire.importer(d)
    assert s1["fichiers"] == 3 and s1["ignores"] == 1 and s1["ajoutees"] == 4
    s2 = memoire.importer(d)
    assert s2["ajoutees"] == 0 and s2["inchangees"] == 4 and s2["mises_a_jour"] == 0
    assert SECRET not in str(memoire.rechercher("nexus")) and "MASQUÉ" in memoire.rechercher("nexus")[0]["contenu"]
    _ecrire(d, "projets/poker-winners.md", "# Poker Winners\n\n## Principe\nSite éducatif, bêta publique.\n")
    s3 = memoire.importer(d)
    assert s3["mises_a_jour"] == 1 and s3["supprimees"] == 1
    assert "publique" in memoire.rechercher("poker-winners", "beta")[0]["contenu"]


def test_import_des_fichiers_du_kit():
    d = RACINE / "projets"
    s = memoire.importer(d.parent)  # projets/ et tests-poker/contexte/
    assert s["fichiers"] >= 6 and s["ajoutees"] > 10
    assert memoire.rechercher("redkards", "pitch")  # contexte REDKARDS indexé
    assert memoire.importer(d.parent)["ajoutees"] == 0


def test_import_dossier_absent(tmp_path):
    assert memoire.importer(tmp_path / "absent")["absent"]


def test_collector_et_checker_recoivent_les_extraits():
    for i in range(5):
        memoire.ajouter("poker-winners", f"Règle {i}", f"La mention jeu responsable est obligatoire en pied de page ({i}). "
                        + "Détail. " * 80, f"charte#{i}", "api")
    mid = creer_mission(titre="Checklist jeu responsable", consigne="Liste les contrôles de la mention jeu responsable",
                        service="OPS-CORE/projets", projet="poker-winners")
    pipeline.traiter(mid)
    collecteur = [e for r, e in FournisseurFactice.entrees if r == "collector"][0]
    assert collecteur.count("[charte#") == 3  # 3 extraits, avec leur source
    bloc = collecteur.split("Connaissances du projet")[1]
    assert len(bloc) <= 2000 + 300  # budget F2 ≈ 2 000 caractères (+ intitulés)
    controle = [e for r, e in FournisseurFactice.entrees if r == "checker"][0]
    assert "ne doit PAS les contredire" in controle and "[charte#" in controle
    assert "connaissances_fournies" in [e["action"] for e in ledger.lister(100)]


def test_budget_adapte_au_niveau():
    for i in range(3):
        memoire.ajouter("turf", f"Note {i}", "cotes chevaux " + "x" * 2000, f"n{i}", "api")
    f1 = sum(len(e["extrait"]) for e in memoire.extraits("turf", "cotes chevaux", "F1"))
    f4 = sum(len(e["extrait"]) for e in memoire.extraits("turf", "cotes chevaux", "F4"))
    assert f1 <= 800 and 800 < f4 <= 3000


def test_memorisation_automatique():
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets", projet="turf")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut == "terminee"
    k = memoire.rechercher("turf")[0]
    assert k["source"] == f"livrable #{mid}" and k["origine"] == "auto" and len(k["contenu"]) <= 800


def test_memorisation_desactivable_et_pas_de_n3_refusee(monkeypatch):
    monkeypatch.setenv("NEXUS_MEMOIRE_AUTO", "0")
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets", projet="turf")
    pipeline.traiter(mid)
    assert memoire.rechercher("turf") == []
    monkeypatch.setenv("NEXUS_MEMOIRE_AUTO", "1")
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions", projet="turf")
    pipeline.traiter(mid)
    from sqlalchemy import select
    from app.db import session_scope
    from app.models import Decision
    with session_scope() as s:
        did = s.execute(select(Decision.id).where(Decision.mission_id == mid)).scalar_one()
    pipeline.decider(did, "refuser", None)
    assert memoire.rechercher("turf") == []  # N3 refusée : rien n'est mémorisé
    mid2 = creer_mission(titre="Devis 2", consigne="Rédige un devis", service="REVENUE-CORE/propositions", projet="turf")
    pipeline.traiter(mid2)
    with session_scope() as s:
        did2 = s.execute(select(Decision.id).where(Decision.mission_id == mid2)).scalar_one()
    pipeline.decider(did2, "valider", None)
    assert memoire.rechercher("turf")[0]["source"] == f"livrable #{mid2}"


def test_memorisation_masque_les_secrets():
    FournisseurFactice.script["analyst"].append(f"BROUILLON\n- Étape 1 : utiliser le jeton {SECRET}")
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets", projet="turf")
    pipeline.traiter(mid)
    k = memoire.rechercher("turf")
    assert k and SECRET not in k[0]["contenu"]
