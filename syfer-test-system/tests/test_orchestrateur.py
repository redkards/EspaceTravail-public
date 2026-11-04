"""Tests de l'orchestrateur SYFER Test System v1 : formule de score, porte, agrégation, saut propre."""
import copy
import json

import pytest

import syfer_test as ST
from sts import commun as C
from sts import porte as P
from sts import score as S
from sts import suites as T


# ----------------------------------------------------------------- formule de score

def test_score_parfait_et_formule(suites_vertes):
    f = S.fiche(suites_vertes)
    assert f["axes"]["fiabilite"]["score"] == 100.0
    assert f["axes"]["securite"]["score"] == 100.0
    # coût : 15 € sur une borne de 150 € → 90
    assert f["axes"]["cout"]["score"] == 90.0
    # charge Décideur : n3 2/j → 100, 0 expiration → 100, délai 5 h → 100
    assert f["axes"]["decideur"]["score"] == 100.0
    # résilience : jumeau_panne = moyenne(100, 90) = 95 → (0,3·100 + 0,25·100 + 0,25·95 + 0,2·100) = 98,75
    assert f["axes"]["resilience"]["score"] == pytest.approx(98.8, abs=0.06)
    assert f["couverture_globale"] == 1.0
    conf = C.lire_json(C.CONFIG / "ponderation.json")
    attendu = sum(f["axes"][a]["score"] * conf["axes"][a]["poids"] for a in conf["axes"]) / \
        sum(v["poids"] for v in conf["axes"].values())
    assert f["global"] == pytest.approx(attendu, abs=0.06)


def test_score_renormalise_si_composante_absente(suites_vertes):
    s = copy.deepcopy(suites_vertes)
    s["tests"]["mesures"]["taux_reussite"] = 50.0
    del s["iterations"]
    f = S.fiche(s)
    # fiabilité = (0,40·50 + 0,30·100 + 0,05·100) / 0,75
    assert f["axes"]["fiabilite"]["score"] == pytest.approx((0.4 * 50 + 0.3 * 100 + 0.05 * 100) / 0.75, abs=0.06)
    assert f["axes"]["fiabilite"]["couverture"] == 0.75


def test_score_ponderation_modifiable(suites_vertes):
    conf = C.lire_json(C.CONFIG / "ponderation.json")
    conf["axes"] = {"cout": dict(conf["axes"]["cout"], poids=1.0)}
    f = S.fiche(suites_vertes, conf)
    assert f["global"] == 90.0 and list(f["axes"]) == ["cout"]


def test_score_penalites_securite(suites_vertes):
    s = copy.deepcopy(suites_vertes)
    s["statiques"]["mesures"]["secrets_suspects"] = 1
    s["attaque"]["mesures"].update(faux_positifs=2, faux_positifs_bloquants=1)
    c = S.composantes(s, C.lire_json(C.CONFIG / "ponderation.json"))
    assert c["secrets"] == 50.0 and c["attaque"] == 100 - 10 - 2


def test_axes_absents_donnent_none(fabrique):
    f = S.fiche({"tests": fabrique("tests", "saute")})
    assert f["global"] is None and all(a["score"] is None for a in f["axes"].values())


# ----------------------------------------------------------------- porte de qualité

def test_porte_verte(suites_vertes):
    pt = P.evaluer(suites_vertes, 95.0, 96.0)
    assert pt["verdict"] == "VERT" and pt["deploiement_autorise"] and not pt["raisons"]


@pytest.mark.parametrize("modif, critere", [
    (lambda s: s["tests"]["mesures"].update(echoues=1), "tests_verts"),
    (lambda s: s["simulations"]["mesures"].update(taux_reussite=98.0), "simulations"),
    (lambda s: s["iterations"]["mesures"].update(critiques_ouverts=1), "iterations_critiques"),
    (lambda s: s["attaque"]["mesures"].update(taux_blocage_pct=94.0), "attaque"),
    (lambda s: s["attaque"]["mesures"].update(faux_positifs_bloquants=1), "attaque"),
    (lambda s: s["statiques"]["mesures"].update(secrets_suspects=1), "secrets"),
    (lambda s: s["charge"]["mesures"].update(pertes_donnees=["S04:doublons_max"]), "charge_sans_perte"),
])
def test_porte_rouge_avec_raison(suites_vertes, modif, critere):
    s = copy.deepcopy(suites_vertes)
    modif(s)
    pt = P.evaluer(s, 95.0, 95.0)
    assert pt["verdict"] == "ROUGE"
    assert [c["critere"] for c in pt["criteres"] if c["bloque"]] == [critere]
    assert pt["raisons"]


def test_porte_regression_du_banc(suites_vertes):
    assert P.evaluer(suites_vertes, 90.0, 95.0)["verdict"] == "VERT"     # baisse de 5 : tolérée
    pt = P.evaluer(suites_vertes, 89.0, 95.0)                              # baisse de 6 : bloquante
    assert pt["verdict"] == "ROUGE" and "baisse de 6.0 points" in pt["raisons"][0]
    assert P.evaluer(suites_vertes, 50.0, None)["verdict"] == "VERT"     # premier passage


def test_porte_suite_absente_bloquante_ou_ignoree(suites_vertes):
    s = copy.deepcopy(suites_vertes)
    s["iterations"] = {"nom": "iterations", "statut": "saute", "motif": "iterer.py absent", "mesures": {}, "defauts": []}
    pt = P.evaluer(s, 95.0, None)
    c = next(c for c in pt["criteres"] if c["critere"] == "iterations_critiques")
    assert pt["verdict"] == "ROUGE" and c["etat"] == "NON ÉVALUÉ" and "iterer.py absent" in c["raison"]
    conf = C.lire_json(C.CONFIG / "porte.json")
    conf["criteres"]["iterations_critiques"]["si_absent"] = "ignore"
    assert P.evaluer(s, 95.0, None, conf)["verdict"] == "VERT"


def test_porte_critere_desactive(suites_vertes):
    s = copy.deepcopy(suites_vertes)
    s["statiques"]["mesures"]["secrets_suspects"] = 3
    conf = C.lire_json(C.CONFIG / "porte.json")
    conf["criteres"]["secrets"]["actif"] = False
    assert P.evaluer(s, 95.0, None, conf)["verdict"] == "VERT"


# ----------------------------------------------------------------- saut propre des suites absentes

@pytest.fixture
def ctx_vide(tmp_path):
    bac = tmp_path / "bac"
    bac.mkdir()
    return T.Contexte(bac, tmp_path / "sortie", ST.charger_profil("A"), "rapide", 1)


@pytest.mark.parametrize("nom", ["protocole", "simulations", "iterations", "attaque", "banc", "charge", "jumeau",
                                 "compaction"])
def test_suite_absente_sautee_proprement(ctx_vide, nom):
    r = T.lancer_suite(nom, ctx_vide)
    assert r["statut"] == "saute" and r["motif"] and r["defauts"] == []


def test_tests_unitaires_tous_absents(ctx_vide):
    r = T.lancer_suite("tests", ctx_vide)
    assert r["statut"] == "saute"
    assert all(v["statut"] == "saute" for v in r["mesures"]["par_dossier"].values())


def test_integration_automatique_quand_le_dossier_apparait(ctx_vide):
    """Un dossier apparu entre deux passages est pris en compte sans configuration."""
    assert T.lancer_suite("iterations", ctx_vide)["motif"] == "dossier iterations-100/ absent"
    (ctx_vide.bac / "iterations-100").mkdir()
    assert "iterer.py absent" in T.lancer_suite("iterations", ctx_vide)["motif"]


def test_epreuve_qui_plante_ne_casse_pas_l_orchestrateur(ctx_vide, monkeypatch):
    def boum(ctx):
        raise RuntimeError("panne simulée")
    monkeypatch.setitem(T.SUITES, "attaque", (boum, "Attaque"))
    ctx_vide.sortie.mkdir(parents=True)
    r = T.lancer_suite("attaque", ctx_vide)
    assert r["statut"] == "erreur" and "panne simulée" in r["motif"]


# ----------------------------------------------------------------- agrégation

def test_trier_defauts_dedoublonne_et_classe():
    d = [T.defaut("a", "mineure", "x", "", "", "", ident="1"), T.defaut("b", "critique", "y", "", "", "", ident="2"),
         T.defaut("c", "haute", "z", "", "", "", ident="3"), T.defaut("a", "mineure", "x", "", "", "", ident="1")]
    out = ST.trier_defauts(d)
    assert [x["id"] for x in out] == ["2", "3", "1"] and out[1]["gravite"] == "majeure"


def test_gravite_numerique_iterations():
    assert T._gravite({"gravite": 1}) == "critique" and T._gravite({"gravite": 3}) == "mineure"
    assert not T._ouvert({"reproduit": False}) and T._ouvert({"gravite": 1})


def test_passage_complet_ecrit_le_schema(tmp_path, monkeypatch):
    """Passage sur un dépôt vide : rien ne plante, tout est sauté, la porte est ROUGE (aucune preuve)."""
    bac = tmp_path / "x" / "depot"
    bac.mkdir(parents=True)
    monkeypatch.setattr(C, "RESULTATS", tmp_path / "resultats")
    monkeypatch.setattr(C, "creer_bac", lambda *a, **k: bac)
    monkeypatch.setattr(C, "supprimer_bac", lambda b: None)
    rc = ST.passage(["iterations", "charge", "compaction"], "rapide", "A", 7, pdf=False)
    assert rc == 1
    f = next((tmp_path / "resultats").glob("*/syfer_test.json"))
    doc = json.loads(f.read_text(encoding="utf-8"))
    for cle in ("schema", "horodatage", "mode", "graine", "profil", "suites", "score", "porte", "defauts", "tendance",
                "depot"):
        assert cle in doc
    assert doc["schema"] == ST.SCHEMA and doc["graine"] == 7
    assert {s["statut"] for s in doc["suites"].values()} == {"saute"}
    assert doc["porte"]["verdict"] == "ROUGE"


def test_rapport_pdf_genere(tmp_path, suites_vertes):
    from sts import rapport_pdf
    fiche = S.fiche(suites_vertes)
    base = {"schema": ST.SCHEMA, "horodatage": "2026-01-01_000000", "mode": "tout", "graine": 1, "duree_s": 60,
            "profil": {"code": "A", "nom": "Éco"}, "suites": suites_vertes, "score": fiche,
            "porte": P.evaluer(suites_vertes, 90, None), "defauts": [], "tendance": []}
    profil = ST.charger_profil("A")
    vers = {"horodatage": "2026-01-01_000100", "graine": 1, "classement": ["A"], "suites_comparees": ["jumeau"],
            "versions": {"A": {"profil": profil, "suites": suites_vertes, "score": fiche, "defauts": []}}}
    cible = rapport_pdf.produire(base, vers, [], tmp_path / "r.pdf")
    assert cible.read_bytes()[:4] == b"%PDF" and cible.stat().st_size > 5000


# ----------------------------------------------------------------- versions, secrets, journal

def test_profils_de_version_valides():
    import importlib.util
    spec = importlib.util.spec_from_file_location("jumeau_test", C.DEPOT / "jumeau-numerique" / "jumeau.py")
    if spec is None or not (C.DEPOT / "jumeau-numerique" / "jumeau.py").exists():
        pytest.skip("jumeau-numerique absent")
    hyp = json.loads((C.DEPOT / "jumeau-numerique" / "hypotheses.json").read_text(encoding="utf-8"))
    for code in ST.CODES_VERSIONS:
        p = ST.charger_profil(code)
        assert p["code"] == code and p["env"] and p["jumeau"] and p["suites"]
        assert set(p["suites"]) <= set(T.SUITES)
        assert set(p["jumeau"]["surcharges"]) <= set(hyp["parametres"])
        assert all(isinstance(v, str) for v in p["env"].values())
    assert ST.charger_profil("C")["jumeau"]["payant_plafond_eur"] == 30
    assert ST.charger_profil("E")["jumeau"]["payant_plafond_eur"] <= 80
    assert ST.charger_profil("D")["env"]["NEXUS_FONCTIONNEMENT_DEFAUT"] == "F3"


def test_recherche_de_secrets(tmp_path):
    faux = "sk-" + "ant-" + "Q7r" * 8                    # construit : jamais écrit tel quel dans le dépôt
    (tmp_path / "app.py").write_text(f"CLE = '{faux}'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(f"CLE = '{faux}'\n", encoding="utf-8")
    (tmp_path / "conf.yaml").write_text("password: " + "Zk3" * 4 + "\n", encoding="utf-8")
    r = T.rechercher_secrets(tmp_path)
    assert {s["fichier"] for s in r["suspects"]} == {"app.py", "conf.yaml"}
    assert r["factices"] == 1
    assert all(faux not in s["extrait"] for s in r["suspects"])


def test_journal_sans_secret():
    faux = "gh" + "p_" + "A1b2C3d4" * 4
    assert faux not in C.masquer(f"jeton {faux} fin") and "<SECRET MASQUÉ>" in C.masquer(f"jeton {faux}")


def test_env_sans_variable_sensible(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x" * 20)
    monkeypatch.setenv("NEXUS_API_KEY", "y" * 20)
    e = C.env_base({"NEXUS_MODEL": "m"})
    assert "ANTHROPIC_API_KEY" not in e and "NEXUS_API_KEY" not in e
    assert e["NEXUS_MODEL"] == "m" and e["LLM_PROVIDER"] == "fake"


def test_delai_max_tue_la_commande(tmp_path):
    import sys
    r = C.executer([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, C.env_base(), 1)
    assert r["delai_depasse"] and r["duree_s"] < 10
