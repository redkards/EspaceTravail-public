"""V2 B2 — charte par projet contrôlée par du code (dont le cas réel du VPS)."""
import json

import pytest

from app import charte, ledger, pipeline, projets
from app.llm import FournisseurFactice

from .conftest import creer_mission, lire_mission

# Cas réel constaté sur le VPS (modèle 3B) : marques mélangées, « À COMPLETER », liste d'attente inventée.
CAS_REEL = """BROUILLON — à valider
## Rejoignez la communauté Poker Winners !
Red Cards vous guidera pas à pas dans vos premières mains.
Inscrivez-vous dès maintenant sur notre liste d'attente : places limitées !
Date d'ouverture : À COMPLETER"""
CORRIGE = """BROUILLON — à valider
## Rejoignez la communauté Poker Winners
Leçons, quiz et tableaux de ranges pour progresser à votre rythme, en vous amusant.
Le jeu comporte des risques : endettement, dépendance. Appelez le 09 74 75 13 13 (appel non surtaxé).
Réservé aux majeurs."""


def test_cas_reel_bloque():
    r = charte.verifier("poker-winners", "CONTENT-ARENA/redaction", CAS_REEL)
    texte = " ".join(r["bloquants"])
    assert r["type"] == "publication"
    assert "Red Cards" in texte and "liste d'attente" in texte and "À COMPLETER" not in texte  # message normalisé
    assert "inachevé" in texte and "09 74 75 13 13" in texte and "reserve aux majeurs" in texte
    assert len(r["bloquants"]) >= 5


def test_version_corrigee_acceptee():
    r = charte.verifier("poker-winners", "CONTENT-ARENA/redaction", CORRIGE)
    assert r["bloquants"] == []


def test_pipeline_bloque_puis_corrige():
    FournisseurFactice.script["analyst"].extend([CAS_REEL, CORRIGE])
    mid = creer_mission(titre="Post d'accueil", consigne="Rédige un post d'accueil pour le site",
                        service="CONTENT-ARENA/redaction", projet="poker-winners")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.revisions == 1 and "Red Cards" not in m.livrable_texte
    correction = [e for r, e in FournisseurFactice.entrees if r == "analyst"][1]
    assert "[charte]" in correction and "Red Cards" in correction and "liste d'attente" in correction
    premier = [e for r, e in FournisseurFactice.entrees if r == "analyst"][0]
    assert "Charte du projet (obligatoire)" in premier and "Ne citez pas : Red Cards" in premier
    assert any(e["details"].get("source") == "charte" for e in ledger.lister(100))
    # Le CHECKER (LLM) n'a été appelé que sur la version conforme.
    assert all("Red Cards vous guidera" not in e for r, e in FournisseurFactice.entrees if r == "checker")


def test_pipeline_cas_reel_jamais_publie_si_non_corrige():
    FournisseurFactice.script["analyst"].extend([CAS_REEL] * 3)
    mid = creer_mission(titre="Post", consigne="Rédige un post", service="CONTENT-ARENA/redaction",
                        projet="poker-winners")
    pipeline.traiter(mid)
    assert lire_mission(mid).statut in ("a_reformuler", "echouee")


def test_red_cards_permis_dans_poker_feeling():
    texte = CORRIGE.replace("Poker Winners", "Poker Feeling") + "\nRed Cards, notre fil rouge, apprend à décider."
    assert charte.verifier("poker-feeling", "CONTENT-ARENA/redaction", texte)["bloquants"] == []


def test_inacheve_avertissement_hors_publication():
    r = charte.verifier("poker-winners", "OPS-CORE/projets", "Checklist :\n- Prix Premium : À COMPLÉTER")
    assert r["bloquants"] == [] and any("inachevé" in a for a in r["avertissements"])
    for marqueur in ("TODO : finir", "[à remplir]", "Lorem ipsum dolor", "XXX"):
        assert charte.verifier("nexus", "CONTENT-ARENA/redaction", marqueur)["bloquants"], marqueur


def test_mention_juridique_et_ton():
    r = charte.verifier("freelance-ia", "LEX-GUARD/conformite", "Note : RGPD applicable.")
    assert any("avocat" in b for b in r["bloquants"])
    r = charte.verifier("poker-feeling", "OPS-CORE/projets", "Tu dois lire ton chapitre et tu progresses.")
    assert any("vouvoiement" in a for a in r["avertissements"])
    assert not charte.verifier("redkards", "CONTENT-ARENA/redaction", "Tu bluffes ? Ton tapis !")["avertissements"]


def test_circuit_reel_interdit_dans_redkards():
    r = charte.verifier("redkards", "CONTENT-ARENA/redaction", "Red Cards arrive aux WSOP de Las Vegas.")
    assert any("circuit" in b for b in r["bloquants"])


def test_negation_et_numero_tolerant():
    r = charte.verifier("poker-winners", "CONTENT-ARENA/redaction",
                        "Aucune liste d'attente. Joueurs Info Service : 0974751313. Interdit aux moins de 18 ans.")
    assert r["bloquants"] == []


def test_avertissements_notes_pour_checker_et_decideur(client, cockpit):
    texte = CORRIGE + "\nBientôt une offre Premium."
    FournisseurFactice.script["analyst"].append(texte)
    mid = creer_mission(titre="Annonce", consigne="Rédige une annonce publique", service="CONTENT-ARENA/redaction",
                        projet="poker-winners", montant_eur=1500)  # N3 → carte Décideur
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert any("premium" in a for a in json.loads(m.charte_avertissements))
    checker = [e for r, e in FournisseurFactice.entrees if r == "checker"][0]
    assert "Avertissements de la charte" in checker
    carte = client.get("/cockpit/api/decideur/etat", headers=cockpit).json()["cartes"][0]
    assert any("premium" in a for a in carte["avertissements"])


def test_surcharge_et_alias(tmp_path, monkeypatch):
    assert projets.resoudre("syfer") == "nexus" and charte.charger("syfer")["projet"] == "nexus"
    (tmp_path / "nexus.yaml").write_text("termes_interdits:\n  - {terme: kraken, gravite: bloquant, motif: test}\n",
                                         encoding="utf-8")
    monkeypatch.setenv("NEXUS_CHARTES_DIR", str(tmp_path))
    assert charte.verifier("syfer", "OPS-CORE/projets", "Le kraken arrive.")["bloquants"]


@pytest.mark.parametrize("code", ["poker-winners", "poker-feeling", "redkards", "top-solver", "nexus", "freelance-ia"])
def test_chartes_de_depart(code):
    c = charte.charger(code)
    assert c["marque"]["nom"] and c["termes_interdits"] and c["inacheve"]["marqueurs"]
    assert charte.consignes_courtes(code, "CONTENT-ARENA/redaction") and len(charte.consignes_courtes(code, None)) <= 600
