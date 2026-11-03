"""Cockpit installable (PWA) : manifest, icônes, service worker minimal et page hors ligne.

Le service worker ne met en cache QUE les ressources statiques listées (icônes, manifest, page
hors ligne). Il ne touche jamais à /cockpit/api/ ni à /api/ (décisions, missions) : ces requêtes
partent toujours sur le réseau. Les pages HTML ne sont pas mises en cache non plus (réseau d'abord,
page hors ligne si le réseau manque). Tout est servi sous /cockpit/ : même protection Caddy.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

router = APIRouter()
ICONES = Path(__file__).resolve().parent / "static" / "icones"
FICHIERS_ICONES = {"icone.svg": "image/svg+xml", "icone-192.png": "image/png", "icone-512.png": "image/png",
                   "icone-maskable-512.png": "image/png", "apple-touch-icon.png": "image/png"}
VERSION_CACHE = "nexus-cockpit-v1"
STATIQUES = ["/cockpit/hors-ligne", "/cockpit/manifest.webmanifest"] + [f"/cockpit/icones/{n}" for n in FICHIERS_ICONES]

MANIFEST = {
    "name": "NEXUS — Cockpit", "short_name": "NEXUS", "lang": "fr", "dir": "ltr",
    "description": "Décisions et suivi des missions du Mini NEXUS MOTHERSHIP",
    "start_url": "/cockpit/decideur", "scope": "/cockpit/", "display": "standalone",
    "background_color": "#ffffff", "theme_color": "#0b4fd6",
    "icons": [
        {"src": "/cockpit/icones/icone-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/cockpit/icones/icone-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/cockpit/icones/icone-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        {"src": "/cockpit/icones/icone.svg", "sizes": "any", "type": "image/svg+xml"},
    ],
    "shortcuts": [{"name": "Décideur", "url": "/cockpit/decideur"}, {"name": "Cockpit complet", "url": "/cockpit"}],
}

SERVICE_WORKER = """// Service worker du cockpit NEXUS : cache des seules ressources statiques.
"use strict";
const VERSION = "%(version)s";
const STATIQUES = %(statiques)s;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(STATIQUES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((cles) => Promise.all(cles.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  // Jamais de cache pour l'API ni les décisions : toujours le réseau.
  if (url.pathname.startsWith("/cockpit/api/") || url.pathname.startsWith("/api/")) return;
  if (STATIQUES.includes(url.pathname)) {
    e.respondWith(caches.match(url.pathname).then((r) => r || fetch(req)));
    return;
  }
  if (req.mode === "navigate") {
    // Pages : réseau d'abord (jamais mises en cache), page hors ligne si le réseau manque.
    e.respondWith(fetch(req).catch(() => caches.match("/cockpit/hors-ligne")));
  }
});
""" % {"version": VERSION_CACHE, "statiques": "[" + ", ".join(f'"{s}"' for s in STATIQUES) + "]"}

HORS_LIGNE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEXUS — hors ligne</title><link rel="icon" href="/cockpit/icones/icone.svg">
<style>
:root { --fond:#fff; --texte:#0a0a0a; --accent:#0b4fd6; }
@media (prefers-color-scheme: dark) { :root { --fond:#0b0f14; --texte:#f4f7fa; --accent:#7aa7ff; } }
body { margin:0; background:var(--fond); color:var(--texte); font:18px/1.5 system-ui, sans-serif;
       display:flex; min-height:100vh; align-items:center; justify-content:center; text-align:center; padding:16px; }
img { width:96px; height:96px; } button { font:inherit; font-weight:700; min-height:56px; padding:0 24px;
  border-radius:12px; border:2px solid var(--accent); background:var(--accent); color:#fff; margin-top:16px; }
</style></head><body><main>
<img src="/cockpit/icones/icone.svg" alt="">
<h1>Pas de connexion</h1>
<p>Le cockpit a besoin du réseau : aucune décision ni mission n'est gardée sur le téléphone.</p>
<button type="button" onclick="location.reload()">Réessayer</button>
</main></body></html>"""


@router.get("/cockpit/manifest.webmanifest", include_in_schema=False)
def manifest() -> JSONResponse:
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


@router.get("/cockpit/sw.js", include_in_schema=False)
def service_worker() -> Response:
    return Response(SERVICE_WORKER, media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/cockpit/"})


@router.get("/cockpit/hors-ligne", include_in_schema=False)
def hors_ligne() -> HTMLResponse:
    return HTMLResponse(HORS_LIGNE)


@router.get("/cockpit/icones/{nom}", include_in_schema=False)
def icone(nom: str) -> FileResponse:
    if nom not in FICHIERS_ICONES:  # liste blanche : aucun accès au système de fichiers par le nom
        raise HTTPException(404, "Icône inconnue")
    return FileResponse(ICONES / nom, media_type=FICHIERS_ICONES[nom],
                        headers={"Cache-Control": "public, max-age=604800"})


ENTETE_HTML = """<link rel="manifest" href="/cockpit/manifest.webmanifest" crossorigin="use-credentials">
<link rel="icon" href="/cockpit/icones/icone.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/cockpit/icones/apple-touch-icon.png">"""
ENREGISTREMENT = """<script>
if ("serviceWorker" in navigator) { navigator.serviceWorker.register("/cockpit/sw.js", { scope: "/cockpit/" }).catch(() => {}); }
</script>"""
