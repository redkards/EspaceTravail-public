"""Connexion à la base : SQLite (MVP, tests) ou PostgreSQL, selon DATABASE_URL."""
import logging
import time
from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import cfg
from .models import Base

log = logging.getLogger("nexus.db")

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = cfg().database_url
        if url.startswith("sqlite:///") and ":memory:" not in url:
            # Crée le dossier du fichier SQLite (ex. /data) s'il manque.
            Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("sqlite"):
            # SQLite (tests et MVP) : accès multi-threads, attente si verrou, mode WAL.
            _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

            @event.listens_for(_engine, "connect")
            def _pragmas(conn, _):
                c = conn.cursor()
                if ":memory:" not in url and url not in ("sqlite://", "sqlite:///"):
                    c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")
                c.execute("PRAGMA busy_timeout=30000")
                c.execute("PRAGMA foreign_keys=ON")
                c.close()
        else:
            # Petit pool : empreinte mémoire faible (1 worker).
            _engine = create_engine(url, pool_size=3, max_overflow=2, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reinitialiser() -> None:
    """Oublie le moteur courant (utilisé par les tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


@contextmanager
def session_scope():
    engine()
    s: Session = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# Colonnes ajoutées après la première version : (table, colonne, définition SQL portable).
COLONNES_AJOUTEES = [
    ("missions", "projet", "VARCHAR(40) NOT NULL DEFAULT 'divers'"),
]


def migrer(eng: Engine) -> list[str]:
    """Migration douce : ajoute les colonnes manquantes (SQLite et PostgreSQL)."""
    ajoutees = []
    existantes = {t: {c["name"] for c in inspect(eng).get_columns(t)}
                  for t in {t for t, _, _ in COLONNES_AJOUTEES}}
    for table, colonne, definition in COLONNES_AJOUTEES:
        if colonne not in existantes[table]:
            with eng.begin() as c:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}"))
                if colonne == "projet":
                    c.execute(text("CREATE INDEX IF NOT EXISTS ix_missions_projet ON missions (projet)"))
            log.info("Migration : colonne %s.%s ajoutée.", table, colonne)
            ajoutees.append(f"{table}.{colonne}")
    return ajoutees


def init_db(tentatives: int = 30, pause_s: float = 2.0) -> None:
    """Crée l'extension vector (si PostgreSQL) puis les tables.

    Réessaie quelques fois : PostgreSQL peut démarrer après nexus-core.
    """
    for i in range(tentatives):
        try:
            eng = engine()
            if eng.dialect.name == "postgresql":
                try:
                    with eng.begin() as c:
                        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                except Exception as e:  # extension absente : on continue sans elle
                    log.warning("Extension vector indisponible : %s", e)
            Base.metadata.create_all(eng)
            migrer(eng)
            return
        except Exception as e:
            if i == tentatives - 1:
                raise
            log.warning("Base indisponible (%s), nouvel essai dans %.0f s", e, pause_s)
            time.sleep(pause_s)
