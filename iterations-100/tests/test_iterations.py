"""Tests de la méthode des 100 itérations : reproductibilité, réduction, oracles sur cas connus.

Lancer : cd iterations-100 && python3 -m pytest -q tests
"""
import copy
import sys
from pathlib import Path

import pytest

ICI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ICI))

import executer  # noqa: E402
import generateur as gen  # noqa: E402
import iterer  # noqa: E402
import oracles  # noqa: E402


def neutre() -> dict:
    return {d: gen.neutre(d) for d in gen.dimensions()}


# --- Reproductibilité ---------------------------------------------------------------------------

def test_briques_valides():
    doc = gen.charger_briques()
    assert len(doc["dimensions"]) >= 10
    for nom, dim in doc["dimensions"].items():
        assert dim["neutre"] in dim["index"], nom


def test_meme_graine_meme_scenario():
    for g in (1, 42, 123456789):
        a, b = gen.generer(g), gen.generer(g)
        assert a == b
        assert gen.materialiser(a) == gen.materialiser(b)
        assert gen.actions(a) == gen.actions(b)


def test_graines_differentes_scenarios_differents():
    vus = {gen.signature(gen.generer(gen.graine_scenario(2026, 1, r))["briques"]) for r in range(20)}
    assert len(vus) >= 15


def test_graine_scenario_stable():
    assert gen.graine_scenario(2026, 3, 7) == gen.graine_scenario(2026, 3, 7)
    assert gen.graine_scenario(2026, 3, 7) != gen.graine_scenario(2026, 3, 8)


def test_mini_scenario_de_1_a_5_actions():
    for g in range(300):
        n = len(gen.actions(gen.generer(g)))
        assert 1 <= n <= 5


def test_exploration_guidee_favorise_les_voisins():
    voisin = {**neutre(), "verbe": "supprimer"}
    n = sum(gen.generer(g, voisins=[voisin], p_voisin=1.0)["origine"] == "voisin" for g in range(50))
    assert n == 50
    # un voisin garde la plupart des briques du défaut
    proches = sum(gen.generer(g, voisins=[voisin], p_voisin=1.0)["briques"]["verbe"] == "supprimer" for g in range(50))
    assert proches >= 35


# --- Réduction ----------------------------------------------------------------------------------

def test_reduction_synthetique(monkeypatch, tmp_path):
    """L'oracle ne dépend que de verbe=supprimer et montant≠aucun : la réduction ne garde que ces deux briques."""
    monkeypatch.setattr(iterer, "DEFAUTS", tmp_path)
    m = iterer.Methode(1, 5, bavard=False)

    def faux_executer(sc, reduction=False):
        b = sc["briques"]
        viol = b["verbe"] == "supprimer" and b["montant"] != "aucun"
        return ([{"oracle": "O02", "observe": "x", "attendu": "y", "gravite": 1}] if viol else []), None

    monkeypatch.setattr(m, "executer", faux_executer)
    sc = gen.generer(99)
    sc["briques"].update(verbe="supprimer", montant="grand-k", service="pilotage", contenu="veille-D",
                         decideur="valider-api", evenement="double-clic-decision")
    minimal = m.reduire(sc, "O02")
    assert gen.non_neutres(minimal) == {"verbe": "supprimer", "montant": "grand-k"}


def test_dedoublonnage_par_cause(monkeypatch, tmp_path):
    monkeypatch.setattr(iterer, "DEFAUTS", tmp_path)
    m = iterer.Methode(1, 5, bavard=False)
    monkeypatch.setattr(iterer.executer, "jouer", lambda sc: {"materiel": {}})
    monkeypatch.setattr(iterer.oracles, "verifier", lambda obs, seulement=None: [
        {"oracle": "O04", "observe": "risque moyen", "attendu": "eleve", "gravite": 2}])
    a = {**neutre(), "montant": "grand-lettres", "verbe": "vire-tu"}
    b = {**neutre(), "montant": "grand-lettres", "reponse_ia": "gate-n3"}
    d1, neuf1 = m.enregistrer("O04", {"graine": 1, "briques": a}, a, 1)
    d2, neuf2 = m.enregistrer("O04", {"graine": 2, "briques": b}, b, 2)
    assert neuf1 and not neuf2 and d1 is d2 and d1["occurrences"] == 2
    assert (tmp_path / f"{d1['id']}.json").is_file()
    assert m.deja_explique("O04", {**neutre(), "montant": "grand-lettres", "projet": "nexus"}) is d1


@pytest.mark.lent
def test_reduction_reelle_verbe_supprimer(monkeypatch, tmp_path):
    """Exécution réelle : « Supprime … » + briques parasites → cas minimal = verbe seul (si le défaut existe)."""
    monkeypatch.setattr(iterer, "DEFAUTS", tmp_path)
    sc = {"graine": 4242, "briques": {**neutre(), "verbe": "supprimer", "projet": "nexus", "gabarit": "mail"}}
    obs = executer.jouer(sc)
    if not [v for v in oracles.verifier(obs) if v["oracle"] == "O02"]:
        pytest.skip("défaut corrigé dans nexus-core : plus rien à réduire")
    m = iterer.Methode(1, 5, bavard=False)
    assert gen.non_neutres(m.reduire(sc, "O02")) == {"verbe": "supprimer"}


# --- Oracles sur cas connus (observations synthétiques) -------------------------------------------

def obs_base(**briques) -> dict:
    b = {**neutre(), **briques}
    return {"graine": 1, "briques": b, "http": [], "mission_id": 1, "missions_creees": [1], "exceptions": [],
            "decision_appels": [], "decisions": [], "exports_qg": [],
            "materiel": {"secret": "sk-ant-api03-SECRET", "canari": "CANARI-SIM-ABCDEF", "marqueur": "ZQX0000001",
                         "consigne": "c", "montant_texte": ""},
            "missions": {1: {"id": 1, "statut": "terminee", "niveau": "N1", "service": "OPS-CORE/projets",
                             "projet": "divers", "action": None, "fonctionnement": "F2", "livrable": "ok",
                             "charte_avertissements": [], "alertes_bouclier": [], "message": "",
                             "fichier_livrable": "x"}},
            "ledger": {"verif": {"valide": True}, "entrees": [
                {"id": 1, "acteur": "GATE", "action": "routage", "mission_id": 1, "details": {}},
                {"id": 2, "acteur": "GATE", "action": "appel_analyst", "mission_id": 1, "details": {"fonctionnement": "F2"}},
                {"id": 3, "acteur": "GATE", "action": "classement", "mission_id": 1, "details": {"niveau": "N1"}}]},
            "archive": {"valide": True}, "fuites": {}}


def ids(obs) -> set:
    return {v["oracle"] for v in oracles.verifier(obs)}


def test_cas_sain_aucune_violation():
    assert ids(obs_base()) == set()


def test_api_qui_valide_est_une_violation():
    o = obs_base()
    o["http"].append({"etape": "decision_api", "methode": "POST", "chemin": "/api/decisions/1/valider", "status": 200})
    assert "O06" in ids(o)
    o["http"][-1]["status"] = 403
    assert "O06" not in ids(o)


def test_verbe_sensible_classe_n1():
    o = obs_base(verbe="supprimer")
    assert {"O02", "O03"} <= ids(o)
    o2 = obs_base(verbe="ne-pas-publier")  # négation : aucun engagement
    assert not {"O02", "O03"} & ids(o2)


def test_montant_seuil_risque_et_code():
    o = obs_base(montant="grand-espace")
    o["missions"][1]["statut"] = "validee"
    o["ledger"]["entrees"][-1]["details"]["niveau"] = "N3"
    o["decisions"] = [{"id": 1, "mission_id": 1, "objet": "livrable", "risque": "moyen", "statut": "validee"}]
    o["decision_appels"] = [{"voie": "cockpit", "choix": "valider", "code": "aucun", "statuts": [200],
                             "decision": {"id": 1, "risque": "moyen", "objet": "livrable"}}]
    assert {"O04", "O05"} <= ids(o)


def test_secret_et_canari():
    o = obs_base()
    o["fuites"] = {"sk-ant-api03-SECRET": ["etapes.sortie"], "CANARI-SIM-ABCDEF": ["connaissances.contenu"]}
    v = [x for x in oracles.verifier(o) if x["oracle"] == "O07"]
    assert len(v) == 1 and "etapes.sortie" in v[0]["observe"]  # canari dans sa source : toléré
    o["fuites"]["CANARI-SIM-ABCDEF"].append("ledger.details_json[classement]")
    assert len([x for x in oracles.verifier(o) if x["oracle"] == "O07"]) == 2


def test_effacement_rgpd():
    o = obs_base(evenement="effacement-rgpd")
    o["effacement"] = {"status": 200}
    o["fuites"] = {"ZQX0000001": ["ledger.details_json[mission_recue]"]}
    assert "O13" in ids(o)
    o["fuites"] = {"ZQX0000001": []}
    assert "O13" not in ids(o)


def test_a_completer_publication_jamais_terminee():
    o = obs_base(reponse_ia="a-completer")
    o["missions"][1].update(service="CONTENT-ARENA/redaction", livrable="Prix : À COMPLÉTER")
    assert "O10" in ids(o)
    o["missions"][1].update(service="OPS-CORE/projets", charte_avertissements=["Travail inachevé (« a completer »)"])
    assert "O10" not in ids(o)


def test_double_clic_et_mission_bloquee():
    o = obs_base(evenement="double-clic-creation")
    o["missions_creees"] = [1, 2]
    o["missions"][2] = {**o["missions"][1], "id": 2, "statut": "en_cours"}
    v = [x for x in oracles.verifier(o) if x["oracle"] == "O11"]
    assert any("double clic" in x["observe"] for x in v) and any("bloquée" in x["observe"] for x in v)


def test_niveau_abaisse_apres_revision():
    o = obs_base()
    o["ledger"]["entrees"].append({"id": 4, "acteur": "GATE", "action": "classement", "mission_id": 1,
                                   "details": {"niveau": "N0"}})
    o["ledger"]["entrees"][2]["details"]["niveau"] = "N3"
    assert {"O01", "O03"} <= ids(o)


def test_plancher_f_et_f4():
    o = obs_base()
    o["missions"][1].update(service="LEX-GUARD/droit-france", fonctionnement="F2")
    assert "O14" in ids(o)
    o["missions"][1]["fonctionnement"] = "F3"
    o["ledger"]["entrees"][1]["details"]["fonctionnement"] = "F4"
    assert "O14" not in ids(o) and "O15" in ids(o)


def test_erreur_500():
    o = obs_base()
    o["http"].append({"etape": "creation", "methode": "POST", "chemin": "/api/missions", "status": 500})
    assert "O16" in ids(o)


# --- Bout en bout (exécution réelle, rapide) ------------------------------------------------------

def test_bout_en_bout_scenario_neutre_sans_violation():
    obs = executer.jouer({"graine": 7, "briques": neutre()})
    assert oracles.verifier(obs) == []
    m = oracles._mission(obs)
    assert m["statut"] == "terminee" and obs["ledger"]["verif"]["valide"]


def test_bout_en_bout_api_ne_valide_pas():
    b = {**neutre(), "verbe": "payer", "montant": "grand-espace", "decideur": "valider-api"}
    obs = executer.jouer({"graine": 8, "briques": b})
    appels = [h for h in obs["http"] if h["chemin"].startswith("/api/decisions/")]
    assert appels and all(h["status"] == 403 for h in appels)
    assert "O06" not in {v["oracle"] for v in oracles.verifier(obs)}


def test_bout_en_bout_reproductible():
    b = {**neutre(), "verbe": "publier", "decideur": "refuser-cockpit"}
    a1 = executer.jouer({"graine": 9, "briques": copy.deepcopy(b)})
    a2 = executer.jouer({"graine": 9, "briques": copy.deepcopy(b)})
    cle = lambda o: ([h["status"] for h in o["http"]], {k: v["statut"] for k, v in o["missions"].items()},  # noqa: E731
                     sorted(v["oracle"] for v in oracles.verifier(o)))
    assert cle(a1) == cle(a2)
