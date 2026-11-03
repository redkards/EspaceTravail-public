"""Configuration de nexus-bridge (variables d'environnement, relues à chaque appel pour les tests)."""
import os
from dataclasses import dataclass, field

# Codes projets partagés avec nexus-core (repli si GET /api/projets est indisponible).
PROJETS_PAR_DEFAUT = [
    "paradoxx", "nexus", "poker-winners", "poker-feeling", "redkards", "top-solver",
    "youtube-poker-winner", "freelance-ia", "esct-boxe", "turf", "divers",
]

# Identités possibles (les trois IA + le propriétaire humain).
IAS = ["claude", "chatgpt", "gemini"]
IDENTITES = IAS + ["proprietaire"]

# Longueur minimale d'un jeton pour qu'il soit accepté (install.sh génère 64 caractères hex).
JETON_LONGUEUR_MIN = 32


@dataclass
class Config:
    db_path: str
    nexus_core_url: str
    nexus_api_key: str
    jetons: dict[str, str] = field(default_factory=dict)  # identite -> jeton
    limite_par_minute: int = 60
    taille_max_octets: int = 8192
    corps_max_octets: int = 65536
    projets: list[str] = field(default_factory=lambda: list(PROJETS_PAR_DEFAUT))
    nexus_host: str = ""


def cfg() -> Config:
    jetons = {}
    for ident in IDENTITES:
        val = os.environ.get(f"BRIDGE_TOKEN_{ident.upper()}", "").strip()
        if len(val) >= JETON_LONGUEUR_MIN:
            jetons[ident] = val
    projets_env = os.environ.get("BRIDGE_PROJETS", "").strip()
    projets = [p.strip() for p in projets_env.split(",") if p.strip()] if projets_env else list(PROJETS_PAR_DEFAUT)
    return Config(
        db_path=os.environ.get("BRIDGE_DB", "/data/bridge.db"),
        nexus_core_url=os.environ.get("NEXUS_CORE_URL", "http://nexus-core:8000").rstrip("/"),
        nexus_api_key=os.environ.get("NEXUS_API_KEY", ""),
        jetons=jetons,
        limite_par_minute=int(os.environ.get("BRIDGE_LIMITE_PAR_MINUTE", "60")),
        projets=projets,
        nexus_host=os.environ.get("NEXUS_HOST", ""),
    )
