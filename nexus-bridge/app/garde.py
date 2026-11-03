"""Garde-fous : détection de secrets, taille des contenus, limite de débit par jeton."""
import re
import threading
import time
from collections import defaultdict, deque

# --- Détection de contenus qui ressemblent à des secrets --------------------------------
# Chaque motif a un nom lisible, renvoyé dans le message d'erreur (jamais la valeur trouvée).
_MOTIFS: list[tuple[str, re.Pattern]] = [
    ("clé privée (bloc PEM)", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("clé API Anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("clé API OpenAI", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("clé API Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("jeton GitHub", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("jeton GitLab", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("jeton Slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("clé d'accès AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("clé Stripe", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("clé Hugging Face", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("jeton JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("en-tête d'authentification", re.compile(r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("hash bcrypt", re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{50,}")),
    ("adresse avec identifiants", re.compile(r"[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]{3,}@", re.I)),
    # « clé API : xxxxx », « token=xxxxx », « NEXUS_API_KEY=... », « secret: ... »
    ("clé, jeton ou secret écrit en clair", re.compile(
        r"(?i)(?:api[_\- ]?key|apikey|secret|token|jeton|cl[ée]\s*(?:api|secr[eè]te|priv[ée]e))"
        r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{16,}")),
    # « mot de passe : Xy7!abc », « password=hunter22 », « mdp: azerty123 »
    ("mot de passe", re.compile(
        r"(?i)(?:mot\s+de\s+passe|mdp|password|passwd|pwd|passphrase)\s*[\"']?\s*[:=]\s*[\"']?"
        r"(?=\S*[0-9!@#$%^&*?_\-])\S{6,}")),
]

# Numéros de carte bancaire : 13 à 19 chiffres (espaces ou tirets possibles) + clé de Luhn.
_CARTE = re.compile(r"(?<![\d])(?:\d[ \-]?){12,18}\d(?![\d])")


def _luhn(chiffres: str) -> bool:
    total, double = 0, False
    for c in reversed(chiffres):
        n = int(c)
        if double:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        double = not double
    return total % 10 == 0


def detecter_secret(texte: str, secrets_connus: list[str] | None = None) -> str | None:
    """Renvoie le TYPE de secret détecté (jamais sa valeur), ou None."""
    if not texte:
        return None
    for connu in secrets_connus or []:
        if connu and len(connu) >= 16 and connu in texte:
            return "jeton ou clé du Mothership"
    for nom, motif in _MOTIFS:
        if motif.search(texte):
            return nom
    for m in _CARTE.finditer(texte):
        chiffres = re.sub(r"\D", "", m.group(0))
        if 13 <= len(chiffres) <= 19 and _luhn(chiffres) and len(set(chiffres)) > 2:
            return "numéro de carte bancaire"
    return None


MESSAGE_SECRET = (
    "Refusé : ce texte ressemble à un secret ({type}). La mémoire commune est lue par "
    "Claude, ChatGPT et Gemini et affichée sur la page /bridge : on n'y met jamais de clé API, "
    "de mot de passe, de jeton ni de numéro de carte. Écrivez plutôt où le secret est rangé "
    "(ex. « clé dans le .env du VPS, variable OLLAMA_API_KEY ») sans sa valeur."
)


def taille_octets(texte: str) -> int:
    return len(texte.encode("utf-8"))


# --- Limite de débit : fenêtre glissante de 60 s par identité ----------------------------
class LimiteDebit:
    def __init__(self) -> None:
        self._appels: dict[str, deque] = defaultdict(deque)
        self._verrou = threading.Lock()

    def autoriser(self, cle: str, limite: int, fenetre: float = 60.0, cout: int = 1) -> tuple[bool, int]:
        """(autorisé, secondes à attendre). `cout` = nombre d'appels (éléments d'un lot JSON-RPC).

        Tout ou rien : un lot qui dépasserait la limite est refusé en entier. Seuls les appels
        acceptés sont comptés.
        """
        cout = max(1, int(cout))
        t = time.monotonic()
        with self._verrou:
            q = self._appels[cle]
            while q and t - q[0] >= fenetre:
                q.popleft()
            if len(q) + cout > limite:
                if not q:  # lot plus grand que la limite elle-même
                    return False, int(fenetre)
                index = min(len(q) - 1, len(q) + cout - limite - 1)
                return False, max(1, int(fenetre - (t - q[index])) + 1)
            q.extend([t] * cout)
            return True, 0

    def reinitialiser(self) -> None:
        with self._verrou:
            self._appels.clear()


limiteur = LimiteDebit()
