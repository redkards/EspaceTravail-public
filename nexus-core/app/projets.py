"""Registre des projets (projets.yaml), rechargeable sans redémarrage."""
import logging
import os
import re
import threading
from pathlib import Path

import yaml

log = logging.getLogger("nexus.projets")

PROJET_DEFAUT = "divers"
_MOTIF_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_verrou = threading.Lock()
_registre: dict[str, dict] | None = None


def chemin() -> Path:
    return Path(os.environ.get("NEXUS_PROJETS_FILE",
                               Path(__file__).resolve().parent.parent / "projets.yaml"))


def _lire() -> dict[str, dict]:
    donnees = yaml.safe_load(chemin().read_text(encoding="utf-8")) or {}
    res: dict[str, dict] = {}
    for p in donnees.get("projets") or []:
        code = str(p.get("code", "")).strip().lower()
        if not _MOTIF_CODE.match(code):
            raise ValueError(f"projets.yaml : code invalide « {code} »")
        if code in res:
            raise ValueError(f"projets.yaml : code en double « {code} »")
        res[code] = {
            "code": code,
            "nom": str(p.get("nom") or code),
            "description": str(p.get("description") or ""),
            "services": [str(s) for s in (p.get("services") or [])],
            "alias": [str(a).strip().lower() for a in (p.get("alias") or [])],
        }
    if PROJET_DEFAUT not in res:
        raise ValueError(f"projets.yaml : le projet « {PROJET_DEFAUT} » est obligatoire")
    return res


def charger(recharger: bool = False) -> dict[str, dict]:
    """Renvoie le registre ; en cas d'erreur au rechargement, garde l'ancien."""
    global _registre
    with _verrou:
        if _registre is None or recharger:
            try:
                _registre = _lire()
                log.info("Registre des projets chargé : %s projet(s).", len(_registre))
            except Exception:
                if _registre is None:
                    raise
                log.exception("Rechargement de projets.yaml impossible : ancien registre conservé.")
                raise
        return _registre


def resoudre(valeur: str | None) -> str:
    """Code projet à partir d'un code ou d'un alias ; vide → « divers ». ValueError si inconnu."""
    v = (valeur or "").strip().lower()
    if not v:
        return PROJET_DEFAUT
    reg = charger()
    if v in reg:
        return v
    for code, p in reg.items():
        if v in p["alias"]:
            return code
    raise ValueError(f"Projet inconnu : « {valeur} ». Projets possibles : {', '.join(sorted(reg))}.")
