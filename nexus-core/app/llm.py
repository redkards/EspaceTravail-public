"""Fournisseurs LLM : Ollama local (défaut), Ollama Cloud, Anthropic (optionnel), factice (tests).

Interface commune : `appeler(systeme, utilisateur, role, temperature) -> Reponse`.
"""
import json
import logging
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx

from .config import cfg

log = logging.getLogger("nexus.llm")


@dataclass
class Reponse:
    texte: str
    tokens: int
    fournisseur: str
    modele: str = ""
    bascule: str | None = None  # motif si le cloud a échoué et que le local a répondu


def estimer_tokens(texte: str) -> int:
    """Estimation grossière (≈ 4 caractères par token) quand l'API ne compte pas."""
    return max(1, len(texte or "") // 4)


class ErreurLLM(Exception):
    pass


# --- Ollama (local et cloud : même API /api/chat) ------------------------------

def modele_pour(role: str, modele: str | None = None) -> str:
    """Modèle de la fiche agent, sinon NEXUS_MODEL_CHECKER pour le CHECKER, sinon NEXUS_MODEL."""
    c = cfg()
    if modele:
        return modele
    return c.modele_checker if role == "checker" else c.modele


def _masquer(texte: str) -> str:
    """Retire la clé Ollama d'un message d'erreur (par précaution)."""
    cle = cfg().ollama_api_key
    return texte.replace(cle, "***") if cle else texte


def _ollama_chat(base_url: str, modele: str, systeme: str, utilisateur: str, role: str,
                 temperature: float, en_tetes: dict | None = None, local: bool = True) -> dict:
    corps = {
        "model": modele,
        "messages": [{"role": "system", "content": systeme},
                     {"role": "user", "content": utilisateur}],
        "stream": False,
        "options": {"temperature": temperature},
    }
    if local:
        # Contexte assez grand pour LLM_MAX_CHARS (≈ 12 000 caractères ≈ 4 000 tokens) + réponse.
        corps["options"]["num_ctx"] = cfg().ollama_num_ctx
    if role == "checker":
        corps["format"] = "json"  # sortie contrainte en JSON
    r = httpx.post(f"{base_url}/api/chat", json=corps, headers=en_tetes or {}, timeout=cfg().llm_timeout_s)
    r.raise_for_status()
    return r.json()


def _reponse(d: dict, systeme: str, utilisateur: str, nom: str, modele: str) -> Reponse:
    texte = (d.get("message") or {}).get("content", "")
    tokens = int(d.get("prompt_eval_count") or 0) + int(d.get("eval_count") or 0)
    return Reponse(texte, tokens or estimer_tokens(systeme + utilisateur + texte), nom, modele)


class FournisseurOllama:
    nom = "ollama"

    def __init__(self, modele_force: str | None = None):
        # modele_force : modèle local utilisé quand on remplace un fournisseur cloud.
        self.modele_force = modele_force

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None) -> Reponse:
        m = self.modele_force or modele_pour(role, modele)
        try:
            d = _ollama_chat(cfg().ollama_url, m, systeme, utilisateur, role, temperature)
        except Exception as e:
            raise ErreurLLM(f"Ollama local injoignable ou en erreur : {e}") from e
        return _reponse(d, systeme, utilisateur, self.nom, m)


def ollama_local_joignable() -> bool:
    try:
        return httpx.get(f"{cfg().ollama_url}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


def _motif(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    if isinstance(e, httpx.TimeoutException):
        return "délai dépassé"
    return type(e).__name__


class FournisseurOllamaCloud:
    """Ollama Cloud (https://ollama.com/api/chat, en-tête Authorization: Bearer).

    En cas d'échec : un nouvel essai, puis repli sur Ollama local si LLM_FALLBACK=ollama
    et si OLLAMA_URL répond ; sinon ErreurLLM. La clé n'apparaît dans aucun message.
    """
    nom = "ollama_cloud"
    ESSAIS = 2  # appel initial + 1 nouvel essai
    MODELE_DEFAUT = "gemma4:31b"

    def __init__(self, modele_force: str | None = None):
        # modele_force : modèle cloud imposé (cas de la bascule depuis Anthropic).
        self.modele_force = modele_force

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None) -> Reponse:
        c = cfg()
        m = self.modele_force or modele_pour(role, modele)
        en_tetes = {"Authorization": f"Bearer {c.ollama_api_key}"}
        motif = ""
        for _ in range(self.ESSAIS):
            try:
                d = _ollama_chat(c.ollama_cloud_url, m, systeme, utilisateur, role, temperature,
                                 en_tetes, local=False)
                return _reponse(d, systeme, utilisateur, self.nom, m)
            except Exception as e:
                motif = _motif(e)
                log.warning("Ollama Cloud en erreur (%s) sur le modèle %s", motif, m)
        if c.llm_fallback == "ollama" and ollama_local_joignable():
            r = FournisseurOllama(c.modele_local).appeler(systeme, utilisateur, role, temperature)
            r.bascule = f"Ollama Cloud en échec ({motif}) : repli sur Ollama local ({c.modele_local})"
            return r
        raise ErreurLLM(_masquer(f"Ollama Cloud en échec ({motif}) et aucun repli disponible."))


# --- Anthropic (optionnel, payant) ---------------------------------------------

class FournisseurAnthropic:
    nom = "anthropic"

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None) -> Reponse:
        c = cfg()
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": c.anthropic_api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": c.anthropic_model, "max_tokens": 1500, "temperature": temperature,
                      "system": systeme, "messages": [{"role": "user", "content": utilisateur}]},
                timeout=c.llm_timeout_s,
            )
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            raise ErreurLLM(f"Anthropic en erreur : {e}") from e
        texte = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        u = d.get("usage") or {}
        tokens = int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
        return Reponse(texte, tokens or estimer_tokens(systeme + utilisateur + texte), self.nom)


# --- Factice (tests, démonstration hors ligne) ---------------------------------

class FournisseurFactice:
    """Réponses déterministes, sans réseau.

    Les tests peuvent imposer des réponses par rôle via `script[role].append(...)`
    et le nombre de tokens par appel via `tokens_par_appel`.
    """
    nom = "fake"
    script: dict = defaultdict(deque)
    tokens_par_appel: int | None = None
    appels: list = []
    entrees: list = []  # (rôle, message utilisateur reçu) : inspecté par les tests

    @classmethod
    def reinitialiser(cls):
        cls.script = defaultdict(deque)
        cls.tokens_par_appel = None
        cls.appels = []
        cls.entrees = []

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None) -> Reponse:
        FournisseurFactice.appels.append(role)
        FournisseurFactice.entrees.append((role, utilisateur))
        if FournisseurFactice.script[role]:
            texte = FournisseurFactice.script[role].popleft()
        else:
            texte = self._defaut(role, utilisateur)
        tokens = FournisseurFactice.tokens_par_appel or estimer_tokens(systeme + utilisateur + texte)
        return Reponse(texte, tokens, self.nom)

    @staticmethod
    def _defaut(role: str, utilisateur: str) -> str:
        if role == "checker":
            return json.dumps({"ok": True, "problemes": []})
        if role == "gate":
            return "NIVEAU: N0"
        if role == "directeur":
            return ("DIAGNOSTIC: consigne trop vague pour le service\nDECISION: REFORMULER\n"
                    "CONSIGNE: préciser le livrable attendu et les éléments fournis")
        if role == "prime":
            return "SERVICE: OPS-CORE/projets"
        if role == "collector":
            return "ELEMENTS:\n- consigne reçue\nMANQUE:\n- aucun élément bloquant"
        if role == "analyst":
            return "# Livrable (brouillon)\n\n- Point 1\n- Point 2\n- Point 3"
        return "OK"


def refus_anthropic() -> str | None:
    """Garde-fou « tout gratuit » : Anthropic refusé sans budget ou sans clé."""
    c = cfg()
    if c.budget_monthly_eur <= 0:
        return ("LLM_PROVIDER=anthropic refusé : BUDGET_MONTHLY_EUR=0 (mode gratuit). "
                "Bascule sur un fournisseur gratuit (ollama_cloud si OLLAMA_API_KEY, sinon ollama).")
    if not c.anthropic_api_key:
        return "LLM_PROVIDER=anthropic refusé : ANTHROPIC_API_KEY vide. Bascule sur un fournisseur gratuit."
    return None


_DEJA_SIGNALE: set[str] = set()


def _avertir_une_fois(message: str) -> None:
    """Évite de répéter le même avertissement à chaque appel."""
    if message not in _DEJA_SIGNALE:
        _DEJA_SIGNALE.add(message)
        log.warning(message)


def _repli_gratuit():
    """Fournisseur gratuit de remplacement : Ollama Cloud si une clé existe, sinon local."""
    if cfg().ollama_api_key:
        # NEXUS_MODEL vide → modèle cloud par défaut (le défaut local ne vaut pas pour le cloud).
        explicite = os.environ.get("NEXUS_MODEL", "").strip()
        return FournisseurOllamaCloud(None if explicite else FournisseurOllamaCloud.MODELE_DEFAUT)
    return FournisseurOllama(cfg().modele_local)


def fournisseur():
    """Choisit le fournisseur selon LLM_PROVIDER ; cloud et Anthropic exigent une clé."""
    c = cfg()
    if c.llm_provider == "fake":
        return FournisseurFactice()
    if c.llm_provider == "ollama_cloud":
        if c.ollama_api_key:
            return FournisseurOllamaCloud()
        _avertir_une_fois("LLM_PROVIDER=ollama_cloud mais OLLAMA_API_KEY vide : Ollama local utilisé.")
        return FournisseurOllama(c.modele_local)
    if c.llm_provider == "anthropic":
        motif = refus_anthropic()
        if motif is None:
            return FournisseurAnthropic()
        _avertir_une_fois(motif)
        return _repli_gratuit()
    return FournisseurOllama()


def info() -> dict:
    """Fournisseur actif et modèles (jamais de clé)."""
    c = cfg()
    f = fournisseur()
    force = getattr(f, "modele_force", None)
    return {
        "fournisseur": f.nom,
        "fournisseur_demande": c.llm_provider,
        "modele": force or c.modele,
        "modele_checker": force or c.modele_checker,
        "repli": c.llm_fallback if f.nom == "ollama_cloud" else "aucun",
    }


# --- Parseurs tolérants --------------------------------------------------------

def parser_verdict(texte: str) -> dict:
    """Extrait {"ok": bool, "problemes": [...]} d'une réponse de petit modèle.

    Tolère : texte autour du JSON, blocs ```json, guillemets simples, true/false
    en français (vrai/faux, oui/non). En cas d'échec : refus prudent.
    """
    brut = (texte or "").strip()
    brut = re.sub(r"```(?:json)?", "", brut)
    m = re.search(r"\{.*\}", brut, re.S)
    if m:
        bloc = m.group(0)
        for essai in (bloc, bloc.replace("'", '"')):
            try:
                d = json.loads(essai)
                ok = d.get("ok")
                if isinstance(ok, str):
                    ok = ok.strip().lower() in ("true", "vrai", "oui", "yes", "1")
                probs = d.get("problemes", d.get("problèmes", d.get("problems", [])))
                if isinstance(probs, str):
                    probs = [probs] if probs.strip() else []
                return {"ok": bool(ok), "problemes": [str(p) for p in (probs or [])]}
            except (json.JSONDecodeError, AttributeError):
                continue
    # Repli : recherche de « ok: true/false » dans le texte libre.
    m = re.search(r"\"?ok\"?\s*[:=]\s*\"?(true|false|vrai|faux|oui|non)", brut, re.I)
    if m:
        ok = m.group(1).lower() in ("true", "vrai", "oui")
        return {"ok": ok, "problemes": [] if ok else ["verdict non détaillé"]}
    return {"ok": False, "problemes": ["réponse du CHECKER illisible"]}


def parser_niveau(texte: str) -> str | None:
    m = re.search(r"\bN\s*([0-3])\b", texte or "", re.I)
    return f"N{m.group(1)}" if m else None
