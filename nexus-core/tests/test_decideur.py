"""Amélioration 2 — Décideur mobile : page, sessions, notifications, risque, confirmation, code."""
import json
import re
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import decideur, ledger, pipeline, sentinel
from app.db import session_scope
from app.models import Decision

from .conftest import COCKPIT_INTERNE, creer_mission

CODE = "482913"


@pytest.fixture
def ntfy(monkeypatch):
    """Capture les notifications ntfy (aucun réseau)."""
    monkeypatch.setenv("NTFY_URL", "http://ntfy.test")
    monkeypatch.setenv("NTFY_TOPIC", "nexus-test")
    envoyees = []
    vrai_post = httpx.post

    def faux_post(url, *a, **k):
        if url.startswith("http://ntfy.test"):
            envoyees.append({"url": url, "corps": k.get("content", b"").decode(), "entetes": k.get("headers", {})})
            return httpx.Response(200, request=httpx.Request("POST", url))
        return vrai_post(url, *a, **k)
    monkeypatch.setattr(httpx, "post", faux_post)
    return envoyees


def _decision(titre="Devis secret client Dupont", consigne="Rédige un devis", **kw):
    mid = creer_mission(titre=titre, consigne=consigne, service="REVENUE-CORE/propositions", **kw)
    pipeline.traiter(mid)
    with session_scope() as s:
        return s.execute(select(Decision.id).where(Decision.mission_id == mid)).scalar_one()


def _dater(did, quand):
    with session_scope() as s:
        s.get(Decision, did).cree_le = quand


# --- Page --------------------------------------------------------------------------------

def test_page_decideur(client):
    r = client.get("/cockpit/decideur")
    assert r.status_code == 200 and "Décideur NEXUS" in r.text and 'lang="fr"' in r.text
    assert "viewport" in r.text and "prefers-color-scheme: dark" in r.text
    assert not re.search(r"""(src|href)=["']https?://""", r.text)  # aucune ressource externe
    assert "confirm(" not in r.text and '"X-Cockpit": "1"' in r.text


# --- Sessions et notifications -----------------------------------------------------------

def test_regroupement_par_session_et_notification_unique(ntfy):
    ids = [_decision() for _ in range(3)]
    assert ntfy == []  # aucune notification à la création (hors urgence)
    base = datetime(2026, 11, 4, 9, 0)  # 10:00 à Paris (UTC+1 en novembre)
    for did in ids:
        _dater(did, base)
    assert decideur.tick(datetime(2026, 11, 4, 11, 0))["session"] is None  # 12:00 Paris : pas encore
    r = decideur.tick(datetime(2026, 11, 4, 11, 31))  # 12:31 Paris
    assert r["session"] == {"heure": "12:30", "decisions": 3} and len(ntfy) == 1
    assert ntfy[0]["corps"] == "3 decisions N3 vous attendent."
    decideur.tick(datetime(2026, 11, 4, 11, 50))  # même session : rien de plus
    assert len(ntfy) == 1
    decideur.tick(datetime(2026, 11, 4, 18, 5))  # 19:05 Paris : 2e session
    assert len(ntfy) == 2


def test_contenu_ntfy_generique_et_lien(ntfy, monkeypatch):
    monkeypatch.setenv("N3_TIMEOUT_HOURS", "3")  # urgente
    _decision(titre="Devis secret client Dupont")
    n = ntfy[0]
    assert "Dupont" not in n["corps"] and "Devis" not in n["corps"] and "Dupont" not in json.dumps(n["entetes"])
    assert n["entetes"]["Click"] == "https://nexus.exemple.fr/cockpit/decideur"
    assert "cle" not in n["entetes"]["Click"].lower() and "?" not in n["entetes"]["Click"]


def test_urgence_notification_immediate(ntfy, monkeypatch):
    monkeypatch.setenv("N3_TIMEOUT_HOURS", "3")
    _decision()
    assert len(ntfy) == 1 and "urgente" in ntfy[0]["corps"]
    monkeypatch.setenv("N3_TIMEOUT_HOURS", "24")
    _decision()
    assert len(ntfy) == 1  # non urgente : attend la session


def test_rappel_deux_heures_avant(ntfy):
    did = _decision()
    t0 = datetime(2026, 11, 4, 3, 0)
    _dater(did, t0)
    decideur.tick(t0 + timedelta(hours=21))  # 3 h avant l'expiration : pas encore
    assert not [n for n in ntfy if "Rappel" in n["corps"]]
    r = decideur.tick(t0 + timedelta(hours=22, minutes=30))
    assert r["rappels"] == 1 and "Rappel : 1 decision N3 sera refusee" in ntfy[-1]["corps"]
    decideur.tick(t0 + timedelta(hours=23))
    assert len([n for n in ntfy if "Rappel" in n["corps"]]) == 1


def test_sessions_configurables(monkeypatch):
    monkeypatch.setenv("NEXUS_SESSIONS_N3", "08:15, 21:00, pas-une-heure")
    assert decideur.sessions() == ["08:15", "21:00"]
    p = decideur.prochaine_session(datetime(2026, 11, 4, 8, 0))  # 09:00 Paris
    assert (p.hour, p.minute) == (21, 0)


# --- Risque ----------------------------------------------------------------------------

@pytest.mark.parametrize("args,niveau,raison", [
    (("Note", "Fais une synthèse interne"), "faible", "aucun critère"),
    (("Offre", "Proposition pour le client"), "moyen", "tiers"),
    (("Hébergement", "Budget de 300 €"), "moyen", "montant cité"),
    (("Ménage", "Supprimer les anciens comptes"), "eleve", "irréversible"),
    (("Serveur", "Déployer la version en production"), "eleve", "production"),
    (("Fichier", "Export des données personnelles"), "eleve", "données sensibles"),
    (("Note", "Aucun paiement n'est prévu"), "faible", "aucun critère"),
])
def test_risque_explicable(args, niveau, raison):
    n, raisons = decideur.evaluer_risque(*args)
    assert n == niveau and any(raison in r for r in raisons)


def test_risque_montant_et_action():
    assert decideur.evaluer_risque("Devis", "x", montant_eur=1500)[0] == "eleve"
    assert decideur.evaluer_risque("Devis", "x", montant_eur=200)[0] == "moyen"
    n, r = decideur.evaluer_risque("Document", "x", action="signer")
    assert n == "eleve" and any("action « signer »" in x for x in r)


def test_carte_resume_et_infos(client, cockpit):
    did = _decision(montant_eur=1500)
    e = client.get("/cockpit/api/decideur/etat", headers=cockpit).json()
    c = e["cartes"][0]
    assert c["id"] == did and c["risque"] == "eleve" and c["code_requis"] is True
    assert set(c["resume"]) == {"quoi", "pourquoi", "si_refus"} and all(c["resume"].values())
    assert "brouillon" in c["resume"]["si_refus"] and c["tokens"] > 0 and c["cout_estime_eur"] >= 1500
    assert c["service"] == "REVENUE-CORE/propositions" and c["fonctionnement"] == "F2"
    assert 0 < c["restant_s"] <= 24 * 3600 and c["lien_livrable"].endswith(f"/missions/{c['mission_id']}")
    assert e["compteur_jour"]["plafond"] == 15 and e["compteur_jour"]["creees"] == 1


# --- Confirmation, code, verrou, CSRF ------------------------------------------------------

def _preparer(client, cockpit, did, choix="valider", **kw):
    return client.post(f"/cockpit/api/decideur/decisions/{did}/preparer", json={"choix": choix, **kw},
                       headers=cockpit)


def _confirmer(client, cockpit, did, jeton, choix="valider", **kw):
    return client.post(f"/cockpit/api/decideur/decisions/{did}/confirmer",
                       json={"choix": choix, "jeton": jeton, **kw}, headers=cockpit)


def test_confirmation_obligatoire(client, cockpit):
    did = _decision()
    assert _confirmer(client, cockpit, did, "x" * 20).status_code == 409  # sans préparation
    p = _preparer(client, cockpit, did).json()
    assert p["libelle"] == f"Confirmer : valider #{did}" and p["code_requis"] is False
    assert _confirmer(client, cockpit, did, p["jeton"], choix="refuser").status_code == 409  # autre action
    r = _confirmer(client, cockpit, did, p["jeton"])
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    assert _confirmer(client, cockpit, did, p["jeton"]).status_code == 409  # usage unique
    action = [e for e in ledger.lister(100) if e["action"] == "decideur_action"][0]
    assert action["details"]["source"] == "decideur_mobile" and action["details"]["utilisateur"] == "decideur"


def test_revision_motif_obligatoire(client, cockpit):
    did = _decision()
    assert _preparer(client, cockpit, did, "reviser").status_code == 422
    p = _preparer(client, cockpit, did, "reviser", commentaire="Ajoute la TVA").json()
    r = _confirmer(client, cockpit, did, p["jeton"], choix="reviser", commentaire="Ajoute la TVA")
    assert r.status_code == 200 and r.json()["statut"] == "revision"


def test_code_exige_pour_risque_eleve(client, cockpit, monkeypatch):
    monkeypatch.setenv("COCKPIT_CODE_DECIDEUR", CODE)
    did = _decision(montant_eur=1500)
    p = _preparer(client, cockpit, did).json()
    assert p["code_requis"] is True
    assert _confirmer(client, cockpit, did, p["jeton"]).status_code == 403
    assert _confirmer(client, cockpit, did, p["jeton"], code="000000").status_code == 403
    r = _confirmer(client, cockpit, did, p["jeton"], code=CODE)  # jeton conservé après une erreur de code
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    assert not any(CODE in json.dumps(e) for e in ledger.lister(200))  # le code n'est jamais journalisé


def test_refuser_risque_eleve_sans_code(client, cockpit, monkeypatch):
    monkeypatch.setenv("COCKPIT_CODE_DECIDEUR", CODE)
    did = _decision(montant_eur=1500)
    p = _preparer(client, cockpit, did, "refuser").json()
    assert p["code_requis"] is False
    assert _confirmer(client, cockpit, did, p["jeton"], choix="refuser").status_code == 200


def test_code_non_configure_bloque_validation_risque_eleve(client, cockpit):
    did = _decision(montant_eur=1500)
    p = _preparer(client, cockpit, did).json()
    r = _confirmer(client, cockpit, did, p["jeton"], code=CODE)
    assert r.status_code == 403 and "non configuré" in r.json()["detail"]


def test_verrou_apres_cinq_erreurs(client, cockpit, monkeypatch):
    monkeypatch.setenv("COCKPIT_CODE_DECIDEUR", CODE)
    did = _decision(montant_eur=1500)
    p = _preparer(client, cockpit, did).json()
    codes = [_confirmer(client, cockpit, did, p["jeton"], code="111111").status_code for _ in range(5)]
    assert codes == [403, 403, 403, 403, 423]
    r = _confirmer(client, cockpit, did, p["jeton"], code=CODE)  # même le bon code est refusé
    assert r.status_code == 423 and "verrouillée" in r.json()["detail"]
    assert client.get("/cockpit/api/decideur/etat", headers=cockpit).json()["verrou_restant_s"] > 14 * 60
    assert "code_decideur_verrou" in [e["action"] for e in ledger.lister(100)]
    sentinel.ecrire("decideur:verrou", (datetime(2000, 1, 1)).isoformat())  # 15 min écoulées
    assert _confirmer(client, cockpit, did, p["jeton"], code=CODE).status_code == 200


def test_ancien_cockpit_exige_aussi_le_code(client, cockpit, monkeypatch):
    monkeypatch.setenv("COCKPIT_CODE_DECIDEUR", CODE)
    did = _decision(montant_eur=1500)
    assert client.post(f"/cockpit/api/decisions/{did}/valider", json={}, headers=cockpit).status_code == 403
    r = client.post(f"/cockpit/api/decisions/{did}/valider", json={"code": CODE}, headers=cockpit)
    assert r.status_code == 200


def test_csrf_decideur(client, cockpit):
    did = _decision()
    assert client.get("/cockpit/api/decideur/etat").status_code == 403
    assert client.get("/cockpit/api/decideur/etat", headers={"X-Cockpit-Auth": COCKPIT_INTERNE}).status_code == 200
    r = client.post(f"/cockpit/api/decideur/decisions/{did}/preparer", data={"choix": "valider"},
                    headers={"X-Cockpit-Auth": COCKPIT_INTERNE})
    assert r.status_code == 403  # formulaire sans X-Cockpit
    r = client.post(f"/cockpit/api/decideur/decisions/{did}/preparer", json={"choix": "valider"},
                    headers={**cockpit, "Origin": "https://pirate.exemple"})
    assert r.status_code == 403


def test_historique_et_compteur(client, cockpit):
    ids = [_decision() for _ in range(2)]
    for did in ids:
        p = _preparer(client, cockpit, did, "refuser").json()
        _confirmer(client, cockpit, did, p["jeton"], choix="refuser")
    e = client.get("/cockpit/api/decideur/etat", headers=cockpit).json()
    assert [h["id"] for h in e["historique"]][:2] == ids[::-1] and e["compteur_jour"]["decidees"] == 2
    assert e["cartes"] == []


def test_utilisateur_transmis_par_caddy(client, cockpit):
    did = _decision()
    p = _preparer(client, cockpit, did, "refuser").json()
    client.post(f"/cockpit/api/decideur/decisions/{did}/confirmer", json={"choix": "refuser", "jeton": p["jeton"]},
                headers={**cockpit, "X-Cockpit-Utilisateur": "proprietaire"})
    action = [e for e in ledger.lister(50) if e["action"] == "decideur_action"][0]
    assert action["details"]["utilisateur"] == "proprietaire"
