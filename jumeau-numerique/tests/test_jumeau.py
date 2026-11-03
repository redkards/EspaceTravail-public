"""Tests du jumeau numérique SYFER V2 (pytest)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jumeau as J  # noqa: E402

HYP = J.charger_hypotheses()
SCEN = {s["id"]: s for s in J.charger_scenarios()}
ETATS_FINAUX = {"executee", "n3_validee", "n3_refusee", "n3_expiree", "n3_en_attente", "fantome_fini", "plan_pilote",
                "echec_budget", "echec_delai", "echec_cout", "echec_escalade", "refusee_lancement",
                "attente_lancement_f4", "en_file", "en_cours", "plan_valider", "plan_refuser", "plan_expire",
                "plan_reviser", "n3_en_attente"}


def moyenne(sc, cle, n=6, **kw):
    return sum(J.simuler(sc, HYP, i, **kw)[cle] for i in range(n)) / n


# ----------------------------------------------------------------- hypothèses et scénarios

def test_hypotheses_completes_et_ordonnees():
    for cle, d in HYP["parametres"].items():
        assert d["min"] <= d["probable"] <= d["max"], cle
        assert d["unite"] and len(d["source"]) > 10, cle


def test_scenarios_demandes_presents():
    for sid in ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]:
        assert sid in SCEN
    assert len(SCEN) >= 12


def test_lecteur_yaml_minimal_identique_a_pyyaml():
    yaml = pytest.importorskip("yaml")
    with open(os.path.join(os.path.dirname(J.__file__), "scenarios.yaml"), encoding="utf-8") as f:
        texte = f.read()
    import builtins
    vrai_import = builtins.__import__

    def sans_yaml(nom, *a, **k):
        if nom == "yaml":
            raise ImportError
        return vrai_import(nom, *a, **k)

    builtins.__import__ = sans_yaml
    try:
        minimal = J.lire_yaml(texte)
    finally:
        builtins.__import__ = vrai_import
    assert minimal == yaml.safe_load(texte)


def test_familles_mix_normalise():
    for nom, f in HYP["fixes"]["familles"].items():
        if not nom.startswith("_"):
            assert abs(sum(f["N"]) - 1) < 1e-9, nom


# ----------------------------------------------------------------- calage et unités

def test_calage_sur_les_mesures_reelles():
    P = J.tirer_parametres(HYP, None)
    for c in J.calage(P, HYP["fixes"]):
        assert abs(c["ecart_duree"]) <= 0.15, c
        assert abs(c["ecart_tokens"]) <= 0.10, c


def test_unites_vitesse_et_duree():
    P = J.tirer_parametres(HYP, None)
    pre, gen = J.vitesses_locales(P, HYP["fixes"], "3b", 1.1)
    assert pre == pytest.approx(P["vitesse.prefill_ref_tok_s"])
    assert gen == pytest.approx(P["vitesse.gen_ref_tok_s"])
    # 1 000 tokens lus + 100 écrits : surcoût + 1000/30 + 100/5 secondes
    d = J.duree_appel_local(P, HYP["fixes"], "3b", 1.1, 1000, 100)
    assert d == pytest.approx(P["vitesse.surcout_appel_s"] + 1000 / pre + 100 / gen)
    # Un 7B est plus lent qu'un 3B, plus de vCPU accélère
    assert J.vitesses_locales(P, HYP["fixes"], "7b", 1.1)[1] < gen
    assert J.vitesses_locales(P, HYP["fixes"], "3b", 4.0)[1] > gen


def test_couts_et_tokens_coherents():
    r = J.simuler(SCEN["S7"], HYP, 0, probable=True)
    assert r["cout_total_eur"] == pytest.approx(r["cout_serveur_eur"] + r["cout_api_eur"])
    assert r["cout_api_eur"] <= SCEN["S7"]["payant_plafond_eur"] + 1.0  # plafond mensuel (+ dernier appel)
    assert r["tokens_mois_payant"] > 0
    r0 = J.simuler(SCEN["S4"], HYP, 0, probable=True)
    assert r0["tokens_mois_payant"] == 0 and r0["tokens_mois_cloud"] == 0 and r0["cout_api_eur"] == 0


def test_tarif_api():
    # 1 M tokens Sonnet en entrée = 2 $ = 1,84 €
    t = HYP["fixes"]["tarifs_usd_par_mtok"]["sonnet"]
    assert 1e6 * t["entree"] / 1e6 * HYP["fixes"]["eur_par_usd"] == pytest.approx(1.84)


# ----------------------------------------------------------------- déterminisme et conservation

def test_determinisme_avec_graine():
    a = J.simuler(SCEN["S5"], HYP, 3)
    b = J.simuler(SCEN["S5"], HYP, 3)
    assert a == b
    c = J.simuler(SCEN["S5"], HYP, 4)
    assert c != a


@pytest.mark.parametrize("sid", ["S1", "S1L", "S5", "S7", "S8", "S10", "S12"])
def test_conservation_des_missions(sid):
    sc = SCEN[sid]
    P = J.tirer_parametres(HYP, None)
    sim = J.Simulation(sc, P, HYP, 2026, 1, 30)
    r = sim.executer()
    assert sum(r["etats"].values()) == len(sim.missions)
    assert set(r["etats"]) <= ETATS_FINAUX
    # chaque mission est dans exactement un état ; aucune « en cours » sans place
    en_cours = sum(1 for m in sim.missions if m.etat == "en_cours")
    assert en_cours == len(sim.actifs) <= sc["max_missions"]
    en_file = sum(1 for m in sim.missions if m.etat == "en_file")
    assert en_file == len(sim.file)
    # livrées + échecs + en attente = démarrées (hors plans)
    for m in sim.missions:
        if m.livre_t is not None:
            assert m.livre_t >= m.arrivee


def test_plafond_n3_respecte():
    sc = dict(SCEN["S5"], charge=8.0)
    P = J.tirer_parametres(HYP, None)
    sim = J.Simulation(sc, P, HYP, 2026, 0, 10)
    sim.executer()
    assert max(sim.dec_crees_jour.values()) <= HYP["fixes"]["n3"]["plafond_jour"]


def test_expiration_24h_si_decideur_absent():
    sc = dict(SCEN["S5"], absence_debut_j=0, absence_duree_j=30)
    P = J.tirer_parametres(HYP, None)
    sim = J.Simulation(sc, P, HYP, 2026, 0, 30)
    sim.executer()
    assert sim.decisions and all(d["etat"] in ("expiree", "attente") for d in sim.decisions)
    for d in sim.decisions:
        if d["etat"] == "attente":
            assert sim.T - d["cree"] <= 24 * 3600 + 1


# ----------------------------------------------------------------- sensibilité

def test_doubler_la_vitesse_reduit_les_delais():
    sc = SCEN["S1L"]
    base = moyenne(sc, "attente_moy_s", probable=True, n=1)
    P = HYP["parametres"]
    rapide = {"vitesse.prefill_ref_tok_s": 2 * P["vitesse.prefill_ref_tok_s"]["probable"],
              "vitesse.gen_ref_tok_s": 2 * P["vitesse.gen_ref_tok_s"]["probable"]}
    r0 = J.simuler(sc, HYP, 0, probable=True)
    r1 = J.simuler(sc, HYP, 0, probable=True, surcharges=rapide)
    assert r1["delai_p50"]["F2"] < r0["delai_p50"]["F2"]
    assert r1["delai_p90"]["F2"] < r0["delai_p90"]["F2"]
    assert r1["cpu_llm"] < r0["cpu_llm"]
    assert r1["attente_moy_s"] <= base


def test_plus_de_charge_plus_de_file():
    # Mix constant : on compare des charges très différentes sur la configuration la plus lente (S1L).
    lourd = dict(SCEN["S1L"], charge=15.0)
    assert moyenne(lourd, "attente_moy_s", n=4) > moyenne(SCEN["S1L"], "attente_moy_s", n=4)
    assert moyenne(SCEN["S8"], "cpu_llm") > moyenne(SCEN["S5"], "cpu_llm")
    assert moyenne(SCEN["S8"], "livrees_jour") > moyenne(SCEN["S5"], "livrees_jour")


def test_panne_cloud_bascule_en_local():
    r_ok = J.simuler(SCEN["S3"], HYP, 0, probable=True)
    r_panne = J.simuler(SCEN["S9"], HYP, 0, probable=True)
    assert r_panne["tokens_mois_local"] > r_ok["tokens_mois_local"]
    assert r_panne["tokens_mois_cloud"] < r_ok["tokens_mois_cloud"]


def test_double_modele_charge_deux_modeles_en_ram():
    r = J.simuler(SCEN["S5"], HYP, 0, probable=True)
    assert r["modeles_simultanes"] == 2
    assert r["ram_pic_go"] > HYP["parametres"]["modele.7b.ram_go"]["probable"] + 1
    assert r["ram_ok"]


def test_ram_insuffisante_force_un_seul_modele():
    sc = dict(SCEN["S5"], offre="KVM2")  # 7B + 8B ne tiennent pas dans 5 Go
    r = J.simuler(sc, HYP, 0, probable=True)
    assert r["modeles_simultanes"] == 1
    assert not r["ram_ok"]


def test_optimisations_v2_reduisent_les_appels_llm():
    r1 = J.simuler(SCEN["S1L"], HYP, 0, probable=True)
    r2 = J.simuler(SCEN["S2L"], HYP, 0, probable=True)
    assert r2["tokens_mois_local"] < r1["tokens_mois_local"]


def test_score_borne():
    for sid in ("S1", "S4", "S7"):
        r = J.simuler(SCEN[sid], HYP, 0, probable=True)
        assert 0 <= r["score"] <= 100
