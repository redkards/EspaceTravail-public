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
    tokens_entree: int = 0
    tokens_sortie: int = 0

    def __post_init__(self):
        # Répartition par défaut quand le fournisseur ne détaille pas entrée/sortie.
        if not self.tokens_entree and not self.tokens_sortie and self.tokens:
            self.tokens_sortie = self.tokens // 4
            self.tokens_entree = self.tokens - self.tokens_sortie


def estimer_tokens(texte: str) -> int:
    """Estimation grossière (≈ 4 caractères par token) quand l'API ne compte pas."""
    return max(1, len(texte or "") // 4)


class ErreurLLM(Exception):
    pass


# --- Ollama (local et cloud : même API /api/chat) ------------------------------

ROLES_LLM = ("prime", "collector", "analyst", "checker", "gate", "directeur")
MODELES_CLOUD_DEFAUT = "gemma4:31b,gpt-oss:120b"


def modeles_roles(fournisseur_nom: str | None = None) -> dict[str, str]:
    """NEXUS_MODELES_ROLES : « role=modele » (tous fournisseurs) ou « role@fournisseur=modele ».

    Exemple : collector=gemma4:31b,analyst=gemma4:31b,checker@ollama_cloud=gpt-oss:120b.
    Une entrée propre au fournisseur l'emporte sur l'entrée générale.
    """
    from .surcharges import lire
    general, specifique = {}, {}
    for entree in (lire("modeles_roles") or os.environ.get("NEXUS_MODELES_ROLES", "")).split(","):
        if "=" not in entree:
            continue
        cle, modele = (x.strip() for x in entree.split("=", 1))
        role, _, four = cle.partition("@")
        role = role.strip().lower()
        if role not in ROLES_LLM or not modele:
            continue
        if four:
            if four.strip().lower() == (fournisseur_nom or ""):
                specifique[role] = modele
        else:
            general[role] = modele
    return {**general, **specifique}


def modeles_cloud() -> list[str]:
    brut = os.environ.get("NEXUS_MODELES_CLOUD", "").strip() or MODELES_CLOUD_DEFAUT
    return [m.strip() for m in brut.split(",") if m.strip()]


def modele_pour(role: str, modele: str | None = None, fournisseur_nom: str | None = None) -> str:
    """Modèle d'un rôle : fiche agent > NEXUS_MODELES_ROLES > NEXUS_MODEL_CHECKER > diversité > NEXUS_MODEL.

    Diversité du contrôle (fournisseur cloud) : sans réglage explicite, le CHECKER prend le premier
    modèle de NEXUS_MODELES_CLOUD différent de celui de l'ANALYST.
    """
    c = cfg()
    if modele:
        return modele
    conf = modeles_roles(fournisseur_nom)
    if role in conf:
        return conf[role]
    if role == "checker":
        if os.environ.get("NEXUS_MODEL_CHECKER", "").strip():
            return c.modele_checker
        if fournisseur_nom == "ollama_cloud":
            analyste = modele_pour("analyst", None, fournisseur_nom)
            autre = next((m for m in modeles_cloud() if m != analyste), None)
            if autre:
                return autre
    return c.modele


def _masquer(texte: str) -> str:
    """Retire la clé Ollama d'un message d'erreur (par précaution)."""
    cle = cfg().ollama_api_key
    return texte.replace(cle, "***") if cle else texte


def _ollama_chat(base_url: str, modele: str, systeme: str, utilisateur: str, role: str,
                 temperature: float, en_tetes: dict | None = None, local: bool = True,
                 num_ctx: int | None = None, timeout: float | None = None) -> dict:
    corps = {
        "model": modele,
        "messages": [{"role": "system", "content": systeme},
                     {"role": "user", "content": utilisateur}],
        "stream": False,
        "options": {"temperature": temperature},
    }
    if local:
        # Contexte assez grand pour LLM_MAX_CHARS (≈ 12 000 caractères ≈ 4 000 tokens) + réponse.
        corps["options"]["num_ctx"] = num_ctx or cfg().ollama_num_ctx
    if role == "checker":
        corps["format"] = "json"  # sortie contrainte en JSON
    r = httpx.post(f"{base_url}/api/chat", json=corps, headers=en_tetes or {},
                   timeout=timeout or cfg().llm_timeout_s)
    r.raise_for_status()
    return r.json()


def _reponse(d: dict, systeme: str, utilisateur: str, nom: str, modele: str) -> Reponse:
    texte = (d.get("message") or {}).get("content", "")
    entree, sortie = int(d.get("prompt_eval_count") or 0), int(d.get("eval_count") or 0)
    if entree + sortie:
        return Reponse(texte, entree + sortie, nom, modele, tokens_entree=entree, tokens_sortie=sortie)
    e, so = estimer_tokens(systeme + utilisateur), estimer_tokens(texte)
    return Reponse(texte, e + so, nom, modele, tokens_entree=e, tokens_sortie=so)


class FournisseurOllama:
    nom = "ollama"

    def __init__(self, modele_force: str | None = None, num_ctx: int | None = None):
        # modele_force : modèle local utilisé quand on remplace un fournisseur cloud.
        self.modele_force = modele_force
        self.num_ctx = num_ctx

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None, timeout: float | None = None) -> Reponse:
        m = self.modele_force or modele_pour(role, modele, self.nom)
        try:
            d = _ollama_chat(cfg().ollama_url, m, systeme, utilisateur, role, temperature,
                             num_ctx=self.num_ctx, timeout=timeout)
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

    def __init__(self, modele_force: str | None = None, num_ctx: int | None = None):
        # modele_force : modèle cloud imposé (cas de la bascule depuis Anthropic).
        self.modele_force = modele_force
        self.num_ctx = num_ctx  # utilisé seulement par le repli local

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None, timeout: float | None = None) -> Reponse:
        c = cfg()
        m = self.modele_force or modele_pour(role, modele, self.nom)
        en_tetes = {"Authorization": f"Bearer {c.ollama_api_key}"}
        motif, bascule_modele = "", None
        for _ in range(self.ESSAIS):
            try:
                d = _ollama_chat(c.ollama_cloud_url, m, systeme, utilisateur, role, temperature,
                                 en_tetes, local=False, timeout=timeout)
                r = _reponse(d, systeme, utilisateur, self.nom, m)
                r.bascule = bascule_modele
                return r
            except Exception as e:
                motif = _motif(e)
                log.warning("Ollama Cloud en erreur (%s) sur le modèle %s", motif, m)
                # Modèle de rôle inconnu du serveur : repli sur le modèle de base, une fois.
                if (isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404
                        and m != c.modele and not bascule_modele):
                    bascule_modele = f"modèle {m} indisponible : repli sur {c.modele}"
                    m = c.modele
        if c.llm_fallback == "ollama" and ollama_local_joignable():
            r = FournisseurOllama(c.modele_local, self.num_ctx).appeler(systeme, utilisateur, role, temperature,
                                                                        timeout=timeout)
            r.bascule = f"Ollama Cloud en échec ({motif}) : repli sur Ollama local ({c.modele_local})"
            return r
        raise ErreurLLM(_masquer(f"Ollama Cloud en échec ({motif}) et aucun repli disponible."))


# --- Anthropic (optionnel, payant) ---------------------------------------------

class FournisseurAnthropic:
    nom = "anthropic"

    MAX_TOKENS_SORTIE = 1500

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None, timeout: float | None = None) -> Reponse:
        c = cfg()
        m = modele or c.anthropic_model
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": c.anthropic_api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": m, "max_tokens": self.MAX_TOKENS_SORTIE, "temperature": temperature,
                      "system": systeme, "messages": [{"role": "user", "content": utilisateur}]},
                timeout=timeout or c.llm_timeout_s,
            )
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            raise ErreurLLM(f"Anthropic en erreur : {e}") from e
        texte = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        u = d.get("usage") or {}
        entree, sortie = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        if not entree + sortie:
            entree, sortie = estimer_tokens(systeme + utilisateur), estimer_tokens(texte)
        return Reponse(texte, entree + sortie, self.nom, m, tokens_entree=entree, tokens_sortie=sortie)


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

    def __init__(self, *_, **__):
        pass  # accepte les mêmes paramètres que les autres fournisseurs

    def appeler(self, systeme: str, utilisateur: str, role: str = "", temperature: float = 0.3,
                modele: str | None = None, timeout: float | None = None) -> Reponse:
        FournisseurFactice.appels.append(role)
        FournisseurFactice.entrees.append((role, utilisateur))
        if FournisseurFactice.script[role]:
            texte = FournisseurFactice.script[role].popleft()
        else:
            texte = self._defaut(role, utilisateur)
        if FournisseurFactice.tokens_par_appel:
            return Reponse(texte, FournisseurFactice.tokens_par_appel, self.nom, modele or "")
        e, so = estimer_tokens(systeme + utilisateur), estimer_tokens(texte)
        return Reponse(texte, e + so, self.nom, modele or "", tokens_entree=e, tokens_sortie=so)

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


def fournisseur_niveau(code_fournisseur: str, num_ctx: int | None = None):
    """Fournisseur d'un niveau de fonctionnement (ollama_local | courant | anthropic).

    En mode test (LLM_PROVIDER=fake), le fournisseur factice est toujours utilisé.
    La disponibilité d'Anthropic (budget, clé) est vérifiée avant, par fonctionnement.py.
    """
    c = cfg()
    if c.llm_provider == "fake":
        return FournisseurFactice()
    if code_fournisseur == "ollama_local":
        return FournisseurOllama(c.modele_local, num_ctx)
    if code_fournisseur == "anthropic":
        return FournisseurAnthropic()
    f = fournisseur()
    if hasattr(f, "num_ctx") and num_ctx:
        f.num_ctx = num_ctx
    return f


def fournisseur_controle_local(num_ctx: int | None = None):
    """Fournisseur du double contrôle : toujours le modèle local (factice en test)."""
    if cfg().llm_provider == "fake":
        return FournisseurFactice()
    return FournisseurOllama(cfg().modele_local, num_ctx)


def info() -> dict:
    """Fournisseur actif et modèles (jamais de clé)."""
    c = cfg()
    f = fournisseur()
    force = getattr(f, "modele_force", None)
    roles = {r: (force or modele_pour(r, None, f.nom)) for r in ROLES_LLM}
    return {
        "fournisseur": f.nom,
        "fournisseur_demande": c.llm_provider,
        "modele": force or c.modele,
        "modele_checker": roles["checker"],
        "modeles_roles": roles,
        "controle_diversifie": roles["checker"] != roles["analyst"],
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
