"""robots.txt, délais polis, ETag/If-Modified-Since, limites de débit, quotas, suspension, journal sans secret."""
import logging
from datetime import timedelta

import collecteur as C
from conftest import FausseHorloge, FauxTransport, fabriquer, lire, source

FLUX = "https://autorite.exemple.fr/rss.xml"
ORIGINE = "https://autorite.exemple.fr"


def test_user_agent_generique_sans_email():
    assert C.USER_AGENT.startswith("SYFER-veille/1.0 (+")
    assert "@" not in C.USER_AGENT


def test_robots_interdit_le_flux(conn):
    t = FauxTransport({FLUX: (200, {}, lire("flux_rss.xml"))},
                      robots={ORIGINE: (200, {}, b"User-agent: SYFER-veille\nDisallow: /\n")})
    b = fabriquer(conn, t).collecter([source()])
    assert FLUX not in t.urls() and b.nouvelles == 0
    e = conn.execute("SELECT * FROM etat_sources").fetchone()
    assert "robots.txt" in e["derniere_erreur"] and e["suspendu_jusqua"]


def test_robots_autorise_autre_chemin(conn):
    t = FauxTransport({FLUX: (200, {}, lire("flux_rss.xml"))},
                      robots={ORIGINE: (200, {}, b"User-agent: *\nDisallow: /prive/\n")})
    assert fabriquer(conn, t).collecter([source()]).nouvelles >= 1
    assert t.urls()[0] == ORIGINE + "/robots.txt"


def test_robots_404_autorise_403_interdit_erreur_reseau_interdit():
    h = FausseHorloge()
    pol = C.Politesse(2, horloge=h, dormir=h.dormir)
    g = C.GardienRobots(FauxTransport(robots={"https://a.exemple": (404, {}, b""),
                                              "https://b.exemple": (403, {}, b""),
                                              "https://c.exemple": OSError("réseau")}), pol)
    assert g.autorise("https://a.exemple/flux") is True
    assert g.autorise("https://b.exemple/flux") is False
    assert g.autorise("https://c.exemple/flux") is False


def test_robots_mis_en_cache_par_origine():
    h = FausseHorloge()
    t = FauxTransport(robots={"https://a.exemple": (200, {}, b"User-agent: *\nAllow: /\n")})
    g = C.GardienRobots(t, C.Politesse(2, horloge=h, dormir=h.dormir))
    g.autorise("https://a.exemple/1")
    g.autorise("https://a.exemple/2")
    assert t.urls().count("https://a.exemple/robots.txt") == 1


def test_delai_minimum_2_secondes_par_domaine():
    h = FausseHorloge()
    p = C.Politesse(0.1, horloge=h, dormir=h.dormir)  # une valeur trop basse est relevée à 2 s
    p.attendre("https://a.exemple/1")
    p.attendre("https://b.exemple/1")  # autre domaine : pas d'attente
    p.attendre("https://a.exemple/2")
    assert len(h.attentes) == 1 and h.attentes[0] >= 2.0 - 1e-9


def test_etag_et_last_modified_renvoyes_puis_304(conn):
    appels = []

    def repondre(url, entetes):
        appels.append(entetes)
        if entetes.get("If-None-Match") == '"v1"':
            return (304, {}, b"")
        return (200, {"ETag": '"v1"', "Last-Modified": "Mon, 02 Nov 2026 10:00:00 GMT"}, lire("flux_rss.xml"))

    t = FauxTransport({FLUX: repondre})
    col = fabriquer(conn, t)
    s = source()
    assert col.collecter([s], forcer=True).nouvelles >= 1
    b2 = col.collecter([s], forcer=True)
    assert appels[1]["If-None-Match"] == '"v1"' and appels[1]["If-Modified-Since"].startswith("Mon, 02 Nov")
    assert b2.nouvelles == 0 and b2.erreurs == 0


def test_frequence_conseillee_respectee(conn):
    t = FauxTransport({FLUX: (200, {}, lire("flux_rss.xml"))})
    col = fabriquer(conn, t)
    col.collecter([source(frequence_conseillee="24h")])
    n = len(t.requetes)
    b = col.collecter([source(frequence_conseillee="24h")])
    assert len(t.requetes) == n and b.ignorees == 1


def test_429_retry_after_suspend_la_source(conn):
    t = FauxTransport({FLUX: (429, {"Retry-After": "3600"}, b"")})
    col = fabriquer(conn, t)
    col.collecter([source()])
    e = conn.execute("SELECT * FROM etat_sources").fetchone()
    assert e["echecs"] == 1 and e["suspendu_jusqua"] == "2026-11-04T13:00:00Z"
    n = len(t.requetes)
    col.collecter([source()])
    assert len(t.requetes) == n  # suspendue : aucune nouvelle requête


def test_suspension_apres_5_echecs(conn):
    t = FauxTransport({FLUX: (500, {}, b"")})
    col = fabriquer(conn, t)
    for _ in range(C.ECHECS_AVANT_SUSPENSION):
        col.collecter([source()], forcer=True)
    e = conn.execute("SELECT * FROM etat_sources").fetchone()
    assert e["echecs"] == 5 and e["suspendu_jusqua"] == C._iso(C.datetime(2026, 11, 4, 12, tzinfo=C.timezone.utc) + C.SUSPENSION)


def test_quota_journalier(conn):
    t = FauxTransport({"https://api.stackexchange.com/": (200, {}, b'{"items": []}')})
    col = fabriquer(conn, t)
    s = source(id="se", acces="api", adaptateur="stackexchange", quota_jour=2,
               url_flux="https://api.stackexchange.com/2.3/questions?site=stackoverflow&fromdate={depuis}")
    for _ in range(4):
        col.collecter([s], forcer=True)
    assert len(t.requetes) == 2
    assert "{depuis}" not in t.urls()[0]


def test_backoff_stackexchange_respecte(conn):
    t = FauxTransport({"https://api.stackexchange.com/": (200, {}, lire("stackexchange.json"))})
    col = fabriquer(conn, t)
    s = source(id="se", acces="api", adaptateur="stackexchange", type="communaute", confiance="C",
               url_flux="https://api.stackexchange.com/2.3/questions?site=stackoverflow")
    col.collecter([s])
    e = conn.execute("SELECT * FROM etat_sources").fetchone()
    assert e["suspendu_jusqua"] == "2026-11-04T12:00:10Z"


def test_cle_api_jamais_dans_le_journal(conn, monkeypatch, caplog):
    monkeypatch.setenv("STACKEXCHANGE_KEY", "CLESECRETE123")
    t = FauxTransport({"https://api.stackexchange.com/": (500, {}, b"")})
    col = fabriquer(conn, t)
    s = source(id="se", acces="api", adaptateur="stackexchange", cle_env="STACKEXCHANGE_KEY",
               url_flux="https://api.stackexchange.com/2.3/questions?site=stackoverflow")
    with caplog.at_level(logging.INFO, logger="syfer.veille"):
        col.collecter([s])
    assert "key=CLESECRETE123" in t.urls()[0]  # la clé part bien vers l'API…
    assert "CLESECRETE123" not in caplog.text  # … mais n'apparaît jamais dans le journal
    e = conn.execute("SELECT derniere_erreur FROM etat_sources").fetchone()[0]
    assert "CLESECRETE123" not in e


def test_masquer():
    assert C.masquer("https://a/x?key=abc&q=1&api_key=zz") == "https://a/x?key=***&q=1&api_key=***"


def test_sources_manuelles_et_a_configurer_jamais_interrogees(conn):
    t = FauxTransport()
    col = fabriquer(conn, t)
    col.collecter([source(acces="manuel", url_flux="", collecte="non", raison="r"),
                   source(id="piste", acces="api", adaptateur="a_configurer", collecte="non", raison="r"),
                   source(id="off", collecte="non", raison="r")])
    assert t.requetes == []


def test_verifier_ne_stocke_rien(conn):
    t = FauxTransport({FLUX: (200, {}, lire("flux_rss.xml"))})
    rapport = fabriquer(conn, t).verifier([source()])
    assert rapport[0]["statut"] == 200 and rapport[0]["elements"] == 4
    assert conn.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == 0


def test_duree_frequence():
    assert C._duree("6h") == timedelta(hours=6) and C._duree("7j") == timedelta(days=7)


def test_robots_inaccessible_compte_comme_erreur_reseau(conn):
    t = FauxTransport({FLUX: (200, {}, lire("flux_rss.xml"))}, robots={ORIGINE: OSError("réseau")})
    b = fabriquer(conn, t).collecter([source()])
    e = conn.execute("SELECT * FROM etat_sources").fetchone()
    assert b.erreurs == 1 and "inaccessible" in e["derniere_erreur"] and e["suspendu_jusqua"] is None
    assert FLUX not in t.urls()
