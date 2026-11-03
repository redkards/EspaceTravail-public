"""Audit 2 — écritures atomiques : décisions, transitions de mission, compteurs."""
import threading

from sqlalchemy import select

from app import ledger, pipeline, sentinel
from app.db import session_scope
from app.models import Decision

from .conftest import creer_mission, lire_mission


def _en_parallele(n, fonction):
    depart = threading.Barrier(n)
    resultats, erreurs = [], []

    def tache(i):
        depart.wait()
        try:
            resultats.append(fonction(i))
        except Exception as e:  # noqa: BLE001 — on compte les refus
            erreurs.append(e)
    fils = [threading.Thread(target=tache, args=(i,)) for i in range(n)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(60)
    return resultats, erreurs


def _decision_en_attente():
    mid = creer_mission(titre="Devis", consigne="Rédige un devis", service="REVENUE-CORE/propositions")
    pipeline.traiter(mid)
    with session_scope() as s:
        return mid, s.execute(select(Decision.id).where(Decision.statut == "en_attente")).scalar_one()


def test_une_seule_decision_gagne():
    mid, did = _decision_en_attente()
    choix = ["valider", "refuser"] * 4
    ok, refus = _en_parallele(8, lambda i: pipeline.decider(did, choix[i], f"fil {i}"))
    assert len(ok) == 1 and len(refus) == 7
    assert all(isinstance(e, PermissionError) for e in refus)
    gagnant = ok[0]["statut"]
    with session_scope() as s:
        assert s.get(Decision, did).statut == gagnant
    assert lire_mission(mid).statut == gagnant
    assert [e["action"] for e in ledger.lister(200)].count(f"decision_{gagnant}") == 1


def test_decision_et_expiration_concurrentes():
    from datetime import timedelta
    from app.models import maintenant
    mid, did = _decision_en_attente()
    with session_scope() as s:
        s.get(Decision, did).cree_le = maintenant() - timedelta(hours=48)
    ok, refus = _en_parallele(2, lambda i: pipeline.decider(did, "valider", None) if i == 0
                              else pipeline.expirer_decisions())
    with session_scope() as s:
        statut = s.get(Decision, did).statut
    assert statut in ("validee", "expiree")
    assert lire_mission(mid).statut == ("validee" if statut == "validee" else "refusee")


def test_mission_traitee_une_seule_fois():
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets")
    _en_parallele(4, lambda i: pipeline.traiter(mid))
    assert lire_mission(mid).statut == "terminee"
    actions = [e["action"] for e in ledger.lister(500) if e["mission_id"] == mid]
    assert actions.count("routage") == 1 and actions.count("mission_deja_prise") == 3


def test_compteur_exact_sous_concurrence():
    _en_parallele(20, lambda i: [sentinel.incrementer("budget:test:tokens", 1) for _ in range(25)])
    assert float(sentinel.lire("budget:test:tokens")) == 500
    _en_parallele(10, lambda i: [sentinel.incrementer("budget:test:eur", 0.01) for _ in range(10)])
    assert abs(float(sentinel.lire("budget:test:eur")) - 1.0) < 1e-9
    assert sentinel.incrementer("nouvelle:cle", 2.5) == 2.5
