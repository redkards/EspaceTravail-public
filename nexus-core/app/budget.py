"""BUDGET : comptage des tokens par mission et dépense mensuelle."""
from datetime import datetime, timezone

from . import sentinel
from .config import cfg


def llm_info() -> dict:
    from .llm import info  # import différé (évite une importation circulaire)
    return info()


class BudgetDepasse(Exception):
    """Levée quand une mission dépasse son budget ou que le mois est épuisé."""


def mois_courant() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def fournisseur_payant(fournisseur: str) -> bool:
    """Anthropic est payant ; Ollama Cloud seulement si un tarif est configuré."""
    if fournisseur == "anthropic":
        return True
    return fournisseur == "ollama_cloud" and cfg().eur_par_1k_tokens > 0


def cout_eur(tokens: int, fournisseur: str) -> float:
    """Ollama local = gratuit ; sinon estimation au millier de tokens (0 € par défaut)."""
    if not fournisseur_payant(fournisseur):
        return 0.0
    return round(tokens / 1000.0 * cfg().eur_par_1k_tokens, 6)


def depense_mois() -> dict:
    m = mois_courant()
    return {
        "mois": m,
        "tokens": int(float(sentinel.lire(f"budget:{m}:tokens", "0") or 0)),
        "eur": round(float(sentinel.lire(f"budget:{m}:eur", "0") or 0), 4),
    }


def verifier_mois(fournisseur: str) -> None:
    """Refuse un appel payant si la dépense du mois atteint BUDGET_MONTHLY_EUR."""
    if fournisseur_payant(fournisseur) and depense_mois()["eur"] >= cfg().budget_monthly_eur:
        raise BudgetDepasse(
            f"Budget mensuel atteint ({cfg().budget_monthly_eur} €) : appel au fournisseur payant refusé."
        )


def enregistrer(tokens: int, fournisseur: str) -> float:
    """Ajoute la consommation aux compteurs du mois ; renvoie le coût en euros."""
    m = mois_courant()
    cout = cout_eur(tokens, fournisseur)
    sentinel.incrementer(f"budget:{m}:tokens", tokens)
    if cout:
        sentinel.incrementer(f"budget:{m}:eur", cout)
    return cout


def verifier_mission(tokens_mission: int) -> None:
    limite = cfg().budget_task_tokens
    if limite > 0 and tokens_mission > limite:
        raise BudgetDepasse(f"Budget de la mission dépassé : {tokens_mission} tokens > {limite}.")


def resume() -> dict:
    c = cfg()
    return {
        **depense_mois(),
        "budget_mensuel_eur": c.budget_monthly_eur,
        "budget_tache_tokens": c.budget_task_tokens,
        **llm_info(),
    }
