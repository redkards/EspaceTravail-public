"""Bout en bout : lancer.sh contre un faux serveur HTTP local."""
import json
import os
import re
import subprocess

import pytest

from faux_serveur import CLE, FauxServeur


def lancer(banc, env, timeout=120, **variables):
    e = dict(env)
    e.update({k: str(v) for k, v in variables.items()})
    return subprocess.run(["bash", str(banc / "lancer.sh")], env=e, cwd=str(banc), capture_output=True,
                          text=True, timeout=timeout)


@pytest.fixture
def serveur(banc):
    with FauxServeur(str(banc / "missions.json")) as s:
        yield s


def test_syntaxe_bash(banc):
    assert subprocess.run(["bash", "-n", str(banc / "lancer.sh")]).returncode == 0


def test_cle_jamais_en_ligne_de_commande(banc):
    """La clé ne passe que par un fichier d'en-tête chmod 600 (curl -H @fichier)."""
    script = (banc / "lancer.sh").read_text()
    assert '-H "@${TMP_ENTETE}"' in script and "chmod 600" in script and "trap nettoyer EXIT" in script
    assert not re.search(r"curl[^\n]*X-Nexus-Key", script)
    assert not re.search(r"-H ['\"]X-Nexus-Key: *\$", script)


def test_rapide_complet(banc, serveur, env_propre, tmp_path):
    res = tmp_path / "r.json"
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F1",
               SELECTION="rapide", FICHIER_RESULTATS=res)
    assert p.returncode == 0, p.stderr
    d = json.loads(res.read_text())
    assert d["fonctionnement"] == "F1" and d["sante"]["llm"]["modele"] == "faux-3b" and d["fin"]
    assert [r["id"] for r in d["resultats"]] == json.loads((banc / "missions.json").read_text())["selection_rapide"]
    assert all(r["notation"]["note_livrable"] == r["notation"]["note_systeme"] == 100 for r in d["resultats"]), [r["notation"] for r in d["resultats"]]
    statuts = {r["id"]: r["statut"] for r in d["resultats"]}
    assert statuts["BE-28"] == "en_attente_n3" and statuts["BE-01"] == "terminee"
    assert "arrêtée pour validation" in p.stderr
    # Corps envoyés : fonctionnement imposé, pas de service (routage mesuré), jamais la clé.
    assert all(c["fonctionnement"] == "F1" and "service" not in c and c["repli_f3"] for c in serveur.posts)
    assert CLE not in json.dumps(serveur.posts) and CLE not in res.read_text() and CLE not in p.stdout + p.stderr
    assert set(serveur.cles_recues) == {CLE}
    assert os.listdir(env_propre["TMPDIR"]) == []  # fichiers temporaires supprimés (trap)


def test_reprise_conserve_les_resultats(banc, serveur, env_propre, tmp_path):
    res = tmp_path / "r.json"
    v = dict(NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F2", FICHIER_RESULTATS=res)
    assert lancer(banc, env_propre, SELECTION="BE-01,BE-02", **v).returncode == 0
    p = lancer(banc, env_propre, SELECTION="BE-01,BE-02,BE-03", **v)
    assert p.returncode == 0 and "déjà obtenu" in p.stderr
    assert len(serveur.posts) == 3
    assert [r["id"] for r in json.loads(res.read_text())["resultats"]] == ["BE-01", "BE-02", "BE-03"]


def test_reprise_mission_en_cours_sans_recreation(banc, serveur, env_propre, tmp_path):
    mid = serveur.creer({"titre": serveur.definitions and next(t for t, m in serveur.definitions.items()
                                                              if m["id"] == "BE-04"),
                         "projet": "freelance-ia", "fonctionnement": "F3"})
    res = tmp_path / "r.json"
    res.write_text(json.dumps({"fonctionnement": "F3", "resultats": [
        {"id": "BE-04", "titre": "x", "mission_id": mid, "statut": "lancee"}]}))
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F3",
               SELECTION="BE-04", FICHIER_RESULTATS=res)
    assert p.returncode == 0, p.stderr
    assert serveur.posts == [] and "reprise du suivi" in p.stderr
    r = json.loads(res.read_text())["resultats"][0]
    assert r["statut"] == "terminee" and r["service"] == "LEX-GUARD/droit-france"


def test_delai_max_puis_reprise(banc, serveur, env_propre, tmp_path):
    titre = next(t for t, m in serveur.definitions.items() if m["id"] == "BE-05")
    serveur.comportements[titre] = {"jamais_final": True}
    res = tmp_path / "r.json"
    v = dict(NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F1", SELECTION="BE-05",
             FICHIER_RESULTATS=res, DELAI_MAX_S=2)
    p = lancer(banc, env_propre, **v)
    assert p.returncode == 0 and "delai_banc_depasse" in p.stderr
    r = json.loads(res.read_text())["resultats"][0]
    assert r["statut"] == "delai_banc_depasse" and r["notation"]["details"]["obligatoires"] == 0
    serveur.comportements.pop(titre)
    assert lancer(banc, env_propre, **v).returncode == 0
    assert len(serveur.posts) == 1
    assert json.loads(res.read_text())["resultats"][0]["statut"] == "terminee"


def test_f4_refuse_sans_forcer(banc, serveur, env_propre, tmp_path):
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F4",
               FICHIER_RESULTATS=tmp_path / "r.json")
    assert p.returncode != 0 and "PAYANT" in p.stderr and serveur.posts == []


def test_f4_force_attend_la_validation_sans_rien_valider(banc, serveur, env_propre, tmp_path):
    res = tmp_path / "r.json"
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F4", FORCER_F4=1,
               SELECTION="BE-24", DELAI_MAX_S=2, FICHIER_RESULTATS=res)
    assert p.returncode == 0 and "PAYANT" in p.stderr and "cockpit" in p.stderr
    assert serveur.posts[0]["fonctionnement"] == "F4" and serveur.posts[0]["repli_f3"] is False
    assert json.loads(res.read_text())["resultats"][0]["statut"] == "delai_banc_depasse"


def test_fonctionnement_invalide(banc, env_propre):
    p = lancer(banc, env_propre, NEXUS_URL="http://127.0.0.1:9", NEXUS_API_KEY="x", FONCTIONNEMENT="F9")
    assert p.returncode != 0 and "invalide" in p.stderr


def test_cle_lue_dans_env_et_cle_refusee(banc, serveur, env_propre, tmp_path):
    fichier_env = tmp_path / ".env"
    fichier_env.write_text(f"NEXUS_HOST=ignore\nNEXUS_API_KEY=\"{CLE}\"\n")
    res = tmp_path / "r.json"
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, ENV_FILE=fichier_env, SELECTION="BE-24",
               FONCTIONNEMENT="F1", FICHIER_RESULTATS=res)
    assert p.returncode == 0, p.stderr
    fichier_env.write_text("NEXUS_API_KEY=mauvaise\n")
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, ENV_FILE=fichier_env, SELECTION="BE-24",
               FONCTIONNEMENT="F1", FICHIER_RESULTATS=tmp_path / "r2.json")
    assert p.returncode != 0 and "refusée" in p.stderr and "mauvaise" not in p.stderr


def test_mission_inconnue(banc, serveur, env_propre):
    p = lancer(banc, env_propre, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, SELECTION="BE-99")
    assert p.returncode != 0 and "inconnue" in p.stderr


def test_audit_syfer_envoie_le_service_en_f3(banc, env_propre, tmp_path):
    fichier = banc / "audit-syfer" / "missions.json"
    with FauxServeur(str(fichier)) as s:
        res = tmp_path / "a.json"
        p = lancer(banc, env_propre, NEXUS_URL=s.url, NEXUS_API_KEY=CLE, MISSIONS=fichier,
                   SELECTION="SY-01,SY-06", FICHIER_RESULTATS=res)
        assert p.returncode == 0, p.stderr
        assert [c["service"] for c in s.posts] == ["CYBER-FORTRESS/audit", "LEX-GUARD/droit-france"]
        assert all(c["fonctionnement"] == "F3" and c["projet"] == "nexus" for c in s.posts)
        d = json.loads(res.read_text())
        assert d["fonctionnement"] == "F3" and all(r["notation"]["note_livrable"] == r["notation"]["note_systeme"] == 100 for r in d["resultats"])
