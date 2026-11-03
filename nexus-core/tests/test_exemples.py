"""V2 B4 — exemples modèles par service (few-shot borné, anti-secret, charte, retrait)."""
from sqlalchemy import select

from app import exemples, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import Decision

from .conftest import creer_mission, lire_mission

PROPRE = ("BROUILLON — à valider\n## Leçon : la position\nJouer en dernière position donne de l'information. "
          "Le jeu comporte des risques : appelez le 09 74 75 13 13. Réservé aux majeurs.\n")


def _terminee(titre="Leçon", projet="poker-winners", service="CONTENT-ARENA/redaction", livrable=PROPRE):
    FournisseurFactice.script["analyst"].append(livrable)
    mid = creer_mission(titre=titre, consigne="Rédige une leçon", service=service, projet=projet)
    pipeline.traiter(mid)
    return mid


def test_note_au_dessus_du_seuil(client, entetes):
    mid = _terminee()
    assert lire_mission(mid).statut == "terminee"
    assert client.post(f"/api/missions/{mid}/note", headers=entetes, json={"note": 3}).json()["exemple"] is None
    r = client.post(f"/api/missions/{mid}/note", headers=entetes, json={"note": 5}).json()
    assert r["exemple"]["service"] == "CONTENT-ARENA/redaction"
    assert client.get("/api/exemples?service=CONTENT-ARENA/redaction", headers=entetes).json()[0]["note"] == 5


def test_validation_n3_devient_exemple():
    FournisseurFactice.script["analyst"].append("BROUILLON\n## Devis\nPrestation : 2 jours.\n")
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions",
                        projet="freelance-ia")
    pipeline.traiter(mid)
    with session_scope() as s:
        did = s.execute(select(Decision.id).where(Decision.mission_id == mid)).scalar_one()
    pipeline.decider(did, "valider", None)
    assert exemples.lister("REVENUE-CORE/propositions")[0]["origine"] == "validation_n3"


def test_maximum_trois_par_service():
    ids = [_terminee(titre=f"Leçon {i}") for i in range(5)]
    for i, mid in enumerate(ids):
        exemples.proposer(mid, "manuel", manuel=True)
    actifs = exemples.lister("CONTENT-ARENA/redaction")
    assert len(actifs) == 3 and {e["mission_id"] for e in actifs} == set(ids[-3:])  # les plus récents
    assert len(exemples.lister("CONTENT-ARENA/redaction", tous=True)) == 5


def test_injection_bornee_dans_l_analyst():
    for i in range(3):
        exemples.proposer(_terminee(titre=f"Leçon {i}", livrable=PROPRE + "Détail. " * 300), "manuel", manuel=True)
    FournisseurFactice.entrees.clear()
    _terminee(titre="Nouvelle leçon")
    analyste = [e for r, e in FournisseurFactice.entrees if r == "analyst"][0]
    bloc = analyste.split("Exemple validé pour ce service")[1]
    assert "[exemple #" in bloc and len(bloc) <= 1500 + 150


def test_pas_de_melange_de_marques_entre_projets():
    autre = PROPRE.replace("Leçon : la position", "Red Cards et la position")
    mid = _terminee(projet="poker-feeling", livrable=autre)
    exemples.proposer(mid, "manuel", manuel=True)
    assert exemples.pour_analyst("CONTENT-ARENA/redaction", "poker-feeling")  # même projet : oui
    assert exemples.pour_analyst("CONTENT-ARENA/redaction", "poker-winners") == ""  # charte PW : Red Cards interdit


def test_anti_secret_et_charte(client, entetes):
    secret = "sk-" + "Ab1" * 10
    mid = _terminee(service="OPS-CORE/projets", projet="nexus", livrable="BROUILLON\n- Jeton : " + secret)
    assert secret not in lire_mission(mid).livrable_texte  # masqué par le pipeline (tous services)
    from app.db import session_scope
    from app.models import Mission
    with session_scope() as s:  # livrable en clair injecté directement en base : refus anti-secret
        s.get(Mission, mid).livrable_texte = "BROUILLON\n- Jeton : " + secret
    r = client.post(f"/api/missions/{mid}/exemple", headers=entetes)
    assert r.status_code == 422 and "secret" in r.json()["detail"]
    assert exemples.proposer(mid, "note") is None  # automatique : écarté sans erreur


def test_retrait_et_cockpit(client, entetes, cockpit):
    mid = _terminee()
    r = client.post(f"/cockpit/api/missions/{mid}/exemple", json={}, headers=cockpit)
    assert r.status_code == 200
    eid = r.json()["id"]
    assert client.post(f"/api/exemples/{eid}/retirer", headers=entetes).json()["actif"] is False
    assert exemples.pour_analyst("CONTENT-ARENA/redaction", "poker-winners") == ""
