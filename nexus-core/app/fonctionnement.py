"""Niveaux de fonctionnement F1..F4 : effort, tokens, coût, délai (fonctionnement.yaml)."""
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import cfg

log = logging.getLogger("nexus.fonctionnement")

CODES = ("F1", "F2", "F3", "F4")
_verrou = threading.Lock()
_grille: dict | None = None


@dataclass(frozen=True)
class Niveau:
    code: str
    nom: str
    effort: str
    fournisseur: str            # ollama_local | courant | anthropic
    budget_tokens: int
    revisions_max: int
    double_controle: bool
    llm_max_chars: int
    num_ctx: int
    delai_max_s: float
    cout_max_eur: float
    modeles: dict = field(default_factory=dict)

    def modele_role(self, role: str) -> str | None:
        return self.modeles.get(role) or self.modeles.get("defaut")

    def public(self) -> dict:
        return {"code": self.code, "nom": self.nom, "effort": self.effort, "fournisseur": self.fournisseur,
                "budget_tokens": self.budget_tokens, "revisions_max": self.revisions_max,
                "double_controle": self.double_controle, "llm_max_chars": self.llm_max_chars,
                "num_ctx": self.num_ctx, "delai_max_s": self.delai_max_s, "cout_max_eur": self.cout_max_eur,
                "modeles": dict(self.modeles)}


def chemin() -> Path:
    return Path(os.environ.get("NEXUS_FONCTIONNEMENT_FILE",
                               Path(__file__).resolve().parent.parent / "fonctionnement.yaml"))


def _lire() -> dict:
    d = yaml.safe_load(chemin().read_text(encoding="utf-8")) or {}
    niveaux = d.get("niveaux") or {}
    manquants = [c for c in CODES if c not in niveaux]
    if manquants:
        raise ValueError(f"fonctionnement.yaml : niveaux manquants {manquants}")
    return d


def charger(recharger: bool = False) -> dict:
    global _grille
    with _verrou:
        if _grille is None or recharger:
            _grille = _lire()
        return _grille


def _env_present(nom: str) -> bool:
    return bool(os.environ.get(nom, "").strip())


def niveau(code: str) -> Niveau:
    """Paramètres effectifs d'un niveau (F2 reprend les variables d'environnement existantes)."""
    code = (code or "").upper()
    if code not in CODES:
        raise ValueError(f"Niveau de fonctionnement inconnu : « {code} » (F1, F2, F3 ou F4).")
    n = charger()["niveaux"][code]
    c = cfg()
    budget_tokens = int(n["budget_tokens"])
    llm_max_chars = int(n["llm_max_chars"])
    num_ctx = int(n["num_ctx"])
    if code == "F2":  # compatibilité : les réglages existants restent la base de F2
        if _env_present("BUDGET_TASK_TOKENS"):
            budget_tokens = c.budget_task_tokens
        if _env_present("LLM_MAX_CHARS"):
            llm_max_chars = c.llm_max_chars
        if _env_present("OLLAMA_NUM_CTX"):
            num_ctx = c.ollama_num_ctx
    return Niveau(code=code, nom=str(n["nom"]), effort=str(n.get("effort", "")),
                  fournisseur=str(n["fournisseur"]), budget_tokens=budget_tokens,
                  revisions_max=int(n["revisions_max"]), double_controle=bool(n["double_controle"]),
                  llm_max_chars=llm_max_chars, num_ctx=num_ctx, delai_max_s=float(n["delai_max_s"]),
                  cout_max_eur=float(n.get("cout_max_eur") or 0), modeles=dict(n.get("modeles") or {}))


def defaut() -> str:
    v = os.environ.get("NEXUS_FONCTIONNEMENT_DEFAUT", "").strip().upper() or str(charger().get("defaut", "F2"))
    if v not in CODES:
        log.warning("NEXUS_FONCTIONNEMENT_DEFAUT invalide (%s) : F2 utilisé.", v)
        return "F2"
    return v


def rang(code: str) -> int:
    return CODES.index(code)


def plus_haut(a: str, b: str) -> str:
    return a if rang(a) >= rang(b) else b


def suivant(code: str) -> str | None:
    i = rang(code)
    return CODES[i + 1] if i + 1 < len(CODES) else None


# --- Coûts (F4) -------------------------------------------------------------------

def eur_par_usd() -> float:
    try:
        return float(os.environ.get("EUR_PAR_USD", "") or charger().get("eur_par_usd", 0.92))
    except ValueError:
        return 0.92


def tarif(modele: str | None) -> dict | None:
    return (charger().get("tarifs_usd_par_mtok") or {}).get(modele or "")


def cout_appel_eur(modele: str | None, tokens_entree: int, tokens_sortie: int) -> float:
    """Coût d'un appel en euros d'après les tarifs ($/MTok) ; 0 si le modèle n'est pas tarifé."""
    t = tarif(modele)
    if not t:
        return 0.0
    usd = tokens_entree * float(t["entree"]) / 1e6 + tokens_sortie * float(t["sortie"]) / 1e6
    return round(usd * eur_par_usd(), 6)


def estimer_cout_eur(code: str) -> dict:
    """Estimation avant lancement : plafond de tokens du niveau × tarif du modèle le plus cher."""
    n = niveau(code)
    part = float(charger().get("part_entree_estimation", 0.75))
    modeles = set(n.modeles.values()) or {None}
    pire = max((cout_appel_eur(m, int(n.budget_tokens * part), int(n.budget_tokens * (1 - part)))
                for m in modeles), default=0.0)
    return {"tokens_prevus": n.budget_tokens, "cout_estime_eur": round(min(pire, n.cout_max_eur or pire), 4),
            "cout_max_eur": n.cout_max_eur, "eur_par_usd": eur_par_usd()}


def disponibilite_f4() -> str | None:
    """None si F4 est utilisable ; sinon la raison claire de l'indisponibilité."""
    from . import budget
    c = cfg()
    if c.budget_monthly_eur <= 0:
        return "budget IA à 0 €"
    if not c.anthropic_api_key:
        return "clé ANTHROPIC_API_KEY absente"
    restant = c.budget_monthly_eur - budget.depense_mois()["eur"]
    estime = estimer_cout_eur("F4")["cout_estime_eur"]
    if restant < estime:
        return f"budget mensuel restant {restant:.2f} € < coût estimé {estime:.2f} €"
    return None


def grille_publique() -> dict:
    return {"defaut": defaut(), "niveaux": [niveau(c).public() for c in CODES],
            "tarifs_usd_par_mtok": charger().get("tarifs_usd_par_mtok") or {},
            "eur_par_usd": eur_par_usd(), "estimation_f4": estimer_cout_eur("F4"),
            "f4_indisponible": disponibilite_f4()}
