"""Outils de test : aucun accès réseau (transport factice, horloge factice)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import collecteur as C

DONNEES = Path(__file__).parent / "donnees"


def lire(nom: str) -> bytes:
    return (DONNEES / nom).read_bytes()


class FauxTransport:
    """Répond à partir d'un dictionnaire {url: (statut, entetes, corps)} ; mémorise les requêtes."""

    def __init__(self, routes: dict | None = None, robots: dict | None = None):
        self.routes = routes or {}
        self.robots = robots or {}
        self.requetes: list[tuple[str, dict]] = []

    def get(self, url, entetes):
        self.requetes.append((url, dict(entetes)))
        if url.endswith("/robots.txt"):
            origine = url[: -len("/robots.txt")]
            r = self.robots.get(origine, (404, {}, b""))
            if isinstance(r, Exception):
                raise r
            return C.Reponse(r[0], r[1], r[2], url)
        for prefixe, r in self.routes.items():
            if url == prefixe or url.startswith(prefixe):
                if callable(r):
                    r = r(url, entetes)
                return C.Reponse(r[0], {k.lower(): v for k, v in r[1].items()}, r[2], url)
        return C.Reponse(404, {}, b"", url)

    def post(self, url, entetes, corps):
        self.corps_envoyes = getattr(self, "corps_envoyes", []) + [corps]
        return self.get(url, entetes)

    def urls(self):
        return [u for u, _ in self.requetes]


class FausseHorloge:
    def __init__(self):
        self.t = 1000.0
        self.attentes: list[float] = []

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.attentes.append(s)
        self.t += s


def source(**kw) -> dict:
    s = {"id": "autorite-test", "nom": "Autorité test", "domaines": ["droit", "ia"],
         "services_syfer": ["LEX-GUARD/droit-france"], "projets": ["poker-winners"], "type": "officielle",
         "confiance": "A", "acces": "rss", "url": "https://autorite.exemple.fr/",
         "url_flux": "https://autorite.exemple.fr/rss.xml", "langue": "fr", "frequence_conseillee": "6h",
         "conditions": "Licence Ouverte", "donnees_personnelles": "non", "verifie": "2026-11-04",
         "flux_verifie": "oui", "collecte": "oui", "licence": "etalab-2.0", "stockage": "extrait",
         "type_doc": "actualite"}
    s.update(kw)
    return s


@pytest.fixture
def conn(tmp_path):
    c = C.ouvrir(tmp_path / "veille.db")
    yield c
    c.close()


@pytest.fixture
def horloge():
    return FausseHorloge()


@pytest.fixture(params=["bouclier", "minimal"])
def nettoyeur(request):
    if request.param == "bouclier":
        n = C.Nettoyeur("auto")
        if n.mode != "bouclier":
            pytest.skip("bouclier de nexus-core absent")
        return n
    return C.Nettoyeur("minimal")


def fabriquer(conn, transport, nettoyeur=None, horloge=None, maintenant=None):
    h = horloge or FausseHorloge()
    pol = C.Politesse(2.0, horloge=h, dormir=h.dormir)
    quand = maintenant or datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    return C.Collecteur(conn, transport, pol, nettoyeur or C.Nettoyeur("minimal"), horloge=lambda: quand)
