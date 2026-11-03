"""Chargement des 40 fiches d'agents (YAML) de la Mini Mothership."""
from functools import lru_cache

import yaml

from .config import AGENTS_DIR

CHAMPS = ["id", "nom", "role", "direction", "departement", "service", "mission", "consignes",
          "outils_autorises"]
ROLES = {"prime", "gate", "sentinel", "ledger", "budget", "directeur", "collector", "analyst",
         "checker", "executor"}


@lru_cache(maxsize=1)
def charger() -> dict[str, dict]:
    agents: dict[str, dict] = {}
    for f in sorted(AGENTS_DIR.glob("*.yaml")):
        a = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        manquants = [c for c in CHAMPS if c not in a]
        if manquants:
            raise ValueError(f"{f.name} : champs manquants {manquants}")
        if a["role"] not in ROLES:
            raise ValueError(f"{f.name} : rôle inconnu {a['role']}")
        if a["id"] in agents:
            raise ValueError(f"{f.name} : identifiant en double {a['id']}")
        agents[a["id"]] = a
    return agents


def agent(agent_id: str) -> dict:
    return charger()[agent_id]


def services() -> dict[str, dict]:
    """{service: {"directeur": id, "collector": id, ...}} construit depuis les fiches."""
    res: dict[str, dict] = {}
    tous = charger()
    directeurs = {a["direction"]: a["id"] for a in tous.values() if a["role"] == "directeur"}
    for a in tous.values():
        if a["role"] in ("collector", "analyst", "checker", "executor") and a.get("service"):
            s = res.setdefault(a["service"], {"direction": a["direction"],
                                              "directeur": directeurs.get(a["direction"])})
            s[a["role"]] = a["id"]
    return res


def par_role(role: str) -> dict:
    return next(a for a in charger().values() if a["role"] == role)
