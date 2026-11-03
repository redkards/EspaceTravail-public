"""Compaction de la mémoire et des archives (app/compaction.py).

Round-trip, lecture aléatoire, déduplication, paliers, Merkle/HMAC et falsification, effacement RGPD
dans un bloc, fusion des quasi-doublons, idempotence, reprise après interruption, compatibilité avec
le format et la chaîne d'archive.py.
"""
import gzip
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import archive, compaction as C

MAINTENANT = datetime(2026, 11, 4, 3, 0, 0)  # 04:00 à Paris : dans la fenêtre de nuit par défaut
CLE = "cle-compaction-test"


@pytest.fixture
def cle(monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    return CLE


@pytest.fixture
def comp(tmp_path, cle):
    c = C.Compacteur(tmp_path / "compact", horloge=lambda: MAINTENANT)
    yield c
    c.fermer()


def mission(i: int, quand: datetime, note=None, refus=False) -> dict:
    livrable = "\n".join([f"# Livrable {i}", "", "## Contexte",
                          f"La mission {i} porte sur le mot motunique{i} et sur la sauvegarde du serveur.",
                          "Respecte la charte du projet. Réponds en français, de façon claire et structurée.",
                          "## Prochaines étapes", "1. Valider ce document avec le Décideur avant diffusion générale.",
                          "_Livrable produit par NEXUS — à relire avant diffusion._"])
    probs = [f"Problème récurrent numéro {i % 3} : sources absentes."] if refus else []
    return {"evenement": "fin_execution", "horodatage": quand.isoformat(timespec="seconds") + "Z", "mission_id": i,
            "titre": f"Mission {i} — sauvegarde", "consigne": f"Rédige la note {i}.\nRespecte la charte du projet. "
            "Réponds en français, de façon claire et structurée, avec des titres et une liste de prochaines étapes.",
            "projet": "studio-master", "service": "REDACTION/article", "statut": "terminee", "niveau": "N2",
            "fonctionnement_demande": "F2", "fonctionnement": "F2", "fonctionnement_raison": None,
            "modeles": {"writer": "claude"}, "etapes": [
                {"agent": "NEXUS-COLLECTOR", "role": "collector", "verdict": None, "tokens": 100,
                 "sortie": "- [base.md#1] Extrait de connaissance partagé entre toutes les missions du projet."},
                {"agent": "NEXUS-WRITER", "role": "writer", "verdict": None, "tokens": 500, "sortie": livrable},
                {"agent": "NEXUS-CHECKER", "role": "checker", "verdict": "refus" if refus else "ok", "tokens": 80,
                 "sortie": json.dumps({"problemes": probs, "commentaire": "x" * 400})}],
            "livrable": livrable, "verdicts_checker": [{"source": "contrôle", "verdict": "refus", "problemes": probs}]
            if refus else [], "charte_violations": [], "charte_avertissements": [],
            "decisions": [{"id": i, "objet": "livrable", "statut": "refusee", "risque": "faible",
                           "commentaire": "Trop long.", "motif": "à revoir"}] if refus else [],
            "montant_eur": None, "action": None, "revisions": 0, "relance_auto": 0, "message": None, "tokens": 680,
            "tokens_entree": 200, "tokens_sortie": 480, "cout_eur": 0.01, "duree_s": 12.5, "note": note,
            "note_banc": None}


def ecrire_archive(dossier: Path, n: int, debut: datetime, pas: timedelta, **kw) -> list[dict]:
    """Lignes au format EXACT d'archive.archiver (fonctions d'archive.py, un membre gzip par ligne)."""
    dossier.mkdir(parents=True, exist_ok=True)
    prec, res = archive.GENESE, []
    for i in range(1, n + 1):
        e = mission(i, debut + pas * (i - 1), note=5 if i % 7 == 0 else None, refus=i % 4 == 0)
        contenu = __import__("hashlib").sha256(archive._canonique(e)).hexdigest()
        ref = "1" * 64
        h = archive._empreinte_ligne(i, prec, contenu, ref, "hmac")
        l = {"seq": i, "prec": prec, "contenu": contenu, "ledger_ref": ref, "algo": "hmac", "hash": h,
             "enregistrement": e}
        with gzip.open(dossier / f"{e['horodatage'][:7]}.jsonl.gz", "ab") as f:
            f.write(archive._canonique(l) + b"\n")
        res.append(l)
        prec = h
    return res


def generique(i: int, quand: datetime, texte: str | None = None) -> dict:
    return {"id": f"k:test:{i}", "type": "connaissance", "date": quand.isoformat(timespec="seconds"), "projet": "p",
            "mission_id": 1000 + i, "forme": "integral",
            "donnees": {"titre": f"Connaissance {i}", "contenu": texte or f"Texte {i} — accentué « ok » ñ 😀\nligne 2",
                        "$cle": {"$f": "pas une référence"}, "liste": [1, 2.5, None, True, {"a": "b"}]}}


# --------------------------------------------------------------------------------- unitaires

def test_merkle_preuves_toutes_tailles():
    for n in (1, 2, 3, 5, 8, 13, 256):
        fs = [C.feuille({"i": i}) for i in range(n)]
        r = C.racine(fs)
        for i in range(n):
            assert C.verifier_preuve(fs[i], C.preuve(fs, i), r)
        assert not C.verifier_preuve(C.feuille({"i": -1}), C.preuve(fs, 0), r)


def test_dictionnaire_borne_et_utile():
    ech = [C.canonique(mission(i, MAINTENANT)) for i in range(200)]
    d = C.entrainer_dictionnaire(ech)
    assert 1000 < len(d) <= C.DICT_TAILLE
    x = ech[0]
    assert C.z_decompresser(C.z_compresser(x, d), d) == x
    assert len(C.z_compresser(x, d)) < len(C.z_compresser(x))


def test_quasi_doublons_minhash():
    base = " ".join(f"mot{i} phrase numero {i}" for i in range(80))
    textes = {1: base, 2: base + " ajout final", 3: base.replace("mot5 ", "autre "), 4: "texte sans rapport " * 30}
    groupes = C.quasi_doublons(textes, 0.8)
    assert groupes == [[1, 2, 3]]


# --------------------------------------------------------------------------------- magasin

def test_round_trip_exact_et_lecture_aleatoire(comp):
    vieux = MAINTENANT - timedelta(days=60)
    enregs = [generique(i, vieux + timedelta(minutes=i)) for i in range(600)]
    enregs[10]["donnees"]["contenu"] = "x" * 3000 + "\n" + "Paragraphe partagé " * 10  # gros texte
    r = comp.ingerer([json.loads(json.dumps(e)) for e in enregs])
    assert r["ajoutes"] == 600 and len(r["blocs"]) >= 3  # blocs de 256
    for i in random.Random(1).sample(range(600), 80):
        lu = comp.lire(f"k:test:{i}")
        assert lu.pop("palier") == "tiede"
        assert lu == enregs[i]  # identique au bit près (clés « $… » échappées puis restituées)
    assert comp.lire("inconnu") is None
    assert comp.verifier()["valide"]


def test_lzma_tiede_et_fts_full(tmp_path, cle, monkeypatch):
    monkeypatch.setenv("COMPACTION_ALGO_TIEDE", "lzma")
    monkeypatch.setenv("COMPACTION_FTS_DETAIL", "full")
    c = C.Compacteur(tmp_path / "c2", horloge=lambda: MAINTENANT)
    enregs = [generique(i, MAINTENANT - timedelta(days=40), f"contenu {i} motclef{i}") for i in range(50)]
    c.ingerer([dict(e) for e in enregs])
    assert c.lire("k:test:7")["donnees"] == enregs[7]["donnees"]
    assert c.db.execute("SELECT algo FROM blocs").fetchone()[0] == "lzma"
    assert [x["id"] for x in c.rechercher("motclef7")] == ["k:test:7"]
    assert c.verifier()["valide"]
    c.fermer()


def test_deduplication_et_liberation(comp):
    partage = "Ce paragraphe type est répété dans de nombreux enregistrements de la mémoire du projet SYFER."
    vieux = MAINTENANT - timedelta(days=40)
    enregs = [generique(i, vieux, f"{partage}\nspécifique {i}\n{partage}") for i in range(20)]
    comp.ingerer(enregs)
    st = comp.statistiques()
    assert st["dedup"]["fragments"] == 1 and st["dedup"]["references"] == 40
    assert st["dedup"]["octets_evites"] > 0
    assert comp.lire("k:test:3")["donnees"]["contenu"] == f"{partage}\nspécifique 3\n{partage}"
    for i in range(20):
        assert comp.effacer(f"k:test:{i}", "test")
    assert comp.statistiques()["dedup"]["fragments"] == 0  # plus référencé : supprimé
    assert comp.verifier()["valide"]


def test_paliers_et_memoire_collective(tmp_path, comp):
    da = tmp_path / "archive"
    # 400 missions, une toutes les 12 h : de -200 j à maintenant
    lignes = ecrire_archive(da, 400, MAINTENANT - timedelta(days=200), timedelta(hours=12))
    r = comp.compacter("tiede", dossier_archive=da)
    ids = {x[0]: x[1] for x in comp.db.execute("SELECT e.seq, b.palier FROM enregs e JOIN blocs b ON b.id=e.bloc")}
    chaudes = [l for l in lignes if datetime.fromisoformat(l["enregistrement"]["horodatage"][:19])
               >= MAINTENANT - timedelta(days=30)]
    assert r["ajoutes"] == 400 - len(chaudes) and all(l["seq"] not in ids for l in chaudes)  # chaud intact
    assert {ids[1], ids[30]} == {"froid"} and ids[100] == "tiede"  # > 180 j : directement au froid
    t = comp.lire("m:100")
    assert t["forme"] == "reduit" and t["donnees"]["livrable"] == lignes[99]["enregistrement"]["livrable"]
    assert all("sortie" not in e for e in t["donnees"]["etapes"])
    assert len(t["donnees"]["etapes"][2]["avis"]) <= C.AVIS_MAX
    f = comp.lire("m:28")  # refus + décision : signaux de leçons conservés au froid
    m = f["donnees"]["memoire"]
    assert len(f["donnees"]["resume"]) <= C.RESUME_MAX
    assert m["problemes"][0]["problemes"] == lignes[27]["enregistrement"]["verdicts_checker"][0]["problemes"]
    assert m["decisions"][0]["commentaire"] == "Trop long."
    assert "exemple" in comp.lire("m:7")["donnees"]["memoire"]  # note 5 : extrait d'exemple gardé
    assert f["donnees"]["tokens"] == 680 and f["chaine"]["hash"] == lignes[27]["hash"]
    # migration tiède -> froid
    avant = comp.statistiques()["paliers"]["tiede"]["enregistrements"]
    r = comp.compacter("froid", avant_date=MAINTENANT)
    assert r["migres"] == avant and "tiede" not in comp.statistiques()["paliers"]
    assert comp.lire("m:100")["forme"] == "resume"
    v = comp.verifier()
    assert v["valide"] and v["chaine_archive"]["lignes"] == 400 - len(chaudes)
    ag = comp.agregats("m")
    assert sum(a["missions"] for a in ag) == 400 - len(chaudes)  # agrégés une seule fois malgré la migration


def test_recherche_index(tmp_path, comp):
    ecrire_archive(tmp_path / "a", 120, MAINTENANT - timedelta(days=100), timedelta(hours=12))
    comp.compacter("tiede", dossier_archive=tmp_path / "a")
    res = comp.rechercher("motunique42")
    assert [r["mission_id"] for r in res] == [42] and "motunique42" in res[0]["extrait"]
    assert len(comp.rechercher("sauvegarde serveur", limite=5)) == 5
    assert comp.rechercher("sauvegarde", projet="autre") == []
    assert comp.lire_mission(42)[0]["chaine"]["seq"] == 42


def test_chaine_archive_compatible_et_retrait_des_mois(tmp_path, comp):
    da = tmp_path / "archive"
    lignes = ecrire_archive(da, 200, MAINTENANT - timedelta(days=100), timedelta(hours=12))
    assert archive.dossier  # même format que archive.lignes()
    comp.compacter("tiede", dossier_archive=da)
    pr = comp.point_de_reprise()
    assert lignes[pr["seq"] - 1]["hash"] == pr["hash"]
    r = comp.retirer_mois(da)
    assert r["retires"] and r["gardes"]
    # les lignes restantes se rechaînent sur le point de reprise (intégration archive.verifier)
    restantes = sorted((json.loads(b) for f in da.glob("*.jsonl.gz") for b in gzip.open(f) if b.strip()),
                       key=lambda l: l["seq"])
    retirees_max = min(l["seq"] for l in restantes) - 1
    assert retirees_max <= pr["seq"]
    prec = comp.lire(f"m:{retirees_max}")["chaine"]["hash"]
    for l in restantes:
        assert l["prec"] == prec
        prec = l["hash"]
    assert any(j["type"] == "retrait_source" for j in
               [{"type": t} for (t,) in comp.db.execute("SELECT type FROM journal")])
    assert comp.verifier()["valide"]


# --------------------------------------------------------------------------------- intégrité

def _reecrire_bloc(c: C.Compacteur, bid: int, modifier) -> None:
    tete, stk = c._lignes_bloc(bid)
    modifier(stk)
    octets, _ = c._encoder(tete["palier"], tete, [C.canonique(s) for s in stk])
    c._chemin(tete["palier"], bid).write_bytes(octets)
    c._cache.clear()


@pytest.fixture
def rempli(comp):
    comp.ingerer([generique(i, MAINTENANT - timedelta(days=50), f"contenu {i} " * 20) for i in range(300)])
    assert comp.verifier()["valide"]
    return comp


def test_falsification_contenu_de_bloc(rempli):
    cible = rempli._lignes_bloc(1)[1][5]["id"]
    _reecrire_bloc(rempli, 1, lambda stk: stk[5]["donnees"].update(contenu="falsifié"))
    v = rempli.verifier()
    assert not v["valide"] and v["premiere_erreur"] == cible
    assert not rempli.verifier_enregistrement(cible)["valide"]
    assert rempli.verifier_enregistrement(rempli._lignes_bloc(1)[1][4]["id"])["valide"]  # voisin non décalé


def test_falsification_index_journal_fichier(rempli):
    rempli.db.execute("UPDATE enregs SET feuille=? WHERE id='k:test:3'", (b"\x00" * 32,))
    assert not rempli.verifier()["valide"]
    rempli.db.execute("UPDATE enregs SET feuille=? WHERE id='k:test:3'",
                      (C.feuille({k: v for k, v in rempli.lire("k:test:3").items() if k != "palier"}),))
    assert rempli.verifier()["valide"]
    racine = rempli.db.execute("SELECT racine FROM blocs WHERE id=1").fetchone()[0]
    rempli.db.execute("UPDATE blocs SET racine=? WHERE id=1", ("ab" * 32,))
    assert rempli.verifier()["motif"] == "bloc : métadonnées modifiées"
    rempli.db.execute("UPDATE blocs SET racine=? WHERE id=1", (racine,))
    d = rempli.db.execute("SELECT details FROM journal WHERE type='bloc_cree' LIMIT 1").fetchone()[0]
    rempli.db.execute("UPDATE journal SET details=? WHERE type='bloc_cree' AND id=(SELECT min(id) FROM journal "
                      "WHERE type='bloc_cree')", (d.replace('"n":256', '"n":255'),))
    assert rempli.verifier()["motif"] == "journal : empreinte ou chaînage invalide"
    rempli.db.execute("UPDATE journal SET details=? WHERE id=(SELECT min(id) FROM journal WHERE type='bloc_cree')", (d,))
    assert rempli.verifier()["valide"]
    f = rempli._chemin("tiede", 1)
    octets = bytearray(f.read_bytes())
    octets[200] ^= 0xFF
    f.write_bytes(bytes(octets))
    assert not rempli.verifier()["valide"]


def test_falsification_fragment_et_cle(tmp_path, comp, monkeypatch):
    partage = "Segment partagé suffisamment long pour être dédupliqué par le module de compaction SYFER."
    comp.ingerer([generique(i, MAINTENANT - timedelta(days=40), partage) for i in range(5)])
    comp.db.execute("UPDATE fragments SET donnees=?", (C.z_compresser(b"x" * 90, comp.dictionnaire(0)),))
    comp._frag_cache.clear()
    assert not comp.verifier()["valide"]
    # sans la clé : vérification impossible et écriture refusée (pas de déclassement HMAC -> SHA-256)
    monkeypatch.delenv("LEDGER_HMAC_KEY")
    c2 = C.Compacteur(tmp_path / "compact", horloge=lambda: MAINTENANT)
    assert "LEDGER_HMAC_KEY absente" in c2.verifier()["motif"]
    with pytest.raises(C.ErreurCompaction):
        c2.ingerer([generique(99, MAINTENANT - timedelta(days=40))])
    c2.fermer()


def test_sans_cle_sha256(tmp_path, monkeypatch):
    monkeypatch.delenv("LEDGER_HMAC_KEY", raising=False)
    c = C.Compacteur(tmp_path / "c", horloge=lambda: MAINTENANT)
    c.ingerer([generique(i, MAINTENANT - timedelta(days=40)) for i in range(10)])
    assert c.db.execute("SELECT DISTINCT algo FROM journal").fetchall() == [("sha256",)]
    v = c.verifier()
    assert v["valide"] and not v["hmac_actif"]
    c.fermer()


# --------------------------------------------------------------------------------- RGPD

def test_effacement_rgpd_dans_un_bloc(tmp_path, comp):
    appels = []
    comp.ledger = lambda *a, **k: appels.append((a, k))
    ecrire_archive(tmp_path / "a", 60, MAINTENANT - timedelta(days=100), timedelta(hours=12))
    comp.compacter("tiede", dossier_archive=tmp_path / "a")
    bid = comp.db.execute("SELECT bloc FROM enregs WHERE id='m:30'").fetchone()[0]
    voisin = comp.lire("m:31")
    assert comp.rechercher("motunique30")
    assert comp.effacer_mission(30, "droit à l'effacement", "Kevin") == 1
    t = comp.lire("m:30")
    assert t["efface"] and "motunique30" not in json.dumps(t) and t["chaine"]["seq"] == 30
    assert comp.lire("m:31") == voisin  # le reste du bloc est intact
    assert b"motunique30" not in comp._decoder(comp._chemin("tiede", bid).read_bytes())
    assert comp.rechercher("motunique30") == []
    assert comp.db.execute("SELECT count(*) FROM cfts WHERE cfts MATCH 'motunique30'").fetchone()[0] == 0
    j = comp.journal_effacements()
    assert len(j) == 1 and j[0]["id"] == "m:30" and j[0]["ancienne_racine"] != j[0]["nouvelle_racine"]
    assert comp.db.execute("SELECT racine FROM blocs WHERE id=?", (bid,)).fetchone()[0] == j[0]["nouvelle_racine"]
    v = comp.verifier()
    assert v["valide"] and v["effaces"] == 1 and v["chaine_archive"]["valide"]
    assert comp.verifier_enregistrement("m:30")["valide"] and comp.verifier_enregistrement("m:29")["valide"]
    assert not comp.effacer("m:30")  # déjà effacé
    assert any(a[1] == "compaction_effacement" for a, _ in appels)
    # la pierre tombale traverse la migration vers le froid
    comp.compacter("froid", avant_date=MAINTENANT)
    assert comp.lire("m:30")["efface"] and comp.verifier()["valide"]


def test_effacement_falsifie_detecte(rempli):
    rempli.effacer("k:test:10")
    pos = rempli.db.execute("SELECT position FROM enregs WHERE id='k:test:10'").fetchone()[0]
    # remettre l'ancien contenu à la place de la pierre tombale : détecté
    _reecrire_bloc(rempli, 1, lambda stk: stk.__setitem__(pos, C._echapper(
        generique(10, MAINTENANT - timedelta(days=50), "contenu 10 " * 20))))
    assert not rempli.verifier()["valide"]


# --------------------------------------------------------------------------------- consolidation

def test_fusion_quasi_doublons_connaissances(tmp_path, comp):
    db = tmp_path / "test.db"  # base nexus créée par conftest (table + déclencheurs FTS réels)
    c = sqlite3.connect(str(db))
    base = " ".join(f"La règle {i} du projet impose une vérification hebdomadaire des sauvegardes." for i in range(12))
    lignes = [("auto", base, "livrable #1"), ("auto", base + " Une phrase de plus.", "livrable #2"),
              ("auto", base.replace("règle 3", "consigne 3"), "livrable #3"), ("manuel", base, "note.md"),
              ("auto", "Texte totalement différent " * 20, "livrable #4")]
    for i, (orig, txt, src) in enumerate(lignes):
        c.execute("INSERT INTO connaissances(projet, titre, contenu, source, date, auteur, version, origine, empreinte,"
                  " suspect) VALUES ('studio-master', ?, ?, ?, ?, 'x', 1, ?, ?, 0)",
                  (f"t{i}", txt, src, (MAINTENANT - timedelta(days=i)).isoformat(sep=" "), orig, f"e{i:063d}"))
    c.commit()
    plan = comp.consolider_connaissances(c, seuil=0.8, appliquer=False)
    assert plan["fusionnees"] == 3 and c.execute("SELECT count(*) FROM connaissances").fetchone()[0] == 5
    res = comp.consolider_connaissances(c, seuil=0.8)
    restantes = {r[0] for r in c.execute("SELECT source FROM connaissances")}
    assert restantes == {"note.md", "livrable #4"}  # le manuel est gardé comme représentant
    assert c.execute("SELECT count(*) FROM connaissances_fts WHERE connaissances_fts MATCH 'hebdomadaire'"
                     ).fetchone()[0] == 1  # FTS synchronisé par les déclencheurs
    archivees = comp.db.execute("SELECT id, mission_id FROM enregs WHERE type='connaissance'").fetchall()
    assert sorted(m for _, m in archivees) == [1, 2, 3]  # rattachées à leur mission (cascade RGPD)
    assert comp.lire(archivees[0][0])["donnees"]["raison"] == "fusion"
    assert comp.effacer_mission(2) == 1
    # plafond : éviction des « auto » les moins utiles, jamais des manuels
    for i in range(10):
        c.execute("INSERT INTO connaissances(projet, titre, contenu, source, date, auteur, version, origine, empreinte,"
                  " suspect) VALUES ('studio-master', ?, ?, ?, ?, 'x', 1, 'auto', ?, 0)",
                  (f"n{i}", f"Sujet distinct {i} " * 15 + f"mot{i}", f"livrable #{100 + i}",
                   (MAINTENANT - timedelta(days=10 * i)).isoformat(sep=" "), f"f{i:063d}"))
    c.commit()
    res = comp.consolider_connaissances(c, plafond=5, acces={})
    assert res["evincees"] == 7
    assert c.execute("SELECT count(*) FROM connaissances").fetchone()[0] == 5
    assert c.execute("SELECT count(*) FROM connaissances WHERE origine='manuel'").fetchone()[0] == 1
    gardes = {r[0] for r in c.execute("SELECT source FROM connaissances WHERE origine='auto'")}
    assert "livrable #100" in gardes and "livrable #109" not in gardes  # le plus récent est le plus utile
    assert comp.verifier()["valide"]
    c.close()


# --------------------------------------------------------------------------------- idempotence / reprise

def test_idempotence(tmp_path, comp):
    da = tmp_path / "a"
    ecrire_archive(da, 150, MAINTENANT - timedelta(days=220), timedelta(days=1))
    r1 = comp.compacter("froid", dossier_archive=da)
    st1 = comp.statistiques()
    r2 = comp.compacter("froid", dossier_archive=da)
    assert r1["ajoutes"] > 0 and r2["ajoutes"] == 0 and r2["migres"] == 0
    st2 = comp.statistiques()
    assert st1["paliers"] == st2["paliers"] and st1["dedup"] == st2["dedup"]
    assert comp.ingerer([generique(1, MAINTENANT - timedelta(days=40))] * 2)["ajoutes"] == 1


def test_tache_nocturne_fenetre_et_une_fois_par_jour(tmp_path, comp, monkeypatch):
    da = tmp_path / "a"
    ecrire_archive(da, 100, MAINTENANT - timedelta(days=250), timedelta(days=2))
    from tests.conftest import Path as _P  # noqa: F401  (conftest déjà chargé)
    veille = tmp_path / "veille.db"
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "veille"))
    import collecteur
    v = sqlite3.connect(str(veille))
    v.executescript(collecteur.SCHEMA)
    for i in range(30):
        d = (MAINTENANT - timedelta(days=10 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        v.execute("INSERT INTO fiches(source_id, titre, resume, url, url_canonique, empreinte, date, confiance,"
                  " collecte_le) VALUES ('s', ?, ?, ?, ?, ?, ?, 'A', ?)",
                  (f"Fiche {i}", f"Résumé veillemot{i} " * 10, f"https://e.fr/{i}", f"https://e.fr/{i}",
                   f"{i:064d}", d[:10], d))
    v.commit()
    v.close()
    assert comp.tache_nocturne(MAINTENANT.replace(hour=12), dossier_archive=da) is None  # hors fenêtre
    r = comp.tache_nocturne(MAINTENANT, dossier_archive=da, veille_db=veille, nexus_db=tmp_path / "test.db")
    assert r and "erreur" not in r, r
    assert r["tiede"]["ajoutes"] > 0 and r["veille"]["archivees"] == 11  # > 180 j
    assert all(e.get("erreur") is None for e in r["entretien"])
    assert comp.tache_nocturne(MAINTENANT + timedelta(minutes=30), dossier_archive=da) is None  # déjà faite
    assert comp.rechercher("veillemot25", type_="veille")[0]["palier"] == "froid"
    v = sqlite3.connect(str(veille))
    assert v.execute("SELECT count(*) FROM fiches").fetchone()[0] == 19
    assert v.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # incrémental après entretien
    v.close()
    assert comp.verifier()["valide"]


def test_reprise_apres_interruption_ecriture_de_bloc(tmp_path, comp, monkeypatch):
    da = tmp_path / "a"
    ecrire_archive(da, 80, MAINTENANT - timedelta(days=100), timedelta(hours=12))
    vrai = comp._journaliser

    def panne(type_, *a, **k):
        if type_ == "bloc_cree":
            raise KeyboardInterrupt("arrêt brutal")
        return vrai(type_, *a, **k)

    monkeypatch.setattr(comp, "_journaliser", panne)
    with pytest.raises(KeyboardInterrupt):
        comp.compacter("tiede", dossier_archive=da)
    assert list((comp.dossier / "blocs" / "tiede").glob("*.blk"))  # fichier écrit, transaction annulée
    assert comp.db.execute("SELECT count(*) FROM enregs").fetchone()[0] == 0
    monkeypatch.setattr(comp, "_journaliser", vrai)
    r = comp.compacter("tiede", dossier_archive=da)
    assert r["reprise"]["orphelins"] == 1 and r["ajoutes"] > 0
    assert comp.verifier()["valide"]


def test_reprise_apres_interruption_effacement(rempli, monkeypatch):
    # 1) arrêt après COMMIT, avant remplacement du fichier : finalisé par reprendre()
    def panne(tmp, final):
        raise KeyboardInterrupt

    monkeypatch.setattr(rempli, "_finaliser_fichier", panne)
    with pytest.raises(KeyboardInterrupt):
        rempli.effacer("k:test:4")
    rempli._cache.clear()
    assert not rempli.verifier()["valide"]  # fichier encore ancien : incohérence détectée
    monkeypatch.undo()
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    assert rempli.reprendre()["finalises"] == 1
    assert rempli.lire("k:test:4")["efface"] and rempli.verifier()["valide"]
    # 2) arrêt avant COMMIT : effacement annulé proprement, contenu intact
    vrai = rempli._journaliser

    def panne_j(type_, *a, **k):
        if type_ == "effacement":
            raise KeyboardInterrupt
        return vrai(type_, *a, **k)

    monkeypatch.setattr(rempli, "_journaliser", panne_j)
    with pytest.raises(KeyboardInterrupt):
        rempli.effacer("k:test:5")
    monkeypatch.setattr(rempli, "_journaliser", vrai)
    assert rempli.reprendre()["annules"] == 1
    assert not rempli.lire("k:test:5").get("efface") and rempli.verifier()["valide"]
    assert rempli.effacer("k:test:5") and rempli.verifier()["valide"]


def test_entretien_sqlite(tmp_path):
    db = tmp_path / "x.db"
    c = sqlite3.connect(str(db))
    c.executescript("CREATE TABLE t(x); CREATE VIRTUAL TABLE f USING fts5(y);")
    c.executemany("INSERT INTO t VALUES (?)", [("a" * 500,)] * 2000)
    c.executemany("INSERT INTO f VALUES (?)", [("bonjour le monde",)] * 200)
    c.commit()
    c.execute("DELETE FROM t")
    c.commit()
    c.close()
    r = C.entretenir(db)
    assert r["vacuum"] and r["fts"] == ["f"] and r["apres"] < r["avant"] and r["erreur"] is None
    c = sqlite3.connect(str(db))
    assert c.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    c.close()
    assert C.entretenir(db, "non")["vacuum"] is False
    assert C.entretenir(tmp_path / "absente.db")["absente"]


def test_api_module_instance_par_defaut(tmp_path, cle, monkeypatch):
    monkeypatch.setenv("NEXUS_COMPACTION_DIR", str(tmp_path / "defaut"))
    c = C.defaut()
    c.horloge = lambda: MAINTENANT
    c.ingerer([generique(1, MAINTENANT - timedelta(days=40))])
    assert C.lire("k:test:1")["donnees"]["titre"] == "Connaissance 1"
    assert C.verifier()["valide"] and C.statistiques()["paliers"]["tiede"]["enregistrements"] == 1
    assert C.rechercher("Connaissance")[0]["id"] == "k:test:1"
    assert C.compacter("chaud")["palier"] == "chaud"
    assert C.effacer("k:test:1") and C.lire("k:test:1")["efface"]
    with pytest.raises(ValueError):
        C.compacter("tiède-mal-écrit")
    c.fermer()
    C._defaut = None
