"""Audit 5 — PRIME : score pondéré par le nombre de mots, « code » seul retiré, départage."""
from app import ledger, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Mission

from .conftest import creer_mission


def _service(titre, consigne):
    mid = creer_mission(titre=titre, consigne=consigne)
    with session_scope() as s:
        ctx = pipeline.Contexte(s.get(Mission, mid))
    return pipeline.choisir_service(ctx), mid


def test_code_du_travail_va_au_droit():
    assert _service("Question", "Quelles sont les obligations du code du travail ?")[0] == "LEX-GUARD/droit-france"
    assert _service("Question", "Que dit le code civil sur ce point ?")[0] == "LEX-GUARD/droit-france"


def test_code_seul_ne_route_plus():
    scores = pipeline.scores_services("Note", "Un code couleur pour le planning")
    assert scores["CODE-CORE/revue"] == 0 and scores["OPS-CORE/projets"] > 0
    assert _service("Revue", "Relis ce code source Python")[0] == "CODE-CORE/revue"


def test_ponderation_par_nombre_de_mots():
    scores = pipeline.scores_services("Question", "obligations du code du travail")
    assert scores["LEX-GUARD/droit-france"] == 3  # « code du travail » vaut 3


def test_resume_d_article_va_a_la_veille():
    # « résumé » (veille) et « article » (rédaction) à égalité : le LLM factice ne tranche pas,
    # la priorité explicite place la veille avant la rédaction (résumer un article = synthèse, pas écriture).
    service, mid = _service("Lecture", "Fais le résumé de l'article")
    assert service == "R&D-PARADOX/veille"
    dep = [e for e in ledger.lister(50) if e["action"] == "routage_departage" and e["mission_id"] == mid]
    assert dep and dep[0]["details"]["par"] == "priorite"


def test_departage_par_le_llm_prime():
    FournisseurFactice.script["prime"].append("SERVICE: CONTENT-ARENA/redaction")
    service, mid = _service("Lecture", "Fais le résumé de l'article")
    assert service == "CONTENT-ARENA/redaction"
    dep = [e for e in ledger.lister(50) if e["action"] == "routage_departage" and e["mission_id"] == mid]
    assert dep[0]["details"]["par"] == "llm"


def test_departage_llm_hors_candidats_ignore():
    FournisseurFactice.script["prime"].append("SERVICE: OPS-CORE/projets")  # pas parmi les ex æquo
    assert _service("Lecture", "Fais le résumé de l'article")[0] == "R&D-PARADOX/veille"
