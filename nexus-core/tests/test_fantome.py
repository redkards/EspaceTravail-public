"""Test fantôme avant activation : rejeux sans effet de bord, gain avant/après, nuit, un seul à la fois."""
import json
import threading
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app import archive, exemples, fantome, lecons, ledger, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import ArchiveIndex, Decision, Lecon, Mission

from .conftest import creer_mission

BON = ("BROUILLON\n## Post\nLeçons et quiz pour progresser. Appelez le 09 74 75 13 13. Réservé aux majeurs.")
MAUVAIS = "BROUILLON\n## Post\nRed Cards vous guidera ! Rejoignez la liste d'attente. À COMPLETER"


def _historique(n=3, livrable=BON):
    for i in range(n):
        FournisseurFactice.script["analyst"].append(livrable)
        mid = creer_mission(titre=f"Post {i}", consigne="Rédige un post", service="CONTENT-ARENA/redaction",
                            projet="poker-winners")
        pipeline.traiter(mid)


def _compter(modele, *filtres):
    with session_scope() as s:
        return s.execute(select(func.count(modele.id)).where(*filtres)).scalar_one()


def test_rejeu_sans_effet_de_bord(monkeypatch, tmp_path):
    _historique(2)
    FournisseurFactice.script["analyst"].append(BON)
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="CONTENT-ARENA/redaction",
                        projet="poker-winners")  # N3 réel → 1 décision
    pipeline.traiter(mid)
    decisions, lignes = _compter(Decision), len(archive.lignes())
    lecons_avant, livrables = _compter(Lecon), len(list((tmp_path / "data" / "livrables").rglob("*.md")))
    notifs = []
    monkeypatch.setattr(pipeline, "notifier", lambda *a, **k: notifs.append(a) or True)
    res = fantome.executer({"type": "lecon", "cible": "1", "variante": {"lecon": "Vouvoyez."},
                            "service": "CONTENT-ARENA/redaction", "projet": "poker-winners"})
    assert res["missions"] == 3
    assert _compter(Decision) == decisions and len(archive.lignes()) == lignes and _compter(Lecon) == lecons_avant
    assert len(list((tmp_path / "data" / "livrables").rglob("*.md"))) == livrables  # aucun EXECUTOR
    assert notifs == []
    assert _compter(Mission, Mission.fantome.is_(True), Mission.statut == "fantome") == 6
    assert _compter(Mission, Mission.fantome.is_(True), Mission.statut != "fantome") == 0


def test_rejeux_exclus_des_listes(client, entetes):
    _historique(1)
    fantome.executer({"type": "lecon", "cible": "x", "variante": {}, "service": "CONTENT-ARENA/redaction"})
    ids = [m["id"] for m in client.get("/api/missions", headers=entetes).json()]
    assert len(ids) == 1
    assert len(client.get("/api/missions?statut=fantome", headers=entetes).json()) == 2


def test_gain_favorable_et_deconseille(monkeypatch):
    monkeypatch.setenv("NEXUS_FANTOME_K", "2")
    _historique(2)
    FournisseurFactice.script["analyst"].extend([MAUVAIS, MAUVAIS, MAUVAIS, MAUVAIS, BON, BON])  # avant puis après
    r = fantome.executer({"type": "lecon", "cible": "7", "variante": {"lecon": "Pas de liste d'attente."},
                          "service": "CONTENT-ARENA/redaction", "projet": "poker-winners"})
    assert r["gain"] > 0 and r["verdict"] == "favorable" and r["texte"].startswith("+")
    FournisseurFactice.script["analyst"].extend([BON, BON, MAUVAIS, MAUVAIS, MAUVAIS, MAUVAIS])
    r = fantome.executer({"type": "lecon", "cible": "8", "variante": {"lecon": "x"},
                          "service": "CONTENT-ARENA/redaction", "projet": "poker-winners"})
    assert r["gain"] < 0 and "déconseillé" in r["texte"] and fantome.resultat("lecon", 8)["gain"] == r["gain"]


def test_lecon_defavorable_exige_confirmation(monkeypatch, client, cockpit):
    monkeypatch.setenv("NEXUS_LECONS_SEUIL", "1")
    FournisseurFactice.script["checker"].append(json.dumps({"ok": False, "problemes": ["oubli des responsables"]}))
    mid = creer_mission(titre="Checklist", consigne="Liste", service="OPS-CORE/projets")
    pipeline.traiter(mid)
    lid = lecons.lister("proposee")[0]["id"]
    assert any(j["type"] == "lecon" and j["cible"] == str(lid) for j in fantome.etat()["file"])  # planifié
    from app import sentinel
    sentinel.ecrire(f"fantome:lecon:{lid}", json.dumps({"gain": -8, "missions": 5, "texte": "-8 → déconseillé"}))
    assert lecons.lister("proposee")[0]["fantome"]["gain"] == -8  # joint à la carte
    r = client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit, json={})
    assert r.status_code == 409 and "confirmation explicite" in r.json()["detail"]
    r = client.post(f"/cockpit/api/memoire/lecons/{lid}/accepter", headers=cockpit, json={"confirmation_fantome": True})
    assert r.status_code == 200


def test_exemple_defavorable_retire(monkeypatch):
    monkeypatch.setenv("NEXUS_FANTOME_K", "1")
    _historique(1)
    FournisseurFactice.script["analyst"].append(BON)
    mid = creer_mission(titre="Leçon", consigne="Rédige une leçon", service="CONTENT-ARENA/redaction",
                        projet="poker-winners")
    pipeline.traiter(mid)
    eid = exemples.proposer(mid, "manuel", manuel=True)["id"]
    FournisseurFactice.script["analyst"].extend([BON, MAUVAIS, MAUVAIS])
    r = fantome.executer({"type": "exemple", "cible": str(eid), "variante": {"exemple": "x"},
                          "service": "CONTENT-ARENA/redaction", "projet": "poker-winners"})
    assert r["gain"] < 0 and exemples.lister("CONTENT-ARENA/redaction") == []


def test_fenetre_de_nuit_et_un_seul_a_la_fois(monkeypatch):
    lance, libere = threading.Event(), threading.Event()

    def lent(job):
        with fantome._verrou_execution:
            lance.set()
            libere.wait(5)
    monkeypatch.setattr(fantome, "executer", lent)
    fantome.planifier("modeles", "a", {"modeles_roles": "checker=x"}, "OPS-CORE/projets")
    fantome.planifier("modeles", "b", {"modeles_roles": "checker=y"}, "OPS-CORE/projets")
    assert fantome.tick(datetime(2026, 11, 4, 11, 0)) is None  # 12:00 Paris : hors fenêtre
    assert fantome.tick(datetime(2026, 11, 4, 1, 0))["cible"] == "a"  # 02:00 Paris
    assert lance.wait(5)
    assert fantome.tick(datetime(2026, 11, 4, 1, 1)) is None  # un test tourne déjà
    libere.set()
    for _ in range(50):
        if not fantome._verrou_execution.locked():
            break
        threading.Event().wait(0.05)
    assert fantome.tick(datetime(2026, 11, 4, 1, 2))["cible"] == "b"


def test_planification_dedoublonnee_et_cockpit(client, cockpit):
    fantome.planifier("lecon", 3, {"lecon": "x"}, "S")
    fantome.planifier("lecon", 3, {"lecon": "y"}, "S")
    assert len(fantome.etat()["file"]) == 1
    r = client.post("/cockpit/api/memoire/fantome", headers=cockpit,
                    json={"type": "modeles", "valeur": "checker=gpt-oss:120b", "service": "OPS-CORE/projets"})
    assert r.status_code == 200 and len(client.get("/cockpit/api/memoire/fantome", headers=cockpit).json()["file"]) == 2


def test_modeles_par_role_surcharge_locale_au_fil():
    from app import surcharges
    from app.llm import modeles_roles
    with surcharges.appliquer(modeles_roles="checker=modele-candidat"):
        assert modeles_roles("ollama")["checker"] == "modele-candidat"
    assert "checker" not in modeles_roles("ollama")
