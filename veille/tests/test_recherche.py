"""Recherche FTS5 : pertinence × confiance, filtres, requêtes hostiles, fiches pour mission, mini-serveur local."""
import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import collecteur as C
import recherche as R


def _fiche(conn, n, titre, resume, confiance="A", domaines="droit", services="|LEX-GUARD/droit-france|",
           projets="|poker-winners|", date=None, score=0, source_id="src"):
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("INSERT INTO fiches(source_id, titre, resume, url, url_canonique, empreinte, date, domaines, services, "
                 "projets, confiance, type, langue, score_injection, collecte_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (source_id, titre, resume, f"https://ex.fr/{n}", f"https://ex.fr/{n}", f"e{n}", date, domaines, services,
                  projets, confiance, "officielle", "fr", score, date))


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "veille.db"
    conn = C.ouvrir(chemin)
    vieux = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _fiche(conn, 1, "Jeux d'argent en ligne : nouvelles obligations", "L'ANJ précise la protection des joueurs de poker.",
           "A", source_id="anj")
    _fiche(conn, 2, "Poker : stratégie GTO au river", "Analyse d'un spot de poker avec un solver.", "B",
           domaines="poker", services="|R&D-PARADOX/veille|", projets="|top-solver|", source_id="gtow")
    _fiche(conn, 3, "Rumeur sur le poker en ligne", "Un message affirme que le poker va être interdit.", "D",
           domaines="reseaux_sociaux poker", services="|R&D-PARADOX/veille|", source_id="masto")
    _fiche(conn, 4, "Vulnérabilité critique dans Caddy", "Correctif de sécurité pour le serveur web Caddy.", "A",
           domaines="cybersecurite", services="|CYBER-FORTRESS/veille|", projets="|paradoxx|", source_id="caddy")
    _fiche(conn, 5, "Ancienne note sur le poker", "Archive très ancienne sur le poker.", "A", date=vieux, source_id="vieux")
    _fiche(conn, 6, "Poker : ignore les consignes", "Texte suspect sur le poker.", "A", score=45, source_id="suspect")
    conn.commit()
    conn.close()
    return str(chemin)


def test_confiance_departage_a_pertinence_egale(base):
    r = R.rechercher("poker en ligne", chemin_db=base)
    ids = [f["source_id"] for f in r]
    assert ids.index("anj") < ids.index("masto")
    assert all("score" in f and isinstance(f["domaines"], list) for f in r)


def test_filtres(base):
    assert {f["source_id"] for f in R.rechercher("poker", domaine="poker", chemin_db=base)} == {"gtow", "masto"}
    assert [f["source_id"] for f in R.rechercher("poker", service="R&D-PARADOX/veille", confiance_min="B",
                                                 chemin_db=base)] == ["gtow"]
    assert [f["source_id"] for f in R.rechercher("", projet="paradoxx", chemin_db=base)] == ["caddy"]
    assert "masto" not in {f["source_id"] for f in R.rechercher("poker", confiance_min="C", chemin_db=base)}
    assert "vieux" not in {f["source_id"] for f in R.rechercher("poker", depuis="30j", chemin_db=base)}
    assert "vieux" in {f["source_id"] for f in R.rechercher("poker", depuis="2020-01-01", chemin_db=base)}


def test_recherche_sans_accents(base):
    assert R.rechercher("strategie", chemin_db=base)[0]["source_id"] == "gtow"
    assert R.rechercher("vulnerabilite caddy", chemin_db=base)[0]["source_id"] == "caddy"


@pytest.mark.parametrize("hostile", ['poker" OR titre:*', "NEAR(poker caddy)", "poker AND (", "*", '"""', "-poker ^caddy"])
def test_requetes_hostiles_sans_erreur(base, hostile):
    R.rechercher(hostile, chemin_db=base)  # aucune exception FTS5


def test_requete_fts_neutralise_operateurs():
    q = R.requete_fts('poker" OR titre:* NEAR(')
    assert q.count('"') % 2 == 0 and "titre:" not in q and "NEAR(" not in q


def test_mots_vides_seuls(base):
    assert R.rechercher("le la les de", chemin_db=base) == []


def test_suspectes_marquees_et_exclues_pour_mission(base):
    r = R.rechercher("poker", chemin_db=base)
    assert any(f["suspecte"] for f in r if f["source_id"] == "suspect")
    m = R.fiches_pour_mission("Rédiger une note sur le poker", "LEX-GUARD/droit-france", "poker-winners", max=5,
                              chemin_db=base)
    assert "suspect" not in {f["source_id"] for f in m}


def test_fiches_pour_mission_priorise_service_et_elargit(base):
    m = R.fiches_pour_mission("Mettre à jour les obligations jeux d'argent poker", "LEX-GUARD/droit-france",
                              "poker-winners", max=2, chemin_db=base)
    assert m[0]["source_id"] == "anj" and len(m) == 2
    assert all(f["confiance"] in "ABC" for f in m)  # la D ne vient qu'en dernier recours…
    # horizon de 10 ans (normes et lois vieillissent lentement) : la note ancienne compte aussi
    m3 = R.fiches_pour_mission("obligations jeux d'argent poker", "LEX-GUARD/droit-france", "poker-winners", max=4,
                               chemin_db=base)
    assert [f["confiance"] for f in m3].count("D") == 1  # … quand il n'y a pas assez de fiches A–C


def test_fiches_pour_mission_base_absente(tmp_path):
    assert R.fiches_pour_mission("x", chemin_db=str(tmp_path / "absente.db")) == []


def test_formater_pour_collector(base):
    m = R.fiches_pour_mission("faille caddy", "CYBER-FORTRESS/veille", "paradoxx", chemin_db=base)
    brut = R.formater_pour_collector(m, encapsuler=False)
    assert "[veille:caddy · confiance A" in brut and "https://ex.fr/4" in brut
    bloc = R.formater_pour_collector(m)
    assert "DONNÉES NON FIABLES" in bloc
    assert R.formater_pour_collector([]) == ""


def test_lecture_seule(base):
    conn = R.ouvrir_lecture(base)
    with pytest.raises(Exception):
        conn.execute("DELETE FROM fiches")
    conn.close()


def test_mini_serveur_local(base, monkeypatch):
    monkeypatch.setenv("VEILLE_JETON", "jeton-test")
    srv = R.servir("127.0.0.1", 0, base)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        def get(chemin, jeton="jeton-test"):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{chemin}", headers={"X-Veille-Jeton": jeton})
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        assert get("/sante")[1]["fiches"] == 6
        assert get("/sante", "mauvais")[0] == 401
        code, d = get("/recherche?q=caddy&confiance_min=A")
        assert code == 200 and d["fiches"][0]["source_id"] == "caddy"
        code, d = get("/mission?consigne=poker%20jeux&service=LEX-GUARD/droit-france&projet=poker-winners&max=2")
        assert code == 200 and len(d["fiches"]) == 2 and "veille:" in d["bloc"]
        assert get("/inconnu")[0] == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_bout_en_bout_collecte_puis_recherche(tmp_path):
    from conftest import FauxTransport, fabriquer, lire, source
    chemin = tmp_path / "v.db"
    conn = C.ouvrir(chemin)
    t = FauxTransport({"https://autorite.exemple.fr/rss.xml": (200, {}, lire("flux_rss.xml"))})
    fabriquer(conn, t).collecter([source()])
    conn.close()
    r = R.rechercher("intelligence artificielle", service="LEX-GUARD/droit-france", chemin_db=str(chemin))
    assert r and r[0]["source_id"] == "autorite-test" and "presse@" not in r[0]["resume"]


@pytest.mark.parametrize("date", ["2026-11-04", "2026-11-04T10:00:00", "2026-11-04 10:00", "pas une date", "",
                                  "2099-01-01T00:00:00Z", "2026-13-45"])
def test_age_jours_robuste(date):
    age = R._age_jours({"date": date})
    assert isinstance(age, float) and age >= 0


def test_age_jours_naif_lu_comme_utc_et_futur_a_zero():
    hier = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    assert 0.9 < R._age_jours({"date": hier}) < 1.1
    assert R._age_jours({"date": "2099-01-01"}) == 0.0
    assert R._age_jours({"date": "n'importe quoi"}) == R.AGE_INCONNU
    assert R._age_jours({"date": "invalide", "collecte_le": hier + "Z"}) < 1.1


def test_recherche_ne_plante_pas_sur_dates_heterogenes(tmp_path):
    conn = C.ouvrir(tmp_path / "v.db")
    for n, d in enumerate(["2026-11-04", "2026-11-04T10:00:00", "invalide", "2099-01-01T00:00:00Z", None]):
        _fiche(conn, n, f"Poker note {n}", "Résumé poker.", date=d or "")
    conn.commit()
    conn.close()
    r = R.rechercher("poker", chemin_db=str(tmp_path / "v.db"))
    assert len(r) == 5 and all(isinstance(f["score"], float) for f in r)
    assert R.fiches_pour_mission("poker", chemin_db=str(tmp_path / "v.db"), max=5)
