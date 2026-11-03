"""rapport.py sur des résultats factices."""
import json

import rapport
from faux_serveur import livrable_ideal


def _r(d, **c):
    r = {"id": d["id"], "titre": d["titre"], "mission_id": 1, "statut": "terminee",
         "service": d["service_attendu"], "niveau": d["niveau_decision_attendu"], "fonctionnement": "F1",
         "tokens": 1000, "tokens_entree": 800, "tokens_sortie": 200, "cout_eur": 0.0, "duree_s": 10.0,
         "revisions": 0, "livrable_texte": livrable_ideal(d)}
    r.update(c)
    return r


def _fichier(tmp_path, nom, f, resultats, modele="qwen2.5:3b"):
    p = tmp_path / nom
    p.write_text(json.dumps({"fonctionnement": f, "debut": "2026-11-03T10:00:00Z",
                             "sante": {"llm": {"fournisseur": "ollama", "modele": modele, "modele_checker": modele}},
                             "resultats": resultats}), encoding="utf-8")
    return str(p)


def test_rapport_agrege(tmp_path, missions, banc):
    m = missions
    f1 = _fichier(tmp_path, "a_F1.json", "F1", [
        _r(m["BE-01"], duree_s=10), _r(m["BE-05"], duree_s=20, service="OPS-CORE/projets"),
        _r(m["BE-10"], statut="plafond_atteint", livrable_texte="court", duree_s=30),
        _r(m["BE-28"], statut="terminee", niveau="N1", duree_s=40),            # piège N3 raté
        _r(m["BE-29"], statut="en_attente_n3", duree_s=50),
        {"id": "BE-24", "titre": "x", "statut": "erreur_creation", "http": "422"}])
    f2 = _fichier(tmp_path, "b_F2.json", "F2", [_r(m["BE-01"], fonctionnement="F2", cout_eur=0.01, duree_s=100),
                                                _r(m["BE-28"], statut="en_attente_n3", cout_eur=0.03, duree_s=200)])
    sortie = tmp_path / "out"
    assert rapport.main([f1, f2, "--missions", str(banc / "missions.json"), "--sortie", str(sortie)]) == 0
    s = json.loads((sortie / "synthese.json").read_text())
    a1, a2 = s["par_fonctionnement"]["F1"], s["par_fonctionnement"]["F2"]
    assert a1["missions"] == 6 and a1["executees"] == 5
    assert a1["taux_routage_correct"] == 80.0
    assert a1["taux_reussite_pieges"] == 50.0 and a1["pieges_evalues"] == 2
    assert a1["duree_mediane_s"] == 30.0 and a1["duree_p90_s"] == 50.0
    assert a1["taux_plafond"] == round(100 / 6, 1) and a1["taux_echec"] == round(100 / 6, 1)
    assert a2["cout_eur_total"] == 0.04 and a2["taux_reussite_pieges"] == 100.0
    assert s["pires_missions"][0]["id"] in ("BE-10", "BE-24")
    assert [p["id"] for p in s["pieges_echoues"]] == ["BE-28"]
    assert any("échantillon petit" in a for a in s["avertissements"])
    md = (sortie / "rapport.md").read_text()
    assert "qwen2.5:3b" in md and "Généré le" in md and "Les 5 pires missions" in md
    assert "CONTENT-ARENA/redaction" in md and "ÉCHEC **BE-28**" in md


def test_rapport_llm_factice_et_nom(tmp_path, audit, banc):
    d = next(iter(audit.values()))
    f = _fichier(tmp_path, "c_F3.json", "F3", [_r(d, fonctionnement="F3")], modele="x")
    f_json = json.loads(open(f).read())
    f_json["sante"]["llm"]["fournisseur"] = "fake"
    open(f, "w").write(json.dumps(f_json))
    sortie = tmp_path / "o"
    rapport.main([f, "--missions", str(banc / "audit-syfer" / "missions.json"), "--sortie", str(sortie),
                  "--nom", "audit-syfer"])
    s = json.loads((sortie / "synthese_audit-syfer.json").read_text())
    assert any("FACTICE" in a for a in s["avertissements"])
    assert (sortie / "rapport_audit-syfer.md").exists()


def test_p90():
    assert rapport.p90([]) is None
    assert rapport.p90(list(range(1, 11))) == 9
    assert rapport.p90([5]) == 5
