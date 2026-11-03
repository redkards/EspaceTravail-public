"""Tests de nexus-bridge (sans réseau)."""
import json
import logging

from tests.conftest import CLE_CORE, JETONS

OUTILS_ATTENDUS = {
    "memoire_ecrire", "memoire_chercher", "memoire_lire", "memoire_oublier",
    "tache_creer", "tache_lister", "tache_prendre", "tache_mettre_a_jour",
    "message_envoyer", "messages_lire", "passation_ecrire", "passation_derniere",
    "projets_lister", "mothership_mission", "mothership_statut", "mothership_decisions_en_attente",
    "journal_lister", "projet_connaissances", "memoire_collective_rechercher", "lecons_lister",
}


# --- Protocole JSON-RPC / MCP ---------------------------------------------------------------
def test_initialize_et_notification(session):
    s = session()
    r = s.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "test", "version": "1"}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18"
    assert res["capabilities"]["tools"] == {"listChanged": False}
    assert res["serverInfo"]["name"] == "nexus-bridge"
    assert "passation" in res["instructions"]
    # Version inconnue proposée par le client -> le serveur répond avec la sienne
    r = s.rpc("initialize", {"protocolVersion": "1999-01-01"})
    assert r.json()["result"]["protocolVersion"] == "2025-06-18"
    # Notification : 202 sans corps
    r = s.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""
    assert s.rpc("ping").json() == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_tools_list_schemas(session):
    r = session().rpc("tools/list")
    outils = r.json()["result"]["tools"]
    assert {o["name"] for o in outils} == OUTILS_ATTENDUS
    for o in outils:
        assert o["description"] and o["inputSchema"]["type"] == "object"
        assert o["inputSchema"]["additionalProperties"] is False
    ecrire = next(o for o in outils if o["name"] == "memoire_ecrire")
    assert set(ecrire["inputSchema"]["required"]) == {"sujet", "contenu", "etiquettes"}
    assert "poker-winners" in ecrire["inputSchema"]["properties"]["projet"]["enum"]
    tache = next(o for o in outils if o["name"] == "tache_creer")
    assert tache["inputSchema"]["properties"]["assigne_a"]["enum"] == ["claude", "chatgpt", "gemini", "proprietaire"]


def test_erreurs_jsonrpc(session, client):
    s = session()
    r = client.post("/mcp", content="{pas du json", headers={"Authorization": f"Bearer {JETONS['claude']}"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700
    r = s.post({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32600
    r = s.rpc("methode/inconnue")
    assert r.json()["error"]["code"] == -32601
    r = s.rpc("tools/call", {"name": "outil_inexistant", "arguments": {}})
    assert r.json()["error"]["code"] == -32602
    # Arguments invalides : erreur d'exécution d'outil (isError) avec message FR
    res, _ = s.outil("tache_creer", titre="x", description="y", assigne_a="personne")
    assert res["isError"] and "assigne_a" in res["content"][0]["text"]
    res, _ = s.outil("memoire_ecrire", sujet="s", contenu="c", etiquettes=[], inconnu=1)
    assert res["isError"] and "inconnu" in res["content"][0]["text"]
    res, _ = s.outil("memoire_lire")
    assert res["isError"] and "obligatoire" in res["content"][0]["text"]
    # Version de protocole non prise en charge
    r = s.post({"jsonrpc": "2.0", "id": 9, "method": "ping"}, {"MCP-Protocol-Version": "1900-01-01"})
    assert r.status_code == 400
    # Lot JSON-RPC
    r = s.post([{"jsonrpc": "2.0", "id": "a", "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}])
    assert r.json() == [{"jsonrpc": "2.0", "id": "a", "result": {}}]


def test_get_et_delete_405(client):
    h = {"Authorization": f"Bearer {JETONS['claude']}"}
    assert client.get("/mcp", headers=h).status_code == 405
    assert client.delete(f"/mcp/{JETONS['claude']}").status_code == 405


# --- Authentification ------------------------------------------------------------------------
def test_jeton_absent_ou_faux(client):
    corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert client.post("/mcp", content=corps).status_code == 401
    r = client.post("/mcp", content=corps, headers={"Authorization": "Bearer " + "x" * 66})
    assert r.status_code == 401 and "WWW-Authenticate" in r.headers
    assert client.post("/mcp/" + "x" * 66, content=corps).status_code == 401
    assert client.post("/mcp/court", content=corps).status_code == 401
    assert client.post("/mcp", content=corps, headers={"Authorization": f"Basic {JETONS['claude']}"}).status_code == 401
    # Jeton presque correct (un caractère de plus)
    assert client.post("/mcp/" + JETONS["claude"] + "0", content=corps).status_code == 401


def test_identite_vide_si_jeton_non_configure(client, monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN_GEMINI", "")
    corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert client.post(f"/mcp/{JETONS['gemini']}", content=corps).status_code == 401
    # Un jeton trop court n'est jamais accepté
    monkeypatch.setenv("BRIDGE_TOKEN_GEMINI", "abc")
    assert client.post("/mcp/abc", content=corps).status_code == 401


def test_jeton_chemin_et_entete_auteur(session):
    _, d1 = session("claude", "entete").outil("memoire_ecrire", sujet="Langue", contenu="Toujours en français", etiquettes=["preference"])
    _, d2 = session("chatgpt", "chemin").outil("memoire_ecrire", sujet="Hébergement", contenu="VPS Hostinger KVM 2", etiquettes=[])
    _, d3 = session("gemini", "chemin").outil("memoire_lire", id=d1["id"])
    assert d1["auteur"] == "claude" and d2["auteur"] == "chatgpt"
    assert d3["auteur"] == "claude"
    _, j = session("gemini").outil("journal_lister")
    auteurs = {(l["auteur"], l["outil"]) for l in j["journal"]}
    assert ("claude", "memoire_ecrire") in auteurs and ("chatgpt", "memoire_ecrire") in auteurs


def test_filtre_masque_jeton_uvicorn():
    from app.main import MasqueJeton
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/1.1" %d',
                            ("1.2.3.4", "POST", "/mcp/" + JETONS["claude"], 200), None)
    MasqueJeton().filter(rec)
    assert JETONS["claude"] not in rec.getMessage() and "/mcp/***" in rec.getMessage()


def test_jeton_jamais_dans_les_logs(session, caplog):
    caplog.set_level(logging.INFO)
    session("claude", "chemin").rpc("ping")
    session("chatgpt", "entete").rpc("ping")
    # Journaux côté serveur (le client de test httpx des tests n'est pas le serveur)
    texte = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert texte
    assert "/mcp/***" in texte
    for j in JETONS.values():
        assert j not in texte


# --- Mémoire ---------------------------------------------------------------------------------
def test_fts_et_versions(session):
    c, g = session("claude"), session("gemini")
    _, a = c.outil("memoire_ecrire", sujet="Tarif coaching poker", contenu="Le coaching individuel coûte 40 € de l'heure.",
                   etiquettes=["decision", "tarif"], projet="poker-winners")
    c.outil("memoire_ecrire", sujet="Chaîne YouTube", contenu="Deux vidéos par semaine, le mardi et le vendredi.",
            etiquettes=["planning"], projet="youtube-poker-winner")
    # Recherche sans accents, par préfixe
    _, r = g.outil("memoire_chercher", requete="cout coach")
    assert r["nombre"] == 1 and r["resultats"][0]["id"] == a["id"] and r["resultats"][0]["auteur"] == "claude"
    _, r = g.outil("memoire_chercher", requete="vidéos", projet="poker-winners")
    assert r["nombre"] == 0
    _, r = g.outil("memoire_chercher", requete="semaine OR NEAR(\"x\")")  # syntaxe FTS neutralisée
    assert r["nombre"] == 1
    # Nouvelle version (même sujet + projet) : l'ancienne est remplacée, pas supprimée
    _, b = g.outil("memoire_ecrire", sujet="Tarif coaching poker", contenu="Le coaching individuel coûte 50 € de l'heure.",
                   etiquettes=["decision"], projet="poker-winners")
    assert b["version"] == 2 and b["remplace_id"] == a["id"]
    _, r = c.outil("memoire_chercher", requete="coaching")
    assert [x["id"] for x in r["resultats"]] == [b["id"]]
    _, lu = c.outil("memoire_lire", id=a["id"])
    assert lu["statut"] == "remplacee" and lu["remplacee_par"] == b["id"] and len(lu["historique"]) == 2
    # Remplacement explicite d'une version déjà remplacée : refusé
    res, _ = c.outil("memoire_ecrire", sujet="x", contenu="y", etiquettes=[], remplace_id=a["id"])
    assert res["isError"]
    # Liste des dernières entrées
    _, r = c.outil("memoire_chercher", requete="*", limite=1)
    assert r["nombre"] == 1 and r["resultats"][0]["id"] == b["id"]


def test_memoire_oublier_droits(session):
    _, m = session("claude").outil("memoire_ecrire", sujet="Note", contenu="À archiver", etiquettes=[])
    res, _ = session("chatgpt").outil("memoire_oublier", id=m["id"], raison="test")
    assert res["isError"] and "claude" in res["content"][0]["text"]
    res, d = session("proprietaire").outil("memoire_oublier", id=m["id"], raison="périmé")
    assert not res["isError"] and d["statut"] == "archivee"
    _, r = session("claude").outil("memoire_chercher", requete="archiver")
    assert r["nombre"] == 0
    _, lu = session("claude").outil("memoire_lire", id=m["id"])
    assert lu["archive_par"] == "proprietaire" and lu["contenu"] == "À archiver"


# --- Garde-fous --------------------------------------------------------------------------------
def test_refus_secrets(session):
    s = session()
    cas = [
        "Ma clé : sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "OPENAI sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "Google AIzaSyA1234567890abcdefghijklmnopqrstu",
        "mot de passe : Azerty123!",
        "password=hunter22",
        "carte 4012 8888 8888 1881",   # Luhn valide (numéro de test Visa)
        "api_key=0123456789abcdef0123",
        "ghp_" + "a" * 36,
        f"le jeton est {JETONS['gemini']}",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "https://admin:motdepasse@exemple.fr",
    ]
    for texte in cas:
        res, _ = s.outil("memoire_ecrire", sujet="Test", contenu=texte, etiquettes=[])
        assert res["isError"], texte
        assert "ressemble à un secret" in res["content"][0]["text"]
        # Le secret n'est jamais renvoyé dans le message d'erreur
        assert texte not in res["content"][0]["text"]
    for texte in ["Le mot de passe est rangé dans le .env du VPS (variable COCKPIT_PASSWORD).",
                  "Commande n° 1234 5678 du 03/11", "Téléphone 06 12 34 56 78"]:
        res, _ = s.outil("memoire_ecrire", sujet="Ok", contenu=texte, etiquettes=[])
        assert not res["isError"], texte
    # Aussi dans les messages et les tâches
    res, _ = s.outil("message_envoyer", destinataire="tous", sujet="clé", contenu="AIzaSyA1234567890abcdefghijklmnopqrstu")
    assert res["isError"]


def test_taille_max(session):
    res, _ = session().outil("memoire_ecrire", sujet="Gros", contenu="é" * 4097, etiquettes=[])  # 8194 octets
    assert res["isError"] and ("8 Ko" in res["content"][0]["text"] or "8192" in res["content"][0]["text"])


def test_limite_de_debit(session, monkeypatch, client):
    monkeypatch.setenv("BRIDGE_LIMITE_PAR_MINUTE", "5")
    s = session("chatgpt")
    for _ in range(5):
        assert s.rpc("ping").status_code == 200
    r = s.rpc("ping")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert "60" not in r.json()["error"]["message"] or "5" in r.json()["error"]["message"]
    # Un autre jeton n'est pas concerné
    assert session("gemini").rpc("ping").status_code == 200


def _lot(n, depart=1):
    return [{"jsonrpc": "2.0", "id": depart + i, "method": "ping"} for i in range(n)]


def test_lot_compte_chaque_element(session, monkeypatch):
    monkeypatch.setenv("BRIDGE_LIMITE_PAR_MINUTE", "5")
    s = session("chatgpt")
    r = s.post(_lot(4))
    assert r.status_code == 200 and len(r.json()) == 4
    r = s.post(_lot(2, 10))  # 4 + 2 > 5 : lot entier refusé (tout ou rien)
    assert r.status_code == 429
    assert s.rpc("ping").status_code == 200  # il restait 1 place
    assert s.rpc("ping").status_code == 429


def test_lot_trop_grand_refuse(session, monkeypatch):
    monkeypatch.setenv("BRIDGE_LIMITE_PAR_MINUTE", "100")
    s = session("claude")
    r = s.post(_lot(11))
    assert r.status_code == 400 and "10 éléments" in r.json()["error"]["message"]
    assert s.post(_lot(10)).status_code == 200


def test_lot_plus_grand_que_la_limite(session, monkeypatch):
    monkeypatch.setenv("BRIDGE_LIMITE_PAR_MINUTE", "3")
    r = session("gemini").post(_lot(5))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


# --- Tâches ----------------------------------------------------------------------------------
def test_verrou_de_tache(session):
    c, g = session("claude"), session("gemini")
    _, t = c.outil("tache_creer", titre="Script vidéo", description="Écrire le script de l'épisode 3",
                   assigne_a="gemini", projet="youtube-poker-winner", priorite="haute")
    _, l = g.outil("tache_lister", assigne_a="gemini")
    assert l["nombre"] == 1 and l["taches"][0]["priorite"] == "haute"
    _, p = g.outil("tache_prendre", id=t["id"])
    assert p["pris_par"] == "gemini"
    res, _ = session("chatgpt").outil("tache_prendre", id=t["id"])
    assert res["isError"] and "gemini" in res["content"][0]["text"]
    res, _ = session("chatgpt").outil("tache_mettre_a_jour", id=t["id"], statut="fait", note="fini")
    assert res["isError"]
    res, _ = g.outil("tache_prendre", id=t["id"])  # reprise par la même IA : idempotent
    assert not res["isError"]
    _, u = g.outil("tache_mettre_a_jour", id=t["id"], statut="a_valider", note="Script dans le Drive")
    assert u["statut"] == "a_valider"
    _, u = session("proprietaire").outil("tache_mettre_a_jour", id=t["id"], statut="fait", note="Validé")
    assert u["statut"] == "fait"
    _, l = g.outil("tache_lister")
    assert l["nombre"] == 0
    _, l = g.outil("tache_lister", statut="fait")
    assert l["nombre"] == 1
    res, _ = c.outil("tache_prendre", id=t["id"])
    assert res["isError"] and "terminée" in res["content"][0]["text"]


# --- Messages --------------------------------------------------------------------------------
def test_messages_non_lus(session):
    c, g, o = session("claude"), session("gemini"), session("chatgpt")
    c.outil("message_envoyer", destinataire="gemini", sujet="Relecture", contenu="Peux-tu relire le chapitre 2 ?")
    c.outil("message_envoyer", destinataire="tous", sujet="Info", contenu="Passation écrite pour poker-feeling.")
    _, m = g.outil("messages_lire")
    assert m["nombre"] == 2 and {x["de"] for x in m["messages"]} == {"claude"}
    _, m = g.outil("messages_lire")
    assert m["nombre"] == 0
    _, m = g.outil("messages_lire", non_lus_seulement=False)
    assert m["nombre"] == 2 and all(x["deja_lu"] for x in m["messages"])
    # ChatGPT ne voit que le message « tous » ; l'expéditeur ne reçoit pas son propre « tous »
    _, m = o.outil("messages_lire")
    assert m["nombre"] == 1 and m["messages"][0]["sujet"] == "Info"
    _, m = c.outil("messages_lire")
    assert m["nombre"] == 0
    _, m = g.outil("messages_lire", non_lus_seulement=False, depuis="2999-01-01T00:00:00+00:00")
    assert m["nombre"] == 0


# --- Passations ------------------------------------------------------------------------------
def test_passations(session):
    _, p = session("claude").outil("passation_derniere", projet="poker-feeling")
    assert p["passation"] is None
    session("claude").outil("passation_ecrire", projet="poker-feeling", resume="Plan du livre", etat="Chapitres 1-3 rédigés",
                            prochaines_etapes="1. Chapitre 4")
    session("chatgpt").outil("passation_ecrire", projet="poker-feeling", resume="Chapitre 4", etat="Chapitres 1-4",
                             prochaines_etapes="1. Relecture")
    _, p = session("gemini").outil("passation_derniere", projet="poker-feeling")
    assert p["passation"]["auteur"] == "chatgpt" and p["passation"]["resume"] == "Chapitre 4"
    res, _ = session("gemini").outil("passation_derniere", projet="projet-inconnu")
    assert res["isError"]


# --- Mothership --------------------------------------------------------------------------------
def test_mothership_mission(session, faux_core):
    res, d = session("chatgpt").outil("mothership_mission", titre="Checklist", consigne="Rédige une checklist",
                                      service="OPS-CORE/projets", projet="nexus")
    assert not res["isError"] and d["id"] == 42 and "cockpit" in d["message"]
    req = faux_core.requetes[-1]
    assert req.url.path == "/api/missions" and req.headers["x-nexus-key"] == CLE_CORE
    corps = json.loads(req.content)
    assert corps["projet"] == "nexus" and corps["service"] == "OPS-CORE/projets" and "chatgpt" in corps["consigne"]
    _, st = session("claude").outil("mothership_statut", id=42)
    assert st["statut"] == "en_attente_n3" and "rappel" in st
    res, _ = session("claude").outil("mothership_statut", id=99)
    assert res["isError"]
    _, dec = session("gemini").outil("mothership_decisions_en_attente")
    assert dec["nombre"] == 1 and faux_core.requetes[-1].url.params["statut"] == "en_attente"
    # Aucun outil de validation
    noms = {o["name"] for o in session().rpc("tools/list").json()["result"]["tools"]}
    assert not any(x in n for n in noms for x in ("valider", "refuser", "reviser", "killswitch"))
    # Journal : écriture tracée, sans contenu
    _, j = session().outil("journal_lister", limite=5)
    assert any(l["outil"] == "mothership_mission" and l["auteur"] == "chatgpt" for l in j["journal"])
    assert "checklist" not in json.dumps(j).lower()


def test_mothership_mission_fonctionnement(session, faux_core):
    # Sans paramètre : rien n'est ajouté (défaut du serveur).
    session().outil("mothership_mission", titre="t", consigne="c")
    assert "fonctionnement" not in json.loads(faux_core.requetes[-1].content)
    # F1..F3 transmis tels quels.
    _, d = session("chatgpt").outil("mothership_mission", titre="t", consigne="c", fonctionnement="F3")
    assert json.loads(faux_core.requetes[-1].content)["fonctionnement"] == "F3" and d["fonctionnement"] == "F3"
    # F4 : transmis, la passerelle annonce l'attente de l'accord humain et ne peut rien approuver.
    res, d = session("gemini").outil("mothership_mission", titre="t", consigne="c", fonctionnement="F4")
    assert not res["isError"] and json.loads(faux_core.requetes[-1].content)["fonctionnement"] == "F4"
    assert d["statut"] == "en_attente_n3" and "validation du propriétaire" in d["message"]
    assert "coût estimé" in d["note_mothership"]
    assert all(r.method != "POST" or not r.url.path.startswith("/api/decisions") for r in faux_core.requetes)
    # Valeur hors énumération refusée avant tout appel à nexus-core.
    n = len(faux_core.requetes)
    res, _ = session().outil("mothership_mission", titre="t", consigne="c", fonctionnement="F9")
    assert res["isError"] and len(faux_core.requetes) == n
    schema = next(o for o in session().rpc("tools/list").json()["result"]["tools"] if o["name"] == "mothership_mission")
    assert schema["inputSchema"]["properties"]["fonctionnement"]["enum"] == ["F1", "F2", "F3", "F4"]


def test_projet_connaissances(session, faux_core):
    res, d = session("chatgpt").outil("projet_connaissances", projet="redkards", q="pitch", limite=3)
    assert not res["isError"] and d["nombre"] == 1 and d["connaissances"][0]["source"] == "contexte/redkards.md#2"
    req = faux_core.requetes[-1]
    assert req.method == "GET" and req.url.path == "/api/projets/redkards/connaissances"
    assert req.url.params["q"] == "pitch" and req.url.params["limite"] == "3"
    assert req.headers["x-nexus-key"] == CLE_CORE
    assert len(d["connaissances"][0]["contenu"]) <= 1500 + 10  # tronqué
    # Projet hors énumération refusé avant tout appel ; aucune écriture possible via la passerelle.
    n = len(faux_core.requetes)
    res, _ = session().outil("projet_connaissances", projet="pas-un-projet")
    assert res["isError"] and len(faux_core.requetes) == n
    assert all(r.method == "GET" for r in faux_core.requetes if "/connaissances" in r.url.path)
    noms = {o["name"] for o in session().rpc("tools/list").json()["result"]["tools"]}
    assert not any("connaissance" in n and n != "projet_connaissances" for n in noms)


def test_memoire_collective_lecture_seule(session, faux_core):
    res, d = session("gemini").outil("memoire_collective_rechercher", q="pitch", projet="redkards")
    assert not res["isError"] and d["connaissances"][0]["titre"] == "Pitch" and d["archive"][0]["seq"] == 1
    req = faux_core.requetes[-1]
    assert req.url.path == "/api/memoire/recherche" and req.url.params["projet"] == "redkards"
    _, l = session("claude").outil("lecons_lister")
    assert l["nombre"] == 1 and faux_core.requetes[-1].url.params["statut"] == "acceptee"
    res, _ = session().outil("lecons_lister", statut="supprimee")
    assert res["isError"]
    assert all(r.method == "GET" for r in faux_core.requetes if "/memoire" in r.url.path)
    noms = {o["name"] for o in session().rpc("tools/list").json()["result"]["tools"]}
    assert not any(x in n for n in noms for x in ("accepter", "rejeter", "effacer", "lecon_"))


def test_mothership_injoignable_ou_cle_refusee(session, monkeypatch):
    monkeypatch.setenv("NEXUS_API_KEY", "mauvaise-cle-" + "1" * 30)
    res, _ = session().outil("mothership_mission", titre="t", consigne="c")
    assert res["isError"] and "401" in res["content"][0]["text"]
    monkeypatch.setenv("NEXUS_API_KEY", "")
    res, _ = session().outil("mothership_decisions_en_attente")
    assert res["isError"]


def test_projets_lister(session, faux_core):
    _, p = session().outil("projets_lister")
    assert p["source"] == "nexus-core" and p["projets"][0]["code"] == "poker-winners"
    faux_core.projets_disponible = False
    _, p = session().outil("projets_lister")
    assert "défaut" in p["source"] and len(p["projets"]) == 11 and p["projets"][0]["code"] == "paradoxx"


# --- Page /bridge et santé ---------------------------------------------------------------------
def test_page_bridge(session, client):
    c = session("claude")
    c.outil("memoire_ecrire", sujet="<script>alert(1)</script>", contenu="Test d'échappement", etiquettes=["x"])
    c.outil("tache_creer", titre="Tâche visible", description="", assigne_a="proprietaire")
    c.outil("message_envoyer", destinataire="chatgpt", sujet="Bonjour", contenu="Salut")
    c.outil("passation_ecrire", projet="redkards", resume="r", etat="e", prochaines_etapes="p")
    r = client.get("/bridge")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert 'lang="fr"' in html and "viewport" in html
    assert "Tâche visible" in html and "Bonjour" in html and "redkards" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    for j in JETONS.values():
        assert j not in html
    assert client.get("/sante").json()["statut"] == "ok"


def test_journal_append_only(session):
    import sqlite3

    import pytest

    from app.config import cfg
    session().outil("tache_creer", titre="t", description="d", assigne_a="claude")
    con = sqlite3.connect(cfg().db_path)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM journal")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE journal SET auteur='x'")
    con.close()
