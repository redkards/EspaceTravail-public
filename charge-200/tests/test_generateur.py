"""Tests minimaux du générateur de charge (fonctions pures, sans lancer nexus-core)."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import charge  # noqa: E402

NOMINAL = {"missions_jour": 40, "pic_heure": 15}


def test_scenarios_valides_et_25():
    doc = charge.charger_scenarios()
    assert charge.valider_scenarios(doc) == []
    assert len(doc["scenarios"]) == 25
    for sc in doc["scenarios"]:
        assert sc["criteres"], sc["id"]


def test_taux_arrivee_pic_et_compression():
    # 100 % du pic = 15 missions/h ; compression 120 → 0,5 mission/s réelle
    assert abs(charge.taux_arrivee(100, NOMINAL, 120) - 0.5) < 1e-9
    assert abs(charge.taux_arrivee(200, NOMINAL, 120) - 1.0) < 1e-9
    # base « jour » : 40/24 missions/h
    assert abs(charge.taux_arrivee(100, NOMINAL, 3600, "jour") - 40 / 24) < 1e-9


def test_poisson_moyenne_et_bornes():
    rng = random.Random(1)
    n = [len(charge.planifier_poisson(2.0, 100, rng)) for _ in range(30)]
    assert 180 < sum(n) / len(n) < 220
    inst = charge.planifier_poisson(2.0, 10, random.Random(2))
    assert inst == sorted(inst) and all(0 <= x < 10 for x in inst)
    assert charge.planifier_poisson(0, 10, random.Random(3)) == []


def test_profil_jour_total_et_pic():
    p = charge.profil_jour(NOMINAL, 100)
    assert len(p) == 24 and abs(sum(p) - 40) < 1e-9 and abs(max(p) - 15) < 1e-9
    p2 = charge.profil_jour(NOMINAL, 200)
    assert abs(sum(p2) - 80) < 1e-9
    inst = charge.planifier_profil(NOMINAL, 200, 864, 24, random.Random(4))
    assert 60 <= len(inst) <= 100 and max(inst) < 24 * 3600 / 864


def test_tirer_mission_mix_et_marqueurs():
    rng = random.Random(5)
    mix = {"fonctionnement": {"F1": 1, "F3": 1}, "part_n3": 1.0, "part_piege": 1.0, "part_refus": 1.0}
    t = charge.tirer_mission(mix, rng, "CHS99-00001")
    c = t["corps"]
    assert c["titre"].startswith("CHS99-00001 ")
    assert c["fonctionnement"] in ("F1", "F3") and c["action"] == "publier"
    assert "PIEGE-CHS99-00001" in c["consigne"] and "[[REFUS]]" in c["consigne"]
    assert c["projet"] in charge.PROJETS
    # proportions approximatives
    mix = {"fonctionnement": {"F2": 1}, "part_n3": 0.2}
    n3 = sum(1 for i in range(2000) if charge.tirer_mission(mix, rng, f"J{i}")["etiquettes"]["n3"])
    assert 330 < n3 < 470


def test_percentiles():
    p = charge.percentiles(list(range(1, 101)))
    assert p["p50"] == 50 and p["p95"] == 95 and p["p99"] == 99 and p["max"] == 100
    assert charge.percentiles([])["p95"] is None


def test_classer_erreur():
    assert charge.classer_erreur(202) is None
    assert charge.classer_erreur(500) == "5xx"
    assert charge.classer_erreur(500, None, "sqlite3.OperationalError: database is locked") == "database_is_locked"
    assert charge.classer_erreur(429) == "429"

    class ReadTimeout(Exception):
        pass

    class ConnectError(Exception):
        pass
    assert charge.classer_erreur(None, ReadTimeout()) == "timeout"
    assert charge.classer_erreur(None, ConnectError()) == "connexion"


def test_verification_ledger_independante():
    cle = b"cle"
    prec, lignes = "0" * 64, []
    for i in range(1, 6):
        d = json.dumps({"n": i})
        h = charge.calcul_ledger(f"2026-11-04T00:00:0{i}", "A", "act", i, d, prec, "hmac", cle)
        lignes.append((i, f"2026-11-04T00:00:0{i}", "A", "act", i, d, prec, h, "hmac"))
        prec = h
    assert charge.verifier_chaine(lignes, cle)["valide"]
    falsifiee = list(lignes)
    falsifiee[2] = falsifiee[2][:5] + ('{"n": 99}',) + falsifiee[2][6:]
    r = charge.verifier_chaine(falsifiee, cle)
    assert not r["valide"] and r["premiere_erreur"] == 3
    assert not charge.verifier_chaine(lignes, b"autre")["valide"]


def test_evaluer_criteres():
    res = charge.evaluer_criteres({"erreurs_5xx_max": 0, "disponibilite_min": 0.99, "ledger_valide": True,
                                   "inconnu": 1}, {"erreurs_5xx": 2, "disponibilite": 0.995, "ledger_valide": True})
    d = {c["critere"]: c["ok"] for c in res}
    assert d == {"erreurs_5xx_max": False, "disponibilite_min": True, "ledger_valide": True}
