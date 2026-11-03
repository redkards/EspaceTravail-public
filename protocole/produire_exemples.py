#!/usr/bin/env python3
"""Produit des exemples RÉELS du protocole en faisant tourner les composants en local, sans réseau.

  python3 produire_exemples.py core   SORTIE   # nexus-core, LLM factice, SQLite temporaire
  python3 produire_exemples.py bridge SORTIE   # nexus-bridge ; ses appels à nexus-core sont servis
                                               # avec les réponses produites par « core » (SORTIE)

Chaque exemple est écrit dans SORTIE/<cible>__<nom>.json, où <cible> est la cible de valider.py
(« # » remplacé par « @ »). Aucun fichier n'est écrit dans nexus-core/ ni nexus-bridge/ (pas de
__pycache__). À lancer dans un processus séparé par composant : les deux s'appellent « app ».
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
RACINE = Path(__file__).resolve().parent.parent


def ecrire(sortie: Path, cible: str, nom: str, objet) -> None:
    (sortie / f"{cible.replace('#', '@')}__{nom}.json").write_text(
        json.dumps(objet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def lire(sortie: Path, cible: str, nom: str):
    return json.loads((sortie / f"{cible.replace('#', '@')}__{nom}.json").read_text(encoding="utf-8"))


def core(sortie: Path) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="protocole-core-"))
    cle = "cle-protocole-exemples"
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{tmp / 'nexus.db'}", "NEXUS_DATA_DIR": str(tmp / "data"),
        "LLM_PROVIDER": "fake", "NEXUS_API_KEY": cle, "NEXUS_TACHES_FOND": "0",
        "COCKPIT_INTERNAL": "secret-interne-exemples", "NEXUS_HOST": "nexus.exemple.fr",
        "BUDGET_TASK_TOKENS": "20000", "LEDGER_HMAC_KEY": "cle-hmac-exemples",
        # F4 « disponible » pour produire une décision de lancement : rien n'est exécuté sans accord.
        "ANTHROPIC_API_KEY": "sk-factice-jamais-appelee", "BUDGET_MONTHLY_EUR": "20",
        "NEXUS_CONNAISSANCES_DIR": str(tmp / "connaissances"),
    })
    for v in ("NTFY_URL", "NTFY_TOPIC", "NEXUS_FONCTIONNEMENT_DEFAUT", "NEXUS_FONCTIONNEMENT_FILE",
              "NEXUS_MAX_MISSIONS", "NEXUS_PROJETS_FILE", "COCKPIT_CODE_DECIDEUR", "NEXUS_SESSIONS_N3",
              "NEXUS_MEMOIRE_AUTO", "EUR_PAR_USD"):
        os.environ.pop(v, None)
    sys.path.insert(0, str(RACINE / "nexus-core"))
    os.chdir(RACINE / "nexus-core")
    from fastapi.testclient import TestClient
    from app.main import app

    h = {"X-Nexus-Key": cle}

    def ok(r, attendu=200):
        assert r.status_code == attendu, (r.status_code, r.text[:500])
        return r.json()

    with TestClient(app) as c:
        ecrire(sortie, "sante", "ok", ok(c.get("/api/sante", headers=h)))
        ecrire(sortie, "fonctionnement", "grille", ok(c.get("/api/fonctionnement", headers=h)))
        creations = {
            "n1_service": {"titre": "Checklist de démarrage", "consigne": "Rédige une checklist de démarrage",
                           "service": "OPS-CORE/projets", "projet": "nexus", "fonctionnement": "F1"},
            "devis_n3": {"titre": "Devis site vitrine", "consigne": "Rédige un devis pour un site vitrine",
                         "montant_eur": 900},
            "f4_lancement": {"titre": "Analyse experte", "consigne": "Analyse approfondie du plan de projet",
                             "projet": "paradoxx", "fonctionnement": "F4"},
        }
        ids = {}
        for nom, corps in creations.items():
            ecrire(sortie, "mission-creation", nom, corps)
            rep = ok(c.post("/api/missions", headers=h, json=corps), 202)
            ecrire(sortie, "mission-creation-reponse", nom, rep)
            ids[nom] = rep["id"]
        for nom, mid in ids.items():
            m = ok(c.get(f"/api/missions/{mid}", headers=h))
            ecrire(sortie, "mission", nom, m)
            for e in m.get("etapes", [])[:2]:
                ecrire(sortie, "etape", f"{nom}_{e['id']}", e)
        ecrire(sortie, "mission#liste", "toutes", ok(c.get("/api/missions", headers=h)))
        decs = ok(c.get("/api/decisions?statut=en_attente", headers=h))
        ecrire(sortie, "decision#liste", "en_attente", decs)
        devis = next(d for d in decs if d["mission_id"] == ids["devis_n3"])
        ecrire(sortie, "decision", "devis", devis)
        action = {"commentaire": "Accord du propriétaire (exemple)."}
        ecrire(sortie, "decision#action", "valider", action)
        ecrire(sortie, "decision#actionReponse", "valider",
               ok(c.post(f"/api/decisions/{devis['id']}/valider", headers=h, json=action)))
        valide = ok(c.get(f"/api/missions/{ids['devis_n3']}", headers=h))
        ecrire(sortie, "mission", "devis_valide", valide)
        ecrire(sortie, "decision#liste", "toutes", ok(c.get("/api/decisions", headers=h)))
        k = {"titre": "Ton éditorial", "contenu": "Phrases courtes, tutoiement interdit, exemples concrets.",
             "source": "exemple protocole"}
        ecrire(sortie, "connaissance#ajout", "ton", k)
        ecrire(sortie, "connaissance#ajoutReponse", "ton",
               ok(c.post("/api/projets/nexus/connaissances", headers=h, json=k), 201))
        ecrire(sortie, "connaissance#ajoutReponse", "ton_inchangee",
               ok(c.post("/api/projets/nexus/connaissances", headers=h, json=k), 201))
        trouve = ok(c.get("/api/projets/nexus/connaissances?q=éditorial", headers=h))
        ecrire(sortie, "connaissance#liste", "recherche", trouve)
        ecrire(sortie, "connaissance#liste", "dernieres", ok(c.get("/api/projets/nexus/connaissances", headers=h)))
        if trouve:
            ecrire(sortie, "connaissance", "ton", trouve[0])
        ecrire(sortie, "agent#liste", "toutes", ok(c.get("/api/agents", headers=h)))
        led = ok(c.get("/api/ledger?limit=20", headers=h))
        ecrire(sortie, "evenement-ledger#liste", "dernieres", led)
        ecrire(sortie, "evenement-ledger", "premiere", led[-1])
        ecrire(sortie, "evenement-ledger#verification", "ok", ok(c.get("/api/ledger/verifier", headers=h)))
        # Données brutes pour servir le faux nexus-core du mode « bridge ».
        ecrire(sortie, "_brut", "projets", ok(c.get("/api/projets", headers=h)))


def bridge(sortie: Path) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="protocole-bridge-"))
    jetons = {i: (i[0] * 40 + "0123456789abcdef0123456789") for i in ("claude", "chatgpt", "gemini", "proprietaire")}
    cle = "cle-core-exemples-" + "0" * 30
    os.environ.update({"BRIDGE_DB": str(tmp / "bridge.db"), "NEXUS_API_KEY": cle,
                       "NEXUS_CORE_URL": "http://nexus-core:8000", "NEXUS_HOST": "nexus.exemple.fr",
                       "BRIDGE_LIMITE_PAR_MINUTE": "1000"})
    os.environ.pop("BRIDGE_PROJETS", None)
    for i, j in jetons.items():
        os.environ[f"BRIDGE_TOKEN_{i.upper()}"] = j
    sys.path.insert(0, str(RACINE / "nexus-bridge"))
    os.chdir(RACINE / "nexus-bridge")
    import httpx
    from fastapi.testclient import TestClient
    from app import outils
    from app.main import app

    # Réponses réelles de nexus-core (mode « core ») rejouées pour la passerelle.
    rep_creation = lire(sortie, "mission-creation-reponse", "n1_service")
    mission = lire(sortie, "mission", "devis_valide")
    attente = lire(sortie, "mission", "f4_lancement")

    def faux_core(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if req.method == "POST" and p == "/api/missions":
            return httpx.Response(202, json=rep_creation)
        if p == f"/api/missions/{mission['id']}":
            return httpx.Response(200, json=mission)
        if p == f"/api/missions/{attente['id']}":
            return httpx.Response(200, json=attente)
        if p == "/api/decisions":
            return httpx.Response(200, json=lire(sortie, "decision#liste", "en_attente"))
        if p == "/api/projets":
            return httpx.Response(200, json=lire(sortie, "_brut", "projets"))
        if p.endswith("/connaissances"):
            return httpx.Response(200, json=lire(sortie, "connaissance#liste", "recherche"))
        return httpx.Response(404, json={"detail": "Not Found"})

    outils._transport = httpx.MockTransport(faux_core)
    n = 0
    with TestClient(app) as c:
        def appel(ident, nom, args, exemple=None):
            nonlocal n
            n += 1
            r = c.post("/mcp", headers={"Authorization": f"Bearer {jetons[ident]}", "Content-Type": "application/json",
                                        "Accept": "application/json, text/event-stream",
                                        "MCP-Protocol-Version": "2025-06-18"},
                       content=json.dumps({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                                           "params": {"name": nom, "arguments": args}}))
            assert r.status_code == 200, r.text
            res = r.json()["result"]
            if res.get("isError"):
                ecrire(sortie, "mcp-outils#erreur", exemple or nom, res)
                return None
            ecrire(sortie, f"mcp-outils#{nom}.entree", exemple or nom, args)
            ecrire(sortie, f"mcp-outils#{nom}.sortie", exemple or nom, res["structuredContent"])
            return res["structuredContent"]

        m1 = appel("claude", "memoire_ecrire", {"sujet": "Ton des vidéos", "contenu": "Ton direct et pédagogique.",
                                                "etiquettes": ["preference"], "projet": "youtube-poker-winner"})
        appel("chatgpt", "memoire_ecrire", {"sujet": "Ton des vidéos", "contenu": "Ton direct, sans jargon.",
                                            "etiquettes": ["preference"], "projet": "youtube-poker-winner",
                                            "remplace_id": m1["id"]}, "nouvelle_version")
        appel("gemini", "memoire_chercher", {"requete": "ton vidéos"})
        appel("gemini", "memoire_chercher", {"requete": "*", "limite": 5}, "dernieres")
        appel("claude", "memoire_lire", {"id": m1["id"]})
        appel("claude", "memoire_oublier", {"id": m1["id"], "raison": "Remplacée par la version 2."})
        t = appel("claude", "tache_creer", {"titre": "Relire le README", "description": "Vérifier les liens.",
                                            "assigne_a": "gemini", "projet": "nexus", "priorite": "haute"})
        appel("gemini", "tache_lister", {})
        appel("gemini", "tache_prendre", {"id": t["id"]})
        appel("gemini", "tache_mettre_a_jour", {"id": t["id"], "statut": "a_valider", "note": "Liens corrigés."})
        appel("claude", "message_envoyer", {"destinataire": "tous", "sujet": "Point", "contenu": "README relu."})
        appel("gemini", "messages_lire", {})
        appel("claude", "passation_ecrire", {"projet": "nexus", "resume": "Protocole v1.", "etat": "Schémas prêts.",
                                             "prochaines_etapes": "1. CI 2. Séparation des dépôts"})
        appel("chatgpt", "passation_derniere", {"projet": "nexus"})
        appel("chatgpt", "passation_derniere", {"projet": "turf"}, "aucune")
        appel("claude", "projets_lister", {})
        appel("claude", "projet_connaissances", {"projet": "nexus", "q": "éditorial"})
        appel("claude", "mothership_mission", {"titre": "Checklist", "consigne": "Rédige une checklist.",
                                               "projet": "nexus", "fonctionnement": "F1"})
        appel("claude", "mothership_statut", {"id": mission["id"]})
        appel("claude", "mothership_statut", {"id": attente["id"]}, "attente_f4")
        appel("claude", "mothership_decisions_en_attente", {})
        appel("proprietaire", "journal_lister", {"limite": 10})
        appel("claude", "memoire_ecrire", {"sujet": "x", "contenu": "y", "etiquettes": [], "inconnu": 1},
              "parametre_inconnu")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("core", "bridge"):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    dossier = Path(sys.argv[2]).resolve()
    dossier.mkdir(parents=True, exist_ok=True)
    {"core": core, "bridge": bridge}[sys.argv[1]](dossier)
    print(f"Exemples écrits dans {dossier}")
