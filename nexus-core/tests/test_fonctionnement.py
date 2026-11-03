"""Niveaux de fonctionnement F1..F4 : grille, défaut, relèvements, F4, plafonds, double contrôle, API."""
import json

import pytest
import yaml
from sqlalchemy import select

from app import fonctionnement as fct
from app import ledger, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Decision, Etape, Mission

from .conftest import creer_mission, lire_mission

REFUS = json.dumps({"ok": False, "problemes": ["défaut relevé"]})
ACCEPTE = json.dumps({"ok": True, "problemes": []})


def _actions(mid=None):
    return [e["action"] for e in ledger.lister(500) if mid is None or e["mission_id"] == mid]


@pytest.fixture
def f4_dispo(monkeypatch):
    monkeypatch.setenv("BUDGET_MONTHLY_EUR", "5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


# --- Grille --------------------------------------------------------------------------

def test_chargement_grille():
    f1, f2, f3, f4 = (fct.niveau(c) for c in fct.CODES)
    assert (f1.nom, f1.fournisseur, f1.budget_tokens, f1.revisions_max, f1.double_controle,
            f1.llm_max_chars, f1.num_ctx, f1.delai_max_s, f1.cout_max_eur) == (
        "Éclair", "ollama_local", 6000, 0, False, 4000, 4096, 180, 0)
    assert (f2.budget_tokens, f2.revisions_max, f2.llm_max_chars, f2.num_ctx, f2.delai_max_s) == (
        20000, 1, 12000, 8192, 600)
    assert (f3.budget_tokens, f3.revisions_max, f3.double_controle, f3.llm_max_chars, f3.delai_max_s) == (
        40000, 2, True, 16000, 1200)
    assert (f4.fournisseur, f4.budget_tokens, f4.revisions_max, f4.cout_max_eur) == ("anthropic", 80000, 3, 0.5)
    assert f4.modele_role("analyst") == "claude-sonnet-5-5" and f4.modele_role("collector") == "claude-haiku-5-5"
    assert f4.modele_role("gate") == "claude-haiku-5-5"
    # Tarifs : 1 M tokens d'entrée Sonnet = 2 $ = 1,84 € au taux par défaut.
    assert fct.cout_appel_eur("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(1.84)
    with pytest.raises(ValueError):
        fct.niveau("F9")


def test_f2_reprend_les_variables_existantes(monkeypatch):
    monkeypatch.setenv("BUDGET_TASK_TOKENS", "15000")
    monkeypatch.setenv("LLM_MAX_CHARS", "9000")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    f2 = fct.niveau("F2")
    assert (f2.budget_tokens, f2.llm_max_chars, f2.num_ctx) == (15000, 9000, 6144)
    assert fct.niveau("F3").budget_tokens == 40000  # les autres niveaux ne changent pas


def test_eur_par_usd_configurable(monkeypatch):
    monkeypatch.setenv("EUR_PAR_USD", "1")
    assert fct.cout_appel_eur("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)


# --- Défaut ---------------------------------------------------------------------------

def test_defaut_f2(client, entetes, monkeypatch):
    r = client.post("/api/missions", headers=entetes, json={"titre": "Checklist", "consigne": "Liste les étapes",
                                                             "service": "OPS-CORE/projets"})
    assert r.json()["fonctionnement"] == "F2"
    m = client.get(f"/api/missions/{r.json()['id']}", headers=entetes).json()
    assert m["fonctionnement_demande"] == "F2" and m["fonctionnement"] == "F2"
    assert client.get("/api/sante").json()["fonctionnement_defaut"] == "F2"
    monkeypatch.setenv("NEXUS_FONCTIONNEMENT_DEFAUT", "F1")
    assert client.get("/api/sante", headers=entetes).json()["fonctionnement_defaut"] == "F1"
    r = client.post("/api/missions", headers=entetes, json={"titre": "a", "consigne": "Liste les étapes"})
    assert r.json()["fonctionnement"] == "F1"
    assert client.post("/api/missions", headers=entetes,
                       json={"titre": "a", "consigne": "b", "fonctionnement": "F7"}).status_code == 422


# --- Relèvements automatiques ---------------------------------------------------------

def test_releve_f1_vers_f2_par_gate_n2():
    mid = creer_mission(titre="Revue", consigne="Relis ce code Python", service="CODE-CORE/revue",
                        fonctionnement="F1", fonctionnement_demande="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.fonctionnement_demande == "F1" and m.fonctionnement == "F2"
    assert "GATE N2" in m.fonctionnement_raison
    assert "fonctionnement_releve" in _actions(mid)


def test_releve_f1_vers_f2_par_gate_sur_livrable():
    # Consigne anodine (N1) mais livrable N3 : relèvement tardif + nouveau passage qualité.
    FournisseurFactice.script["analyst"].append("BROUILLON\n- Étape 1 : déployer en production")
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.fonctionnement == "F2" and "livrable" in m.fonctionnement_raison
    assert FournisseurFactice.appels.count("checker") == 2 and FournisseurFactice.appels.count("gate") == 2
    assert m.statut == "en_attente_n3"


@pytest.mark.parametrize("service", ["LEX-GUARD/droit-france", "PILOT-CORE/etudes"])
def test_plancher_f3_droit_et_pilotage(service):
    mid = creer_mission(titre="Question", consigne="Quelle règle s'applique ?", service=service,
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.fonctionnement == "F3" and f"service {service}" in m.fonctionnement_raison


def test_jamais_de_descente():
    mid = creer_mission(titre="Synthèse", consigne="Fais une synthèse interne", service="R&D-PARADOX/veille",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    assert lire_mission(mid).fonctionnement == "F3"


# --- F4 ---------------------------------------------------------------------------------

def test_f4_refuse_budget_zero_avec_repli_f3(client, entetes):
    r = client.post("/api/missions", headers=entetes,
                    json={"titre": "Étude", "consigne": "Liste les étapes", "fonctionnement": "F4"})
    assert r.status_code == 202
    d = r.json()
    assert d["fonctionnement_demande"] == "F4" and d["fonctionnement"] == "F3"
    assert d["message"] == "F4 indisponible : budget IA à 0 € — mission lancée en F3"
    m = client.get(f"/api/missions/{d['id']}", headers=entetes).json()
    assert m["fonctionnement"] == "F3" and m["statut"] == "terminee"
    assert m["fonctionnement_raison"] == "F4 indisponible : budget IA à 0 € — mission lancée en F3"


def test_f4_refuse_sans_repli(client, entetes, monkeypatch):
    r = client.post("/api/missions", headers=entetes, json={"titre": "Étude", "consigne": "x",
                                                             "fonctionnement": "F4", "repli_f3": False})
    assert r.status_code == 422 and "budget IA à 0 €" in r.json()["detail"]
    monkeypatch.setenv("BUDGET_MONTHLY_EUR", "5")  # budget mais pas de clé
    r = client.post("/api/missions", headers=entetes, json={"titre": "Étude", "consigne": "x",
                                                             "fonctionnement": "F4", "repli_f3": False})
    assert r.status_code == 422 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert client.get("/api/missions", headers=entetes).json() == []
    assert "f4_refuse" in _actions()


def test_f4_budget_restant_insuffisant(f4_dispo, monkeypatch):
    monkeypatch.setenv("BUDGET_MONTHLY_EUR", "0.10")  # estimation F4 ≈ 0,29 €
    assert "budget mensuel restant" in fct.disponibilite_f4()


def test_f4_decision_n3_avant_lancement(client, entetes, f4_dispo):
    r = client.post("/api/missions", headers=entetes,
                    json={"titre": "Business plan", "consigne": "Liste les étapes", "service": "OPS-CORE/projets",
                          "fonctionnement": "F4"})
    d = r.json()
    assert d["statut"] == "en_attente_n3" and d["fonctionnement"] == "F4"
    estime = fct.estimer_cout_eur("F4")["cout_estime_eur"]
    assert 0 < estime <= 0.5 and d["cout_estime_eur"] == estime
    assert FournisseurFactice.appels == []  # rien n'est exécuté avant l'accord
    decs = client.get("/api/decisions?statut=en_attente", headers=entetes).json()
    assert len(decs) == 1 and decs[0]["objet"] == "lancement_f4"
    assert decs[0]["resume"].startswith(f"Lancer en F4 — coût estimé {estime:.2f} €")
    assert decs[0]["cout_estime_eur"] == estime
    # Révision impossible ; validation → lancement réel.
    assert client.post(f"/api/decisions/{decs[0]['id']}/reviser", headers=entetes).status_code == 409
    v = client.post(f"/api/decisions/{decs[0]['id']}/valider", headers=entetes).json()
    assert v["lancer"] is True
    m = client.get(f"/api/missions/{d['id']}", headers=entetes).json()
    assert m["statut"] == "terminee" and m["fonctionnement"] == "F4"
    assert 0 < m["cout_eur"] <= 0.5 and m["tokens_entree"] > 0 and m["tokens_sortie"] > 0
    # Modèles par rôle transmis au fournisseur et coût journalisé par appel.
    appels = [e for e in ledger.lister(200) if e["mission_id"] == d["id"] and e["action"].startswith("appel_")]
    modeles = {e["details"]["modele"] for e in appels}
    assert {"claude-sonnet-5-5", "claude-haiku-5-5"} <= modeles
    assert all(e["details"]["cout_eur"] > 0 for e in appels if not e["details"]["double_controle"])


def test_f4_refuse_par_le_proprietaire(client, entetes, f4_dispo):
    mid = client.post("/api/missions", headers=entetes,
                      json={"titre": "X", "consigne": "Liste les étapes", "fonctionnement": "F4"}).json()["id"]
    did = client.get("/api/decisions?statut=en_attente", headers=entetes).json()[0]["id"]
    client.post(f"/api/decisions/{did}/refuser", headers=entetes)
    assert client.get(f"/api/missions/{mid}", headers=entetes).json()["statut"] == "refusee"
    assert FournisseurFactice.appels == []


def test_f4_plafond_de_cout(client, entetes, f4_dispo, tmp_path, monkeypatch):
    grille = yaml.safe_load(fct.chemin().read_text(encoding="utf-8"))
    grille["niveaux"]["F4"]["cout_max_eur"] = 0.01
    fichier = tmp_path / "fonctionnement.yaml"
    fichier.write_text(yaml.safe_dump(grille, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("NEXUS_FONCTIONNEMENT_FILE", str(fichier))
    fct.charger(recharger=True)
    FournisseurFactice.tokens_par_appel = 4000  # appels coûteux au tarif Sonnet
    mid = client.post("/api/missions", headers=entetes, json={"titre": "X", "consigne": "Liste les étapes",
                                                              "service": "OPS-CORE/projets",
                                                              "fonctionnement": "F4"}).json()["id"]
    did = client.get("/api/decisions?statut=en_attente", headers=entetes).json()[0]["id"]
    client.post(f"/api/decisions/{did}/valider", headers=entetes)
    m = client.get(f"/api/missions/{mid}", headers=entetes).json()
    assert m["statut"] == "plafond_atteint" and "Coût maximal" in m["message"]
    assert m["cout_eur"] <= 0.01  # jamais de dépassement : arrêt avant l'appel de trop


# --- Plafonds -----------------------------------------------------------------------

def test_delai_depasse_arret_propre(monkeypatch):
    t = {"v": 0.0}

    def horloge():
        t["v"] += 20.0  # chaque lecture du chrono avance de 20 s
        return t["v"]
    monkeypatch.setattr(pipeline, "_horloge", horloge)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "plafond_atteint"
    assert "Délai maximal du niveau F1" in m.message and "niveau supérieur (F2)" in m.message
    assert m.livrable_texte  # livrable partiel conservé
    assert m.duree_s > 180
    assert "plafond_atteint" in _actions(mid) and "mission_bilan" in _actions(mid)


def test_budget_tokens_depasse_arret_propre():
    FournisseurFactice.tokens_par_appel = 2500  # F1 : 6 000 tokens
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "plafond_atteint" and "Budget de tokens du niveau F1" in m.message
    assert m.tokens == 7500 and "relancer la mission au niveau supérieur (F2)" in m.message
    assert m.livrable_texte


# --- Double contrôle -----------------------------------------------------------------

def test_double_controle_f3_refus_puis_revision():
    # CHECKER principal OK, contrôle local refuse → révision ; puis les deux valident.
    FournisseurFactice.script["checker"].extend([ACCEPTE, REFUS, ACCEPTE, ACCEPTE])
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F3")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "terminee" and m.revisions == 1
    assert FournisseurFactice.appels.count("analyst") == 2 and FournisseurFactice.appels.count("checker") == 4
    with session_scope() as s:
        locaux = s.execute(select(Etape).where(Etape.mission_id == mid)
                           .where(Etape.role == "checker_local")).scalars().all()
        verdicts = [e.verdict for e in locaux if e.verdict]
    assert verdicts == ["refus", "ok"]
    analyste = [e for r, e in FournisseurFactice.entrees if r == "analyst"][1]
    assert "[double contrôle] défaut relevé" in analyste


def test_f2_sans_double_controle():
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F2")
    pipeline.traiter(mid)
    assert FournisseurFactice.appels.count("checker") == 1


def test_f1_aucune_correction():
    FournisseurFactice.script["checker"].append(REFUS)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.statut == "echouee" and FournisseurFactice.appels.count("analyst") == 1
    assert "1 fois" in m.message and "0 correction" in m.message


# --- Mesures et API -------------------------------------------------------------------

def test_mesures_et_route_fonctionnement(client, entetes):
    for f in ("F1", "F2", "F2"):
        client.post("/api/missions", headers=entetes, json={"titre": "Checklist", "consigne": "Liste les étapes",
                                                             "service": "OPS-CORE/projets", "fonctionnement": f})
    m = client.get("/api/missions", headers=entetes).json()[0]
    assert m["tokens_entree"] > 0 and m["tokens_sortie"] > 0
    assert m["tokens"] == m["tokens_entree"] + m["tokens_sortie"] and m["duree_s"] >= 0
    bilan = [e for e in ledger.lister(300) if e["action"] == "mission_bilan" and e["mission_id"] == m["id"]]
    assert bilan and bilan[0]["details"]["fonctionnement"] == "F2"
    r = client.get("/api/fonctionnement", headers=entetes).json()
    assert [n["code"] for n in r["niveaux"]] == ["F1", "F2", "F3", "F4"] and r["defaut"] == "F2"
    conso = {c["code"]: c for c in r["consommation"]}
    assert conso["F1"]["missions"] == 1 and conso["F2"]["missions"] == 2 and conso["F4"]["missions"] == 0
    assert conso["F2"]["tokens"] > 0 and conso["F2"]["duree_moyenne_s"] is not None
    assert r["f4_indisponible"] == "budget IA à 0 €"
    assert client.get("/api/fonctionnement").status_code == 401
    assert client.get("/cockpit/api/fonctionnement").status_code == 200


def test_migration_colonnes_fonctionnement(tmp_path, monkeypatch):
    import sqlite3
    from sqlalchemy import inspect
    from app import db
    chemin = tmp_path / "v1.db"
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE missions (id INTEGER PRIMARY KEY, titre VARCHAR(200), consigne TEXT,
                 service VARCHAR(80), statut VARCHAR(20), niveau VARCHAR(2), cree_le DATETIME, maj_le DATETIME,
                 livrable_texte TEXT, tokens INTEGER, cout_eur FLOAT, montant_eur FLOAT, action VARCHAR(40),
                 directeur VARCHAR(40), message TEXT, projet VARCHAR(40) NOT NULL DEFAULT 'divers')""")
    c.execute("""CREATE TABLE decisions (id INTEGER PRIMARY KEY, mission_id INTEGER, niveau VARCHAR(2),
                 resume TEXT, recommandation TEXT, cout_estime_eur FLOAT, risque VARCHAR(10), sources TEXT,
                 avis_checker TEXT, statut VARCHAR(12), cree_le DATETIME, decide_le DATETIME, commentaire TEXT)""")
    c.execute("INSERT INTO missions (id, titre, consigne, statut, cree_le, maj_le, tokens, cout_eur, montant_eur) "
              "VALUES (1, 'Ancienne', 'x', 'terminee', '2026-01-01', '2026-01-01', 10, 0, 0)")
    c.commit()
    c.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{chemin}")
    db.reinitialiser()
    db.init_db()
    cols = {x["name"] for x in inspect(db.engine()).get_columns("missions")}
    assert {"fonctionnement", "fonctionnement_demande", "tokens_entree", "duree_s", "repli_f3"} <= cols
    assert "objet" in {x["name"] for x in inspect(db.engine()).get_columns("decisions")}
    with session_scope() as s:
        m = s.get(Mission, 1)
        assert m.fonctionnement == "F2" and m.repli_f3 is True and m.tokens_entree == 0


def test_f1_sans_ia_locale_releve_en_f2(monkeypatch):
    # Installation « --sans-repli » : pas d'IA locale, F1 est impossible → F2 (jamais d'échec silencieux).
    from app.llm import FournisseurFactice as Faux
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(pipeline, "ollama_local_joignable", lambda: False)
    monkeypatch.setattr(pipeline, "fournisseur_niveau", lambda *a, **k: Faux())
    monkeypatch.setattr(pipeline, "fournisseur_controle_local", lambda *a, **k: Faux())
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets",
                        fonctionnement="F1")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.fonctionnement == "F2" and "IA locale injoignable" in m.fonctionnement_raison
    assert m.statut == "terminee"
