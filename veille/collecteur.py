"""VEILLE SYFER — collecteur de la base de veille « virtuelle » (stdlib + PyYAML déjà présent dans nexus-core).

Principe : on ne copie PAS le web. Le catalogue (catalogue.yaml) liste des sources vérifiées ; le
collecteur ne lit que des accès AUTORISÉS (flux RSS/Atom, API publiques officielles) et range des
FICHES COURTES (titre, résumé ≤ 500 caractères, lien, date, source, confiance) dans veille.db
(SQLite + index plein texte FTS5). Jamais d'article intégral, jamais de profil de personne.

Garde-fous appliqués à chaque passage
- User-Agent générique « SYFER-veille/1.0 (+contact) » (contact = variable VEILLE_CONTACT, pas d'e-mail en dur) ;
- robots.txt respecté pour les flux et pages des sites (les API officielles suivent leurs propres conditions + quotas) ;
- délai poli ≥ 2 s entre deux requêtes vers un même domaine ; ETag / If-Modified-Since (304 = rien de neuf) ;
- quotas journaliers par source, respect de Retry-After / 429 / 503 / champ « backoff » (Stack Exchange) ;
- suspension automatique d'une source après 5 échecs consécutifs ;
- nettoyage : bouclier de nexus-core (nettoyer_contenu + detecter_injection) s'il est présent, sinon
  nettoyage HTML minimal + détection simple ; score ≥ 60 = fiche rejetée, ≥ 30 = fiche marquée « suspecte » ;
- retrait des données personnelles évidentes (e-mails, téléphones, @pseudos, u/pseudos) ; jamais de champ auteur ;
- rejet des fiches contenant un secret apparent (cyber.detecter_secrets si disponible) ;
- déduplication par URL canonique + empreinte (titre + début du résumé) ;
- rétention configurable (180 jours par défaut) ; journal sans secret (paramètres key/token masqués).

Commandes
    python collecteur.py valider                    # contrôle du catalogue (schéma, unicité, URL…)
    python collecteur.py collecter [--source ID] [--domaine D] [--forcer] [--simulation]
    python collecteur.py verifier  [--source ID]    # teste chaque flux (statut, nb d'éléments) sans rien stocker
    python collecteur.py purger    [--jours 180]
    python collecteur.py supprimer --texte "Nom Prénom" | --url URL | --source ID   # effacement ciblé (RGPD)
    python collecteur.py stats
    python collecteur.py tableau                    # régénère CATALOGUE.md depuis catalogue.yaml

Variables d'environnement : VEILLE_DB, VEILLE_CATALOGUE, VEILLE_CONTACT, VEILLE_RETENTION_JOURS,
VEILLE_DELAI_DOMAINE (≥ 2), VEILLE_JOURNAL, VEILLE_NEXUS_CORE (chemin de nexus-core), VEILLE_SANS_BOUCLIER=1,
et les clés facultatives nommées dans le catalogue (cle_env : NVD_API_KEY, STACKEXCHANGE_KEY…).
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import html
import io
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable

ICI = Path(__file__).resolve().parent
log = logging.getLogger("syfer.veille")

# --------------------------------------------------------------------------------------------- réglages
CATALOGUE = Path(os.environ.get("VEILLE_CATALOGUE", ICI / "catalogue.yaml"))
DB_DEFAUT = Path(os.environ.get("VEILLE_DB", ICI / "veille.db"))
CONTACT = os.environ.get("VEILLE_CONTACT", "contact du propriétaire à configurer")
USER_AGENT = f"SYFER-veille/1.0 (+{CONTACT})"
UA_ROBOTS = "SYFER-veille"
DELAI_MIN = 2.0
DELAI_DOMAINE = max(DELAI_MIN, float(os.environ.get("VEILLE_DELAI_DOMAINE", "2") or 2))
RETENTION_JOURS = int(os.environ.get("VEILLE_RETENTION_JOURS", "180") or 180)
MAX_RESUME = 500
MAX_RESUME_PRESSE = 300  # presse (type media) : extrait plus court (droit voisin des éditeurs de presse)
MAX_TITRE = 300
MAX_OCTETS = 5_000_000
DELAI_RESEAU = 20
MAX_PAR_PASSAGE = 30
ECHECS_AVANT_SUSPENSION = 5
SUSPENSION = timedelta(hours=48)
SEUIL_REJET = 60
SEUIL_ALERTE = 30

DOMAINES = {"droit", "cybersecurite", "ia", "entreprise", "environnement", "design_ux", "marketing_communication",
            "poker", "bd_edition", "forums_experts", "reseaux_sociaux", "communication_institutionnelle", "tech"}
DOMAINES |= {"normes_documentation", "marches_publics", "medias"}
DOMAINES_PRINCIPAUX = DOMAINES - {"tech", "communication_institutionnelle"}
TYPES = {"officielle", "expert", "communaute", "reseau_social", "media"}
CONFIANCES = ("A", "B", "C", "D")
CONFIANCE_PAR_TYPE = {"officielle": {"A"}, "expert": {"B"}, "media": {"B", "C"}, "communaute": {"C"}, "reseau_social": {"D"}}
ACCES = {"rss", "atom", "api", "manuel", "document"}
FLUX_VERIFIE = {"oui", "motif", "non", "sans_objet"}
ADAPTATEURS = {"jsonfeed", "cisa_kev", "nvd", "hn", "stackexchange", "github_advisories", "a_configurer",
               "hal", "opendatasoft", "ted", "datagouv", "gdelt", "youtube", "bluesky_fil", "mastodon_tag"}
TYPES_DOC = {"actualite", "norme", "guide", "loi", "jurisprudence", "documentation", "cahier_des_charges",
             "appel_offres", "donnees", "recherche", "release", "discussion", "social", "podcast"}
STOCKAGES = ("metadonnees", "agrege", "extrait", "integral")  # du plus restrictif au plus large
# Politique de stockage selon la LICENCE (le texte intégral n'est permis que pour les licences ouvertes)
LICENCES_INTEGRAL = {"etalab-2.0", "domaine-public", "domaine-public-us", "cc0", "cc-by", "cc-by-sa", "ietf-tlp",
                     "w3c-document", "reutilisation-ue", "mit", "apache-2.0", "ogl-uk"}
LICENCES_EXTRAIT = {"droits-reserves", "metadonnees-ouvertes", "psf-documentation", "cgu-plateforme"}
LICENCES_METADONNEES = {"etsi-copyright", "iso-payant"}
LICENCES = LICENCES_INTEGRAL | LICENCES_EXTRAIT | LICENCES_METADONNEES
RETENTION_SOCIAL_JOURS = int(os.environ.get("VEILLE_RETENTION_SOCIAL_JOURS", "30") or 30)
MAX_EXTRAIT_SOCIAL = 200


def stockage_autorise(licence: str) -> str:
    """Stockage maximal permis par une licence : integral | extrait | metadonnees."""
    if licence in LICENCES_INTEGRAL:
        return "integral"
    if licence in LICENCES_METADONNEES:
        return "metadonnees"
    return "extrait"  # droits réservés, CGU, licence inconnue : prudence


def stockage_effectif(source: dict) -> str:
    """Le plus restrictif entre ce que demande la source et ce que permet sa licence."""
    demande = source.get("stockage", "extrait")
    permis = stockage_autorise(source.get("licence", "droits-reserves"))
    if demande == "agrege":
        return "agrege"
    rang = {"metadonnees": 0, "extrait": 1, "integral": 2}
    return demande if rang.get(demande, 1) <= rang[permis] else permis


def canal_de(source: dict) -> str:
    if source.get("acces") == "document":
        return "document"
    if str(source.get("id", "")).startswith("web-"):
        return "web"
    if source.get("type") == "reseau_social" or source.get("stockage") == "agrege":
        return "social"
    if (source.get("domaines") or [""])[0] == "medias" or source.get("type") == "media":
        return "media"
    if str(source.get("id", "")).startswith("web-"):
        return "web"
    return "flux"


def confiance_fiche(confiance: str, canal: str) -> str:
    """Les fiches médias et sociales restent C/D (jamais présentées comme des faits) tant qu'elles ne sont pas
    recoupées par une source A/B : un média → C au mieux, un réseau social → D."""
    if canal == "social":
        return "D"
    if canal == "media" and confiance in ("A", "B"):
        return "C"
    return confiance


AUTORITE_PAR_TYPE = {"officielle": 1.0, "expert": 0.7, "media": 0.5, "communaute": 0.3, "reseau_social": 0.1}
LANGUES = {"fr", "en", "multi"}
SERVICES = {
    "AGENT-FACTORY/evaluation", "CODE-CORE/conception", "CODE-CORE/revue", "CONTENT-ARENA/redaction",
    "CYBER-FORTRESS/audit", "CYBER-FORTRESS/conformite", "CYBER-FORTRESS/incident", "CYBER-FORTRESS/veille",
    "DESIGN-SYSTEM/ui", "GREEN-CORE/environnement", "GREEN-CORE/rse", "LEX-GUARD/conformite",
    "LEX-GUARD/droit-europe", "LEX-GUARD/droit-france", "LEX-GUARD/droit-international", "OPS-CORE/projets",
    "PILOT-CORE/etudes", "PILOT-CORE/pilotage", "R&D-PARADOX/veille", "REVENUE-CORE/propositions",
}
PROJETS_SECOURS = {"paradoxx", "nexus", "poker-winners", "poker-feeling", "redkards", "top-solver",
                   "youtube-poker-winner", "freelance-ia", "esct-boxe", "turf", "divers"}
# Plateformes fermées : jamais collectées (CGU : pas d'accès automatisé légitime pour ce besoin).
HOTES_INTERDITS = ("twitter.com", "x.com", "linkedin.com", "facebook.com", "fb.com", "instagram.com", "tiktok.com",
                   "threads.net")
# Reddit : fin des flux RSS annoncée pour le 13/11/2026 + API réservée aux applis enregistrées → pas de collecte.
HOTES_SANS_COLLECTE = HOTES_INTERDITS + ("reddit.com",)
REGLE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
REGLE_FREQ = re.compile(r"^(\d+)(h|j)$")
REGLE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------------------------- catalogue
def charger_catalogue(chemin: Path | str = CATALOGUE) -> dict:
    try:
        import yaml  # présent dans l'image nexus-core (pyyaml épinglé)
    except ImportError as e:  # pragma: no cover
        raise SystemExit("PyYAML manquant : lancer le collecteur avec l'environnement Python de nexus-core.") from e
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def codes_projets() -> set[str]:
    chemin = Path(os.environ.get("VEILLE_NEXUS_CORE", ICI.parent / "nexus-core")) / "projets.yaml"
    try:
        import yaml
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        liste = donnees.get("projets", donnees) if isinstance(donnees, dict) else donnees
        codes = {p["code"] for p in liste if isinstance(p, dict) and p.get("code")}
        return codes or set(PROJETS_SECOURS)
    except Exception:
        return set(PROJETS_SECOURS)


def _hote(url: str) -> str:
    return (urllib.parse.urlsplit(url or "").hostname or "").lower()


def _sur_hote(url: str, hotes: Iterable[str]) -> bool:
    h = _hote(url)
    return any(h == x or h.endswith("." + x) for x in hotes)


def url_bien_formee(url: str) -> bool:
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname) and "." in p.hostname and " " not in url


def valider_catalogue(cat: dict, min_par_domaine: int = 0, projets: set[str] | None = None) -> list[str]:
    """Liste des erreurs du catalogue (vide = valide)."""
    err: list[str] = []
    sources = cat.get("sources") if isinstance(cat, dict) else None
    if not isinstance(sources, list) or not sources:
        return ["catalogue vide ou sans clé « sources »"]
    projets = projets if projets is not None else codes_projets()
    vus: set[str] = set()
    obligatoires = ("id", "nom", "domaines", "services_syfer", "projets", "type", "confiance", "acces", "url",
                    "url_flux", "langue", "frequence_conseillee", "conditions", "donnees_personnelles", "verifie",
                    "flux_verifie", "collecte", "licence", "stockage", "type_doc")
    for i, s in enumerate(sources):
        ref = f"source n°{i + 1} ({s.get('id', '?') if isinstance(s, dict) else '?'})"
        if not isinstance(s, dict):
            err.append(f"{ref} : n'est pas un dictionnaire")
            continue
        for k in obligatoires:
            if k not in s:
                err.append(f"{ref} : champ manquant « {k} »")
        sid = str(s.get("id", ""))
        if not REGLE_ID.match(sid):
            err.append(f"{ref} : id invalide (minuscules, chiffres, tirets)")
        if sid in vus:
            err.append(f"{ref} : id en double")
        vus.add(sid)
        doms = s.get("domaines") or []
        if not doms or any(d not in DOMAINES for d in doms):
            err.append(f"{ref} : domaine(s) inconnu(s) {doms}")
        if any(x not in SERVICES for x in s.get("services_syfer") or []):
            err.append(f"{ref} : service SYFER inconnu {s.get('services_syfer')}")
        if any(x not in projets for x in s.get("projets") or []):
            err.append(f"{ref} : projet inconnu {s.get('projets')}")
        typ, conf, acces = s.get("type"), s.get("confiance"), s.get("acces")
        if typ not in TYPES:
            err.append(f"{ref} : type inconnu {typ}")
        elif conf not in CONFIANCE_PAR_TYPE[typ]:
            err.append(f"{ref} : confiance {conf} incohérente avec le type {typ}")
        if acces not in ACCES:
            err.append(f"{ref} : accès inconnu {acces}")
        if not url_bien_formee(str(s.get("url", ""))):
            err.append(f"{ref} : url mal formée")
        flux = str(s.get("url_flux") or "")
        if acces in ("rss", "atom", "api") and not url_bien_formee(flux.replace("{depuis}", "0")):
            err.append(f"{ref} : url_flux absente ou mal formée pour un accès {acces}")
        if acces == "manuel" and flux:
            err.append(f"{ref} : une source manuelle ne doit pas avoir d'url_flux")
        if acces == "api" and s.get("adaptateur") not in ADAPTATEURS:
            err.append(f"{ref} : adaptateur d'API inconnu {s.get('adaptateur')}")
        if s.get("langue") not in LANGUES:
            err.append(f"{ref} : langue inconnue")
        if not REGLE_FREQ.match(str(s.get("frequence_conseillee", ""))):
            err.append(f"{ref} : frequence_conseillee attendue « 6h », « 24h », « 7j »…")
        dp = str(s.get("donnees_personnelles", ""))
        if not (dp == "non" or dp.startswith("non ") or dp.startswith("risque:")):
            err.append(f"{ref} : donnees_personnelles doit valoir « non » ou « risque: <règle> »")
        v = str(s.get("verifie", ""))
        if not (v == "non_verifie" or REGLE_DATE.match(v)):
            err.append(f"{ref} : verifie doit être une date AAAA-MM-JJ ou « non_verifie »")
        if s.get("flux_verifie") not in FLUX_VERIFIE:
            err.append(f"{ref} : flux_verifie inconnu")
        col = s.get("collecte")
        if col not in ("oui", "non"):
            err.append(f"{ref} : collecte doit valoir oui ou non")
        if col == "non" and not s.get("raison"):
            err.append(f"{ref} : raison obligatoire quand collecte = non")
        lic, sto = s.get("licence"), s.get("stockage")
        if lic not in LICENCES:
            err.append(f"{ref} : licence inconnue {lic}")
        if sto not in STOCKAGES:
            err.append(f"{ref} : stockage inconnu {sto}")
        elif sto != "agrege" and lic in LICENCES and STOCKAGES.index(sto) > STOCKAGES.index(stockage_autorise(lic)):
            err.append(f"{ref} : stockage « {sto} » interdit par la licence {lic} (maximum {stockage_autorise(lic)})")
        if sto == "agrege" and typ != "reseau_social":
            err.append(f"{ref} : stockage agrege réservé aux réseaux sociaux")
        if typ == "reseau_social" and acces == "api" and sto != "agrege" and col == "oui":
            err.append(f"{ref} : une source sociale collectée doit être en stockage agrege (RGPD)")
        if s.get("type_doc") not in TYPES_DOC:
            err.append(f"{ref} : type_doc inconnu {s.get('type_doc')}")
        if acces == "manuel" and col == "oui":
            err.append(f"{ref} : une source manuelle ne peut pas être collectée")
        if (_sur_hote(s.get("url", ""), HOTES_SANS_COLLECTE) or _sur_hote(flux, HOTES_SANS_COLLECTE)) and col != "non":
            err.append(f"{ref} : plateforme exclue de la collecte automatique (CGU / fin des flux)")
        if _sur_hote(flux, HOTES_INTERDITS):
            err.append(f"{ref} : aucun flux de plateforme fermée n'est autorisé")
        if "cle_env" in s and not re.match(r"^[A-Z][A-Z0-9_]{2,40}$", str(s["cle_env"])):
            err.append(f"{ref} : cle_env doit être un NOM de variable d'environnement, jamais une clé")
        if re.search(r"(api[_-]?key|token|secret|password)=\w{8,}", flux, re.I):
            err.append(f"{ref} : url_flux semble contenir une clé : interdit")
    if min_par_domaine:
        for d in sorted(DOMAINES_PRINCIPAUX):
            n = sum(1 for s in sources if isinstance(s, dict) and d in (s.get("domaines") or []))
            if n < min_par_domaine:
                err.append(f"domaine {d} : {n} source(s) < minimum {min_par_domaine}")
    return err


# --------------------------------------------------------------------------------------------- nettoyage
_INVISIBLES = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­\U000e0000-\U000e007f]")
_BLOCS = re.compile(r"<\s*(script|style|iframe|noscript|template|svg)\b.*?<\s*/\s*\1\s*>", re.S | re.I)
_COMMENTAIRES = re.compile(r"<!--.*?(?:-->|$)", re.S)
_BALISES = re.compile(r"<[^>]{0,2000}>")
_ESPACES = re.compile(r"\s+")
_INJ_MINIMAL = [
    (re.compile(r"\b(ignore|disregard|oublie|ignorez?)\b.{0,40}\b(previous|prior|above|précédentes?|instructions?|consignes?|règles?)", re.I), 45),
    (re.compile(r"\b(system prompt|prompt système|you are now|tu es maintenant|nouvelles? instructions?)\b", re.I), 35),
    (re.compile(r"\b(reveal|send|envoie|révèle|affiche)\b.{0,40}\b(api key|clé d'?api|mot de passe|password|token|jeton|secret)", re.I), 45),
    (re.compile(r"\b(valide|approuve|approve|publie|publish|execute|exécute)\b.{0,30}\b(la décision|decision|mission|paiement|virement)", re.I), 30),
]
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_TEL = re.compile(r"(?<![\w+])(?:(?:\+|00)33[\s.-]?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)"
                    r"|(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)")
RE_PSEUDO = re.compile(r"(?<![\w@/.])@([A-Za-z0-9_][A-Za-z0-9_.-]{0,40})(?:@[\w.-]+)?")
RE_PSEUDO_REDDIT = re.compile(r"(?<![\w/])/?u/[A-Za-z0-9_-]{3,30}\b")


@dataclass
class Nettoyage:
    texte: str
    score: int = 0
    motifs: list[str] = field(default_factory=list)
    alertes: list[str] = field(default_factory=list)


class Nettoyeur:
    """Utilise le bouclier de nexus-core s'il est importable, sinon un nettoyage minimal (marqué comme tel)."""

    def __init__(self, mode: str = "auto"):
        self.bouclier = self.cyber = None
        if mode in ("auto", "bouclier") and not os.environ.get("VEILLE_SANS_BOUCLIER"):
            self.bouclier, self.cyber = _charger_bouclier()
            if mode == "bouclier" and self.bouclier is None:
                raise RuntimeError("bouclier de nexus-core introuvable")
        self.mode = "bouclier" if self.bouclier else "minimal"

    def nettoyer(self, brut: str, source: str) -> Nettoyage:
        brut = brut if isinstance(brut, str) else str(brut or "")
        if self.bouclier:
            n = self.bouclier.nettoyer_contenu(brut, source)
            texte = _ESPACES.sub(" ", html.unescape(n.texte)).strip()
            d = self.bouclier.detecter_injection(texte)
            score, motifs = d.score, list(d.motifs)
            for cache in getattr(n, "caches", []) or []:
                dc = self.bouclier.detecter_injection(cache)
                if dc.score > 0:
                    score = max(score, min(100, dc.score + getattr(self.bouclier, "BONUS_CACHE", 25)))
                    motifs += [f"caché:{m}" for m in dc.motifs]
            return Nettoyage(texte, score, motifs, list(n.alertes))
        t = _BLOCS.sub(" ", brut)
        caches = [c for c in _COMMENTAIRES.findall(t)]
        t = _COMMENTAIRES.sub(" ", t)
        t = re.sub(r"<\s*(br|/p|/div|/li|/h\d)\s*/?>", " ", t, flags=re.I)
        t = html.unescape(_BALISES.sub(" ", t))
        t = unicodedata.normalize("NFKC", _INVISIBLES.sub("", t))
        t = _ESPACES.sub(" ", t).strip()
        score, motifs = 0, []
        for motif, poids in _INJ_MINIMAL:
            for cible, bonus in ((t, 0), (" ".join(caches), 25)):
                if cible and motif.search(cible):
                    score = max(score, min(100, poids + bonus))
                    motifs.append(motif.pattern[:40])
        if len(motifs) >= 2:
            score = min(100, score + 15)
        return Nettoyage(t, score, motifs, ["nettoyage minimal (bouclier absent)"])

    def secrets(self, texte: str) -> list[str]:
        if self.cyber:
            try:
                return list(self.cyber.detecter_secrets(texte))
            except Exception:
                return []
        return ["clé privée"] if "PRIVATE KEY-----" in texte else []


def _charger_bouclier():
    chemin = Path(os.environ.get("VEILLE_NEXUS_CORE", ICI.parent / "nexus-core"))
    if not (chemin / "app" / "bouclier.py").exists():
        return None, None
    if str(chemin) not in sys.path:
        sys.path.append(str(chemin))
    try:
        from app import bouclier, cyber  # type: ignore
        return bouclier, cyber
    except Exception as e:  # le collecteur reste utilisable sans nexus-core
        log.warning("bouclier de nexus-core non chargé (%s) : nettoyage minimal", type(e).__name__)
        return None, None


RE_URL = re.compile(r"https?://[^\s<>\"')]+")


def anonymiser(texte: str, autorises: Iterable[str] = ()) -> str:
    """Retire e-mails, téléphones et pseudos d'individus. `autorises` : comptes institutionnels conservés.
    Les liens sont laissés intacts, sauf ceux qui désignent une personne (« @ », « /u/ », « /user/ ») : retirés."""
    ok = {a.lower().lstrip("@") for a in autorises}

    def partie(t: str) -> str:
        t = RE_EMAIL.sub("[e-mail retiré]", t)
        t = RE_TEL.sub("[téléphone retiré]", t)
        t = RE_PSEUDO.sub(lambda m: m.group(0) if m.group(1).lower() in ok else "[pseudo retiré]", t)
        return RE_PSEUDO_REDDIT.sub("[pseudo retiré]", t)

    def lien(u: str) -> str:
        bas = u.lower()
        if "@" in u and not any(f"/@{a}" in bas for a in ok) or re.search(r"/(u|user|users|profile)/", bas):
            return "[lien vers un profil retiré]"
        return u

    morceaux, pos = [], 0
    for m in RE_URL.finditer(texte or ""):
        morceaux += [partie(texte[pos:m.start()]), lien(m.group(0))]
        pos = m.end()
    morceaux.append(partie((texte or "")[pos:]))
    return "".join(morceaux)


def tronquer(texte: str, maxi: int) -> str:
    texte = (texte or "").strip()
    if len(texte) <= maxi:
        return texte
    coupe = texte[: maxi - 1]
    if " " in coupe[maxi // 2:]:
        coupe = coupe[: coupe.rfind(" ")]
    return coupe.rstrip(" ,;:.-") + "…"


PARAMS_SUIVI = re.compile(r"^(utm_.*|fbclid|gclid|dclid|mc_cid|mc_eid|igshid|ref|ref_src|_hs.*|mkt_tok|spm|cmpid|xtor|at_.*)$", re.I)


def url_canonique(url: str) -> str:
    p = urllib.parse.urlsplit((url or "").strip())
    schema = "https" if p.scheme in ("http", "https") else p.scheme.lower()
    hote = (p.hostname or "").lower()
    if hote.startswith("www."):
        hote = hote[4:]
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    chemin = re.sub(r"/{2,}", "/", p.path or "/")
    if len(chemin) > 1:
        chemin = chemin.rstrip("/")
    params = sorted((k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not PARAMS_SUIVI.match(k))
    return urllib.parse.urlunsplit((schema, hote + port, chemin, urllib.parse.urlencode(params), ""))


def empreinte(titre: str, resume: str) -> str:
    def norm(x: str) -> str:
        x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+", " ", x).strip()
    return hashlib.sha256(f"{norm(titre)}|{norm(resume)[:200]}".encode()).hexdigest()


def masquer(url: str) -> str:
    """Pour le journal : masque les paramètres sensibles d'une URL."""
    return re.sub(r"(?i)((?:api[_-]?key|key|token|access_token|apikey|secret|client_secret)=)[^&#]+", r"\1***", url or "")


# --------------------------------------------------------------------------------------------- réseau
@dataclass
class Reponse:
    statut: int
    entetes: dict
    corps: bytes = b""
    url: str = ""


class TransportHTTP:
    """GET via urllib (aucune dépendance) ; taille plafonnée ; gzip décompressé avec plafond (anti-bombe)."""

    def get(self, url: str, entetes: dict) -> Reponse:
        return self._requete(url, entetes, None)

    def post(self, url: str, entetes: dict, corps: bytes) -> Reponse:
        return self._requete(url, entetes, corps)

    def _requete(self, url: str, entetes: dict, donnees: bytes | None) -> Reponse:
        req = urllib.request.Request(url, headers=entetes, data=donnees, method="POST" if donnees is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=DELAI_RESEAU) as r:
                corps = r.read(MAX_OCTETS + 1)
                h = {k.lower(): v for k, v in r.headers.items()}
                statut, final = r.status, r.geturl()
        except urllib.error.HTTPError as e:
            h = {k.lower(): v for k, v in (e.headers or {}).items()}
            return Reponse(e.code, h, b"", url)
        if len(corps) > MAX_OCTETS:
            raise ValueError("réponse trop volumineuse")
        if h.get("content-encoding", "").lower() == "gzip" or corps[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(corps)) as g:
                corps = g.read(MAX_OCTETS + 1)
            if len(corps) > MAX_OCTETS:
                raise ValueError("réponse décompressée trop volumineuse")
        return Reponse(statut, h, corps, final)


class Politesse:
    """Au moins `delai` secondes entre deux requêtes vers le même domaine."""

    def __init__(self, delai: float = DELAI_DOMAINE, horloge: Callable[[], float] = time.monotonic,
                 dormir: Callable[[float], None] = time.sleep):
        self.delai, self.horloge, self.dormir = max(DELAI_MIN, delai), horloge, dormir
        self.dernier: dict[str, float] = {}

    def attendre(self, url: str) -> None:
        dom = _hote(url)
        if dom in self.dernier:
            reste = self.delai - (self.horloge() - self.dernier[dom])
            if reste > 0:
                self.dormir(reste)
        self.dernier[dom] = self.horloge()


class GardienRobots:
    """robots.txt par origine, mis en cache pour le passage. 401/403 → tout interdit ; 404 → tout permis ;
    erreur réseau ou 5xx → interdit pour ce passage (prudence), avec un motif distinct dans le journal."""

    def __init__(self, transport, politesse: Politesse):
        self.transport, self.politesse = transport, politesse
        self.cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.motifs: dict[str, str] = {}

    @staticmethod
    def _origine(url: str) -> str:
        p = urllib.parse.urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def autorise(self, url: str) -> bool:
        origine = self._origine(url)
        rp = self.cache.get(origine)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            self.motifs[origine] = "interdit par robots.txt"
            try:
                self.politesse.attendre(origine)
                r = self.transport.get(origine + "/robots.txt", {"User-Agent": USER_AGENT})
                if r.statut in (401, 403):
                    rp.disallow_all = True
                elif 400 <= r.statut < 500:
                    rp.allow_all = True
                elif r.statut >= 500:
                    rp.disallow_all = True
                    self.motifs[origine] = f"robots.txt indisponible (HTTP {r.statut})"
                else:
                    rp.parse(r.corps.decode("utf-8", "replace").splitlines())
            except Exception as e:
                rp.disallow_all = True
                self.motifs[origine] = f"robots.txt inaccessible ({type(e).__name__})"
            self.cache[origine] = rp
        return rp.can_fetch(UA_ROBOTS, url)

    def motif(self, url: str) -> str:
        return self.motifs.get(self._origine(url), "interdit par robots.txt")


# --------------------------------------------------------------------------------------------- analyse des flux
class FluxInvalide(ValueError):
    pass


def _ln(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _enfant(el, *noms):
    for c in el:
        if _ln(c.tag) in noms:
            return c
    return None


def _texte(el) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _date_iso(valeur) -> str | None:
    if valeur in (None, ""):
        return None
    d = None
    if isinstance(valeur, (int, float)):
        try:
            d = datetime.fromtimestamp(valeur, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        v = str(valeur).strip()
        try:
            d = parsedate_to_datetime(v)
        except (TypeError, ValueError, IndexError, OverflowError):
            try:
                d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone.utc)
    if d > datetime.now(timezone.utc) + timedelta(days=2):
        return None  # date future fantaisiste
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def analyser_xml(octets: bytes) -> list[dict]:
    """RSS 2.0, RSS 1.0 (RDF) et Atom → [{titre, lien, resume, date}] ; refuse DTD et entités (XXE / billion laughs)."""
    tete = octets[:4096].lower()
    if b"<!doctype" in tete or b"<!entity" in octets.lower():
        raise FluxInvalide("DTD/entités XML refusées")
    try:
        racine = ET.fromstring(octets.lstrip(b"\xef\xbb\xbf \r\n\t"))
    except ET.ParseError as e:
        raise FluxInvalide(f"XML illisible ({e})") from None
    nom = _ln(racine.tag)
    sortie: list[dict] = []
    if nom == "feed":  # Atom
        for e in racine:
            if _ln(e.tag) != "entry":
                continue
            lien = ""
            for l in e:
                if _ln(l.tag) == "link" and l.get("rel", "alternate") == "alternate" and l.get("href"):
                    lien = l.get("href")
                    break
            resume = _enfant(e, "summary")
            if resume is None:
                resume = _enfant(e, "content")
            date = _texte(_enfant(e, "published")) or _texte(_enfant(e, "updated"))
            sortie.append({"titre": _texte(_enfant(e, "title")), "lien": lien, "resume": _texte(resume), "date": date})
    elif nom in ("rss", "rdf"):
        canal = racine.find("channel")
        items = racine.iter() if nom == "rdf" or canal is None else canal.iter()
        for it in items:
            if _ln(it.tag) != "item":
                continue
            lien = _texte(_enfant(it, "link"))
            guid = _enfant(it, "guid")
            if not lien and guid is not None and guid.get("isPermaLink", "true") != "false":
                lien = _texte(guid)
            resume = _enfant(it, "description")
            if resume is None or not _texte(resume):
                resume = _enfant(it, "encoded", "summary")
            date = _texte(_enfant(it, "pubdate")) or _texte(_enfant(it, "date"))
            sortie.append({"titre": _texte(_enfant(it, "title")), "lien": (lien or "").strip(), "resume": _texte(resume),
                           "date": date})
    else:
        raise FluxInvalide(f"format XML inconnu ({nom})")
    return sortie


def _json(octets: bytes):
    try:
        return json.loads(octets.decode("utf-8", "replace"))
    except ValueError:
        raise FluxInvalide("JSON illisible") from None


def _premier(v):
    """Premier élément d'une liste, ou valeur d'un dictionnaire multilingue (fra > eng > autre)."""
    if isinstance(v, list):
        return _premier(v[0]) if v else ""
    if isinstance(v, dict):
        for k in ("fra", "fr", "eng", "en"):
            if k in v:
                return _premier(v[k])
        return _premier(next(iter(v.values()), ""))
    return "" if v is None else str(v)


def analyser_json(octets: bytes, adaptateur: str, source: dict | None = None) -> list[dict]:
    """Adaptateurs d'API publiques. Les champs auteur (by, owner, user…) ne sont JAMAIS lus."""
    d = _json(octets)
    out: list[dict] = []
    if adaptateur == "jsonfeed":
        for it in d.get("items", []):
            out.append({"titre": it.get("title", ""), "lien": it.get("url", ""),
                        "resume": it.get("summary") or it.get("content_text") or it.get("content_html", ""),
                        "date": it.get("date_published") or it.get("date_modified")})
    elif adaptateur == "cisa_kev":
        vulns = sorted(d.get("vulnerabilities", []), key=lambda v: v.get("dateAdded", ""), reverse=True)
        for v in vulns:
            cve = v.get("cveID", "")
            out.append({"titre": f"{cve} — {v.get('vulnerabilityName', '')} ({v.get('vendorProject', '')})",
                        "lien": f"https://nvd.nist.gov/vuln/detail/{cve}",
                        "resume": f"{v.get('shortDescription', '')} Action requise : {v.get('requiredAction', '')}",
                        "date": v.get("dateAdded")})
    elif adaptateur == "nvd":
        for v in d.get("vulnerabilities", []):
            c = v.get("cve", {})
            desc = next((x.get("value", "") for x in c.get("descriptions", []) if x.get("lang") == "en"), "")
            out.append({"titre": f"{c.get('id', '')} — {tronquer(desc, 120)}",
                        "lien": f"https://nvd.nist.gov/vuln/detail/{c.get('id', '')}", "resume": desc,
                        "date": c.get("lastModified") or c.get("published")})
    elif adaptateur == "stackexchange":
        for it in d.get("items", []):
            out.append({"titre": html.unescape(it.get("title", "")), "lien": it.get("link", ""),
                        "resume": f"Tags : {', '.join(it.get('tags', []))} — score {it.get('score', 0)}, "
                                  f"{it.get('answer_count', 0)} réponse(s), "
                                  f"{'résolue' if it.get('is_answered') else 'non résolue'}.",
                        "date": it.get("creation_date")})
    elif adaptateur == "github_advisories":
        for it in d if isinstance(d, list) else []:
            out.append({"titre": f"{it.get('ghsa_id', '')} ({it.get('severity', '?')}) — {it.get('summary', '')}",
                        "lien": it.get("html_url", ""), "resume": it.get("description", ""),
                        "date": it.get("published_at")})
    elif adaptateur == "hal":
        for it in (d.get("response") or {}).get("docs", []):
            out.append({"titre": _premier(it.get("title_s")), "lien": it.get("uri_s", ""),
                        "resume": _premier(it.get("abstract_s")), "date": it.get("producedDate_s")})
    elif adaptateur == "opendatasoft":
        ch = (source or {}).get("champs") or {}
        for it in d.get("results", []):
            parties = [f"{k} : {_premier(it.get(k))}" for k in ch.get("resume", []) if it.get(k) not in (None, "", [])]
            try:
                lien = ch.get("lien", "").format(**{k: _premier(v) for k, v in it.items()})
            except (KeyError, IndexError, ValueError):
                lien = ""
            out.append({"titre": _premier(it.get(ch.get("titre", "titre"))), "lien": lien, "resume": " ; ".join(parties),
                        "date": _premier(it.get(ch.get("date", "date")))})
    elif adaptateur == "ted":
        for it in d.get("notices", []):
            num = _premier(it.get("publication-number"))
            out.append({"titre": _premier(it.get("notice-title")) or f"Avis TED {num}",
                        "lien": f"https://ted.europa.eu/fr/notice/-/detail/{num}",
                        "resume": f"Acheteur : {_premier(it.get('buyer-name'))} ; date limite : "
                                  f"{_premier(it.get('deadline-receipt-tender-date-lot')) or 'non précisée'}",
                        "date": _premier(it.get("publication-date"))[:10]})
    elif adaptateur == "datagouv":
        for it in d.get("data", []):
            out.append({"titre": it.get("title", ""), "lien": it.get("page", ""), "resume": it.get("description", ""),
                        "date": it.get("last_update") or it.get("created_at")})
    elif adaptateur == "gdelt":
        for it in d.get("articles", []):
            out.append({"titre": it.get("title", ""), "lien": it.get("url", ""),
                        "resume": f"Article de {it.get('domain', '?')} ({it.get('language', '?')}) repéré par GDELT.",
                        "date": it.get("seendate")})
    elif adaptateur == "youtube":
        for it in d.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if vid:  # le nom de la chaîne n'est pas stocké (peut être une personne physique)
                out.append({"titre": sn.get("title", ""), "lien": f"https://www.youtube.com/watch?v={vid}",
                            "resume": sn.get("description", ""), "date": sn.get("publishedAt"),
                            "auteur": sn.get("channelId", "")})
    elif adaptateur == "bluesky_fil":
        for it in d.get("feed", []):
            p = it.get("post") or {}
            rec, handle = p.get("record") or {}, (p.get("author") or {}).get("handle", "")
            rkey = str(p.get("uri", "")).rsplit("/", 1)[-1]
            out.append({"titre": "", "resume": rec.get("text", ""), "date": rec.get("createdAt") or p.get("indexedAt"),
                        "lien": f"https://bsky.app/profile/{handle}/post/{rkey}", "auteur": handle,
                        "cle": p.get("uri", "")})
    elif adaptateur == "mastodon_tag":
        for it in d if isinstance(d, list) else []:
            if it.get("reblog") or it.get("sensitive") or it.get("visibility") != "public":
                continue  # partages, contenus sensibles ou non publics : ignorés
            out.append({"titre": "", "resume": it.get("content", ""), "date": it.get("created_at"),
                        "lien": it.get("url") or it.get("uri", ""), "auteur": (it.get("account") or {}).get("acct", ""),
                        "cle": it.get("uri", "")})
    elif adaptateur == "hn_item":
        if d and d.get("type") == "story" and not d.get("dead") and not d.get("deleted"):
            out.append({"titre": d.get("title", ""),
                        "lien": d.get("url") or f"https://news.ycombinator.com/item?id={d.get('id')}",
                        "resume": d.get("text", "") or f"Discussion Hacker News — {d.get('descendants', 0)} commentaire(s).",
                        "date": d.get("time")})
    else:
        raise FluxInvalide(f"adaptateur inconnu {adaptateur}")
    return out


# --------------------------------------------------------------------------------------------- base SQLite
SCHEMA = """
CREATE TABLE IF NOT EXISTS fiches (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL,
    titre TEXT NOT NULL,
    resume TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    url_canonique TEXT NOT NULL UNIQUE,
    empreinte TEXT NOT NULL UNIQUE,
    date TEXT,
    domaines TEXT NOT NULL DEFAULT '',
    services TEXT NOT NULL DEFAULT '',
    projets TEXT NOT NULL DEFAULT '',
    confiance TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '',
    langue TEXT NOT NULL DEFAULT '',
    score_injection INTEGER NOT NULL DEFAULT 0,
    collecte_le TEXT NOT NULL,
    type_doc TEXT NOT NULL DEFAULT 'actualite',
    canal TEXT NOT NULL DEFAULT 'flux',
    licence TEXT NOT NULL DEFAULT '',
    stockage TEXT NOT NULL DEFAULT 'extrait',
    ref TEXT NOT NULL DEFAULT '',
    texte TEXT NOT NULL DEFAULT '',
    document TEXT NOT NULL DEFAULT '',
    autorite REAL NOT NULL DEFAULT 0.5,
    tonalite TEXT NOT NULL DEFAULT '',
    sujet TEXT NOT NULL DEFAULT '',
    expire_le TEXT
);
CREATE INDEX IF NOT EXISTS fiches_collecte ON fiches(collecte_le);
CREATE INDEX IF NOT EXISTS fiches_source ON fiches(source_id);
CREATE INDEX IF NOT EXISTS fiches_expire ON fiches(expire_le);
CREATE VIRTUAL TABLE IF NOT EXISTS fiches_fts USING fts5(
    titre, resume, domaines, texte, ref, content='fiches', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS fiches_ai AFTER INSERT ON fiches BEGIN
    INSERT INTO fiches_fts(rowid, titre, resume, domaines, texte, ref)
    VALUES (new.id, new.titre, new.resume, new.domaines, new.texte, new.ref);
END;
CREATE TRIGGER IF NOT EXISTS fiches_ad AFTER DELETE ON fiches BEGIN
    INSERT INTO fiches_fts(fiches_fts, rowid, titre, resume, domaines, texte, ref)
    VALUES ('delete', old.id, old.titre, old.resume, old.domaines, old.texte, old.ref);
END;
CREATE TRIGGER IF NOT EXISTS fiches_au AFTER UPDATE ON fiches BEGIN
    INSERT INTO fiches_fts(fiches_fts, rowid, titre, resume, domaines, texte, ref)
    VALUES ('delete', old.id, old.titre, old.resume, old.domaines, old.texte, old.ref);
    INSERT INTO fiches_fts(rowid, titre, resume, domaines, texte, ref)
    VALUES (new.id, new.titre, new.resume, new.domaines, new.texte, new.ref);
END;
CREATE TABLE IF NOT EXISTS etat_sources (
    source_id TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, dernier_passage TEXT, dernier_succes TEXT,
    echecs INTEGER NOT NULL DEFAULT 0, derniere_erreur TEXT, suspendu_jusqua TEXT, nb_fiches INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quotas (source_id TEXT, jour TEXT, requetes INTEGER NOT NULL DEFAULT 0,
                                   PRIMARY KEY (source_id, jour));
CREATE TABLE IF NOT EXISTS passages (id INTEGER PRIMARY KEY, debut TEXT, fin TEXT, sources INTEGER, nouvelles INTEGER,
                                     doublons INTEGER, rejetees INTEGER, erreurs INTEGER, nettoyage TEXT);
"""


COLONNES_V2 = {"type_doc": "TEXT NOT NULL DEFAULT 'actualite'", "canal": "TEXT NOT NULL DEFAULT 'flux'",
               "licence": "TEXT NOT NULL DEFAULT ''", "stockage": "TEXT NOT NULL DEFAULT 'extrait'",
               "ref": "TEXT NOT NULL DEFAULT ''", "texte": "TEXT NOT NULL DEFAULT ''", "document": "TEXT NOT NULL DEFAULT ''",
               "autorite": "REAL NOT NULL DEFAULT 0.5", "tonalite": "TEXT NOT NULL DEFAULT ''",
               "sujet": "TEXT NOT NULL DEFAULT ''", "expire_le": "TEXT"}


def _migrer(conn: sqlite3.Connection) -> None:
    """Base v1 → v2 : nouvelles colonnes + index plein texte reconstruit (texte, ref)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(fiches)")}
    if not cols:
        return
    for nom, decl in COLONNES_V2.items():
        if nom not in cols:
            conn.execute(f"ALTER TABLE fiches ADD COLUMN {nom} {decl}")
    fts = {r[1] for r in conn.execute("PRAGMA table_info(fiches_fts)")}
    if fts and "texte" not in fts:
        conn.executescript("DROP TRIGGER IF EXISTS fiches_ai; DROP TRIGGER IF EXISTS fiches_ad; "
                           "DROP TRIGGER IF EXISTS fiches_au; DROP TABLE IF EXISTS fiches_fts;")
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO fiches_fts(fiches_fts) VALUES ('rebuild')")
    conn.commit()


def ouvrir(chemin: Path | str = DB_DEFAUT) -> sqlite3.Connection:
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    # Journal DELETE (pas de WAL) : la base publiée se lit sur un montage en lecture seule sans -wal/-shm.
    conn.execute("PRAGMA journal_mode=DELETE")
    _migrer(conn)
    conn.executescript(SCHEMA)
    return conn


def _fsync(chemin: Path) -> None:
    fd = os.open(str(chemin), os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:  # certains systèmes refusent fsync sur un dossier
        pass
    finally:
        os.close(fd)


@contextlib.contextmanager
def base_de_travail(chemin: Path | str = DB_DEFAUT, publier: bool = True):
    """Copie de travail `veille.db.tmp` (journal DELETE) puis publication ATOMIQUE vers `veille.db`.

    Les lecteurs (nexus-core, montage en lecture seule) voient toujours soit l'ancienne base complète, soit la
    nouvelle : jamais un état intermédiaire. Un verrou `veille.db.lock` empêche deux collectes simultanées.
    En cas d'erreur, ou si publier=False (simulation), la copie de travail est jetée.
    """
    chemin = Path(chemin)
    tmp = chemin.with_name(chemin.name + ".tmp")
    verrou = open(chemin.with_name(chemin.name + ".lock"), "w")
    try:
        try:
            import fcntl
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # pragma: no cover (Windows)
            pass
        except OSError:
            raise RuntimeError("une autre collecte est en cours (veille.db.lock)") from None
        for reste in (tmp, Path(str(tmp) + "-journal"), Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            reste.unlink(missing_ok=True)
        if chemin.exists():  # copie cohérente via l'API de sauvegarde SQLite (gère aussi une ancienne base en WAL)
            src = sqlite3.connect(f"file:{chemin.resolve()}?mode=ro", uri=True)
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
        conn = ouvrir(tmp)
        ok = False
        try:
            yield conn
            ok = True
        finally:
            if ok and publier:
                conn.commit()
                conn.execute("PRAGMA journal_mode=DELETE")
            conn.close()
            if ok and publier:
                _fsync(tmp)
                os.replace(tmp, chemin)  # atomique sur un même système de fichiers
                _fsync(chemin.parent)
                for reste in (Path(str(chemin) + "-wal"), Path(str(chemin) + "-shm")):
                    reste.unlink(missing_ok=True)  # vestiges d'une ancienne base en WAL
            else:
                tmp.unlink(missing_ok=True)
                Path(str(tmp) + "-journal").unlink(missing_ok=True)
    finally:
        verrou.close()


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _liste(valeurs: Iterable[str]) -> str:
    return "|" + "|".join(valeurs) + "|" if valeurs else ""


def supprimer(conn: sqlite3.Connection, url: str | None = None, texte: str | None = None,
              source_id: str | None = None) -> int:
    """Effacement ciblé (demande d'une personne, erreur, retrait d'une source). Renvoie le nombre de fiches supprimées."""
    if url:
        n = conn.execute("DELETE FROM fiches WHERE url_canonique = ? OR url = ?", (url_canonique(url), url)).rowcount
    elif texte:
        motif = f"%{texte}%"
        n = conn.execute("DELETE FROM fiches WHERE titre LIKE ? OR resume LIKE ?", (motif, motif)).rowcount
    elif source_id:
        n = conn.execute("DELETE FROM fiches WHERE source_id = ?", (source_id,)).rowcount
    else:
        raise ValueError("préciser --url, --texte ou --source")
    conn.commit()
    log.info("effacement ciblé : %d fiche(s) supprimée(s)", n)
    return n


def purger(conn: sqlite3.Connection, jours: int = RETENTION_JOURS, maintenant: datetime | None = None) -> int:
    """Supprime les fiches collectées il y a plus de `jours` jours (et les vieux compteurs de quota)."""
    limite = _iso((maintenant or _maintenant()) - timedelta(days=jours))
    n = conn.execute("DELETE FROM fiches WHERE collecte_le < ?", (limite,)).rowcount
    # rétention courte du social (30 j par défaut) : champ expire_le fixé à l'insertion
    n += conn.execute("DELETE FROM fiches WHERE expire_le IS NOT NULL AND expire_le < ?",
                      (_iso(maintenant or _maintenant()),)).rowcount
    conn.execute("DELETE FROM quotas WHERE jour < ?", (limite[:10],))
    conn.commit()
    if n:
        log.info("rétention : %d fiche(s) de plus de %d jours supprimée(s)", n, jours)
    return n


# --------------------------------------------------------------------------------------------- collecte
@dataclass
class Bilan:
    sources: int = 0
    nouvelles: int = 0
    doublons: int = 0
    rejetees: int = 0
    erreurs: int = 0
    ignorees: int = 0
    details: list[dict] = field(default_factory=list)


def _duree(freq: str) -> timedelta:
    m = REGLE_FREQ.match(freq or "24h")
    n, u = (int(m.group(1)), m.group(2)) if m else (24, "h")
    return timedelta(hours=n) if u == "h" else timedelta(days=n)


class Collecteur:
    def __init__(self, conn: sqlite3.Connection, transport=None, politesse: Politesse | None = None,
                 nettoyeur: Nettoyeur | None = None, horloge: Callable[[], datetime] = _maintenant):
        self.conn = conn
        self.transport = transport or TransportHTTP()
        self.politesse = politesse or Politesse()
        self.robots = GardienRobots(self.transport, self.politesse)
        self.nettoyeur = nettoyeur or Nettoyeur()
        self.horloge = horloge
        self._suspensions: dict[str, str] = {}
        self._erreur_reseau = False

    # -- état / quotas
    def _etat(self, sid: str) -> sqlite3.Row:
        self.conn.execute("INSERT OR IGNORE INTO etat_sources(source_id) VALUES (?)", (sid,))
        return self.conn.execute("SELECT * FROM etat_sources WHERE source_id=?", (sid,)).fetchone()

    def _maj_etat(self, sid: str, **champs) -> None:
        cles = ", ".join(f"{k}=?" for k in champs)
        self.conn.execute(f"UPDATE etat_sources SET {cles} WHERE source_id=?", (*champs.values(), sid))

    def _quota_ok(self, s: dict) -> bool:
        q = s.get("quota_jour")
        if not q:
            return True
        jour = self.horloge().strftime("%Y-%m-%d")
        r = self.conn.execute("SELECT requetes FROM quotas WHERE source_id=? AND jour=?", (s["id"], jour)).fetchone()
        return (r["requetes"] if r else 0) < int(q)

    def _compter(self, sid: str) -> None:
        jour = self.horloge().strftime("%Y-%m-%d")
        self.conn.execute("INSERT INTO quotas(source_id, jour, requetes) VALUES (?, ?, 1) "
                          "ON CONFLICT(source_id, jour) DO UPDATE SET requetes = requetes + 1", (sid, jour))

    def _echec(self, s: dict, message: str, attente: timedelta | None = None) -> None:
        e = self._etat(s["id"])
        echecs = (e["echecs"] or 0) + 1
        suspendu = None
        if attente:
            suspendu = _iso(self.horloge() + min(attente, timedelta(hours=24)))
        elif echecs >= ECHECS_AVANT_SUSPENSION:
            suspendu = _iso(self.horloge() + SUSPENSION)
            log.warning("source %s suspendue %s après %d échecs", s["id"], SUSPENSION, echecs)
        self._maj_etat(s["id"], echecs=echecs, derniere_erreur=message[:200], suspendu_jusqua=suspendu,
                       dernier_passage=_iso(self.horloge()))
        log.warning("source %s : %s", s["id"], message[:200])

    # -- requêtes
    def _entetes(self, s: dict, conditionnel: bool = True) -> dict:
        h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
             "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.5"}
        if conditionnel:
            e = self._etat(s["id"])
            if e["etag"]:
                h["If-None-Match"] = e["etag"]
            if e["last_modified"]:
                h["If-Modified-Since"] = e["last_modified"]
        cle = os.environ.get(s.get("cle_env", "") or "", "")
        if cle and s.get("adaptateur") == "nvd":
            h["apiKey"] = cle
        if cle and s.get("adaptateur") == "github_advisories":
            h["Authorization"] = f"Bearer {cle}"
        return h

    def _url(self, s: dict) -> str:
        url = str(s["url_flux"])
        depuis = int((self.horloge() - timedelta(days=7)).timestamp())
        url = url.replace("{depuis}", str(depuis))
        if s.get("adaptateur") == "nvd" and "lastModStartDate" not in url:
            fin = self.horloge()
            debut = fin - timedelta(days=2)
            fmt = "%Y-%m-%dT%H:%M:%S.000Z"
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                {"lastModStartDate": debut.strftime(fmt), "lastModEndDate": fin.strftime(fmt),
                 "resultsPerPage": int(s.get("max_par_passage") or MAX_PAR_PASSAGE)})
        cle = os.environ.get(s.get("cle_env", "") or "", "")
        if cle and s.get("adaptateur") == "stackexchange":
            url += "&key=" + urllib.parse.quote(cle)
        if cle and s.get("adaptateur") == "youtube":
            url += "&key=" + urllib.parse.quote(cle)
        return url

    def _get(self, s: dict, url: str, conditionnel: bool = True) -> Reponse | None:
        if s["acces"] in ("rss", "atom") and not self.robots.autorise(url):
            motif = self.robots.motif(url)
            interdit = motif == "interdit par robots.txt"
            self._echec(s, f"{motif} — source ignorée", attente=timedelta(hours=24) if interdit else None)
            if not interdit:
                self._erreur_reseau = True
            return None
        if not self._quota_ok(s):
            log.info("source %s : quota journalier atteint", s["id"])
            return None
        self.politesse.attendre(url)
        self._compter(s["id"])
        if s.get("corps_json"):
            h = self._entetes(s, conditionnel=False)
            h["Content-Type"] = "application/json"
            r = self.transport.post(url, h, json.dumps(s["corps_json"]).encode("utf-8"))
        else:
            r = self.transport.get(url, self._entetes(s, conditionnel))
        if r.statut in (429, 503):
            ra = r.entetes.get("retry-after", "")
            attente = timedelta(seconds=int(ra)) if ra.isdigit() else timedelta(hours=6)
            self._echec(s, f"HTTP {r.statut} (limite de débit) sur {masquer(url)}", attente=attente)
            return None
        return r

    def _elements(self, s: dict) -> tuple[list[dict], Reponse | None]:
        url = self._url(s)
        r = self._get(s, url)
        if r is None:
            return [], None
        if r.statut == 304 or r.statut >= 400:
            return [], r
        maxi = int(s.get("max_par_passage") or MAX_PAR_PASSAGE)
        if s["acces"] in ("rss", "atom"):
            return analyser_xml(r.corps)[:maxi], r
        ad = s.get("adaptateur")
        if ad == "hn":
            liste = _json(r.corps)
            ids = liste[:maxi] if isinstance(liste, list) else []
            sortie = []
            for i in ids:
                ri = self._get(s, f"https://hacker-news.firebaseio.com/v0/item/{int(i)}.json", conditionnel=False)
                if ri is not None and ri.statut == 200:
                    sortie += analyser_json(ri.corps, "hn_item")
            return sortie, r
        donnees = analyser_json(r.corps, ad, s)
        if ad == "stackexchange":
            b = _json(r.corps).get("backoff")
            if b:  # l'API demande d'attendre : on n'y revient pas avant
                self._suspensions[s["id"]] = _iso(self.horloge() + timedelta(seconds=int(b)))
        return donnees[:maxi], r

    # -- fiches
    def preparer_fiche(self, el: dict, s: dict) -> tuple[dict | None, str]:
        base = s.get("url_flux") or s.get("url")
        lien = urllib.parse.urljoin(base, str(el.get("lien") or "").strip())
        if not url_bien_formee(lien):
            return None, "lien invalide"
        nt = self.nettoyeur.nettoyer(str(el.get("titre") or ""), s["id"])
        nr = self.nettoyeur.nettoyer(str(el.get("resume") or ""), s["id"])
        score = max(nt.score, nr.score)
        if self.nettoyeur.bouclier is not None:
            score = max(score, self.nettoyeur.bouclier.detecter_injection(f"{nt.texte}\n{nr.texte}").score)
        if score >= SEUIL_REJET:
            return None, f"injection (score {score})"
        if self.nettoyeur.secrets(f"{nt.texte}\n{nr.texte}"):
            return None, "secret apparent"
        autorises = s.get("comptes_autorises") or []
        canal = canal_de(s)
        sto = stockage_effectif(s)
        maint = self.horloge()
        titre = tronquer(anonymiser(nt.texte, autorises), MAX_TITRE)
        maxi = min(MAX_RESUME, int(s.get("resume_max") or (MAX_RESUME_PRESSE if canal == "media" or s.get("type") == "media"
                                                          else MAX_RESUME)))
        expire = None
        auteur = str(el.get("auteur") or "").lower().lstrip("@")
        institutionnel = bool(auteur) and auteur in {a.lower().lstrip("@") for a in autorises}
        if canal == "social":
            # Social listening (recommandations CNIL) : extrait court anonymisé, aucun identifiant de personne,
            # lien vers la page du SUJET (pas du profil) sauf compte institutionnel, rétention courte.
            maxi = MAX_EXTRAIT_SOCIAL
            expire = _iso(maint + timedelta(days=RETENTION_SOCIAL_JOURS))
            if not institutionnel:
                cle = hashlib.sha256(str(el.get("cle") or lien).encode()).hexdigest()[:16]
                lien = f"{s['url'].split('#')[0]}#{cle}"  # pseudonyme par contenu, jamais par personne
            titre = ""
        resume = tronquer(anonymiser(nr.texte, autorises), maxi)
        if sto == "metadonnees":
            resume = ""
        if not titre:
            titre = tronquer(resume, 120) or lien
        tonalite = ""
        if canal in ("social", "media"):
            try:
                from tendances import tonalite as _ton
            except ImportError:  # pragma: no cover
                from .tendances import tonalite as _ton  # type: ignore
            tonalite = _ton(f"{titre} {resume}")
        return {
            "source_id": s["id"], "titre": titre, "resume": resume, "url": lien, "url_canonique": url_canonique(lien) +
            (("#" + lien.split("#", 1)[1]) if canal == "social" and "#" in lien else ""),
            "empreinte": empreinte(titre, resume), "date": _date_iso(el.get("date")),
            "domaines": " ".join(s.get("domaines") or []), "services": _liste(s.get("services_syfer") or []),
            "projets": _liste(s.get("projets") or []), "confiance": confiance_fiche(s["confiance"], canal),
            "type": s["type"], "langue": s.get("langue", ""), "score_injection": int(score), "collecte_le": _iso(maint),
            "type_doc": s.get("type_doc", "actualite"), "canal": canal, "licence": s.get("licence", ""), "stockage": sto,
            "autorite": float(s.get("autorite", AUTORITE_PAR_TYPE.get(s.get("type"), 0.5))), "tonalite": tonalite,
            "expire_le": expire,
        }, "ok"

    def enregistrer(self, fiche: dict) -> bool:
        fiche = dict(fiche)
        fiche["date"] = _date_iso(fiche.get("date"))  # toujours ISO 8601 UTC (ou NULL) en base
        fiche["collecte_le"] = _date_iso(fiche.get("collecte_le")) or _iso(self.horloge())
        cols = ", ".join(fiche)
        try:
            self.conn.execute(f"INSERT INTO fiches({cols}) VALUES ({', '.join('?' * len(fiche))})", tuple(fiche.values()))
            return True
        except sqlite3.IntegrityError:
            return False  # URL canonique ou empreinte déjà connue

    def collecter_source(self, s: dict, bilan: Bilan, forcer: bool = False, simulation: bool = False) -> None:
        e = self._etat(s["id"])
        maint = self.horloge()
        if not forcer:
            if e["suspendu_jusqua"] and e["suspendu_jusqua"] > _iso(maint):
                bilan.ignorees += 1
                return
            if e["dernier_passage"] and e["dernier_passage"] > _iso(maint - _duree(s.get("frequence_conseillee")) + timedelta(minutes=10)):
                bilan.ignorees += 1
                return
        bilan.sources += 1
        d = {"source": s["id"], "nouvelles": 0, "doublons": 0, "rejetees": 0, "erreur": None}
        try:
            elements, r = self._elements(s)
        except Exception as ex:  # flux invalide, réseau…
            bilan.erreurs += 1
            d["erreur"] = f"{type(ex).__name__}: {str(ex)[:120]}"
            self._echec(s, d["erreur"])
            bilan.details.append(d)
            return
        if r is None:
            if self._erreur_reseau:
                bilan.erreurs += 1
                self._erreur_reseau = False
            bilan.details.append(d | {"erreur": "non récupéré (robots.txt, réseau, quota ou limite de débit)"})
            return
        if r.statut >= 400:
            bilan.erreurs += 1
            d["erreur"] = f"HTTP {r.statut}"
            self._echec(s, f"HTTP {r.statut} sur {masquer(self._url(s))}")
            bilan.details.append(d)
            return
        for el in elements:
            fiche, motif = self.preparer_fiche(el, s)
            if fiche is None:
                d["rejetees"] += 1
                bilan.rejetees += 1
                log.info("fiche rejetée (%s) : source %s", motif, s["id"])
                continue
            if simulation:
                d["nouvelles"] += 1
                continue
            if self.enregistrer(fiche):
                d["nouvelles"] += 1
            else:
                d["doublons"] += 1
        bilan.nouvelles += d["nouvelles"]
        bilan.doublons += d["doublons"]
        champs = {"echecs": 0, "derniere_erreur": None, "suspendu_jusqua": self._suspensions.pop(s["id"], None), "dernier_passage": _iso(maint),
                  "dernier_succes": _iso(maint), "nb_fiches": (e["nb_fiches"] or 0) + d["nouvelles"]}
        if r.statut == 200:
            champs["etag"] = r.entetes.get("etag")
            champs["last_modified"] = r.entetes.get("last-modified")
        self._maj_etat(s["id"], **champs)
        self.conn.commit()
        bilan.details.append(d)

    def collecter(self, sources: list[dict], forcer: bool = False, simulation: bool = False) -> Bilan:
        bilan = Bilan()
        debut = _iso(self.horloge())
        for s in sources:
            if (s.get("collecte") != "oui" or s.get("acces") in ("manuel", "document")
                    or s.get("adaptateur") == "a_configurer"):
                continue
            if _sur_hote(s.get("url_flux", ""), HOTES_SANS_COLLECTE):
                continue  # double sécurité, même si le catalogue a été mal modifié
            self.collecter_source(s, bilan, forcer, simulation)
        if not simulation:
            purger(self.conn, maintenant=self.horloge())
            self.conn.execute("INSERT INTO passages(debut, fin, sources, nouvelles, doublons, rejetees, erreurs, nettoyage) "
                              "VALUES (?,?,?,?,?,?,?,?)", (debut, _iso(self.horloge()), bilan.sources, bilan.nouvelles,
                                                           bilan.doublons, bilan.rejetees, bilan.erreurs, self.nettoyeur.mode))
            self.conn.commit()
        log.info("passage : %d source(s), %d nouvelle(s), %d doublon(s), %d rejetée(s), %d erreur(s), %d ignorée(s) [%s]",
                 bilan.sources, bilan.nouvelles, bilan.doublons, bilan.rejetees, bilan.erreurs, bilan.ignorees,
                 self.nettoyeur.mode)
        return bilan

    def verifier(self, sources: list[dict]) -> list[dict]:
        """Teste chaque flux collectable : statut HTTP, nombre d'éléments lisibles. Ne stocke aucune fiche."""
        rapport = []
        for s in sources:
            if s.get("acces") in ("manuel", "document") or s.get("adaptateur") == "a_configurer":
                continue
            ligne = {"id": s["id"], "url_flux": masquer(s.get("url_flux", "")), "statut": None, "elements": 0, "erreur": None}
            try:
                url = self._url(s)
                if s["acces"] in ("rss", "atom") and not self.robots.autorise(url):
                    ligne["erreur"] = self.robots.motif(url)
                else:
                    self.politesse.attendre(url)
                    if s.get("corps_json"):
                        h = self._entetes(s, conditionnel=False) | {"Content-Type": "application/json"}
                        r = self.transport.post(url, h, json.dumps(s["corps_json"]).encode("utf-8"))
                    else:
                        r = self.transport.get(url, self._entetes(s, conditionnel=False))
                    ligne["statut"] = r.statut
                    if r.statut == 200:
                        els = analyser_xml(r.corps) if s["acces"] in ("rss", "atom") else (
                            _json(r.corps) if s.get("adaptateur") == "hn" else analyser_json(r.corps, s["adaptateur"], s))
                        ligne["elements"] = len(els)
            except Exception as ex:
                ligne["erreur"] = f"{type(ex).__name__}: {str(ex)[:120]}"
            rapport.append(ligne)
            log.info("vérification %-32s statut=%s éléments=%s %s", s["id"], ligne["statut"], ligne["elements"],
                     ligne["erreur"] or "")
        return rapport


# --------------------------------------------------------------------------------------------- tableau lisible
NOMS_DOMAINES = {
    "droit": "Droit (France, UE, international)", "cybersecurite": "Cybersécurité", "ia": "Intelligence artificielle",
    "entreprise": "Entreprise et pilotage", "environnement": "Environnement et numérique responsable",
    "design_ux": "Design, UX et accessibilité", "marketing_communication": "Marketing et communication",
    "poker": "Poker", "bd_edition": "BD et édition", "forums_experts": "Forums d'experts techniques",
    "reseaux_sociaux": "Réseaux sociaux (ouverts) et plateformes exclues",
    "communication_institutionnelle": "Communication institutionnelle", "tech": "Actualité technique et logiciels de la pile",
}


def generer_catalogue_md(cat: dict) -> str:
    """CATALOGUE.md : un tableau par domaine (une source apparaît dans son domaine principal)."""
    sources = cat.get("sources", [])
    from collections import Counter
    types = Counter(s["type"] for s in sources)
    verif = sum(1 for s in sources if s["verifie"] != "non_verifie")
    flux = Counter(s["flux_verifie"] for s in sources)
    col = sum(1 for s in sources if s["collecte"] == "oui")
    l = ["# Catalogue de veille SYFER", "",
         f"Généré depuis `catalogue.yaml` (mise à jour {cat.get('mis_a_jour', '?')}) par `python collecteur.py tableau`. "
         "Ne pas modifier à la main : modifier `catalogue.yaml` puis régénérer.", "",
         f"**{len(sources)} sources** — {col} collectées automatiquement, {len(sources) - col} en consultation manuelle "
         f"ou non collectées. Types : " + ", ".join(f"{k} {v}" for k, v in sorted(types.items())) + ".", "",
         f"**Vérification** : {verif} sources vues en ligne le {cat.get('mis_a_jour', '?')} ; flux exacts confirmés : "
         f"{flux['oui']}, construits selon un motif documenté : {flux['motif']}, à confirmer sur le VPS "
         f"(`python collecteur.py verifier`) : {flux['non']}.", "",
         "Légende — Confiance : **A** officielle · **B** expert reconnu / presse spécialisée · **C** communauté · "
         "**D** réseau social. Accès : rss · atom · api · manuel. Vérifié : date ou « non ». "
         "Flux : oui (URL confirmée) · motif (motif documenté) · non (à confirmer) · — (sans objet).", ""]
    for d, titre in NOMS_DOMAINES.items():
        groupe = [s for s in sources if (s.get("domaines") or [""])[0] == d]
        if not groupe:
            continue
        l += [f"## {titre} ({len(groupe)})", "", "| Nom | Type | Confiance | Accès | Collecte | Vérifié | Flux |",
              "|---|---|---|---|---|---|---|"]
        for s in sorted(groupe, key=lambda x: (x["collecte"] != "oui", x["confiance"], x["nom"].lower())):
            nom = s["nom"].replace("|", "/")
            v = s["verifie"] if s["verifie"] != "non_verifie" else "non"
            f = {"sans_objet": "—"}.get(s["flux_verifie"], s["flux_verifie"])
            c = "oui" if s["collecte"] == "oui" else "non"
            l.append(f"| [{nom}]({s['url']}) | {s['type']} | {s['confiance']} | {s['acces']} | {c} | {v} | {f} |")
        l.append("")
    exclues = [s for s in sources if s["collecte"] == "non"]
    l += ["## Sources non collectées et pourquoi", "", "| Source | Raison |", "|---|---|"]
    l += [f"| {s['nom'].replace('|', '/')} | {str(s.get('raison', '')).replace('|', '/')} |" for s in exclues]
    return "\n".join(l) + "\n"


# --------------------------------------------------------------------------------------------- CLI
def configurer_journal(fichier: str | None = None) -> None:
    fichier = fichier or os.environ.get("VEILLE_JOURNAL", str(ICI / "journal" / "veille.log"))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    racine = logging.getLogger("syfer.veille")
    racine.setLevel(logging.INFO)
    if not racine.handlers:
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        racine.addHandler(h)
        try:
            Path(fichier).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(fichier, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            fh.setFormatter(fmt)
            racine.addHandler(fh)
        except OSError:
            pass


def _selection(cat: dict, ids: list[str] | None, domaine: str | None) -> list[dict]:
    sources = cat.get("sources", [])
    if ids:
        sources = [s for s in sources if s["id"] in ids]
    if domaine:
        sources = [s for s in sources if domaine in (s.get("domaines") or [])]
    return sources


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collecteur de veille SYFER (fiches courtes, accès autorisés uniquement)")
    ap.add_argument("commande", choices=["valider", "collecter", "verifier", "purger", "stats", "tableau", "supprimer"])
    ap.add_argument("--source", action="append", help="id de source (répétable)")
    ap.add_argument("--domaine")
    ap.add_argument("--forcer", action="store_true", help="ignorer fréquence et suspension")
    ap.add_argument("--simulation", action="store_true", help="n'enregistrer aucune fiche (l'état des sources est mis à jour)")
    ap.add_argument("--jours", type=int, default=RETENTION_JOURS)
    ap.add_argument("--url", help="supprimer : fiche de cette URL")
    ap.add_argument("--texte", help="supprimer : fiches contenant ce texte (ex. un nom, sur demande RGPD)")
    ap.add_argument("--db", default=str(DB_DEFAUT))
    ap.add_argument("--catalogue", default=str(CATALOGUE))
    a = ap.parse_args(argv)
    configurer_journal()
    cat = charger_catalogue(a.catalogue)
    if a.commande == "valider":
        erreurs = valider_catalogue(cat, min_par_domaine=8)
        for e in erreurs:
            print("ERREUR :", e)
        n = len(cat.get("sources", []))
        print(f"{n} source(s), {len(erreurs)} erreur(s).")
        return 1 if erreurs else 0
    if a.commande == "tableau":
        (ICI / "CATALOGUE.md").write_text(generer_catalogue_md(cat), encoding="utf-8")
        print(f"CATALOGUE.md régénéré ({len(cat.get('sources', []))} sources).")
        return 0
    erreurs = valider_catalogue(cat)
    if erreurs:
        print("Catalogue invalide : lancer « python collecteur.py valider ».", file=sys.stderr)
        return 1
    if a.commande == "stats":
        if not Path(a.db).exists():
            print("Base absente : lancer « python collecteur.py collecter ».")
            return 0
        conn = sqlite3.connect(f"file:{Path(a.db).resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        tot = conn.execute("SELECT COUNT(*) FROM fiches").fetchone()[0]
        print(f"{tot} fiche(s) ; taille de la base : {Path(a.db).stat().st_size / 1e6:.1f} Mo")
        for r in conn.execute("SELECT confiance, COUNT(*) n FROM fiches GROUP BY confiance ORDER BY confiance"):
            print(f"  confiance {r['confiance']} : {r['n']}")
        for r in conn.execute("SELECT source_id, echecs, derniere_erreur, suspendu_jusqua FROM etat_sources WHERE echecs > 0"):
            print(f"  ⚠ {r['source_id']} : {r['echecs']} échec(s) — {r['derniere_erreur']} (suspendu jusqu'à {r['suspendu_jusqua']})")
        conn.close()
        return 0
    publier = not (a.commande == "verifier" or (a.commande == "collecter" and a.simulation))
    with base_de_travail(a.db, publier=publier) as conn:
        if a.commande == "purger":
            print(f"{purger(conn, a.jours)} fiche(s) supprimée(s).")
            return 0
        if a.commande == "supprimer":
            sid = a.source[0] if a.source else None
            print(f"{supprimer(conn, a.url, a.texte, sid)} fiche(s) supprimée(s).")
            return 0
        col = Collecteur(conn)
        sources = _selection(cat, a.source, a.domaine)
        if a.commande == "verifier":
            rapport = col.verifier(sources)
            dossier = ICI / "journal"
            dossier.mkdir(exist_ok=True)
            sortie = dossier / f"verification-{_maintenant():%Y%m%d-%H%M}.json"
            sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
            ok = sum(1 for r in rapport if r["statut"] == 200 and r["elements"])
            print(f"{ok}/{len(rapport)} flux lisibles — rapport : {sortie}")
            return 0
        b = col.collecter(sources, forcer=a.forcer, simulation=a.simulation)
        print(f"{b.sources} source(s) interrogée(s), {b.nouvelles} nouvelle(s) fiche(s), {b.doublons} doublon(s), "
              f"{b.rejetees} rejetée(s), {b.erreurs} erreur(s). Nettoyage : {col.nettoyeur.mode}.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
