"""Stockage SQLite (WAL) + recherche plein texte FTS5.

Bibliothèque standard « sqlite3 » uniquement : une connexion par requête,
transactions courtes (BEGIN IMMEDIATE pour les écritures).
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS memoires (
    id            INTEGER PRIMARY KEY,
    sujet         TEXT NOT NULL,
    contenu       TEXT NOT NULL,
    etiquettes    TEXT NOT NULL DEFAULT '',        -- étiquettes séparées par des virgules
    projet        TEXT,
    auteur        TEXT NOT NULL,
    cree_le       TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    racine_id     INTEGER,                         -- id de la 1re version (chaîne de versions)
    remplace_id   INTEGER REFERENCES memoires(id), -- version précédente
    statut        TEXT NOT NULL DEFAULT 'active',  -- active | remplacee | archivee
    remplacee_par INTEGER,
    archive_par   TEXT,
    archive_raison TEXT,
    archive_le    TEXT
);
CREATE INDEX IF NOT EXISTS ix_memoires_statut ON memoires(statut, cree_le);

CREATE VIRTUAL TABLE IF NOT EXISTS memoires_fts USING fts5(
    sujet, contenu, etiquettes,
    content='memoires', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS memoires_ai AFTER INSERT ON memoires BEGIN
    INSERT INTO memoires_fts(rowid, sujet, contenu, etiquettes)
    VALUES (new.id, new.sujet, new.contenu, new.etiquettes);
END;
-- Le contenu d'une mémoire n'est jamais modifié (seul le statut change) ;
-- par sécurité l'index suit quand même une éventuelle suppression.
CREATE TRIGGER IF NOT EXISTS memoires_ad AFTER DELETE ON memoires BEGIN
    INSERT INTO memoires_fts(memoires_fts, rowid, sujet, contenu, etiquettes)
    VALUES ('delete', old.id, old.sujet, old.contenu, old.etiquettes);
END;

CREATE TABLE IF NOT EXISTS taches (
    id          INTEGER PRIMARY KEY,
    titre       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    assigne_a   TEXT NOT NULL,
    projet      TEXT,
    priorite    TEXT NOT NULL DEFAULT 'normale',  -- basse | normale | haute | urgente
    statut      TEXT NOT NULL DEFAULT 'a_faire',  -- a_faire | en_cours | a_valider | fait
    cree_par    TEXT NOT NULL,
    pris_par    TEXT,
    cree_le     TEXT NOT NULL,
    maj_le      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_taches_statut ON taches(statut, assigne_a);

CREATE TABLE IF NOT EXISTS taches_notes (
    id       INTEGER PRIMARY KEY,
    tache_id INTEGER NOT NULL REFERENCES taches(id),
    auteur   TEXT NOT NULL,
    statut   TEXT NOT NULL,
    note     TEXT NOT NULL DEFAULT '',
    cree_le  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY,
    expediteur   TEXT NOT NULL,
    destinataire TEXT NOT NULL,                   -- claude | chatgpt | gemini | proprietaire | tous
    sujet        TEXT NOT NULL,
    contenu      TEXT NOT NULL,
    cree_le      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_dest ON messages(destinataire, cree_le);

CREATE TABLE IF NOT EXISTS messages_lus (
    message_id INTEGER NOT NULL REFERENCES messages(id),
    lecteur    TEXT NOT NULL,
    lu_le      TEXT NOT NULL,
    PRIMARY KEY (message_id, lecteur)
);

CREATE TABLE IF NOT EXISTS passations (
    id                INTEGER PRIMARY KEY,
    projet            TEXT NOT NULL,
    auteur            TEXT NOT NULL,
    resume            TEXT NOT NULL,
    etat              TEXT NOT NULL,
    prochaines_etapes TEXT NOT NULL,
    cree_le           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_passations_projet ON passations(projet, cree_le);

-- Journal append-only : qui a écrit quoi et quand, SANS contenu.
CREATE TABLE IF NOT EXISTS journal (
    id         INTEGER PRIMARY KEY,
    horodatage TEXT NOT NULL,
    auteur     TEXT NOT NULL,
    outil      TEXT NOT NULL,
    objet      TEXT NOT NULL DEFAULT '',
    resultat   TEXT NOT NULL DEFAULT 'ok'
);
CREATE TRIGGER IF NOT EXISTS journal_pas_de_modif BEFORE UPDATE ON journal BEGIN
    SELECT RAISE(ABORT, 'journal en ajout seul');
END;
CREATE TRIGGER IF NOT EXISTS journal_pas_de_suppr BEFORE DELETE ON journal BEGIN
    SELECT RAISE(ABORT, 'journal en ajout seul');
END;
"""

_init_lock = threading.Lock()
_initialise: set[str] = set()


def maintenant() -> str:
    """Horodatage UTC ISO 8601 (précision microseconde, tri lexicographique fiable)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connecter(chemin: str) -> sqlite3.Connection:
    con = sqlite3.connect(chemin, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 10000")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def initialiser(chemin: str | None = None) -> None:
    chemin = chemin or cfg().db_path
    with _init_lock:
        if chemin in _initialise and (chemin == ":memory:" or os.path.exists(chemin)):
            return
        dossier = os.path.dirname(chemin)
        if dossier:
            os.makedirs(dossier, exist_ok=True)
        con = _connecter(chemin)
        try:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(SCHEMA)
        finally:
            con.close()
        _initialise.add(chemin)


@contextmanager
def connexion(ecriture: bool = False):
    """Connexion courte. En écriture : transaction IMMEDIATE (verrou pris d'emblée)."""
    chemin = cfg().db_path
    initialiser(chemin)
    con = _connecter(chemin)
    try:
        if ecriture:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")
        else:
            yield con
    finally:
        con.close()


def journaliser(con: sqlite3.Connection, auteur: str, outil: str, objet: str = "", resultat: str = "ok") -> None:
    con.execute("INSERT INTO journal(horodatage, auteur, outil, objet, resultat) VALUES (?,?,?,?,?)",
                (maintenant(), auteur, outil, objet[:80], resultat[:80]))


def journaliser_seul(auteur: str, outil: str, objet: str = "", resultat: str = "ok") -> None:
    with connexion(ecriture=True) as con:
        journaliser(con, auteur, outil, objet, resultat)
