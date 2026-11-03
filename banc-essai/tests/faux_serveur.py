"""Faux serveur nexus-core (http.server) imitant les routes utilisées par lancer.sh.

Routes : GET /api/sante, GET /api/fonctionnement, POST /api/missions, GET /api/missions/{id}.
Chaque mission devient finale après `polls_avant_final` lectures. Le résultat (service, niveau,
statut, livrable) est tiré de la définition de la mission (missions.json) retrouvée par son titre,
et peut être modifié par `comportements[titre]` (dict fusionné dans la réponse ; clé spéciale
« jamais_final » pour simuler une mission qui ne se termine pas).
"""
import json
import re
import threading

import noter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLE = "cle-faux-serveur-123"


def livrable_ideal(definition):
    """Livrable qui satisfait obligatoires, sections et longueur minimale."""
    lignes = []
    for s in definition.get("sections", []) or ["Contenu"]:
        lignes.append(f"## {s}")
    for el in definition.get("obligatoires", []):
        el = el[0] if isinstance(el, list) else el
        lignes.append(f"- {el.rstrip('*')}")
    lignes.append("Hypothèse : chiffres indicatifs.")
    if "regle:reference_juridique_non_verifiee" in definition.get("interdits", []):
        lignes.append("Référence à vérifier pour chaque article cité.")
    mini = (definition.get("longueur") or {}).get("min_mots", 0)
    while noter.nb_mots("\n".join(lignes)) < mini + 5:
        lignes.append("Texte de remplissage neutre pour atteindre la longueur demandée.")
    return "\n".join(lignes)


class FauxServeur:
    def __init__(self, missions_json, polls_avant_final=1, cle=CLE):
        with open(missions_json, encoding="utf-8") as f:
            self.definitions = {m["titre"]: m for m in json.load(f)["missions"]}
        self.polls_avant_final = polls_avant_final
        self.cle = cle
        self.comportements = {}
        self.missions = {}
        self.posts = []
        self.cles_recues = []
        self.verrou = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.httpd.shutdown()
        self.httpd.server_close()

    def creer(self, corps):
        with self.verrou:
            mid = len(self.missions) + 1
            self.missions[mid] = {"corps": corps, "lectures": 0}
            return mid

    def detail(self, mid):
        m = self.missions[mid]
        m["lectures"] += 1
        corps = m["corps"]
        d = self.definitions.get(corps["titre"], {})
        comp = dict(self.comportements.get(corps["titre"], {}))
        base = {"id": mid, "titre": corps["titre"], "projet": corps.get("projet"), "statut": "en_cours",
                "service": None, "niveau": None, "fonctionnement_demande": corps.get("fonctionnement"),
                "fonctionnement": corps.get("fonctionnement"), "tokens": 1000, "tokens_entree": 800,
                "tokens_sortie": 200, "cout_eur": 0.0, "duree_s": 12.5, "revisions": 0, "attente": None,
                "message": None, "livrable_texte": None, "etapes": []}
        if corps.get("fonctionnement") == "F4" and not comp:
            base.update(statut="en_attente_n3", attente="lancement_f4")
            return base
        if comp.pop("jamais_final", False) or m["lectures"] <= self.polls_avant_final - 1:
            return base
        niveau = d.get("niveau_decision_attendu", "N1")
        base.update(statut="en_attente_n3" if niveau == "N3" else "terminee",
                    service=corps.get("service") or d.get("service_attendu"), niveau=niveau,
                    livrable_texte=livrable_ideal(d) if d else "Livrable.")
        base.update(comp)
        return base

    def _handler(srv):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _auth(self):
                k = self.headers.get("X-Nexus-Key")
                srv.cles_recues.append(k)
                if k != srv.cle:
                    self._json(401, {"detail": "Clé API absente ou invalide"})
                    return False
                return True

            def do_GET(self):
                if self.path == "/api/sante":
                    return self._json(200, {"statut": "ok", "llm": {"fournisseur": "faux", "modele": "faux-3b",
                                                                   "modele_checker": "faux-3b"},
                                            "fonctionnement_defaut": "F2"})
                if not self._auth():
                    return
                if self.path == "/api/fonctionnement":
                    return self._json(200, {"niveaux": [{"code": c, "nom": c, "fournisseur": "x", "budget_tokens": 1,
                                                         "revisions_max": 0, "double_controle": False,
                                                         "delai_max_s": 1, "cout_max_eur": 0}
                                                        for c in ("F1", "F2", "F3", "F4")]})
                m = re.fullmatch(r"/api/missions/(\d+)", self.path)
                if m and int(m.group(1)) in srv.missions:
                    return self._json(200, srv.detail(int(m.group(1))))
                return self._json(404, {"detail": "introuvable"})

            def do_POST(self):
                if not self._auth():
                    return
                if self.path != "/api/missions":
                    return self._json(404, {"detail": "introuvable"})
                n = int(self.headers.get("Content-Length") or 0)
                corps = json.loads(self.rfile.read(n) or b"{}")
                srv.posts.append(corps)
                if corps.get("service") and not corps["service"].count("/"):
                    return self._json(422, {"detail": "Service inconnu"})
                mid = srv.creer(corps)
                return self._json(202, {"id": mid, "statut": "recue"})
        return H
