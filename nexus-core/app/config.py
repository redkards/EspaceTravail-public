"""Configuration de nexus-core, lue depuis les variables d'environnement.

Les valeurs sont relues à chaque appel de `cfg()` : cela coûte peu et permet
aux tests de modifier l'environnement sans redémarrer le processus.
"""
import os
from dataclasses import dataclass
from pathlib import Path


def _int(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, "") or defaut)
    except ValueError:
        return defaut


def _float(nom: str, defaut: float) -> float:
    try:
        return float(os.environ.get(nom, "") or defaut)
    except ValueError:
        return defaut


@dataclass(frozen=True)
class Config:
    database_url: str
    data_dir: Path
    api_key: str
    llm_provider: str
    ollama_url: str
    modele: str
    modele_checker: str
    modele_local: str
    ollama_cloud_url: str
    ollama_api_key: str
    llm_fallback: str
    anthropic_api_key: str
    anthropic_model: str
    eur_par_1k_tokens: float
    budget_monthly_eur: float
    budget_task_tokens: int
    n3_timeout_hours: float
    n3_daily_cap: int
    ntfy_url: str
    ntfy_topic: str
    nexus_host: str
    taches_fond: bool
    llm_timeout_s: float
    llm_max_chars: int


def cfg() -> Config:
    data_dir = Path(os.environ.get("NEXUS_DATA_DIR", "/data"))
    url = os.environ.get("DATABASE_URL", "").strip() or f"sqlite:///{data_dir / 'nexus.db'}"
    # Accepte « postgresql:// » et force le pilote psycopg 3.
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    fournisseur = os.environ.get("LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    defaut_modele = "gemma4:31b" if fournisseur == "ollama_cloud" else "qwen2.5:3b"
    modele = os.environ.get("NEXUS_MODEL", "").strip() or defaut_modele
    return Config(
        database_url=url,
        data_dir=data_dir,
        api_key=os.environ.get("NEXUS_API_KEY", ""),
        llm_provider=fournisseur,
        ollama_url=os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/"),
        modele=modele,
        # Modèle dédié au CHECKER (facultatif), sinon NEXUS_MODEL.
        modele_checker=os.environ.get("NEXUS_MODEL_CHECKER", "").strip() or modele,
        # Modèle du repli local quand le fournisseur cloud échoue.
        modele_local=os.environ.get("NEXUS_MODEL_LOCAL", "").strip() or "qwen2.5:3b",
        ollama_cloud_url=os.environ.get("OLLAMA_CLOUD_URL", "").strip().rstrip("/") or "https://ollama.com",
        # Secret : jamais journalisé ni renvoyé par l'API.
        ollama_api_key=os.environ.get("OLLAMA_API_KEY", "").strip(),
        llm_fallback=(os.environ.get("LLM_FALLBACK", "ollama").strip().lower() or "ollama"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-3-5-haiku-latest",
        # Offre cloud gratuite : coût nul par défaut (tokens toujours comptés).
        eur_par_1k_tokens=_float("LLM_EUR_PAR_1K_TOKENS", 0.0),
        budget_monthly_eur=_float("BUDGET_MONTHLY_EUR", 0.0),
        # 20 000 : une mission avec 2 boucles de correction tient dans le budget.
        budget_task_tokens=_int("BUDGET_TASK_TOKENS", 20000),
        n3_timeout_hours=_float("N3_TIMEOUT_HOURS", 24.0),
        n3_daily_cap=_int("N3_DAILY_CAP", 15),
        ntfy_url=os.environ.get("NTFY_URL", "").rstrip("/"),
        ntfy_topic=os.environ.get("NTFY_TOPIC", ""),
        nexus_host=os.environ.get("NEXUS_HOST", ""),
        taches_fond=os.environ.get("NEXUS_TACHES_FOND", "1") != "0",
        llm_timeout_s=_float("LLM_TIMEOUT_S", 180.0),
        # Taille maximale (caractères) du message utilisateur envoyé au LLM.
        llm_max_chars=max(1000, _int("LLM_MAX_CHARS", 12000)),
    )


# Répertoire des fiches YAML des agents (embarqué dans l'image).
AGENTS_DIR = Path(os.environ.get("NEXUS_AGENTS_DIR", Path(__file__).resolve().parent.parent / "agents"))
