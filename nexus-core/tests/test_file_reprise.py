"""Audit 3 — reprise au redémarrage et file FIFO bornée (NEXUS_MAX_MISSIONS)."""
import threading

from app import file_missions, ledger, pipeline
from app.file_missions import FileMissions

from .conftest import creer_mission, lire_mission


def test_capacite_par_defaut(monkeypatch):
    assert file_missions.capacite() == 1  # modèle local (ici factice)
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", "cle-test")
    assert file_missions.capacite() == 2
    monkeypatch.setenv("NEXUS_MAX_MISSIONS", "3")
    assert file_missions.capacite() == 3


def test_file_fifo_et_statut_en_attente_de_place(monkeypatch):
    monkeypatch.setenv("NEXUS_MAX_MISSIONS", "1")
    file = FileMissions()
    ordre, libere = [], threading.Event()
    debut = threading.Event()

    def travail(mid):
        ordre.append(mid)
        pipeline.transition(mid, ("recue", "en_attente_place"), "en_cours")
        if len(ordre) == 1:
            debut.set()
            libere.wait(10)
        pipeline.transition(mid, ("en_cours",), "terminee")

    ids = [creer_mission(titre=f"M{i}", consigne="Liste les étapes") for i in range(3)]
    file.soumettre(ids[0], travail)
    assert debut.wait(5)
    file.soumettre(ids[1], travail)
    file.soumettre(ids[2], travail)
    for _ in range(50):  # les deux suivantes passent en attente de place
        if all(lire_mission(m).statut == "en_attente_place" for m in ids[1:]):
            break
        threading.Event().wait(0.05)
    assert lire_mission(ids[1]).statut == "en_attente_place" and "position 1" in lire_mission(ids[1]).message
    assert lire_mission(ids[2]).statut == "en_attente_place" and "position 2" in lire_mission(ids[2]).message
    assert file.etat()["en_cours"] == [ids[0]]
    libere.set()
    assert file.attendre_vide(10)
    assert ordre == ids  # FIFO
    assert all(lire_mission(m).statut == "terminee" for m in ids)


def test_jamais_plus_que_la_capacite(monkeypatch):
    monkeypatch.setenv("NEXUS_MAX_MISSIONS", "2")
    file = FileMissions()
    verrou, courant, maxi = threading.Lock(), [0], [0]

    def travail(mid):
        with verrou:
            courant[0] += 1
            maxi[0] = max(maxi[0], courant[0])
        threading.Event().wait(0.05)
        with verrou:
            courant[0] -= 1
    for i in range(6):
        file.soumettre(creer_mission(titre=f"M{i}", consigne="x"), travail)
    assert file.attendre_vide(10) and maxi[0] == 2


def test_reprise_au_demarrage():
    interrompue = creer_mission(titre="A", consigne="Liste les étapes", service="OPS-CORE/projets",
                                statut="en_cours")
    en_attente = creer_mission(titre="B", consigne="Liste les étapes", service="OPS-CORE/projets",
                               statut="en_attente_place")
    recue = creer_mission(titre="C", consigne="Liste les étapes", service="OPS-CORE/projets")
    decision = creer_mission(titre="D", consigne="x", statut="en_attente_n3")
    res = pipeline.reprendre_au_demarrage()
    assert res == {"interrompues": [interrompue], "relancees": [en_attente, recue]}
    assert file_missions.FILE.attendre_vide(10)
    m = lire_mission(interrompue)
    assert m.statut == "echouee" and "interrompue par un redémarrage" in m.message and "relancer" in m.message
    assert lire_mission(en_attente).statut == "terminee" and lire_mission(recue).statut == "terminee"
    assert lire_mission(decision).statut == "en_attente_n3"  # inchangée
    actions = [e["action"] for e in ledger.lister(300)]
    assert "mission_interrompue_redemarrage" in actions and actions.count("mission_reprise_redemarrage") == 2


def test_reprise_lancee_par_le_demarrage_de_l_application(monkeypatch):
    mid = creer_mission(titre="A", consigne="x", statut="en_cours")
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app):
        pass
    assert lire_mission(mid).statut == "echouee"
