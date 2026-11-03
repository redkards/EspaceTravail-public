"""Nouveaux services : conception, design, droit FR/UE/international, pilotage, environnement, RSE."""
import pytest

from app import agents as reg
from app import gate, pipeline, projets
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Mission

from .conftest import creer_mission, lire_mission

NOUVEAUX = ["CODE-CORE/conception", "DESIGN-SYSTEM/ui", "LEX-GUARD/droit-france", "LEX-GUARD/droit-europe",
            "LEX-GUARD/droit-international", "PILOT-CORE/etudes", "PILOT-CORE/pilotage",
            "GREEN-CORE/environnement", "GREEN-CORE/rse"]
AVOCAT = "Information générale, ne remplace pas l'avis d'un avocat"


def test_93_agents_et_nouvelle_direction():
    tous = reg.charger()
    assert len(tous) == 93
    assert tous["DIR-IMPACT"]["role"] == "directeur" and tous["DIR-IMPACT"]["direction"] == "IMPACT"
    s = reg.services()
    for srv in NOUVEAUX:
        assert {"collector", "analyst", "checker", "executor"} <= set(s[srv]), srv
    assert s["GREEN-CORE/rse"]["directeur"] == "DIR-IMPACT"
    assert s["PILOT-CORE/etudes"]["directeur"] == "DIR-OPERATIONS"
    assert s["LEX-GUARD/droit-france"]["directeur"] == "DIR-STRATEGIE"
    assert tous["PILOT-CORE-ETUDES-ANALYST"]["departement"] == "Pilotage"
    assert tous["GREEN-CORE-RSE-CHECKER"]["departement"] == "Environnement"


def test_consignes_juridiques_et_checker_json():
    for srv in ("france", "europe", "international"):
        p = f"LEX-GUARD-DROIT-{srv.upper()}"
        analyst = reg.agent(f"{p}-ANALYST")["consignes"]
        assert AVOCAT in analyst and "N'invente JAMAIS de jurisprudence" in analyst
        checker = reg.agent(f"{p}-CHECKER")["consignes"]
        assert "{\"ok\": true, \"problemes\": []}" in checker and "vérifiable" in checker
    assert "HYPOTHÈSE" in reg.agent("PILOT-CORE-ETUDES-ANALYST")["consignes"]
    assert "greenwashing" in reg.agent("GREEN-CORE-RSE-CHECKER")["consignes"]


def _service(titre, consigne):
    mid = creer_mission(titre=titre, consigne=consigne)
    with session_scope() as s:
        ctx = pipeline.Contexte(s.get(Mission, mid))
    return pipeline.choisir_service(ctx)


@pytest.mark.parametrize("titre,consigne,attendu", [
    ("Solver", "Propose l'architecture et le choix de stack du moteur", "CODE-CORE/conception"),
    ("Écran", "Décris les wireframes et le parcours utilisateur de l'inscription", "DESIGN-SYSTEM/ui"),
    ("Jeux", "Quelles règles de l'ANJ s'appliquent à un site de poker gratuit ?", "LEX-GUARD/droit-france"),
    ("Plateforme", "Quelles obligations du DSA pour une plateforme de forum ?", "LEX-GUARD/droit-europe"),
    ("Export", "Compare les juridictions pour exporter l'application hors UE", "LEX-GUARD/droit-international"),
    ("Lancement", "Fais l'étude de marché et le prévisionnel de l'activité", "PILOT-CORE/etudes"),
    ("Mensuel", "Prépare le tableau de bord et les OKR du trimestre", "PILOT-CORE/pilotage"),
    ("Serveur", "Évalue l'empreinte carbone et la sobriété numérique du VPS", "GREEN-CORE/environnement"),
    ("Démarche", "Propose une démarche RSE et d'éco-conception", "GREEN-CORE/rse"),
])
def test_routage_nouveaux_services(titre, consigne, attendu):
    assert _service(titre, consigne) == attendu


def test_routage_existant_intact():
    assert _service("Revue", "Relis ce code PYTHON") == "CODE-CORE/revue"
    assert _service("Conformité", "Vérifie la CONFORMITÉ RGPD") == "LEX-GUARD/conformite"
    assert _service("Démarrage", "Rédige une checklist de démarrage") == "OPS-CORE/projets"


# --- GATE ------------------------------------------------------------------------

@pytest.mark.parametrize("srv", ["LEX-GUARD/droit-france", "LEX-GUARD/droit-europe", "LEX-GUARD/droit-international"])
def test_gate_droit_minimum_n2_et_n3_pour_tiers(srv):
    assert gate.classer("Question", "Quelle règle s'applique au statut ?", service=srv)[0] == "N2"
    # Même une « synthèse » juridique ne descend pas sous N2.
    assert gate.classer("Synthèse", "Fais une synthèse interne", service=srv)[0] == "N2"
    assert gate.classer("CGV", "Rédige les CGV du site", service=srv)[0] == "N3"
    assert gate.classer("Note", "Note à remettre au client", service=srv)[0] == "N3"
    assert gate.classer("Note", "Analyse du contrat de licence", service=srv)[0] == "N3"
    assert gate.classer("Q", "Question", service=srv, niveau_llm="N0")[0] == "N2"


def test_gate_pilotage_engagement_n3():
    for srv in ("PILOT-CORE/etudes", "PILOT-CORE/pilotage"):
        assert gate.classer("Étude", "Étude de marché du coaching", service=srv)[0] in ("N0", "N1")
        assert gate.classer("Décision", "Faut-il investir 5 000 € dans du matériel ?", service=srv)[0] == "N3"
        assert gate.classer("RH", "Prévoir de recruter un développeur", service=srv)[0] == "N3"
        assert gate.classer("Prêt", "Comparer un emprunt bancaire", service=srv)[0] == "N3"


def test_gate_rse_publication_externe_n3():
    assert gate.classer("RSE", "Propose une démarche RSE interne", service="GREEN-CORE/rse")[0] != "N3"
    assert gate.classer("RSE", "Rédige la communication RSE pour le site web",
                        service="GREEN-CORE/rse")[0] == "N3"
    assert gate.classer("RSE", "Slogan éco pour la campagne", service="GREEN-CORE/rse")[0] == "N3"
    assert gate.classer("Énergie", "Mesure la consommation du serveur",
                        service="GREEN-CORE/environnement")[0] in ("N0", "N1")


# --- Mention juridique dans la sortie (LLM factice) -------------------------------

def test_mention_avocat_dans_sortie_juridique():
    # Le modèle « oublie » la mention : le pipeline l'ajoute avant contrôle et livraison.
    FournisseurFactice.script["analyst"].append("BROUILLON — à valider\n## Question\nStatut ANJ d'un site gratuit.")
    mid = creer_mission(titre="ANJ", consigne="Quelles règles ANJ pour un site de poker gratuit ?",
                        service="LEX-GUARD/droit-france")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.niveau == "N2" and m.statut == "terminee"
    assert m.livrable_texte.rstrip().endswith(AVOCAT + ".")
    assert AVOCAT in [e for r, e in FournisseurFactice.entrees if r == "checker"][0]


def test_mention_non_dupliquee_et_absente_hors_droit():
    texte = f"Note.\n\n{AVOCAT}."
    assert pipeline.garantir_mention_juridique("LEX-GUARD/droit-europe", texte) == texte
    assert pipeline.garantir_mention_juridique("CODE-CORE/conception", "x") == "x"


def test_projets_services_conseilles_valides():
    srv = reg.services()
    reg_p = projets.charger(recharger=True)
    for p in reg_p.values():
        assert all(s in srv for s in p["services"]), p["code"]
    assert "LEX-GUARD/droit-france" in reg_p["poker-winners"]["services"]
    assert "PILOT-CORE/etudes" in reg_p["freelance-ia"]["services"]
    assert "CODE-CORE/conception" in reg_p["top-solver"]["services"]
    assert "DESIGN-SYSTEM/ui" in reg_p["redkards"]["services"]
    assert "DESIGN-SYSTEM/ui" in reg_p["poker-feeling"]["services"]


def test_organigramme_api_expose_la_nouvelle_direction(client, cockpit):
    agents = client.get("/cockpit/api/agents", headers=cockpit).json()
    assert len(agents) == 93
    directions = {a["direction"] for a in agents}
    assert "IMPACT" in directions
    services = {a["service"] for a in agents if a["service"]}
    assert set(NOUVEAUX) <= services


# --- Audit 6 : tout LEX-GUARD/ (conformité incluse) ---------------------------------

def test_conformite_plancher_n2_et_mention():
    assert gate.classer("Synthèse", "Fais une synthèse interne", service="LEX-GUARD/conformite")[0] == "N2"
    assert gate.classer("CGV", "Relis les CGV du site", service="LEX-GUARD/conformite")[0] == "N3"
    FournisseurFactice.script["analyst"].append("BROUILLON — à valider\n## Résumé\nRGPD : registre à tenir.")
    mid = creer_mission(titre="RGPD", consigne="Fais une synthèse interne RGPD", service="LEX-GUARD/conformite")
    pipeline.traiter(mid)
    m = lire_mission(mid)
    assert m.niveau == "N2" and m.livrable_texte.rstrip().endswith(AVOCAT + ".")


def test_checkers_juridiques_controle_de_forme():
    for f in ("LEX-GUARD-CHECKER", "LEX-GUARD-DROIT-FRANCE-CHECKER", "LEX-GUARD-DROIT-EUROPE-CHECKER",
              "LEX-GUARD-DROIT-INTERNATIONAL-CHECKER"):
        c = reg.agent(f)["consignes"]
        assert "FORME" in c and "sections attendues" in c and "référence à vérifier" in c and AVOCAT in c
        assert "est-elle exacte" not in c and "exactitude du droit" in c
    analyste = reg.agent("LEX-GUARD-ANALYST")["consignes"]
    assert AVOCAT in analyste and "N'invente JAMAIS de jurisprudence" in analyste
