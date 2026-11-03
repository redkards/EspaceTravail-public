"""Outils communs : chemins, bac à sable, exécution avec délai max, masquage des secrets, journal."""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
SYSTEME = ICI.parent                       # syfer-test-system/
DEPOT = SYSTEME.parent                     # racine du dépôt (LECTURE SEULE)
RESULTATS = SYSTEME / "resultats"
CONFIG = SYSTEME / "config"
VERSIONS = SYSTEME / "versions"

# Variables héritées jamais transmises aux épreuves (clés réelles, URL de production…).
PREFIXES_EXCLUS = ("NEXUS_", "ANTHROPIC_", "OLLAMA_", "LLM_", "BUDGET_", "COCKPIT_", "LEDGER_", "NTFY_",
                   "DATABASE_URL", "BACKUP_", "FONCTIONNEMENT", "SELECTION", "MISSIONS", "FORCER_F4", "ENV_FILE",
                   "VEILLE_", "CHARGE_", "COMPACTION_", "PYTEST_ADDOPTS")
EXCLUS_COPIE = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", "syfer-test-system"}


# --------------------------------------------------------------------------- secrets

_SECRETS_SECOURS = [
    ("clé privée", r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----", 0),
    ("clé d'API", r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}", 0),
    ("jeton GitHub", r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}", 0),
    ("clé AWS", r"\bAKIA[0-9A-Z]{16}\b", 0),
    ("jeton Slack", r"\bxox[abprs]-[A-Za-z0-9-]{10,}", 0),
    ("jeton JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", 0),
    ("empreinte bcrypt", r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}", 0),
]


def _drapeaux(noeud) -> int:
    if noeud is None:
        return 0
    noms = [n.attr for n in ast.walk(noeud) if isinstance(n, ast.Attribute)]
    f = 0
    for n in noms:
        f |= getattr(re, n, 0) if n in ("S", "I", "M", "X", "DOTALL", "IGNORECASE", "MULTILINE") else 0
    return f


def motifs_secrets(racine: Path = DEPOT) -> tuple[list[tuple[str, re.Pattern]], re.Pattern | None, re.Pattern | None, str]:
    """Motifs du filtre anti-secret de nexus-core (app/cyber.py), lus par analyse du source (sans import).

    Renvoie (motifs nommés, motif d'affectation, motif de gabarit toléré, origine)."""
    src = racine / "nexus-core" / "app" / "cyber.py"
    try:
        arbre = ast.parse(src.read_text(encoding="utf-8"))
        motifs, aff, gab = [], None, None
        for n in arbre.body:
            if not isinstance(n, ast.Assign) or not isinstance(n.targets[0], ast.Name):
                continue
            nom = n.targets[0].id
            if nom == "_SECRETS" and isinstance(n.value, ast.List):
                for t in n.value.elts:
                    lib = ast.literal_eval(t.elts[0])
                    appel = t.elts[1]
                    motifs.append((lib, re.compile(ast.literal_eval(appel.args[0]),
                                                   _drapeaux(appel.args[1] if len(appel.args) > 1 else None))))
            elif nom in ("_AFFECTATION", "_GABARIT") and isinstance(n.value, ast.Call):
                a = n.value.args
                motif = re.compile(ast.literal_eval(a[0]), _drapeaux(a[1] if len(a) > 1 else None))
                if nom == "_AFFECTATION":
                    aff = motif
                else:
                    gab = motif
        if motifs:
            return motifs, aff, gab, "nexus-core/app/cyber.py"
    except Exception:  # noqa: BLE001 — repli sur la copie embarquée
        pass
    return [(l, re.compile(m, f)) for l, m, f in _SECRETS_SECOURS], None, None, "copie de secours"


_MOTIFS_CACHE: list | None = None


def masquer(texte: str) -> str:
    """Masque tout secret reconnu (journal sans secret)."""
    global _MOTIFS_CACHE
    if _MOTIFS_CACHE is None:
        m, aff, _, _ = motifs_secrets()
        _MOTIFS_CACHE = [p for _, p in m] + ([aff] if aff else [])
    for p in _MOTIFS_CACHE:
        if p.groups >= 3:
            texte = p.sub(lambda x: x.group(1) + x.group(2) + "<SECRET MASQUÉ>", texte)
        else:
            texte = p.sub("<SECRET MASQUÉ>", texte)
    return texte


# --------------------------------------------------------------------------- bac à sable

def creer_bac(parent: Path | None = None, racine: Path = DEPOT) -> Path:
    """Copie jetable du dépôt (sans .git ni caches) : chaque épreuve écrit dans le bac, jamais dans le dépôt."""
    base = Path(tempfile.mkdtemp(prefix="syfer-bac-", dir=str(parent) if parent else None))
    bac = base / "depot"

    def ignorer(dossier, noms):
        return [n for n in noms if n in EXCLUS_COPIE or n.endswith(".pyc")]

    shutil.copytree(racine, bac, ignore=ignorer, symlinks=True, ignore_dangling_symlinks=True)
    return bac


def supprimer_bac(bac: Path) -> None:
    shutil.rmtree(bac.parent, ignore_errors=True)


def env_base(extra: dict | None = None, tmp: Path | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(PREFIXES_EXCLUS)}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", LLM_PROVIDER="fake", NEXUS_TACHES_FOND="0",
               LANG=env.get("LANG", "C.UTF-8"), PYTHONIOENCODING="utf-8")
    if tmp:
        tmp.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(tmp)
    for k, v in (extra or {}).items():
        env[k] = str(v)
    return env


def executer(cmd: list[str], cwd: Path, env: dict, delai_s: float, journal: Path | None = None,
             entree: str | None = None) -> dict:
    """Lance une commande dans son propre groupe de processus ; la tue (groupe entier) au-delà du délai."""
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.PIPE if entree is not None else subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace", start_new_session=True)
    except FileNotFoundError as e:
        return {"rc": 127, "sortie": "", "erreurs": str(e), "duree_s": 0.0, "delai_depasse": False}
    depasse = False
    try:
        out, err = p.communicate(input=entree, timeout=delai_s)
    except subprocess.TimeoutExpired:
        depasse = True
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = p.communicate()
    duree = round(time.time() - t0, 1)
    if journal:
        journal.parent.mkdir(parents=True, exist_ok=True)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}   (dossier : {cwd.name}, {duree} s, rc={p.returncode}"
                    f"{', DÉLAI DÉPASSÉ' if depasse else ''})\n")
            f.write(masquer((out or "")[-20000:]))
            if err:
                f.write("\n--- stderr ---\n" + masquer(err[-20000:]))
            f.write("\n\n")
    return {"rc": p.returncode, "sortie": out or "", "erreurs": err or "", "duree_s": duree, "delai_depasse": depasse}


def horodatage() -> str:
    return time.strftime("%Y-%m-%d_%H%M%S")


def lire_json(chemin: Path, defaut=None):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defaut


def ecrire_json(chemin: Path, donnees) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(chemin)


def options_aide(script: Path, cwd: Path, env: dict) -> str:
    """Texte de --help d'un script (pour détecter les options d'une épreuve encore en construction)."""
    r = executer([sys.executable, str(script), "--help"], cwd, env, 30)
    return (r["sortie"] or "") + (r["erreurs"] or "")


def choisir_option(aide: str, candidats: list[str]) -> str | None:
    for c in candidats:
        if re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", aide):
            return c
    return None


def plus_recent_json(dossier: Path, apres: float) -> Path | None:
    if not dossier.exists():
        return None
    cand = [p for p in dossier.rglob("*.json") if p.stat().st_mtime >= apres - 1]
    return max(cand, key=lambda p: p.stat().st_mtime) if cand else None
