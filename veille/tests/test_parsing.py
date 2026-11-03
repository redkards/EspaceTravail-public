"""Analyse des flux RSS 2.0 / RSS 1.0 (RDF) / Atom et des API JSON — fichiers locaux, aucun réseau."""
import pytest

import collecteur as C
from conftest import FauxTransport, fabriquer, lire, source


def test_rss2():
    els = C.analyser_xml(lire("flux_rss.xml"))
    assert len(els) == 4
    assert els[0]["titre"].startswith("Nouvelle recommandation")
    assert els[0]["lien"] == "https://autorite.exemple.fr/actu/ia-recommandation?utm_source=rss&utm_medium=flux"
    assert "recommandation" in els[0]["resume"]
    assert els[0]["date"] == "Mon, 02 Nov 2026 10:00:00 +0100"


def test_atom_lien_alternate_et_dates():
    els = C.analyser_xml(lire("flux_atom.xml"))
    assert [e["titre"] for e in els] == ["v2.11.7", "v2.11.6"]
    assert els[0]["lien"].endswith("/v2.11.7")
    assert els[1]["lien"] == "/exemple/serveur/releases/tag/v2.11.6"  # relatif : résolu à la préparation
    assert els[1]["date"] == "2026-09-01T08:30:00+02:00"


def test_rss1_rdf():
    els = C.analyser_xml(lire("flux_rdf.xml"))
    assert len(els) == 1 and els[0]["lien"] == "https://seo.exemple.com/mise-a-jour-algorithme"
    assert els[0]["date"] == "2026-11-03T07:00:00Z"


def test_dtd_et_entites_refusees():
    with pytest.raises(C.FluxInvalide):
        C.analyser_xml(lire("flux_xxe.xml"))


def test_xml_casse_et_format_inconnu():
    with pytest.raises(C.FluxInvalide):
        C.analyser_xml(b"<rss><channel><item>")
    with pytest.raises(C.FluxInvalide):
        C.analyser_xml(b"<html><body>page</body></html>")


@pytest.mark.parametrize("brut, attendu", [
    ("Mon, 02 Nov 2026 10:00:00 +0100", "2026-11-02T09:00:00Z"),
    ("2026-09-01T08:30:00+02:00", "2026-09-01T06:30:00Z"),
    ("2026-11-03T07:00:00Z", "2026-11-03T07:00:00Z"),
    (1762000000, "2025-11-01T12:26:40Z"),
    ("n'importe quoi", None),
    ("2099-01-01T00:00:00Z", None),
])
def test_dates_normalisees_utc(brut, attendu):
    assert C._date_iso(brut) == attendu


def test_cisa_kev_trie_du_plus_recent():
    els = C.analyser_json(lire("cisa_kev.json"), "cisa_kev")
    assert els[0]["titre"].startswith("CVE-2026-0001")
    assert els[0]["lien"] == "https://nvd.nist.gov/vuln/detail/CVE-2026-0001"
    assert "Appliquer le correctif" in els[0]["resume"]


def test_stackexchange_sans_proprietaire():
    els = C.analyser_json(lire("stackexchange.json"), "stackexchange")
    assert els[0]["titre"] == "FTS5 & bm25 ranking in SQLite"
    texte = str(els)
    assert "Jean Dupont" not in texte and "users/42" not in texte


def test_hn_seules_les_stories_sans_pseudo():
    assert C.analyser_json(lire("hn_102.json"), "hn_item") == []
    els = C.analyser_json(lire("hn_101.json"), "hn_item")
    assert els[0]["lien"] == "https://exemple.dev/solver" and "pseudo_hn" not in str(els)


def test_jsonfeed_et_adaptateur_inconnu():
    els = C.analyser_json(b'{"items":[{"title":"T","url":"https://a.exemple/1","summary":"S","date_published":"2026-11-01T00:00:00Z"}]}',
                          "jsonfeed")
    assert els == [{"titre": "T", "lien": "https://a.exemple/1", "resume": "S", "date": "2026-11-01T00:00:00Z"}]
    with pytest.raises(C.FluxInvalide):
        C.analyser_json(b"{}", "inconnu")


def test_collecte_api_hn_de_bout_en_bout(conn):
    t = FauxTransport({
        "https://hacker-news.firebaseio.com/v0/topstories.json": (200, {}, lire("hn_top.json")),
        "https://hacker-news.firebaseio.com/v0/item/101.json": (200, {}, lire("hn_101.json")),
        "https://hacker-news.firebaseio.com/v0/item/102.json": (200, {}, lire("hn_102.json")),
    })
    col = fabriquer(conn, t)
    s = source(id="hn-api", acces="api", adaptateur="hn", type="communaute", confiance="C",
               url_flux="https://hacker-news.firebaseio.com/v0/topstories.json", domaines=["forums_experts"])
    b = col.collecter([s])
    assert b.nouvelles == 1
    assert not any(u.endswith("robots.txt") for u in t.urls())  # API officielle : conditions d'API, pas robots
    row = conn.execute("SELECT * FROM fiches").fetchone()
    assert row["titre"].startswith("Show HN") and row["confiance"] == "C"


def test_collecte_atom_resout_les_liens_relatifs(conn):
    t = FauxTransport({"https://github.com/exemple/serveur/releases.atom": (200, {}, lire("flux_atom.xml"))})
    col = fabriquer(conn, t)
    s = source(id="gh-serveur", acces="atom", url_flux="https://github.com/exemple/serveur/releases.atom")
    assert col.collecter([s]).nouvelles == 2
    liens = {r["url"] for r in conn.execute("SELECT url FROM fiches")}
    assert "https://github.com/exemple/serveur/releases/tag/v2.11.6" in liens


def test_nvd_ajoute_la_fenetre_de_dates(conn):
    t = FauxTransport({"https://services.nvd.nist.gov/": (200, {}, b'{"vulnerabilities": []}')})
    col = fabriquer(conn, t)
    s = source(id="nvd-api", acces="api", adaptateur="nvd", url_flux="https://services.nvd.nist.gov/rest/json/cves/2.0",
               quota_jour=48)
    col.collecter([s])
    url = t.urls()[0]
    assert "lastModStartDate=" in url and "lastModEndDate=" in url and "resultsPerPage=" in url
