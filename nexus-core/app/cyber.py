"""Garde-fous déterministes du département CYBER-FORTRESS.

Le CHECKER (LLM) reçoit des consignes de refus ; ces règles le doublent sans dépendre du modèle :
- un livrable qui contient un secret (clé privée, jeton, mot de passe en clair) est refusé et le
  secret est masqué avant tout stockage ;
- un livrable qui propose une action offensive (exploitation, malware, contournement
  d'authentification, attaque d'un système tiers) est refusé.
Les motifs visent des formes précises pour ne pas bloquer un texte défensif (« se protéger
contre les rançongiciels », « Docker contourne UFW »…).
"""
import re

from .gate import contient_mot, normaliser

PREFIXE = "CYBER-FORTRESS/"
MASQUE = "<SECRET MASQUÉ>"

# Secrets reconnaissables à leur forme (texte brut, sensible à la casse).
_SECRETS = [
    ("clé privée", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|$)", re.S)),
    ("clé d'API", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}")),
    ("jeton GitHub", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("clé AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jeton Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("jeton JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("empreinte bcrypt", re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}")),
]
# « mot de passe : valeur », « token=valeur »… ; les gabarits (<…>, ${…}, ***, xxxx) sont tolérés.
_AFFECTATION = re.compile(
    r"(?i)\b(mot de passe|password|passwd|pwd|secret|token|jeton|api[_ -]?key|cl[ée] (?:d'?)?api)"
    r"(\s*[:=]\s*[\"']?)([^\s\"'<>]{8,})")
_GABARIT = re.compile(r"^(?:\$\{|\$\(|\*{3,}|x{4,}|X{4,}|changez|change_me|changeme|exemple|example|a_completer)", re.I)

# Actions offensives (texte normalisé, mots entiers).
_OFFENSIF = [
    r"reverse shell", r"bind shell", r"meterpreter", r"msfvenom", r"metasploit", r"/dev/tcp/",
    r"nc -e", r"ncat -e", r"bash -i", r"sqlmap", r"keylogger", r"enregistreur de frappe",
    r"code d'exploitation", r"exploit fonctionnel", r"charge utile malveillante",
    r"contourner l'authentification", r"contournement de l'authentification", r"bypass(?:er)? l'authentification",
    r"authentication bypass", r"auth bypass", r"credential stuffing",
    r"lancer une attaque", r"attaquer (?:le|la|les|leur|son|sa|ses) (?:serveur|site|systeme|reseau|compte)s?",
    r"pirater", r"desactiver l'antivirus", r"creer un (?:malware|virus|rancongiciel|ransomware)",
    r"ecrire un (?:malware|virus|rancongiciel|ransomware)",
]


def concerne(service: str | None) -> bool:
    return (service or "").startswith(PREFIXE)


def _affectations(texte: str):
    for m in _AFFECTATION.finditer(texte):
        if not _GABARIT.match(m.group(3)):
            yield m


def detecter_secrets(texte: str) -> list[str]:
    trouves = [nom for nom, motif in _SECRETS if motif.search(texte or "")]
    if any(True for _ in _affectations(texte or "")):
        trouves.append("mot de passe ou jeton en clair")
    return trouves


def masquer(texte: str) -> str:
    """Remplace chaque secret reconnu par « <SECRET MASQUÉ> »."""
    t = texte or ""
    for _, motif in _SECRETS:
        t = motif.sub(MASQUE, t)
    return _AFFECTATION.sub(lambda m: m.group(0) if _GABARIT.match(m.group(3))
                            else f"{m.group(1)}{m.group(2)}{MASQUE}", t)


def detecter_offensif(texte: str) -> list[str]:
    t = normaliser(texte)
    return [m for m in _OFFENSIF if contient_mot(t, m)]


def verdict_garde_fou(livrable: str) -> dict | None:
    """Refus déterministe (même format que le CHECKER) ou None si rien n'est détecté."""
    problemes = []
    secrets = detecter_secrets(livrable)
    if secrets:
        problemes.append("Secret présent dans le livrable (" + ", ".join(sorted(set(secrets))) +
                         ") : il a été masqué ; écrire « <SECRET> » à la place, jamais la valeur.")
    offensif = detecter_offensif(livrable)
    if offensif:
        problemes.append("Action offensive proposée (" + ", ".join(offensif[:3]) +
                         ") : posture strictement défensive, à retirer.")
    return {"ok": False, "problemes": problemes} if problemes else None
