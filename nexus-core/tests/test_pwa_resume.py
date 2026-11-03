"""V2 D2 — cockpit installable (PWA) et résumé quotidien ntfy."""
import re
from datetime import datetime

import httpx
import pytest

from app import pipeline, pwa, resume

from .conftest import creer_mission


def test_manifest(client):
    r = client.get("/cockpit/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["scope"] == "/cockpit/" and m["start_url"] == "/cockpit/decideur" and m["display"] == "standalone"
    assert {i["sizes"] for i in m["icons"]} >= {"192x192", "512x512"} and m["lang"] == "fr"
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


@pytest.mark.parametrize("nom,signature", [("icone-192.png", b"\x89PNG"), ("icone-512.png", b"\x89PNG"),
                                           ("icone-maskable-512.png", b"\x89PNG"), ("icone.svg", b"<svg")])
def test_icones(client, nom, signature):
    r = client.get(f"/cockpit/icones/{nom}")
    assert r.status_code == 200 and r.content.startswith(signature)


def test_icones_liste_blanche(client):
    for nom in ("../main.py", "..%2Fmain.py", "inconnu.png"):
        assert client.get(f"/cockpit/icones/{nom}").status_code == 404


def test_service_worker_ne_cache_que_le_statique(client):
    r = client.get("/cockpit/sw.js")
    assert r.status_code == 200 and r.headers["service-worker-allowed"] == "/cockpit/"
    js = r.text
    assert 'url.pathname.startsWith("/cockpit/api/")' in js and 'url.pathname.startsWith("/api/")' in js
    assert "cache.put" not in js and "c.put" not in js  # aucune mise en cache dynamique (pages, API)
    statiques = re.search(r"const STATIQUES = (\[.*?\]);", js).group(1)
    assert "/api" not in statiques and "decideur" not in statiques and "/cockpit\"" not in statiques
    assert all(s.startswith(("/cockpit/icones/", "/cockpit/manifest", "/cockpit/hors-ligne")) for s in pwa.STATIQUES)


def test_page_hors_ligne_et_pages_installables(client):
    h = client.get("/cockpit/hors-ligne")
    assert h.status_code == 200 and "Pas de connexion" in h.text and "aucune décision" in h.text
    for page in ("/cockpit", "/cockpit/decideur"):
        t = client.get(page).text
        assert 'rel="manifest"' in t and 'serviceWorker.register("/cockpit/sw.js"' in t


@pytest.fixture
def ntfy(monkeypatch):
    monkeypatch.setenv("NTFY_URL", "http://ntfy.test")
    monkeypatch.setenv("NTFY_TOPIC", "t")
    envoyees = []

    def faux(url, *a, **k):
        envoyees.append({"corps": k.get("content", b"").decode(), "entetes": k.get("headers", {})})
        return httpx.Response(200, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", faux)
    return envoyees


def test_resume_quotidien_une_fois_par_jour(ntfy):
    mid = creer_mission(titre="Checklist secrète Dupont", consigne="Liste les étapes", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid + 1)
    from app.models import maintenant
    jour = maintenant().replace(hour=17, minute=59, second=0, microsecond=0)  # 18:59 ou 19:59 à Paris
    t = jour.replace(hour=18, minute=5)  # 19:05 Paris en heure d'hiver (UTC+1)
    if resume.tick(t) is None:  # heure d'été : 20:05 → hors fenêtre, on vise 17:05 UTC
        t = jour.replace(hour=17, minute=5)
        assert resume.tick(t) is not None
    assert len(ntfy) == 1
    corps = ntfy[0]["corps"]
    assert corps.startswith("Bilan du jour : 1 mission terminee, 1 decision N3 en attente")
    assert "Dupont" not in corps and "Checklist" not in corps
    assert resume.tick(t.replace(minute=30)) is None and len(ntfy) == 1  # une seule fois par jour


def test_resume_hors_fenetre_et_desactivable(ntfy, monkeypatch):
    assert resume.tick(datetime(2026, 11, 4, 10, 0)) is None  # 11:00 Paris
    monkeypatch.setenv("NEXUS_RESUME_QUOTIDIEN", "off")
    assert resume.heure() is None and resume.tick(datetime(2026, 11, 4, 18, 5)) is None
    monkeypatch.setenv("NEXUS_RESUME_QUOTIDIEN", "07:30")
    assert resume.tick(datetime(2026, 11, 4, 6, 40)) is not None  # 07:40 Paris
    assert ntfy and ntfy[-1]["entetes"]["Click"] == "https://nexus.exemple.fr/cockpit"
