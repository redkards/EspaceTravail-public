"""Validation du catalogue réel : schéma, unicité, minimum par domaine, URL, exclusions légales."""
import copy
from collections import Counter
from urllib.parse import urlsplit

import pytest

import collecteur as C
from conftest import source


@pytest.fixture(scope="module")
def cat():
    return C.charger_catalogue(C.ICI / "catalogue.yaml")


def test_catalogue_valide_sans_erreur(cat):
    assert C.valider_catalogue(cat, min_par_domaine=8) == []


def test_taille_du_catalogue(cat):
    # v1 : 150–250 sources ; v2 (documents techniques, marchés publics, médias, social) : jusqu'à 400
    assert 300 <= len(cat["sources"]) <= 400


def test_ids_uniques(cat):
    ids = [s["id"] for s in cat["sources"]]
    assert [i for i, n in Counter(ids).items() if n > 1] == []


def test_au_moins_8_sources_par_domaine_principal(cat):
    compte = Counter(d for s in cat["sources"] for d in s["domaines"])
    for d in C.DOMAINES_PRINCIPAUX:
        assert compte[d] >= 8, d


def test_urls_bien_formees(cat):
    for s in cat["sources"]:
        assert C.url_bien_formee(s["url"]), s["id"]
        if s["url_flux"]:
            assert C.url_bien_formee(s["url_flux"].replace("{depuis}", "0")), s["id"]


def test_au_moins_moitie_des_sources_verifiees_en_ligne(cat):
    verifiees = [s for s in cat["sources"] if s["verifie"] != "non_verifie"]
    assert len(verifiees) >= len(cat["sources"]) // 2


@pytest.mark.parametrize("hote", ["x.com", "linkedin.com", "facebook.com", "instagram.com", "tiktok.com", "reddit.com"])
def test_plateformes_fermees_jamais_collectees(cat, hote):
    concernees = [s for s in cat["sources"] if C._sur_hote(s["url"], [hote]) or C._sur_hote(s["url_flux"], [hote])]
    if hote != "reddit.com":
        assert concernees, f"{hote} doit figurer pour mémoire (consultation manuelle)"
    for s in concernees:
        assert s["collecte"] == "non" and s["acces"] == "manuel" and s["raison"], s["id"]


def test_aucune_cle_dans_le_catalogue(cat):
    for s in cat["sources"]:
        assert "apikey=" not in s["url_flux"].lower() and "token=" not in s["url_flux"].lower()
        if "cle_env" in s:
            assert s["cle_env"].isupper()


def test_sources_communautaires_signalent_le_risque_pseudos(cat):
    for s in cat["sources"]:
        if s["type"] == "communaute" and s["domaines"][0] == "forums_experts":
            assert s["donnees_personnelles"].startswith("risque:"), s["id"]


def test_services_identiques_a_nexus_core():
    C._charger_bouclier()  # ajoute nexus-core au chemin s'il est présent
    try:
        from app import agents  # type: ignore
        services = set(agents.services())
    except Exception:
        pytest.skip("nexus-core non importable")
    assert services == C.SERVICES


def test_projets_issus_de_projets_yaml(cat):
    codes = C.codes_projets()
    assert {"poker-winners", "top-solver", "nexus"} <= codes
    assert all(p in codes for s in cat["sources"] for p in s["projets"])


# --- le validateur détecte bien les erreurs -----------------------------------------------------------
def _cat(*sources):
    return {"sources": list(sources)}


def test_validateur_accepte_une_source_correcte():
    assert C.valider_catalogue(_cat(source())) == []


@pytest.mark.parametrize("modif, attendu", [
    ({"id": "Pas Bon"}, "id invalide"),
    ({"confiance": "D"}, "incohérente"),
    ({"acces": "manuel"}, "ne doit pas avoir d'url_flux"),
    ({"url": "pas-une-url"}, "url mal formée"),
    ({"url_flux": ""}, "url_flux absente"),
    ({"domaines": ["astrologie"]}, "domaine"),
    ({"services_syfer": ["FAUX/service"]}, "service SYFER inconnu"),
    ({"projets": ["inconnu"]}, "projet inconnu"),
    ({"verifie": "hier"}, "verifie"),
    ({"collecte": "non"}, "raison obligatoire"),
    ({"url_flux": "https://x.com/cnil/rss"}, "plateforme"),
    ({"url_flux": "https://api.exemple.org/v1?api_key=ABCDEF123456"}, "clé"),
    ({"cle_env": "sk-1234567890abcdef"}, "NOM de variable"),
    ({"donnees_personnelles": "peut-être"}, "donnees_personnelles"),
])
def test_validateur_detecte(modif, attendu):
    s = source(**modif)
    erreurs = C.valider_catalogue(_cat(s))
    assert any(attendu in e for e in erreurs), erreurs


def test_validateur_detecte_doublon_et_champ_manquant():
    a, b = source(), source()
    del b["conditions"]
    erreurs = C.valider_catalogue(_cat(a, b))
    assert any("en double" in e for e in erreurs) and any("conditions" in e for e in erreurs)


def test_validateur_minimum_par_domaine():
    erreurs = C.valider_catalogue(_cat(source()), min_par_domaine=2)
    assert any("minimum" in e for e in erreurs)


def test_collecteur_ignore_une_plateforme_meme_si_catalogue_trafique(conn):
    from conftest import FauxTransport, fabriquer
    t = FauxTransport()
    col = fabriquer(conn, t)
    s = source(url_flux="https://www.reddit.com/r/poker/.rss")
    col.collecter([s])
    assert t.requetes == []
    assert urlsplit("https://www.reddit.com/r/poker/.rss").hostname.endswith("reddit.com")
    assert copy.deepcopy(s)["collecte"] == "oui"  # même marquée « oui », elle n'est pas interrogée
