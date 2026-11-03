"""V2 D1 — export QG : résumé court, webhook signé HMAC, file et reprise (faux serveur local)."""
import hashlib
import hmac
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import export_qg, pipeline
from app.db import session_scope
from app.llm import FournisseurFactice
from app.models import ExportQG, maintenant

from .conftest import creer_mission

SECRET = "secret-webhook-de-test"


class Recepteur:
    def __init__(self):
        self.recus, self.code = [], 200
        etat = self

        class G(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                corps = self.rfile.read(int(self.headers["Content-Length"]))
                etat.recus.append({"corps": corps, "entetes": dict(self.headers)})
                self.send_response(etat.code)
                self.end_headers()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), G)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}/qg"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def recepteur(monkeypatch):
    r = Recepteur()
    monkeypatch.setenv("NEXUS_WEBHOOK_QG", r.url)
    monkeypatch.setenv("NEXUS_WEBHOOK_SECRET", SECRET)
    yield r
    r.http.shutdown()


def _mission(livrable="BROUILLON\n## Plan\n" + "Étape importante. " * 80):
    FournisseurFactice.script["analyst"].append(livrable)
    mid = creer_mission(titre="Checklist", consigne="Liste les étapes", service="OPS-CORE/projets", projet="turf")
    pipeline.traiter(mid)
    return mid


def _attendus_echus():
    with session_scope() as s:
        for e in s.query(ExportQG).all():
            e.prochain_essai = maintenant() - timedelta(seconds=1)


def test_envoi_signe_et_resume_court(recepteur):
    mid = _mission()
    assert export_qg.envoyer_en_attente() == {"envoyes": 1, "echecs": 0, "abandonnes": 0}
    r = recepteur.recus[0]
    charge = json.loads(r["corps"])
    assert charge["mission_id"] == mid and charge["projet"] == "turf" and len(charge["resume"]) <= 600
    attendu = "sha256=" + hmac.new(SECRET.encode(), r["entetes"]["X-Nexus-Horodatage"].encode() + b"." + r["corps"],
                                   hashlib.sha256).hexdigest()
    assert hmac.compare_digest(r["entetes"]["X-Nexus-Signature"], attendu)
    assert export_qg.envoyer_en_attente()["envoyes"] == 0  # déjà envoyé : pas de doublon


def test_reprise_apres_echec(recepteur):
    _mission()
    recepteur.code = 500
    assert export_qg.envoyer_en_attente()["echecs"] == 1
    assert export_qg.envoyer_en_attente()["echecs"] == 0  # attente avant le nouvel essai
    recepteur.code = 200
    _attendus_echus()
    assert export_qg.envoyer_en_attente()["envoyes"] == 1 and len(recepteur.recus) == 2


def test_abandon_apres_dix_tentatives(recepteur):
    _mission()
    recepteur.code = 503
    for _ in range(10):
        _attendus_echus()
        export_qg.envoyer_en_attente()
    assert export_qg.etat()["par_statut"] == {"echec": 1}


def test_sans_secret_rien_n_est_envoye(recepteur, monkeypatch):
    monkeypatch.setenv("NEXUS_WEBHOOK_SECRET", "")
    _mission()
    assert export_qg.envoyer_en_attente()["echecs"] == 1 and recepteur.recus == []


def test_secret_masque_dans_le_resume(recepteur):
    _mission("BROUILLON\n- Utiliser le jeton sk-" + "Ab1" * 10)
    export_qg.envoyer_en_attente()
    assert "sk-Ab1" not in recepteur.recus[0]["corps"].decode()


def test_non_configure_rien_en_file():
    _mission()
    assert export_qg.etat() == {"configure": False, "par_statut": {}}


def test_serveur_injoignable(monkeypatch):
    monkeypatch.setenv("NEXUS_WEBHOOK_QG", "http://127.0.0.1:9/qg")
    monkeypatch.setenv("NEXUS_WEBHOOK_SECRET", SECRET)
    _mission()
    assert export_qg.envoyer_en_attente()["echecs"] == 1
