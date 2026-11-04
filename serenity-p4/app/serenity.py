"""SERENITY P4 — service léger (bibliothèque standard Python uniquement, 0 €).

BROUILLON — généré par IA, à valider. Méthode : SERENITY Package V3.1 (consigne unique).
- 4 rôles : COLLECTOR → ANALYST → CHECKER → EXECUTOR (3 refus du CHECKER = ÉCHEC).
- Classement N0/N1/N2/ADMIN JÉRÉMY/REFUS ; jamais de baisse ; doute = niveau supérieur.
- Mini-structures : un profil par domaine (structures.json), dupliquable sans code.
- MNEMOS : mémoire commune SQLite, chaque entrée signée HMAC ; leçons proposées,
  acceptées SEULEMENT par le Décideur (jeton dédié), 5 leçons acceptées au plus.
- Aucune action externe : SERENITY produit des brouillons et des cartes, n'exécute rien.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICI = Path(__file__).parent
DONNEES = Path(os.environ.get("SERENITY_DATA", "/data"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
MODELE = os.environ.get("SERENITY_MODEL", "qwen2.5:3b")
CLE_HMAC = os.environ.get("SERENITY_HMAC_KEY", "").encode()
JETON_IA = os.environ.get("SERENITY_TOKEN", "")          # appels des IA / de nexus
JETON_DECIDEUR = os.environ.get("SERENITY_ADMIN_TOKEN", "")  # acceptation des leçons
MAX_LECONS = 5
MAX_REFUS = 3
MAX_CORPS = 64 * 1024
NIVEAUX = ["N0", "N1", "N2", "ADMIN JÉRÉMY"]

CONSIGNE = (ICI / "consigne_v3_1.txt").read_text(encoding="utf-8")
STRUCTURES = json.loads((ICI / "structures.json").read_text(encoding="utf-8"))

# --------------------------------------------------------------------------- règles
MOTS_ADMIN = re.compile(r"\b(pay|achat|acheter|d[ée]pens|cr[ée]dit|abonnement|contrat|sign|publi|envoy|envoi|"
                        r"supprim|effac|virement|facture|voix|visage)\w*", re.I)
MOTS_REFUS = re.compile(r"(je suis (le )?d[ée]cideur|baisse(r)? (le|un) niveau|ignore (les|tes) (r[èe]gles|consignes)|"
                        r"gains? garanti|d[ée]pense d[ée]j[àa] faite|public mineur)", re.I)
SECRETS = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|"
                     r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:mot de passe|password|passwd)\s*[:=]\s*\S+)")


def masquer(texte: str) -> str:
    return SECRETS.sub("[masqué]", texte or "")


def classer(demande: str, niveau_propose: str | None = None) -> dict:
    """Classement déterministe (garde-fou) ; le niveau ne peut jamais baisser."""
    if MOTS_REFUS.search(demande):
        return {"niveau": "REFUS", "motif": "ordre interdit (point 5 de la consigne)", "certitude": "haute"}
    niveau = "ADMIN JÉRÉMY" if MOTS_ADMIN.search(demande) else ("N1" if len(demande) > 40 else "N0")
    if niveau_propose in NIVEAUX and NIVEAUX.index(niveau_propose) > NIVEAUX.index(niveau):
        niveau = niveau_propose  # on peut monter, jamais descendre
    return {"niveau": niveau, "motif": "règles V3.1", "certitude": "moyenne"}


# --------------------------------------------------------------------------- LLM
def llm(systeme: str, message: str) -> str:
    corps = json.dumps({"model": MODELE, "stream": False, "options": {"num_ctx": 4096},
                        "messages": [{"role": "system", "content": systeme},
                                     {"role": "user", "content": message}]}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=corps,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["message"]["content"]


# --------------------------------------------------------------------------- MNEMOS
class Mnemos:
    def __init__(self, chemin: Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(chemin, check_same_thread=False)
        self.verrou = threading.Lock()
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS entrees(id INTEGER PRIMARY KEY, date TEXT, structure TEXT,
              tache TEXT, livrable TEXT, signaux TEXT, note INTEGER, lecon TEXT, sig TEXT);
            CREATE TABLE IF NOT EXISTS lecons(id INTEGER PRIMARY KEY, texte TEXT UNIQUE, vues INTEGER,
              statut TEXT DEFAULT 'CANDIDATE', sources TEXT DEFAULT '[]');
        """)

    @staticmethod
    def signer(champs: list) -> str:
        return hmac.new(CLE_HMAC, json.dumps(champs, ensure_ascii=False).encode(), hashlib.sha256).hexdigest()

    def ajouter(self, structure, tache, livrable, signaux, note, lecon) -> int:
        champs = [time.strftime("%Y-%m-%d %H:%M"), structure, masquer(tache)[:500],
                  masquer(livrable)[:2000], json.dumps(signaux), int(note), masquer(lecon or "")[:300]]
        with self.verrou:
            cur = self.con.execute("INSERT INTO entrees(date,structure,tache,livrable,signaux,note,lecon,sig)"
                                   " VALUES(?,?,?,?,?,?,?,?)", champs + [self.signer(champs)])
            if lecon:
                self._compter_lecon(masquer(lecon)[:300], structure)
            self.con.commit()
            return cur.lastrowid

    def _compter_lecon(self, texte, structure):
        ligne = self.con.execute("SELECT id, vues, sources FROM lecons WHERE texte=?", (texte,)).fetchone()
        if ligne:
            sources = sorted(set(json.loads(ligne[2]) + [structure]))
            vues = ligne[1] + 1
            statut = "PROPOSÉE" if vues >= 3 and len(sources) >= 2 else ("QUARANTAINE" if vues >= 3 else "CANDIDATE")
            self.con.execute("UPDATE lecons SET vues=?, sources=?, statut=CASE WHEN statut='ACCEPTÉE' "
                             "THEN statut ELSE ? END WHERE id=?", (vues, json.dumps(sources), statut, ligne[0]))
        else:
            self.con.execute("INSERT INTO lecons(texte,vues,sources) VALUES(?,1,?)", (texte, json.dumps([structure])))

    def verifier(self) -> dict:
        mauvaises = [r[0] for r in self.con.execute("SELECT * FROM entrees")
                     if not hmac.compare_digest(r[8], self.signer(list(r[1:8])))]
        return {"entrees": self.con.execute("SELECT COUNT(*) FROM entrees").fetchone()[0], "alterees": mauvaises}

    def chercher(self, mot: str, limite=5) -> list:
        return [dict(zip(("date", "structure", "tache", "note", "lecon"), r)) for r in self.con.execute(
            "SELECT date,structure,tache,note,lecon FROM entrees WHERE tache LIKE ? OR livrable LIKE ? "
            "ORDER BY id DESC LIMIT ?", (f"%{mot}%", f"%{mot}%", limite))]

    def lecons(self, statut=None) -> list:
        q = "SELECT id,texte,vues,statut,sources FROM lecons" + (" WHERE statut=?" if statut else "")
        return [dict(zip(("id", "texte", "vues", "statut", "sources"), r))
                for r in self.con.execute(q, (statut,) if statut else ())]

    def accepter(self, lecon_id: int) -> dict:
        with self.verrou:
            n = self.con.execute("SELECT COUNT(*) FROM lecons WHERE statut='ACCEPTÉE'").fetchone()[0]
            if n >= MAX_LECONS:
                return {"ok": False, "raison": f"{MAX_LECONS} leçons acceptées au maximum"}
            st = self.con.execute("SELECT statut FROM lecons WHERE id=?", (lecon_id,)).fetchone()
            if not st or st[0] != "PROPOSÉE":
                return {"ok": False, "raison": "seule une leçon PROPOSÉE (vue 3 fois, 2 sources) peut être acceptée"}
            self.con.execute("UPDATE lecons SET statut='ACCEPTÉE' WHERE id=?", (lecon_id,))
            self.con.commit()
            return {"ok": True}


# --------------------------------------------------------------------------- mission
def mission(m: Mnemos, demande: str, structure_id: str, appel_llm=llm) -> dict:
    demande = masquer(demande)[:4000]
    struct = STRUCTURES.get(structure_id) or STRUCTURES["generale"]
    classe = classer(demande, struct.get("niveau_min"))
    if classe["niveau"] == "REFUS":
        return {"classement": classe, "statut": "REFUS", "livrable": None}
    acceptees = "\n".join(f"- {l['texte']}" for l in m.lecons("ACCEPTÉE"))
    contexte = "\n".join(f"- {e['tache']} (note {e['note']})" for e in m.chercher(demande.split()[0] if demande else ""))
    systeme = f"{CONSIGNE}\n\nMODULE {struct['nom']} :\n{struct['module']}\n\nLEÇONS ACCEPTÉES :\n{acceptees or '- aucune'}"
    faits = appel_llm(systeme, f"RÔLE COLLECTOR. Liste les faits fournis et les sources, statut FAIT/NON TROUVÉ/SIMULÉ.\n"
                               f"Demande : {demande}\nHistorique MNEMOS :\n{contexte or '- vide'}")
    brouillon, retours = "", ""
    for essai in range(1, MAX_REFUS + 1):
        brouillon = appel_llm(systeme, f"RÔLE ANALYST. Utilise SEULEMENT ces faits.\nFaits :\n{faits}\n"
                                       f"Demande : {demande}\nCorrections demandées : {retours or 'aucune'}")
        verdict = appel_llm(systeme, "RÔLE CHECKER. Relis comme si un autre avait écrit. Réponds en JSON "
                                     '{"verdict":"accepte|refuse","problemes":[...]} (5 max).\n' + brouillon)
        try:
            v = json.loads(re.search(r"\{.*\}", verdict, re.S).group(0))
        except Exception:
            v = {"verdict": "refuse", "problemes": ["réponse du CHECKER illisible"]}
        if v.get("verdict") == "accepte":
            break
        retours = "; ".join(map(str, v.get("problemes", [])[:5]))
    else:
        m.ajouter(structure_id, demande, "ÉCHEC", ["REF"], 0, None)
        return {"classement": classe, "statut": "ÉCHEC", "livrable": None, "problemes": retours}
    livrable = "BROUILLON — généré par IA, à valider\n\n" + masquer(brouillon)
    signaux = ["COR"] if essai > 1 else []
    lecon = f"[{struct['nom']}] {retours.split(';')[0].strip()}" if retours else None
    eid = m.ajouter(structure_id, demande, livrable, signaux, 90 - 10 * (essai - 1), lecon)
    return {"classement": classe, "statut": "BROUILLON", "essais": essai, "livrable": livrable, "mnemos": eid,
            "carte_requise": classe["niveau"] == "ADMIN JÉRÉMY"}


# --------------------------------------------------------------------------- HTTP
class Gestion(BaseHTTPRequestHandler):
    server_version = "SERENITY/3.1"
    mnemos: Mnemos = None  # type: ignore

    def log_message(self, fmt, *args):  # journal sans contenu ni jeton
        print(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}", flush=True)

    def _rep(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _jeton(self, attendu) -> bool:
        recu = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return bool(attendu) and hmac.compare_digest(recu, attendu)

    def _corps(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > MAX_CORPS:
            raise ValueError("corps trop gros")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/sante":
            return self._rep(200, {"ok": True, "version": "3.1", "structures": len(STRUCTURES)})
        if not self._jeton(JETON_IA):
            return self._rep(401, {"erreur": "jeton requis"})
        if self.path == "/structures":
            return self._rep(200, {k: v["nom"] for k, v in STRUCTURES.items()})
        if self.path == "/lecons":
            return self._rep(200, self.mnemos.lecons())
        if self.path == "/mnemos/verifier":
            return self._rep(200, self.mnemos.verifier())
        return self._rep(404, {"erreur": "inconnu"})

    def do_POST(self):
        try:
            corps = self._corps()
        except Exception:
            return self._rep(400, {"erreur": "JSON invalide ou trop gros"})
        if self.path.startswith("/lecons/") and self.path.endswith("/accepter"):
            if not self._jeton(JETON_DECIDEUR):
                return self._rep(403, {"erreur": "réservé au Décideur"})
            return self._rep(200, self.mnemos.accepter(int(self.path.split("/")[2])))
        if not self._jeton(JETON_IA):
            return self._rep(401, {"erreur": "jeton requis"})
        if self.path == "/mission":
            try:
                return self._rep(200, mission(self.mnemos, str(corps.get("demande", "")), str(corps.get("structure", "generale"))))
            except Exception as e:  # LLM indisponible, etc.
                return self._rep(503, {"erreur": f"mission impossible : {type(e).__name__}"})
        if self.path == "/classer":
            return self._rep(200, classer(str(corps.get("demande", ""))))
        return self._rep(404, {"erreur": "inconnu"})


def main():
    if len(CLE_HMAC) < 32 or len(JETON_IA) < 24 or len(JETON_DECIDEUR) < 24:
        raise SystemExit("SERENITY_HMAC_KEY / SERENITY_TOKEN / SERENITY_ADMIN_TOKEN manquants ou trop courts")
    Gestion.mnemos = Mnemos(DONNEES / "mnemos.db")
    ThreadingHTTPServer(("0.0.0.0", 8100), Gestion).serve_forever()


if __name__ == "__main__":
    main()
