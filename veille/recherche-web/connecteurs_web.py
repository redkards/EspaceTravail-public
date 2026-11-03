"""VEILLE SYFER — recherche Web À LA DEMANDE (« tout le Web »), connecteurs légaux et gratuits, DÉSACTIVÉS par défaut.

Connecteurs implémentés (gratuits et autorisés, vérifiés le 2026-11-04)
- searxng   : méta-moteur open source AUTO-HÉBERGÉ (service docker-compose fourni : docker-compose.searxng.yml),
              API JSON /search?q=…&format=json (le format json doit être activé dans settings.yml).
- wikipedia : API REST de Wikimédia (gratuite, sans clé ; User-Agent identifiable obligatoire ; contenus CC BY-SA).
Non implémentés (payants, à valider par le propriétaire) : Brave Search API (plus d'offre gratuite, ≈ 4 à 5 $ / 1 000
requêtes), Mojeek API (≈ 2 £ / 1 000 requêtes, carte bancaire requise). Voir config.yaml.

Règles
- désactivé tant que config.yaml (actif: true) ET la variable VEILLE_WEB=1 ne sont pas posés ;
- requête refusée si elle contient une donnée personnelle évidente (e-mail, téléphone, @pseudo) ;
- quotas par jour et par connecteur (fichier d'état JSON, hors base publiée) ; délai poli ≥ 2 s ;
- journal SANS la requête en clair (empreinte SHA-256 tronquée + connecteur + nombre de résultats) ;
- chaque résultat passe par le bouclier (nettoyage + score d'injection ; rejet ≥ 60) et l'anonymisation ;
- résultats = fiches « web » de confiance D (C pour Wikipédia) ; RECOUPEMENT : si l'URL appartient au site d'une
  source A/B du catalogue, la fiche prend la confiance de cette source (et le champ recoupe_avec) ;
- par défaut rien n'est enregistré dans veille.db (résultats éphémères renvoyés à l'appelant).

Usage
    VEILLE_WEB=1 python recherche-web/connecteurs_web.py "cahier des charges site vitrine accessibilité"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))
import collecteur as C  # noqa: E402

log = logging.getLogger("syfer.veille.web")
CONFIG = ICI / "config.yaml"
ETAT = Path(os.environ.get("VEILLE_WEB_ETAT", ICI.parent / "journal" / "web_quotas.json"))


class RequeteRefusee(ValueError):
    pass


def charger_config(chemin: Path = CONFIG) -> dict:
    import yaml
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


def verifier_requete(q: str) -> str:
    q = " ".join((q or "").split())[:300]
    if not q:
        raise RequeteRefusee("requête vide")
    if C.anonymiser(q) != q:
        raise RequeteRefusee("la requête contient une donnée personnelle (e-mail, téléphone ou pseudo) : refusée")
    return q


def empreinte_requete(q: str) -> str:
    return hashlib.sha256(q.lower().encode()).hexdigest()[:12]


def index_sites_catalogue(catalogue: dict) -> dict[str, dict]:
    """Hôte → source A/B du catalogue (pour le recoupement)."""
    idx: dict[str, dict] = {}
    for s in catalogue.get("sources", []):
        if s.get("confiance") in ("A", "B"):
            h = C._hote(s.get("url", ""))
            if h and h not in idx and h not in ("github.com", "www.youtube.com", "www.data.gouv.fr"):
                idx[h.removeprefix("www.")] = s
    return idx


def recouper(url: str, index: dict[str, dict]) -> dict | None:
    h = C._hote(url).removeprefix("www.")
    while h:
        if h in index:
            return index[h]
        h = h.split(".", 1)[1] if "." in h else ""
    return None


class Quotas:
    def __init__(self, chemin: Path = ETAT):
        self.chemin = chemin
        try:
            self.etat = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.etat = {}

    def consommer(self, nom: str, maxi: int) -> bool:
        jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cle = f"{nom}:{jour}"
        n = self.etat.get(cle, 0)
        if n >= maxi:
            return False
        self.etat = {k: v for k, v in self.etat.items() if k.endswith(jour)} | {cle: n + 1}
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            self.chemin.write_text(json.dumps(self.etat), encoding="utf-8")
        except OSError:
            pass  # montage en lecture seule : quota tenu en mémoire pour ce processus
        return True


def _url_searxng(base: str, q: str, langue: str) -> str:
    return f"{base.rstrip('/')}/search?" + urllib.parse.urlencode({"q": q, "format": "json", "language": langue,
                                                                   "safesearch": 1})


def _url_wikipedia(langue: str, q: str, n: int) -> str:
    return f"https://{langue}.wikipedia.org/w/rest.php/v1/search/page?" + urllib.parse.urlencode({"q": q, "limit": n})


def analyser(nom: str, octets: bytes, langue: str = "fr") -> list[dict]:
    d = json.loads(octets.decode("utf-8", "replace"))
    if nom == "searxng":
        return [{"titre": r.get("title", ""), "lien": r.get("url", ""), "resume": r.get("content", ""),
                 "date": r.get("publishedDate")} for r in d.get("results", [])]
    if nom == "wikipedia":
        return [{"titre": p.get("title", ""), "lien": f"https://{langue}.wikipedia.org/wiki/{urllib.parse.quote(p.get('key', ''))}",
                 "resume": f"{p.get('description') or ''} — {p.get('excerpt') or ''}", "date": None}
                for p in d.get("pages", [])]
    raise ValueError(f"connecteur inconnu {nom}")


def rechercher_web(requete: str, config: dict | None = None, catalogue: dict | None = None, transport=None,
                   politesse: C.Politesse | None = None, nettoyeur: C.Nettoyeur | None = None,
                   quotas: Quotas | None = None, forcer_actif: bool = False) -> list[dict]:
    """Interroge les connecteurs actifs ; renvoie des fiches web (non enregistrées)."""
    config = config if config is not None else charger_config()
    if not forcer_actif and (not config.get("actif") or os.environ.get("VEILLE_WEB") != "1"):
        raise RequeteRefusee("recherche Web désactivée (config.yaml actif: true ET VEILLE_WEB=1 requis)")
    q = verifier_requete(requete)
    catalogue = catalogue if catalogue is not None else C.charger_catalogue()
    index = index_sites_catalogue(catalogue)
    transport = transport or C.TransportHTTP()
    politesse = politesse or C.Politesse()
    nettoyeur = nettoyeur or C.Nettoyeur()
    quotas = quotas or Quotas()
    col = C.Collecteur(sqlite_memoire(), transport, politesse, nettoyeur)
    fiches: list[dict] = []
    for nom, cfg in (config.get("connecteurs") or {}).items():
        if not cfg.get("actif") or nom not in ("searxng", "wikipedia"):
            continue
        if not quotas.consommer(nom, int(cfg.get("quota_jour", 100))):
            log.info("web %s : quota journalier atteint", nom)
            continue
        langue = cfg.get("langue", "fr")
        url = _url_searxng(cfg["url"], q, langue) if nom == "searxng" else _url_wikipedia(langue, q, int(cfg.get("resultats", 10)))
        politesse.attendre(url)
        r = transport.get(url, {"User-Agent": C.USER_AGENT, "Accept": "application/json"})
        if r.statut != 200:
            log.warning("web %s : HTTP %s", nom, r.statut)
            continue
        elements = analyser(nom, r.corps, langue)[: int(cfg.get("resultats", 10))]
        source = {"id": f"web-{nom}", "url": url, "url_flux": url, "type": "communaute" if nom == "wikipedia" else "reseau_social",
                  "confiance": "C" if nom == "wikipedia" else "D", "domaines": ["web"], "langue": langue,
                  "licence": "cc-by-sa" if nom == "wikipedia" else "droits-reserves", "stockage": "extrait",
                  "type_doc": "guide" if nom == "wikipedia" else "actualite"}
        retenus = 0
        for el in elements:
            f, motif = col.preparer_fiche(el, source)
            if f is None:
                continue
            f["canal"] = "web"
            f["confiance"] = source["confiance"]
            src = recouper(f["url"], index)
            if src:  # le résultat EST une page d'une source A/B du catalogue
                f["confiance"], f["recoupe_avec"], f["autorite"] = src["confiance"], src["id"], C.AUTORITE_PAR_TYPE.get(src["type"], 0.5)
            fiches.append(f)
            retenus += 1
        log.info("web %s : requête %s → %d résultat(s)", nom, empreinte_requete(q), retenus)
    vus, uniques = set(), []
    for f in sorted(fiches, key=lambda x: "ABCD".index(x["confiance"])):
        if f["url_canonique"] not in vus:
            vus.add(f["url_canonique"])
            uniques.append(f)
    return uniques


def sqlite_memoire():
    return C.ouvrir(":memory:")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recherche Web à la demande (connecteurs gratuits, désactivés par défaut)")
    ap.add_argument("requete")
    a = ap.parse_args(argv)
    C.configurer_journal()
    try:
        for f in rechercher_web(a.requete):
            rec = f" (recoupé : {f['recoupe_avec']})" if f.get("recoupe_avec") else ""
            print(f"[{f['confiance']}] {f['source_id']} — {f['titre']}{rec}\n    {f['url']}")
    except RequeteRefusee as e:
        print(f"Refusé : {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
