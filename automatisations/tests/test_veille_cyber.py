"""Tests de automatisations/veille-cyber.sh avec un faux serveur nexus-core + ntfy (aucun réseau externe)."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "veille-cyber.sh"
CLE = "cle-api-tres-secrete-" + "q" * 24
MDP = "MotDePassePostgresTresSecret42"
HASH = "$2a$14$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234"


class FauxServeur:
    def __init__(self, statut_final="terminee"):
        self.missions, self.ntfy, self.cles, self.lectures = [], [], [], 0
        self.statut_final = statut_final
        etat = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, corps):
                donnees = json.dumps(corps).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def do_GET(self):
                if self.path.startswith("/api/"):
                    etat.cles.append(self.headers.get("X-Nexus-Key"))
                if self.path == "/api/sante":
                    return self._json(200, {"statut": "ok"})
                if self.path.startswith("/api/missions/"):
                    etat.lectures += 1
                    mid = int(self.path.rsplit("/", 1)[1])
                    statut = etat.statut_final if etat.lectures > 1 else "en_cours"
                    return self._json(200, {"id": mid, "statut": statut})
                self._json(404, {})

            def do_POST(self):
                corps = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path == "/api/missions":
                    etat.cles.append(self.headers.get("X-Nexus-Key"))
                    etat.missions.append(json.loads(corps))
                    return self._json(202, {"id": 100 + len(etat.missions), "statut": "recue"})
                if self.path == "/sujet-ntfy":
                    etat.ntfy.append({"corps": corps.decode(), "titre": self.headers.get("Title"),
                                      "clic": self.headers.get("Click")})
                    return self._json(200, {})
                self._json(404, {})

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def kit(tmp_path):
    k = tmp_path / "kit"
    (k / "nexus-core").mkdir(parents=True)
    (k / ".env").write_text(f"NEXUS_HOST=nexus.exemple.fr\nNEXUS_API_KEY={CLE}\nPOSTGRES_PASSWORD={MDP}\n"
                            f"NTFY_TOPIC=sujet-ntfy\nCOCKPIT_PASSWORD_HASH='{HASH}'\n", encoding="utf-8")
    (k / "docker-compose.yml").write_text(f"""services:
  caddy:
    image: caddy:2.8
    ports:
      - "80:80"
      - "443:443"
    environment:
      COCKPIT_PASSWORD_HASH: {HASH}
      NEXUS_API_KEY: {CLE}
    mem_limit: 64m
  nexus-core:
    image: p1-nexus/nexus-core:local
    environment:
      DATABASE_URL: postgresql://nexus:{MDP}@postgres/nexus
    read_only: true
    user: "10001"
""", encoding="utf-8")
    (k / "Caddyfile.mvp").write_text(f"""{{$NEXUS_HOST}} {{
    header {{
        Strict-Transport-Security "max-age=31536000"
        X-Frame-Options DENY
    }}
    basic_auth {{
        decideur {HASH}
    }}
}}
""", encoding="utf-8")
    (k / "nexus-core" / "requirements.txt").write_text("fastapi==0.162.0\nuvicorn[standard]==0.54.0\n")
    return k


def lancer(kit, serveur, *args, **env):
    e = {**{k: v for k, v in os.environ.items() if not k.startswith(("NEXUS_", "NTFY_"))},
         "KIT_DIR": str(kit), "NEXUS_URL": serveur.url if serveur else "http://127.0.0.1:9",
         "NTFY_URL_HOTE": serveur.url if serveur else "", "INTERVALLE_S": "0", "DELAI_MAX_S": "20",
         "DOCKER_BIN": "docker-absent", "ETAT_DIR": str(kit / "etat"), **env}
    return subprocess.run(["bash", str(SCRIPT), *args], env=e, capture_output=True, text=True, timeout=60)


def test_syntaxe_bash():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_collecte_filtree_sans_secret(kit):
    r = lancer(kit, None, "--collecte")
    assert r.returncode == 0
    sortie = r.stdout
    for secret in (CLE, MDP, HASH, "$2a$"):
        assert secret not in sortie
    assert "image: caddy:2.8" in sortie and "service nexus-core:" in sortie and '- "443:443"' in sortie
    assert "read_only: true" in sortie and "mem_limit: 64m" in sortie
    assert "Strict-Transport-Security" in sortie and "basic_auth : présent" in sortie
    assert "fastapi==0.162.0" in sortie and "environment" not in sortie and "DATABASE_URL" not in sortie


def test_execution_complete(kit):
    s = FauxServeur()
    r = lancer(kit, s)
    assert r.returncode == 0, r.stderr
    assert [m["service"] for m in s.missions] == ["CYBER-FORTRESS/veille", "CYBER-FORTRESS/audit"]
    assert all(m["projet"] == "nexus" and m["fonctionnement"] == "F3" for m in s.missions)
    assert "caddy:2.8" in s.missions[1]["consigne"]
    corps = json.dumps(s.missions)
    assert CLE not in corps and MDP not in corps and HASH not in corps
    assert set(s.cles) == {CLE}  # clé transmise en en-tête
    assert len(s.ntfy) == 1 and s.ntfy[0]["corps"] == "Rapport cyber hebdo pret."
    assert s.ntfy[0]["clic"] == "https://nexus.exemple.fr/cockpit"
    log = (kit / "etat" / "veille-cyber.log").read_text()
    assert "Mission veille créée" in log and "Notification ntfy envoyée" in log
    for secret in (CLE, MDP, HASH):
        assert secret not in log and secret not in r.stderr


def test_idempotent_dans_la_semaine(kit):
    s = FauxServeur()
    assert lancer(kit, s).returncode == 0
    r = lancer(kit, s)
    assert r.returncode == 0 and len(s.missions) == 2 and len(s.ntfy) == 1
    assert "déjà traitée" in (kit / "etat" / "veille-cyber.log").read_text()


def test_delai_depasse_puis_reprise(kit):
    s = FauxServeur(statut_final="en_cours")
    r = lancer(kit, s, DELAI_MAX_S="1", INTERVALLE_S="1")
    assert r.returncode == 3 and len(s.missions) == 2 and s.ntfy == []
    s.statut_final = "terminee"
    r = lancer(kit, s)
    assert r.returncode == 0 and len(s.missions) == 2 and len(s.ntfy) == 1  # reprise sans recréer


def test_api_injoignable_et_config(kit):
    assert lancer(kit, None).returncode == 2
    (kit / ".env").write_text("NEXUS_HOST=nexus.exemple.fr\n")
    assert lancer(kit, FauxServeur()).returncode == 1


def test_cle_jamais_en_ligne_de_commande():
    texte = SCRIPT.read_text()
    assert '-H @"$TMP/entetes"' in texte and "umask 077" in texte
    assert not any("curl" in l and ("$CLE" in l or "NEXUS_API_KEY" in l) for l in texte.splitlines())
