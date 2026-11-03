"""Audit 8 — LEDGER chaîné en HMAC-SHA256 (LEDGER_HMAC_KEY)."""
import hashlib
import json

from sqlalchemy import select

from app import ledger
from app.db import session_scope
from app.models import Ledger

CLE = "cle-hmac-de-test-" + "0" * 20


def test_sans_cle_avertissement_et_sha256(client):
    ledger.journaliser("TEST", "a")
    assert ledger.lister(1)[0]["algo"] == "sha256" and ledger.verifier()["valide"]
    sante = client.get("/api/sante").json()
    assert sante["ledger_hmac"] is False and "LEDGER_HMAC_KEY absente" in sante["avertissements"][0]


def test_avec_cle_hmac_valide(client, entetes, monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    for i in range(3):
        ledger.journaliser("TEST", f"a{i}", None, i=i)
    v = client.get("/api/ledger/verifier", headers=entetes).json()
    assert v["valide"] and v["hmac_actif"] and v["entrees_signees"] >= 3
    assert client.get("/api/sante").json()["avertissements"] == []


def test_reecriture_sans_cle_detectee(monkeypatch):
    """Un attaquant qui modifie une ligne et recalcule le SHA-256 « classique » est détecté."""
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    for i in range(3):
        ledger.journaliser("TEST", f"a{i}", None, i=i)
    with session_scope() as s:
        lignes = s.execute(select(Ledger).order_by(Ledger.id)).scalars().all()
        cible = lignes[1]
        cible.details_json = json.dumps({"i": 999})
        charge = ledger._charge(cible.horodatage, cible.acteur, cible.action, cible.mission_id,
                                cible.details_json, cible.hash_prec)
        cible.hash = hashlib.sha256(charge).hexdigest()  # recalcul sans la clé
        cid = cible.id
    v = ledger.verifier()
    assert not v["valide"] and v["premiere_erreur"] == cid


def test_declassement_vers_sha256_refuse(monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    ledger.journaliser("TEST", "signee")
    monkeypatch.delenv("LEDGER_HMAC_KEY")
    ledger.journaliser("TEST", "non_signee")  # écrite sans clé après une entrée signée
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    v = ledger.verifier()
    assert not v["valide"] and "déclassement" in v["motif"]


def test_mauvaise_cle_detectee(monkeypatch):
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    ledger.journaliser("TEST", "a")
    monkeypatch.setenv("LEDGER_HMAC_KEY", "une-autre-cle-" + "1" * 20)
    assert not ledger.verifier()["valide"]
    monkeypatch.delenv("LEDGER_HMAC_KEY")
    v = ledger.verifier()
    assert not v["valide"] and "vérification impossible" in v["motif"]


def test_passage_sha256_vers_hmac_accepte(monkeypatch):
    ledger.journaliser("TEST", "ancienne")  # journal existant sans clé
    monkeypatch.setenv("LEDGER_HMAC_KEY", CLE)
    ledger.journaliser("TEST", "nouvelle")
    v = ledger.verifier()
    assert v["valide"] and v["entrees_signees"] >= 1 and v["entrees_non_signees"] >= 1
