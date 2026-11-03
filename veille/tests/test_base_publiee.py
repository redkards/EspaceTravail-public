"""Base publiée : copie de travail + remplacement atomique ; lecture sur un montage en lecture seule."""
import os
import stat
import threading
from pathlib import Path

import pytest

import collecteur as C
import recherche as R
from conftest import FauxTransport, fabriquer, lire, source

FLUX = "https://autorite.exemple.fr/rss.xml"


def _collecte(chemin, flux=FLUX, corps=None, sid="autorite-test", publier=True):
    t = FauxTransport({flux: (200, {}, corps or lire("flux_rss.xml"))})
    with C.base_de_travail(chemin, publier=publier) as conn:
        fabriquer(conn, t).collecter([source(id=sid, url_flux=flux)], forcer=True)


def _annexes(dossier: Path):
    return sorted(p.name for p in dossier.iterdir() if p.name.endswith(("-wal", "-shm", "-journal", ".tmp")))


def _fiche_xml(n):
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><item><title>Poker publication {n}</title>'
            f'<link>https://p.exemple.fr/{n}</link><description>Note poker numéro {n}.</description></item>'
            f'</channel></rss>').encode()


def test_publication_atomique_journal_delete_sans_annexes(tmp_path):
    db = tmp_path / "veille.db"
    _collecte(db)
    assert db.exists() and not (tmp_path / "veille.db.tmp").exists()
    assert _annexes(tmp_path) == []
    c = R.ouvrir_lecture(str(db))
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert c.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == 2
    c.close()


def test_collecte_suivante_part_de_la_base_publiee(tmp_path):
    db = tmp_path / "veille.db"
    _collecte(db)
    _collecte(db, flux="https://p.exemple.fr/rss", corps=_fiche_xml(1), sid="autre")
    c = R.ouvrir_lecture(str(db))
    assert c.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == 3
    c.close()


def test_simulation_ou_erreur_ne_publie_rien(tmp_path):
    db = tmp_path / "veille.db"
    _collecte(db)
    avant = db.stat().st_ino
    _collecte(db, flux="https://p.exemple.fr/rss", corps=_fiche_xml(1), sid="autre", publier=False)
    with pytest.raises(RuntimeError):
        with C.base_de_travail(db) as conn:
            conn.execute("DELETE FROM fiches")
            raise RuntimeError("panne au milieu de la collecte")
    assert db.stat().st_ino == avant and _annexes(tmp_path) == []
    c = R.ouvrir_lecture(str(db))
    assert c.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == 2  # intacte
    c.close()


def test_ancienne_base_wal_convertie(tmp_path):
    db = tmp_path / "veille.db"
    vieille = C.ouvrir(db)
    vieille.execute("PRAGMA journal_mode=WAL")
    vieille.close()
    _collecte(db)
    c = R.ouvrir_lecture(str(db))
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    c.close()
    assert _annexes(tmp_path) == []


def test_deux_collectes_simultanees_refusees(tmp_path):
    db = tmp_path / "veille.db"
    with C.base_de_travail(db):
        with pytest.raises(RuntimeError, match="autre collecte"):
            with C.base_de_travail(db):
                pass


def test_lecture_pendant_un_remplacement(tmp_path):
    db = tmp_path / "veille.db"
    _collecte(db)
    lecteur = R.ouvrir_lecture(str(db))
    avant = lecteur.execute("SELECT COUNT(*) FROM fiches").fetchone()[0]
    _collecte(db, flux="https://p.exemple.fr/rss", corps=_fiche_xml(1), sid="autre")
    # la connexion déjà ouverte lit toujours l'ancienne version, complète et cohérente
    assert lecteur.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == avant
    assert lecteur.execute("SELECT COUNT(*) FROM fiches_fts WHERE fiches_fts MATCH 'recommandation'").fetchone()[0] == 1
    lecteur.close()
    assert len(R.rechercher("poker publication", chemin_db=str(db))) == 1  # nouvelle connexion : nouvelle version


def test_lectures_concurrentes_sans_erreur(tmp_path):
    db = tmp_path / "veille.db"
    _collecte(db)
    erreurs, fini = [], threading.Event()
    par_fil: list[list[int]] = [[], [], []]

    def lire_en_boucle(comptes):
        while not fini.is_set():
            try:
                comptes.append(len(R.rechercher("poker recommandation", chemin_db=str(db), limite=100)))
            except Exception as e:  # noqa: BLE001
                erreurs.append(repr(e))

    fils = [threading.Thread(target=lire_en_boucle, args=(c,)) for c in par_fil]
    for f in fils:
        f.start()
    try:
        for n in range(1, 16):
            _collecte(db, flux=f"https://p.exemple.fr/rss{n}", corps=_fiche_xml(n), sid=f"s{n}")
    finally:
        fini.set()
        for f in fils:
            f.join()
    assert erreurs == [] and all(par_fil)
    for comptes in par_fil:  # pour chaque lecteur : jamais de retour en arrière ni d'état partiel
        assert comptes == sorted(comptes) and max(comptes) <= 16


@pytest.fixture
def montage_lecture_seule(tmp_path):
    dossier = tmp_path / "veille-donnees"
    dossier.mkdir()
    db = dossier / "veille.db"
    _collecte(db)
    os.chmod(db, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)                       # 444
    os.chmod(dossier, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)  # 555
    yield db
    os.chmod(dossier, 0o755)
    os.chmod(db, 0o644)


def test_montage_lecture_seule_variable(montage_lecture_seule, monkeypatch):
    monkeypatch.setenv("VEILLE_LECTURE_SEULE", "1")
    db = montage_lecture_seule
    assert "immutable=1" in R.uri_lecture(str(db))
    assert R.rechercher("intelligence artificielle", chemin_db=str(db))
    assert R.fiches_pour_mission("intelligence artificielle", chemin_db=str(db))
    c = R.ouvrir_lecture(str(db))
    with pytest.raises(Exception):
        c.execute("DELETE FROM fiches")
    c.close()
    assert _annexes(db.parent) == []  # aucun -wal / -shm / -journal créé


def test_montage_lecture_seule_detecte_sans_variable(montage_lecture_seule, monkeypatch):
    monkeypatch.delenv("VEILLE_LECTURE_SEULE", raising=False)
    db = montage_lecture_seule
    vrai_access = os.access
    # root ignore les droits : on simule ce que verrait l'utilisateur non privilégié du conteneur
    monkeypatch.setattr(R.os, "access", lambda p, m: False if m == os.W_OK else vrai_access(p, m))
    assert R.lecture_seule_imposee(str(db))
    assert "immutable=1" in R.uri_lecture(str(db))
    assert R.rechercher("intelligence artificielle", chemin_db=str(db))
    assert _annexes(db.parent) == []


def test_base_inscriptible_lue_sans_immutable(tmp_path, monkeypatch):
    monkeypatch.delenv("VEILLE_LECTURE_SEULE", raising=False)
    db = tmp_path / "veille.db"
    _collecte(db)
    uri = R.uri_lecture(str(db))
    assert "mode=ro" in uri and "immutable" not in uri
