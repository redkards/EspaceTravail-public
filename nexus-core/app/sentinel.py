"""SENTINEL : état clé/valeur et kill switch (grille, direction, agent)."""
from sqlalchemy import select

from .db import session_scope
from .models import Etat


# --- Accès à la table etat -------------------------------------------------

def lire(cle: str, defaut: str = "") -> str:
    with session_scope() as s:
        e = s.get(Etat, cle)
        return e.valeur if e else defaut


def ecrire(cle: str, valeur: str) -> None:
    with session_scope() as s:
        e = s.get(Etat, cle)
        if e:
            e.valeur = valeur
        else:
            s.add(Etat(cle=cle, valeur=valeur))


def incrementer(cle: str, delta: float) -> float:
    """Incrément atomique (UPSERT) : aucun compteur perdu entre traitements concurrents.

    INSERT … ON CONFLICT(cle) DO UPDATE SET valeur = CAST(valeur AS réel) + excluded.valeur,
    identique sous SQLite (≥ 3.35) et PostgreSQL.
    """
    from sqlalchemy import text
    with session_scope() as s:
        reel = "DOUBLE PRECISION" if s.get_bind().dialect.name == "postgresql" else "REAL"
        r = s.execute(text(
            f"INSERT INTO etat (cle, valeur) VALUES (:cle, :delta) "
            f"ON CONFLICT (cle) DO UPDATE SET valeur = CAST(CAST(etat.valeur AS {reel}) "
            f"+ CAST(excluded.valeur AS {reel}) AS TEXT) RETURNING valeur"),
            {"cle": cle, "delta": repr(float(delta))})
        return float(r.scalar_one())


# --- Kill switch -------------------------------------------------------------

def normaliser_direction(cible: str) -> str:
    """Accepte « tech », « DIR-TECH »… et renvoie « DIR-TECH »."""
    c = (cible or "").strip().upper()
    return c if c.startswith("DIR-") else f"DIR-{c}"


def cle_kill(portee: str, cible: str | None = None) -> str:
    if portee == "grille":
        return "kill:grille"
    if portee == "direction":
        return f"kill:dir:{normaliser_direction(cible or '')}"
    if portee == "agent":
        return f"kill:agent:{(cible or '').strip()}"
    raise ValueError("portée inconnue (grille | direction | agent)")


def basculer(portee: str, cible: str | None, actif: bool) -> str:
    cle = cle_kill(portee, cible)
    ecrire(cle, "1" if actif else "0")
    return cle


def actifs() -> dict:
    """Liste des interrupteurs actuellement enclenchés."""
    with session_scope() as s:
        rows = s.execute(select(Etat).where(Etat.cle.like("kill:%"))).scalars().all()
        return {e.cle: True for e in rows if e.valeur == "1"}


def bloque(directeur: str | None = None, agent_id: str | None = None) -> str | None:
    """Renvoie la clé qui bloque (ou None si tout est autorisé)."""
    k = actifs()
    if "kill:grille" in k:
        return "kill:grille"
    if directeur and f"kill:dir:{directeur}" in k:
        return f"kill:dir:{directeur}"
    if agent_id and f"kill:agent:{agent_id}" in k:
        return f"kill:agent:{agent_id}"
    return None
