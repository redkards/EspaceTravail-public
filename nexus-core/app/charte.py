"""Charte par projet, contrôlée par du code (pas par le LLM).

Fichiers : nexus-core/chartes/<code>.yaml (embarqués) ; une copie dans /config/chartes/<code>.yaml
(montage) ou dans NEXUS_CHARTES_DIR la remplace. _commun.yaml s'applique à tous les projets.

Le contrôle tourne AVANT le CHECKER :
- violation « bloquant » → retour à l'ANALYST avec la liste précise ;
- « avertissement » → noté pour le CHECKER et la carte du Décideur.
Contrôles : marques d'autres projets (ne pas mélanger), termes interdits, mentions obligatoires
selon le type de livrable, ton (vouvoiement), marqueurs de travail inachevé.
"""
import os
import re
from pathlib import Path

import yaml

from . import gate
from . import projets as registre

EMBARQUE = Path(__file__).resolve().parent.parent / "chartes"
CONFIG_MONTEE = Path("/config/chartes")

# Type de livrable selon le service : décide des mentions obligatoires et de la gravité de l'inachevé.
TYPES_SERVICE = {
    "CONTENT-ARENA/redaction": "publication", "DESIGN-SYSTEM/ui": "publication", "GREEN-CORE/rse": "publication",
    "REVENUE-CORE/propositions": "commercial",
}
_TUTOIEMENT = re.compile(r"(?<![a-z0-9'])(tu|toi|ton|tes|t'as|t'es)(?![a-z0-9])")


def type_livrable(service: str | None, action: str | None = None) -> str:
    srv = service or ""
    if srv.startswith("LEX-GUARD/"):
        return "juridique"
    if action in ("publier", "envoyer_client"):
        return "publication" if action == "publier" else "commercial"
    return TYPES_SERVICE.get(srv, "interne")


def _dossiers() -> list[Path]:
    d = [Path(os.environ["NEXUS_CHARTES_DIR"])] if os.environ.get("NEXUS_CHARTES_DIR", "").strip() else []
    return d + [CONFIG_MONTEE, EMBARQUE]


def _lire(nom: str) -> dict:
    for dossier in _dossiers():
        f = dossier / f"{nom}.yaml"
        if f.is_file():
            return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return {}


def charger(projet: str | None) -> dict:
    """Charte effective du projet (alias résolus) fusionnée avec _commun.yaml."""
    try:
        code = registre.resoudre(projet)
    except ValueError:
        code = "divers"
    commun, propre = _lire("_commun"), _lire(code)
    from .config import cfg
    ajouts_f = cfg().data_dir / "chartes_ajouts" / f"{code}.yaml"  # leçons acceptées « vers la charte »
    ajouts = (yaml.safe_load(ajouts_f.read_text(encoding="utf-8")) or {}) if ajouts_f.is_file() else {}
    propre = {**propre, "termes_interdits": (propre.get("termes_interdits") or []) + (ajouts.get("termes_interdits") or [])}
    return {
        "projet": code,
        "marque": propre.get("marque") or {},
        "marques_interdites": propre.get("marques_interdites") or [],
        "termes_interdits": (commun.get("termes_interdits") or []) + (propre.get("termes_interdits") or []),
        "mentions_obligatoires": (commun.get("mentions_obligatoires") or []) + (propre.get("mentions_obligatoires") or []),
        "ton": propre.get("ton") or {},
        "inacheve": {**(commun.get("inacheve") or {}), **(propre.get("inacheve") or {})},
    }


def _present(texte_norm: str, chiffres: str, alternative: str) -> bool:
    if re.search(r"\d{2}", alternative):  # numéro : comparaison sur les seuls chiffres
        return re.sub(r"\D", "", alternative) in chiffres
    return gate.normaliser(alternative) in texte_norm


def verifier(projet: str | None, service: str | None, livrable: str, action: str | None = None) -> dict:
    """Renvoie {"bloquants": [...], "avertissements": [...], "type": ...} (messages précis, en français)."""
    c = charger(projet)
    t = gate.normaliser(livrable or "")
    chiffres = re.sub(r"\D", "", livrable or "")
    typ = type_livrable(service, action)
    res = {"bloquants": [], "avertissements": [], "type": typ, "projet": c["projet"]}

    def noter(gravite: str, message: str):
        (res["bloquants"] if gravite == "bloquant" else res["avertissements"]).append(message)

    marque = c["marque"].get("nom") or c["projet"]
    for m in c["marques_interdites"]:
        variantes = [gate.normaliser(v) for v in (m.get("variantes") or [m["nom"]])]
        trouve = gate._contient(t, [re.escape(v) for v in variantes])
        if trouve:
            noter(m.get("gravite", "bloquant"),
                  f"Marque d'un autre univers : « {m['nom']} » ({m.get('contexte', 'autre projet')}) "
                  f"ne doit pas apparaître dans un livrable « {marque} ». Retirez-la.")
    for terme in c["termes_interdits"]:
        mot = gate.normaliser(terme["terme"])
        if gate._contient(t, [re.escape(mot)]):
            noter(terme.get("gravite", "bloquant"),
                  f"Terme interdit « {terme['terme']} » : {terme.get('motif', 'contraire à la charte')}.")
    for regle in c["mentions_obligatoires"]:
        if typ not in (regle.get("types") or []):
            continue
        si = [gate.normaliser(x) for x in (regle.get("si") or [])]
        if si and not any(x in t for x in si):
            continue
        for groupe in regle.get("toutes") or []:
            if not any(_present(t, chiffres, alt) for alt in groupe):
                noter(regle.get("gravite", "bloquant"),
                      f"Mention obligatoire absente ({regle.get('nom', 'mention')}) : ajoutez « {groupe[0]} »"
                      + (f" (ou : {', '.join(groupe[1:])})" if len(groupe) > 1 else "") + ".")
    ton = c["ton"]
    if ton.get("vouvoiement") and len(_TUTOIEMENT.findall(t)) >= 2:
        noter(ton.get("gravite", "avertissement"), "Ton : la charte impose le vouvoiement (tutoiement détecté).")
    inach = c["inacheve"]
    trouves = [m for m in inach.get("marqueurs") or []
               if re.search(rf"(?<![a-z0-9]){re.escape(gate.normaliser(m))}(?![a-z0-9])", t)]
    if trouves:
        gravite = inach.get("gravite_publication" if typ in ("publication", "commercial") else "gravite_autres",
                            "avertissement")
        noter(gravite, "Travail inachevé (" + ", ".join(f"« {m} »" for m in trouves) + ") : complétez avec les "
                       "éléments fournis ou supprimez le passage — n'inventez aucune information.")
    return res


def consignes_courtes(projet: str | None, service: str | None, action: str | None = None, maxi: int = 600) -> str:
    """Rappel de charte injecté dans le message de l'ANALYST (≤ maxi caractères)."""
    c = charger(projet)
    typ = type_livrable(service, action)
    lignes = []
    if c["marque"]:
        lignes.append(f"Marque : {c['marque'].get('nom')} — {c['marque'].get('contexte', '')}.")
    autres = [m["nom"] for m in c["marques_interdites"] if m.get("gravite", "bloquant") == "bloquant"]
    if autres:
        lignes.append("Ne citez pas : " + ", ".join(autres) + ".")
    interdits = [t["terme"] for t in c["termes_interdits"] if t.get("gravite", "bloquant") == "bloquant"]
    if interdits:
        lignes.append("Termes interdits : " + ", ".join(f"« {x} »" for x in interdits[:6]) + ".")
    for regle in c["mentions_obligatoires"]:
        if typ in (regle.get("types") or []):
            lignes.append("Mention obligatoire : " + " + ".join(f"« {g[0]} »" for g in regle.get("toutes") or []) + ".")
    if c["ton"].get("vouvoiement"):
        lignes.append("Vouvoiement.")
    if typ in ("publication", "commercial"):
        lignes.append("Texte destiné à être publié : aucun « À COMPLÉTER », aucune information inventée.")
    texte = " ".join(lignes)
    return texte if len(texte) <= maxi else texte[: maxi - 1] + "…"
