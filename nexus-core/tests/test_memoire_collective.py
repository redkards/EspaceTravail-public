"""Mémoire collective : archive chaînée, effacement, leçons (extraction, seuil, décisions, injection,
régression), revue hebdomadaire, recherche, rapport."""
import gzip
import json
from datetime import datetime

import pytest
from sqlalchemy import select

from app import archive, lecons, ledger, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Decision, Lecon

from .conftest import creer_mission, lire_mission

REFUS = json.dumps({"ok": False, "problemes": ["Le tableau des étapes oublie les responsables"]})
CLE = "cle-hmac-memoire-" + "7" * 20


def _mission(titre="Checklist", refus=False, projet="nexus", livrable=None):
    if refus:
        FournisseurFactice.script["checker"].append(REFUS)
    if livrable:
        FournisseurFactice.script["analyst"].append(livrable)
    mid = creer_mission(titre=titre, consigne="Liste les étapes du chantier", service="OPS-CORE/projets",
                        projet=projet)
    pipeline.traiter(mid)
    return mid


# --- Archive ----------------------------------------------------------------------------------

def test_archive_complete_chainee_et_verifiable(monkeypatch, tmp_path):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    mid = _mission(refus=True)
    lignes = archive.lignes()
    assert lignes and all(l["algo"] == "hmac" for l in lignes)
    e = lignes[-1]["enregistrement"]
    assert e["mission_id"] == mid and e["consigne"] and e["livrable"] and e["modeles"] and e["etapes"]
    assert e["verdicts_checker"] and e["fonctionnement"] == "F2"
    assert archive.verifier()["valide"]
    assert "archive_ajout" in [x["action"] for x in ledger.lister(100)]
    assert list((tmp_path / "data" / "archive").glob("*.jsonl.gz"))


def test_archive_alteration_detectee(monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    _mission()
    _mission(titre="Deuxième")
    f = sorted(archive.dossier().glob("*.jsonl.gz"))[0]
    lignes = [json.loads(b) for b in gzip.open(f) if b.strip()]
    lignes[0]["enregistrement"]["livrable"] = "falsifié"
    with gzip.open(f, "wb") as g:
        for l in lignes:
            g.write(json.dumps(l).encode() + b"\n")
    v = archive.verifier()
    assert not v["valide"] and v["motif"] == "contenu modifié"


def test_archive_sans_secret(monkeypatch):
    secret = "sk-" + "Qw9" * 10
    _mission(livrable=f"BROUILLON\n- Jeton : {secret}")
    brut = b"".join(gzip.open(f).read() for f in archive.dossier().glob("*.jsonl.gz"))
    assert secret.encode() not in brut


def test_effacement_pierre_tombale_chaine_intacte(monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    a = _mission(titre="Données de Dupont")
    _mission(titre="Autre")
    assert archive.effacer(a, "proprietaire", "demande RGPD") >= 1
    lignes = archive.lignes()
    tombe = [l for l in lignes if l["enregistrement"].get("mission_id") == a][0]["enregistrement"]
    assert tombe["efface"] and "à la demande de proprietaire" in tombe["mention"] and "Dupont" not in json.dumps(tombe)
    v = archive.verifier()
    assert v["valide"] and v["effacees"] >= 1
    assert archive.rechercher("Dupont") == []
    assert "archive_effacement" in [x["action"] for x in ledger.lister(200)]


def test_effacement_cockpit_seulement(client, entetes, cockpit):
    mid = _mission()
    assert client.post(f"/api/archive/effacer/{mid}", headers=entetes, json={}).status_code in (404, 405)
    r = client.post(f"/cockpit/api/memoire/archive/effacer/{mid}", headers=cockpit, json={"motif": "test"})
    assert r.status_code == 200 and r.json()["lignes_effacees"] >= 1


# --- Leçons -------------------------------------------------------------------------------------

def test_extraction_deterministe_et_seuil(monkeypatch):
    monkeypatch.setenv("NEXUS_LECONS_SEUIL", "3")
    for i in range(2):
        _mission(titre=f"C{i}", refus=True)
    l = lecons.lister("candidate", service="OPS-CORE/projets")
    assert len(l) == 1 and l[0]["occurrences"] == 2 and l[0]["origine"] == "checker"
    _mission(titre="C3", refus=True)
    p = lecons.lister("proposee")
    assert len(p) == 1 and p[0]["occurrences"] == 3 and p[0]["type"] == "obligation"
    assert "lecon_proposee" in [x["action"] for x in ledger.lister(300)]


def test_une_mission_compte_une_fois():
    mid = _mission(refus=True)
    assert lecons.enregistrer_signaux(mid)["incrementees"] == 0  # déjà comptée en fin d'exécution
    assert lecons.lister()[0]["occurrences"] == 1


def test_signaux_charte_decideur_plafond():
    FournisseurFactice.script["analyst"].append("BROUILLON\n## Post\nRejoignez notre liste d'attente !")
    mid = creer_mission(titre="Post", consigne="Rédige un post", service="CONTENT-ARENA/redaction",
                        projet="poker-winners")
    pipeline.traiter(mid)
    assert any(o == "charte" for o, _ in lecons.signaux(mid))
    mid2 = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid2)
    with session_scope() as s:
        did = s.execute(select(Decision.id).where(Decision.mission_id == mid2)).scalar_one()
    pipeline.decider(did, "refuser", "les prix sont inventés")
    assert ("decideur", "Refus par le Décideur : les prix sont inventés") in lecons.signaux(mid2)
    FournisseurFactice.tokens_par_appel = 4000
    mid3 = creer_mission(titre="Checklist", consigne="Liste", service="OPS-CORE/projets", fonctionnement="F1")
    pipeline.traiter(mid3)
    assert lire_mission(mid3).statut == "plafond_atteint"
    assert any(o == "plafond" for o, _ in lecons.signaux(mid3))


def _proposee(monkeypatch):
    monkeypatch.setenv("NEXUS_LECONS_SEUIL", "1")
    _mission(refus=True)
    return lecons.lister("proposee")[0]["id"]


def test_injection_seulement_si_acceptee_et_bornee(monkeypatch, client, cockpit):
    lid = _proposee(monkeypatch)
    FournisseurFactice.entrees.clear()
    _mission(titre="Avant acceptation")
    assert not any("Leçons apprises" in e for _, e in FournisseurFactice.entrees)
    r = client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit, json={})
    assert r.status_code == 200 and r.json()["statut"] == "acceptee"
    FournisseurFactice.entrees.clear()
    _mission(titre="Après acceptation")
    analyste = [e for r_, e in FournisseurFactice.entrees if r_ == "analyst"][0]
    controle = [e for r_, e in FournisseurFactice.entrees if r_ == "checker"][0]
    assert "Leçons apprises (validées" in analyste and "oublie les responsables" in analyste
    assert "Leçons apprises à vérifier" in controle
    with session_scope() as s:  # bornes : ≤ 5 leçons, ≤ 800 caractères
        for i in range(8):
            s.add(Lecon(cle=f"x{i}", service="OPS-CORE/projets", projet=None, texte=("Règle %d " % i) + "x" * 150,
                        type="methode", origine="checker", statut="acceptee", occurrences=10 + i, sources_json="[]"))
    texte = lecons.actives("OPS-CORE/projets", "nexus")
    assert texte.count("\n- ") + 1 <= 5 and len(texte) <= 800


def test_decisions_reservees_au_cockpit(monkeypatch, client, entetes, cockpit):
    lid = _proposee(monkeypatch)
    assert client.post(f"/api/memoire/lecons/{lid}/accepter", headers=entetes, json={}).status_code in (404, 405)
    r = client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", json={},
                    headers={"X-Cockpit-Auth": cockpit["X-Cockpit-Auth"]})
    assert r.status_code == 403  # anti-CSRF
    r = client.post(f"/cockpit/api/memoire/lecons/{lid}/rejeter", headers=cockpit, json={"motif": "trop vague"})
    assert r.json()["statut"] == "rejetee"
    assert lecons.actives("OPS-CORE/projets", "nexus") == ""


def test_acceptation_avec_reformulation_et_charte(monkeypatch, client, cockpit):
    lid = _proposee(monkeypatch)
    r = client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit,
                    json={"texte": "Toujours nommer un responsable par étape.", "terme_charte": "sans responsable"})
    assert r.status_code == 200
    assert lecons.lister("acceptee")[0]["texte"] == "Toujours nommer un responsable par étape."
    from app import charte
    assert charte.verifier("nexus", "OPS-CORE/projets", "Étape 1 sans responsable.")["bloquants"]


def _tableau(tmp_path, monkeypatch, notes):
    f = tmp_path / "tableau.json"
    f.write_text(json.dumps({"semaines": [{"semaine": s, "note_livrable": n} for s, n in notes]}))
    monkeypatch.setenv("NEXUS_BANC_RESULTATS", str(f))
    return f


def test_suspension_sur_regression(monkeypatch, tmp_path, client, cockpit):
    f = _tableau(tmp_path, monkeypatch, [("2026-W40", 80.0)])
    lid = _proposee(monkeypatch)
    client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit, json={})
    assert lecons.lister("acceptee")[0]["note_activation"] == 80.0
    f.write_text(json.dumps({"semaines": [{"semaine": "2026-W40", "note_livrable": 80},
                                          {"semaine": "2026-W41", "note_livrable": 66},
                                          {"semaine": "2026-W42", "note_livrable": 68}]}))
    assert lecons.verifier_regressions() == []  # 2 mesures < 3 : pas encore de verdict
    f.write_text(json.dumps({"semaines": [{"semaine": "2026-W40", "note_livrable": 80},
                                          {"semaine": "2026-W41", "note_livrable": 66},
                                          {"semaine": "2026-W42", "note_livrable": 68},
                                          {"semaine": "2026-W43", "note_livrable": 67}]}))
    s = lecons.verifier_regressions()
    assert s and s[0]["id"] == lid
    l = lecons.lister("suspendue")[0]
    assert "Régression mesurée" in l["motif"] and lecons.actives("OPS-CORE/projets", "nexus") == ""


def test_pas_de_suspension_si_stable(monkeypatch, tmp_path, client, cockpit):
    _tableau(tmp_path, monkeypatch, [("2026-W40", 80.0)])
    lid = _proposee(monkeypatch)
    client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit, json={})
    _tableau(tmp_path, monkeypatch, [("2026-W40", 80), ("2026-W41", 75), ("2026-W42", 78), ("2026-W43", 76)])
    assert lecons.verifier_regressions() == []


def test_revue_hebdomadaire(monkeypatch):
    _proposee(monkeypatch)
    assert lecons.revue_hebdo(datetime(2026, 11, 9, 6, 0)) is None  # lundi 07:00 Paris : trop tôt
    r = lecons.revue_hebdo(datetime(2026, 11, 9, 8, 0))  # lundi 09:00 Paris
    assert r == {"semaine": "2026-W46", "proposees": 1}
    assert lecons.revue_hebdo(datetime(2026, 11, 9, 9, 0)) is None  # une seule fois


def test_carte_lecons_sur_le_decideur(monkeypatch, client, cockpit):
    _proposee(monkeypatch)
    e = client.get("/cockpit/api/decideur/etat", headers=cockpit).json()
    assert len(e["lecons_proposees"]) == 1


# --- Recherche et rapport -----------------------------------------------------------------------------

def test_recherche_commune(monkeypatch, client, entetes, cockpit):
    from app import memoire
    memoire.ajouter("nexus", "Chantier", "Le chantier du VPS se fait par étapes.", "note", "api")
    lid = _proposee(monkeypatch)
    client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit, json={})
    r = client.get("/api/memoire/recherche?q=responsables chantier&projet=nexus", headers=entetes).json()
    assert r["connaissances"] and r["lecons"] and r["archive"]
    assert client.get("/api/memoire/recherche?q=chantier").status_code == 401
    assert client.get("/cockpit/api/memoire/recherche?q=chantier", headers=cockpit).status_code == 200


def test_rapport(monkeypatch, client, entetes):
    _proposee(monkeypatch)
    r = client.get("/api/memoire/rapport", headers=entetes).json()
    assert r["proposees_en_attente"] and r["erreurs_frequentes"] and "satisfaction" in r
    assert client.get("/api/archive/verifier", headers=entetes).json()["valide"]
