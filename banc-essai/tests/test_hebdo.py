"""B5 : hebdo.sh (bout en bout contre le faux serveur), tableau.py (cumul) et tableau.html (autonome)."""
import json
import re
import shutil
import subprocess

import pytest

from faux_serveur import CLE, FauxServeur


@pytest.fixture
def serveur(banc):
    with FauxServeur(str(banc / "missions.json")) as s:
        yield s


def hebdo(banc, env, tmp_path, timeout=180, **variables):
    e = dict(env)
    e.update(RESULTATS_DIR=str(tmp_path / "res"))
    e.update({k: str(v) for k, v in variables.items()})
    return subprocess.run(["bash", str(banc / "hebdo.sh")], env=e, cwd=str(banc), capture_output=True, text=True,
                          timeout=timeout)


def test_syntaxe_et_cron(banc):
    assert subprocess.run(["bash", "-n", str(banc / "hebdo.sh")]).returncode == 0
    texte = (banc / "hebdo.sh").read_text()
    assert "17 4 * * 0 root /srv/p1/nexus-mothership/banc-essai/hebdo.sh" in texte
    if shutil.which("shellcheck"):
        assert subprocess.run(["shellcheck", "-S", "warning", str(banc / "hebdo.sh")]).returncode == 0


def test_local_f1_puis_cumul(banc, serveur, env_propre, tmp_path):
    v = dict(NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE)
    p = hebdo(banc, env_propre, tmp_path, SEMAINE="2026-W44", **v)
    assert p.returncode == 0, p.stderr
    assert "→ niveau F1" in p.stderr  # fournisseur non cloud → F1
    res = tmp_path / "res"
    assert (res / "hebdo" / "2026-W44_F1.json").is_file()
    assert (res / "hebdo" / "rapport_hebdo-2026-W44.md").is_file()
    assert all(c["fonctionnement"] == "F1" for c in serveur.posts) and len(serveur.posts) == 8  # sélection rapide
    t = json.loads((res / "tableau.json").read_text())
    assert [s["semaine"] for s in t["semaines"]] == ["2026-W44"]
    s = t["semaines"][0]
    for cle in ("note_livrable", "note_systeme", "pieges", "tokens_moyens", "duree_mediane_s", "taux_n3", "modele"):
        assert cle in s, cle
    assert s["note_livrable"] == 100 and s["fonctionnement"] == "F1" and s["modele"].startswith("faux / faux-3b")
    assert s["taux_n3"] > 0 and s["tokens_moyens"] == 1000 and s["duree_mediane_s"] == 12.5
    # Semaine suivante, cloud détecté → F2 ; le tableau cumule.
    serveur.fournisseur = "ollama_cloud"
    p = hebdo(banc, env_propre, tmp_path, SEMAINE="2026-W45", **v)
    assert p.returncode == 0, p.stderr
    t = json.loads((res / "tableau.json").read_text())
    assert [(s["semaine"], s["fonctionnement"]) for s in t["semaines"]] == [("2026-W44", "F1"), ("2026-W45", "F2")]
    # Relance la même semaine : rien de recréé, ligne remplacée (pas de doublon).
    n = len(serveur.posts)
    p = hebdo(banc, env_propre, tmp_path, SEMAINE="2026-W45", **v)
    assert p.returncode == 0 and len(serveur.posts) == n
    assert len(json.loads((res / "tableau.json").read_text())["semaines"]) == 2
    assert CLE not in (res / "tableau.json").read_text() + (res / "hebdo.log").read_text()


def test_refus_f4_et_erreurs(banc, serveur, env_propre, tmp_path):
    p = hebdo(banc, env_propre, tmp_path, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, FONCTIONNEMENT="F4")
    assert p.returncode == 1 and "payant" in p.stderr and serveur.posts == []
    p = hebdo(banc, env_propre, tmp_path, NEXUS_URL="http://127.0.0.1:9", NEXUS_API_KEY=CLE)
    assert p.returncode == 2 and "injoignable" in p.stderr
    p = hebdo(banc, env_propre, tmp_path, NEXUS_URL=serveur.url, SEMAINE="45")
    assert p.returncode == 1


def test_echec_du_banc_ne_touche_pas_le_tableau(banc, serveur, env_propre, tmp_path):
    faux = tmp_path / "lanceur.sh"
    faux.write_text("#!/usr/bin/env bash\necho boum >&2\nexit 3\n")
    p = hebdo(banc, env_propre, tmp_path, NEXUS_URL=serveur.url, NEXUS_API_KEY=CLE, LANCEUR=faux)
    assert p.returncode == 2 and "code 3" in p.stderr
    assert not (tmp_path / "res" / "tableau.json").exists()


def test_tableau_fusion_et_tri(tmp_path):
    import tableau
    t = {"semaines": [{"semaine": "2026-W46", "x": 1}, {"semaine": "2026-W44", "x": 1}]}
    t = tableau.fusionner(t, {"semaine": "2026-W45", "x": 2})
    t = tableau.fusionner(t, {"semaine": "2026-W46", "x": 3})
    assert [(s["semaine"], s["x"]) for s in t["semaines"]] == [("2026-W44", 1), ("2026-W45", 2), ("2026-W46", 3)]
    assert re.fullmatch(r"\d{4}-W\d{2}", tableau.semaine_iso())
    mauvais = tmp_path / "t.json"
    mauvais.write_text("[]")
    with pytest.raises(ValueError):
        tableau.charger_tableau(str(mauvais))


def test_tableau_html_autonome(banc):
    h = (banc / "tableau.html").read_text()
    # Aucune ressource externe : pas d'URL http(s) chargée, pas de <link>, pas de script src.
    assert not re.search(r"""(src|href)\s*=\s*["']?https?:""", h)
    assert "<link" not in h and "<script src" not in h and "@import" not in h
    assert "fetch(url" in h and '"tableau.json"' in h
    assert "prefers-color-scheme: dark" in h and 'data-theme="dark"' in h
    assert 'role: "img"' in h and "aria-label" in h and "<table" in h
    assert "innerHTML" not in h  # données insérées par textContent uniquement
    js = h.split("<script>")[1].split("</script>")[0]
    if shutil.which("node"):
        f = banc / "resultats" / ".tableau-syntaxe.js"
        try:
            f.write_text(js)
            assert subprocess.run(["node", "--check", str(f)], capture_output=True).returncode == 0
        finally:
            f.unlink(missing_ok=True)
