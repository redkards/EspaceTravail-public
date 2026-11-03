"""Jumeau numérique de SYFER V2 — simulateur de performance et de capacité.

Simulation à événements discrets + Monte Carlo (graine fixe). Python 3 standard uniquement.

Ce qui est modélisé (voir README.md) :
- arrivée des missions : manuelles (profil horaire), pilote hebdomadaire (lundi 07:30), banc d'essai
  (dimanche 04:17), veille (03:17), audits SYFER, tests fantômes de nuit ;
- pipeline réel de nexus-core/app/pipeline.py : PRIME (LLM si égalité) → COLLECTOR → ANALYST ⇄ CHECKER
  (+ double contrôle F3/F4 par le modèle local) → révisions (F1 0, F2 1, F3 2, F4 3) → escalade au
  directeur (relance possible) → GATE (règles + avis LLM) → relèvement F1→F2 si N2/N3 → N3 / EXECUTOR ;
- plafonds réels de fonctionnement.yaml : budget tokens, délai max, coût max F4 ;
- file FIFO bornée par NEXUS_MAX_MISSIONS, priorité jour/nuit (option V2) ;
- modèle local : vitesse prefill + génération selon taille et vCPU, 1 appel par modèle à la fois
  (OLLAMA_NUM_PARALLEL=1), partage du CPU entre modèles, chargement/déchargement (keep-alive, RAM) ;
- cloud gratuit : latence, quota journalier, pannes → repli local ; IA payante F4 plafonnée/mois ;
- Décideur : sessions 12:30/19:00, plafond 15 fiches/jour, expiration 24 h, révisions demandées ;
- redémarrages du serveur (missions relancées, modèles déchargés).
"""
from __future__ import annotations

import heapq
import json
import math
import os
import random
from collections import deque

ICI = os.path.dirname(os.path.abspath(__file__))
MINUTE, HEURE, JOUR = 60.0, 3600.0, 86400.0
ORDRE_F = ["F1", "F2", "F3", "F4"]
NIVEAUX_N = ["N0", "N1", "N2", "N3"]
LOCAUX = ("3b", "7b", "8b")
SOURCES_NUIT = ("banc", "audit", "veille", "fantome")


# --------------------------------------------------------------------------- chargement

def _scalaire(v: str):
    v = v.strip()
    if v == "" or v in ("null", "~"):
        return None
    if v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if v.lower() in ("true", "yes", "oui"):
        return True
    if v.lower() in ("false", "no", "non"):
        return False
    if v.startswith("[") and v.endswith("]"):
        return [_scalaire(x) for x in v[1:-1].split(",") if x.strip()]
    for typ in (int, float):
        try:
            return typ(v)
        except ValueError:
            pass
    return v


def lire_yaml(texte: str):
    """Lecteur YAML minimal (mappings, listes « - », scalaires, listes en ligne). PyYAML si présent."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(texte)
    except ImportError:
        pass
    lignes = []
    for brute in texte.splitlines():
        sans = brute.split(" #")[0].rstrip() if not brute.lstrip().startswith("#") else ""
        if sans.strip():
            lignes.append((len(sans) - len(sans.lstrip()), sans.strip()))

    def bloc(i, indent):
        if lignes[i][1].startswith("- "):
            res = []
            while i < len(lignes) and lignes[i][0] == indent and lignes[i][1].startswith("- "):
                contenu = lignes[i][1][2:]
                if ":" in contenu and not contenu.startswith(("\"", "'")):
                    lignes[i] = (indent + 2, contenu)
                    val, i = bloc(i, indent + 2)
                else:
                    val, i = _scalaire(contenu), i + 1
                res.append(val)
            return res, i
        res = {}
        while i < len(lignes) and lignes[i][0] == indent:
            cle, _, reste = lignes[i][1].partition(":")
            if reste.strip():
                res[cle.strip()] = _scalaire(reste)
                i += 1
            elif i + 1 < len(lignes) and lignes[i + 1][0] > indent:
                res[cle.strip()], i = bloc(i + 1, lignes[i + 1][0])
            else:
                res[cle.strip()] = None
                i += 1
        return res, i

    return bloc(0, lignes[0][0])[0] if lignes else {}


def charger_hypotheses(chemin: str | None = None) -> dict:
    with open(chemin or os.path.join(ICI, "hypotheses.json"), encoding="utf-8") as f:
        return json.load(f)


def charger_scenarios(chemin: str | None = None) -> list[dict]:
    with open(chemin or os.path.join(ICI, "scenarios.yaml"), encoding="utf-8") as f:
        doc = lire_yaml(f.read())
    defaut = doc.get("defaut", {})
    res = []
    for s in doc["scenarios"]:
        sc = dict(defaut)
        sc.update(s)
        sc["surcharges"] = dict(s.get("surcharges") or {})
        res.append(sc)
    return res


def triangulaire(rng: random.Random, mn: float, pr: float, mx: float) -> float:
    if mx <= mn:
        return pr
    return rng.triangular(mn, mx, min(max(pr, mn), mx))


def tirer_parametres(hyp: dict, rng: random.Random | None, surcharges: dict | None = None) -> dict:
    """rng=None → valeurs « probables » ; sinon tirage triangulaire (min, probable, max)."""
    P = {}
    for cle, d in sorted(hyp["parametres"].items()):
        P[cle] = d["probable"] if rng is None else triangulaire(rng, d["min"], d["probable"], d["max"])
    for cle, v in (surcharges or {}).items():
        if cle not in P:
            raise KeyError(f"surcharge inconnue : {cle}")
        P[cle] = v
    return P


def graine(base: int, tirage: int, flux: int) -> int:
    return (base * 1_000_003 + tirage * 7_919 + flux * 104_729) & 0xFFFFFFFF


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def pct(valeurs: list[float], q: float) -> float | None:
    if not valeurs:
        return None
    v = sorted(valeurs)
    pos = (len(v) - 1) * q
    a, b = int(math.floor(pos)), int(math.ceil(pos))
    return v[a] + (v[b] - v[a]) * (pos - a)


# --------------------------------------------------------------------------- vitesses

def vitesses_locales(P: dict, fixes: dict, modele: str, cpus: float) -> tuple[float, float]:
    """(prefill tok/s, génération tok/s) d'un modèle local sur `cpus` vCPU dédiés au LLM."""
    taille = fixes["taille_modele_md"][modele]
    r = cpus / 1.1
    k = (3.1 / taille) ** P["vitesse.expo_taille"]
    return (P["vitesse.prefill_ref_tok_s"] * r ** P["vitesse.expo_cpu_prefill"] * k,
            P["vitesse.gen_ref_tok_s"] * r ** P["vitesse.expo_cpu_gen"] * k)


def duree_appel_local(P, fixes, modele, cpus, t_in, t_out, prefixe=0.0) -> float:
    pre, gen = vitesses_locales(P, fixes, modele, cpus)
    return P["vitesse.surcout_appel_s"] + t_in * (1 - prefixe) / pre + t_out / gen


def calage(P: dict, fixes: dict) -> list[dict]:
    """Rejoue les deux missions mesurées (3B, KVM 2, 1,1 vCPU) avec les tokens « probables ».

    Chemins reconstitués (hypothèse) :
    - checklist N1 F1, taille 0,55 : COLLECTOR, ANALYST, CHECKER (ok), GATE ;
    - post Poker Feeling F1, taille 1,25 : PRIME, COLLECTOR, ANALYST, CHECKER (refus), directeur,
      relance ANALYST, CHECKER → budget F1 (6 000) dépassé.
    """
    def tok(role, taille, livrable=0.0):
        return (P[f"tokens.{role}.entree"] * taille + livrable, P[f"tokens.{role}.sortie"] * taille)

    res = []
    for nom, taille, chemin, mesure_s, mesure_tok in (
            ("checklist N1", 0.55, ["collector", "analyst", "checker", "gate"], 131, 1611),
            ("post Poker Feeling", 1.25, ["prime", "collector", "analyst", "checker", "directeur", "analyst", "checker"],
             480, 6396)):
        duree = tokens = 0.0
        sortie_collector = sortie_analyst = 0.0
        for role in chemin:
            extra = sortie_collector if role == "analyst" else (
                sortie_analyst if role in ("checker", "gate", "directeur") else 0.0)
            t_in, t_out = tok(role, taille, extra)
            if role == "collector":
                sortie_collector = t_out
            if role == "analyst":
                sortie_analyst = t_out
            duree += duree_appel_local(P, fixes, "3b", 1.1, t_in, t_out)
            tokens += t_in + t_out
        res.append({"mission": nom, "duree_s": round(duree, 1), "mesure_s": mesure_s,
                    "tokens": round(tokens), "mesure_tokens": mesure_tok,
                    "ecart_duree": round(duree / mesure_s - 1, 3), "ecart_tokens": round(tokens / mesure_tok - 1, 3)})
    return res


# --------------------------------------------------------------------------- mission

class Mission:
    __slots__ = ("id", "source", "famille", "f", "f_demande", "n", "arrivee", "taille", "preclasse", "pilote",
                 "fantome", "etat", "gen", "epoch", "appel", "debut", "debut_premier", "deadline", "tokens",
                 "cout", "revisions", "relances", "bon", "modele_analyst", "sortie_analyst", "livre_t", "fin_t",
                 "rev_proprio", "en_revision", "au_dessus_plafond", "lancement_f4", "f4_ok", "plan_id", "nb_appels",
                 "tok_local", "tok_cloud", "tok_payant")

    def __init__(self, mid, source, famille, f, n, arrivee, taille):
        self.id, self.source, self.famille, self.f, self.f_demande = mid, source, famille, f, f
        self.n, self.arrivee, self.taille = n, arrivee, taille
        self.preclasse = True
        self.pilote = self.fantome = False
        self.etat = "en_file"
        self.gen = None
        self.epoch = self.appel = 0
        self.debut = self.debut_premier = self.deadline = None
        self.tokens = self.cout = 0.0
        self.revisions = self.relances = self.rev_proprio = 0
        self.bon = False
        self.modele_analyst = None
        self.sortie_analyst = 0.0
        self.livre_t = self.fin_t = None
        self.en_revision = self.au_dessus_plafond = self.lancement_f4 = False
        self.f4_ok = True
        self.plan_id = None
        self.nb_appels = 0
        self.tok_local = self.tok_cloud = self.tok_payant = 0.0


class Abandon(Exception):
    pass


# --------------------------------------------------------------------------- simulation

class Simulation:
    def __init__(self, sc: dict, P: dict, hyp: dict, base: int = 2026, tirage: int = 0, jours: int = 30,
                 trace_jours: int = 7):
        self.sc, self.P, self.fx = sc, P, hyp["fixes"]
        self.jours, self.T = jours, jours * JOUR
        self.trace_jours = trace_jours
        self.r_arr = random.Random(graine(base, tirage, 1))
        self.r_svc = random.Random(graine(base, tirage, 2))
        self.r_pan = random.Random(graine(base, tirage, 3))
        self.r_dec = random.Random(graine(base, tirage, 4))
        self.r_tok = random.Random(graine(base, tirage, 5))
        self.t = 0.0
        self.ev: list = []
        self.seq = 0
        self.missions: list[Mission] = []
        self.file: deque = deque()
        self.actifs: dict[int, Mission] = {}
        self.K = int(sc["max_missions"])
        self.v2 = bool(sc["v2"])
        offre = sc["offre"]
        self.vcpu = self.fx["offres"][offre]["vcpu"]
        self.cpus = P[f"offre.{offre}.cpus_llm"]
        self.ram_limite = P[f"offre.{offre}.ram_p1_go"]
        self.m_princ, self.m_ctrl = sc["modele_principal"], sc["modele_controleur"]
        modeles = sorted({self.m_princ, self.m_ctrl}, key=lambda m: -P[f"modele.{m}.ram_go"])
        base_ram = P["ram.services_go"]
        self.n_charges, cumul = 0, base_ram
        for m in modeles:
            if cumul + P[f"modele.{m}.ram_go"] <= self.ram_limite + 1e-9:
                cumul += P[f"modele.{m}.ram_go"]
                self.n_charges += 1
        self.ram_depasse = self.n_charges == 0
        self.n_charges = max(1, self.n_charges)
        self.ram_pic = base_ram
        # Modèle local : file d'appels, travaux en cours (partage du CPU), modèles chargés.
        self.lfile: deque = deque()
        self.ljobs: dict[int, list] = {}
        self.lt, self.lver = 0.0, 0
        self.charges: dict[str, float] = {}  # modèle → dernier usage
        self.occupe_s = 0.0
        self.occupe_pond = 0.0
        # Cloud gratuit
        self.pannes_cloud = self._tirer_pannes_cloud()
        self.cloud_jour: dict[int, float] = {}
        # Payant
        self.depense_mois = 0.0
        # Serveur
        self.hors_service_jusqua = -1.0
        self.redemarrages = 0
        # Décideur
        self.dec_attente: list[dict] = []
        self.dec_plafond: deque = deque()
        self.dec_crees_jour: dict[int, int] = {}
        self.decisions: list[dict] = []
        self.plans: dict[int, dict] = {}
        # Traces
        self.trace_file: list[int] = []
        self.trace_actifs: list[int] = []
        self.cache_hits = 0

    # ----------------------------------------------------------------- événements
    def pousser(self, t, typ, data=None):
        self.seq += 1
        heapq.heappush(self.ev, (t, self.seq, typ, data))

    def executer(self) -> dict:
        self._planifier_arrivees()
        self._planifier_cycles()
        while self.ev:
            t, _, typ, data = heapq.heappop(self.ev)
            if t > self.T:
                break
            self.t = t
            getattr(self, "_ev_" + typ)(data)
        self.t = self.T
        self._ps_avancer()
        return self.mesures()

    # ----------------------------------------------------------------- arrivées
    def _famille(self, rng, table=None):
        fam = table or {k: v["poids"] for k, v in self.fx["familles"].items() if not k.startswith("_")}
        total = sum(v for k, v in fam.items() if not k.startswith("_"))
        x = rng.random() * total
        for k, v in fam.items():
            if k.startswith("_"):
                continue
            x -= v
            if x <= 0:
                return k
        return k

    def _niveau_n(self, rng, famille):
        x, acc = rng.random(), 0.0
        for i, p in enumerate(self.fx["familles"][famille]["N"]):
            acc += p
            if x <= acc:
                return NIVEAUX_N[i]
        return "N1"

    def _taille(self, rng, famille):
        return math.exp(rng.gauss(0, self.P["tokens.taille_sigma"])) * self.fx["familles"][famille]["taille"]

    def _creer(self, t, source, famille=None, f="F2", n=None, rng=None) -> Mission:
        rng = rng or self.r_arr
        famille = famille or self._famille(rng)
        n = n or self._niveau_n(rng, famille)
        m = Mission(len(self.missions), source, famille, f, n, t, self._taille(rng, famille))
        x_plancher, x_pre = rng.random(), rng.random()
        if x_plancher < self.fx["familles"][famille]["plancher_f3"]:
            m.f = max(m.f, "F3", key=ORDRE_F.index)
        if n in ("N2", "N3"):
            m.preclasse = x_pre < self.P["gate.p_preclassement"]
            if m.preclasse:
                m.f = max(m.f, "F2", key=ORDRE_F.index)
        self.missions.append(m)
        return m

    def _f_manuel(self, rng):
        x = rng.random()
        P = self.P
        if x < P["mix.p_F1"]:
            return "F1"
        if x < P["mix.p_F1"] + P["mix.p_F3"]:
            return "F3"
        if x < P["mix.p_F1"] + P["mix.p_F3"] + P["mix.p_F4"]:
            return "F4"
        return "F2"

    def _manuel(self, t, rng=None):
        rng = rng or self.r_arr
        f = self._f_manuel(rng)
        x_pub = rng.random()
        m = self._creer(t, "manuel", f=f, rng=rng)
        if x_pub < self.P["gate.p_publication"]:
            m.n = "N3"
            if m.preclasse is True or rng.random() < self.P["gate.p_preclassement"]:
                m.preclasse = True
                m.f = max(m.f, "F2", key=ORDRE_F.index)
            else:
                m.preclasse = False
        return m

    def _heure_profil(self, rng):
        plages = self.fx["profil_horaire_manuel"]["heures"]
        x = rng.random() * sum(p[2] for p in plages)
        for a, b, w in plages:
            x -= w
            if x <= 0:
                return rng.uniform(a, b)
        return rng.uniform(plages[-1][0], plages[-1][1])

    def _planifier_arrivees(self):
        P, fx, sc, rng = self.P, self.fx, self.sc, self.r_arr
        cloud_prevu = bool(sc["cloud_gratuit"])
        for j in range(self.jours):
            jour_sem = j % 7  # jour 0 = lundi
            lam = (P["arrivees.manuel_jour_ouvre"] if jour_sem < 5 else P["arrivees.manuel_weekend"]) * sc["charge"]
            for _ in range(poisson(rng, lam)):
                self.pousser(j * JOUR + self._heure_profil(rng) * HEURE, "arrivee", ("manuel", None))
            if jour_sem == 0 and sc.get("pic_lundi"):
                for _ in range(int(sc["pic_lundi"])):
                    self.pousser(j * JOUR + rng.uniform(8, 10) * HEURE, "arrivee", ("manuel", None))
            if jour_sem == 0:
                self.pousser(j * JOUR + fx["pilote"]["heure"] * HEURE, "pilote", None)
            nuit_chargee = sc.get("nuit_chargee") and jour_sem == 6
            nb_veille = int(round(P["arrivees.veille_jour"])) * (3 if nuit_chargee else 1)
            for _ in range(nb_veille):
                self.pousser(j * JOUR + fx["veille"]["heure"] * HEURE, "arrivee",
                             ("veille", {"famille": "CYBER-FORTRESS", "f": "F2"}))
            if jour_sem == 6:
                nb = 30 if nuit_chargee else fx["banc"]["missions"]
                f_banc = "F2" if cloud_prevu else "F1"
                for _ in range(nb):
                    self.pousser(j * JOUR + fx["banc"]["heure"] * HEURE, "arrivee", ("banc", {"f": f_banc}))
            periode = max(1, int(round(P["arrivees.audit_periode_j"])))
            if nuit_chargee or (not sc.get("nuit_chargee") and j % periode == 5):
                for _ in range(fx["audit"]["missions"]):
                    self.pousser(j * JOUR + fx["audit"]["heure"] * HEURE, "arrivee", ("audit", None))
            if rng.random() < P["arrivees.fantome_p_nuit"]:
                for _ in range(fx["fantome"]["executions"]):
                    self.pousser(j * JOUR + fx["nuit"]["debut_h"] * HEURE, "arrivee", ("fantome", None))

    def _planifier_cycles(self):
        fx = self.fx
        for j in range(self.jours):
            for h in fx["n3"]["sessions_h"]:
                self.pousser(j * JOUR + h * HEURE, "session", None)
        for hh in range(self.jours * 24):
            self.pousser(hh * HEURE + 1e-3, "heure", hh)
        # Redémarrages du serveur (processus de Poisson)
        taux = self.P["pannes.redemarrages_mois"] / (30 * JOUR)
        t = 0.0
        while taux > 0:
            t += self.r_pan.expovariate(taux)
            if t >= self.T:
                break
            self.pousser(t, "redemarrage", self.P["pannes.duree_redemarrage_min"] * MINUTE)

    def _tirer_pannes_cloud(self):
        pannes = []
        if self.sc.get("panne_cloud_duree_j"):
            d = self.sc["panne_cloud_debut_j"] * JOUR
            pannes.append((d, d + self.sc["panne_cloud_duree_j"] * JOUR))
        taux = self.P["cloud.pannes_mois"] / (30 * JOUR)
        t = 0.0
        while taux > 0:
            t += self.r_pan.expovariate(taux)
            if t >= self.T:
                break
            duree = math.exp(self.r_pan.gauss(math.log(self.P["cloud.duree_panne_h"]), 0.6)) * HEURE
            pannes.append((t, t + duree))
        return pannes

    # ----------------------------------------------------------------- gestion des arrivées
    def _ev_arrivee(self, data):
        source, opts = data
        opts = opts or {}
        if source == "manuel":
            m = self._manuel(self.t)
        elif source == "audit":
            fam = self._famille(self.r_arr, {k: v for k, v in self.fx["mix_audit"].items()})
            n = "N3" if self.r_arr.random() < self.fx["mix_audit"]["_p_n3"] else self._niveau_n(self.r_arr, fam)
            m = self._creer(self.t, "audit", famille=fam, f="F2", n=n)
            m.taille *= 1.15
        elif source == "fantome":
            m = self._creer(self.t, "fantome", f="F2")
            m.fantome = True
        else:
            m = self._creer(self.t, source, famille=opts.get("famille"), f=opts.get("f", "F2"))
        self._admettre(m)

    def _admettre(self, m: Mission):
        if m.f == "F4":
            if self.sc["payant_plafond_eur"] > 0:
                m.lancement_f4 = True
                m.etat = "attente_lancement_f4"
                self._creer_decision(m, "lancement_f4")
                return
            m.f = "F3"  # pas d'IA payante : repli F3 (gratuit)
            m.f4_ok = False
        self._enfiler(m)

    def _enfiler(self, m: Mission, devant=False):
        m.etat = "en_file"
        (self.file.appendleft if devant else self.file.append)(m)
        self._demarrer()

    def _ev_pilote(self, _):
        n = self.fx["pilote"]["projets_actifs"]
        pid = len(self.plans)
        self.plans[pid] = {"restant": n, "ok": 0}
        for _ in range(n):
            m = self._creer(self.t, "pilote", famille="PILOT-CORE", f="F2", n="N1")
            m.pilote, m.plan_id = True, pid
            self._enfiler(m)

    def _plan_fini(self, m: Mission, ok: bool):
        plan = self.plans[m.plan_id]
        plan["restant"] -= 1
        plan["ok"] += 1 if ok else 0
        if plan["restant"] == 0 and plan["ok"] > 0:
            d = Mission(len(self.missions), "plan", "PILOT-CORE", "F2", "N3", self.t, 0)
            d.etat, d.livre_t, d.plan_id = "n3_en_attente", self.t, m.plan_id
            self.missions.append(d)
            self._creer_decision(d, "plan")

    # ----------------------------------------------------------------- file et démarrage
    def _de_nuit(self):
        h = (self.t % JOUR) / HEURE
        return self.fx["nuit"]["debut_h"] <= h < self.fx["nuit"]["fin_h"]

    def _choisir(self) -> Mission | None:
        if not self.file:
            return None
        if not self.sc["priorite_jour"]:
            return self.file.popleft()
        for m in self.file:
            if m.source not in SOURCES_NUIT:
                self.file.remove(m)
                return m
        if self._de_nuit():
            return self.file.popleft()
        return None

    def _demarrer(self):
        if self.t < self.hors_service_jusqua:
            return
        while len(self.actifs) < self.K:
            m = self._choisir()
            if m is None:
                return
            m.epoch += 1
            m.appel = 0
            m.debut = self.t
            if m.debut_premier is None:
                m.debut_premier = self.t
            if m.f == "F4" and not m.en_revision:
                est = self.fx["f4_cout_estime_eur"]
                if self.depense_mois + est > self.sc["payant_plafond_eur"]:
                    m.f, m.f4_ok = "F3", False  # _verifier_f4_au_lancement : repli F3
            m.etat = "en_cours"
            self.actifs[m.id] = m
            self._armer_delai(m)
            m.gen = self._revision(m) if m.en_revision else self._processus(m)
            self._avancer(m, None)

    def _niveau(self, m):
        return self.fx["fonctionnement"][m.f]

    def _armer_delai(self, m):
        m.deadline = m.debut + self._niveau(m)["delai_max_s"]
        self.pousser(m.deadline, "delai", (m.id, m.epoch))

    def _relever(self, m, cible):
        if ORDRE_F.index(cible) > ORDRE_F.index(m.f):
            m.f = cible
            self._armer_delai(m)
            return True
        return False

    # ----------------------------------------------------------------- moteur des processus
    def _avancer(self, m: Mission, valeur):
        try:
            req = m.gen.send(valeur)
        except StopIteration as fin:
            self._fin_pipeline(m, fin.value)
            return
        except Abandon as e:
            self._abandonner(m, str(e))
            return
        m.appel += 1
        if req[0] == "code":
            self.pousser(self.t + req[1], "reprise", (m.id, m.epoch, m.appel, None))
        else:
            self._lancer_appel(m, req[1], req[2], req[3])

    def _ev_reprise(self, data):
        mid, epoch, appel, info = data
        m = self.missions[mid]
        if m.etat != "en_cours" or m.epoch != epoch or m.appel != appel:
            return
        if info is not None:
            self._compter(m, info)
            if m.etat != "en_cours":
                return
        self._avancer(m, info)

    def _ev_delai(self, data):
        mid, epoch = data
        m = self.missions[mid]
        if m.etat == "en_cours" and m.epoch == epoch and self.t >= m.deadline - 1e-6:
            self._abandonner(m, "delai")

    # ----------------------------------------------------------------- appels LLM
    def _route(self, m: Mission, role: str):
        if role == "checker_local":
            return "local", self.m_ctrl
        local = self.m_ctrl if role == "checker" else self.m_princ
        if m.f == "F1":
            return "local", local
        if m.f == "F4":
            mod = self.fx["f4_modeles"].get(role, self.fx["f4_modeles"]["defaut"])
            return "payant", mod
        if m.f == "F3" and self.sc["payant_f3"] and self.depense_mois < self.sc["payant_plafond_eur"]:
            return "payant", "haiku"
        if self.sc["cloud_gratuit"]:
            return "cloud", "cloud"
        return "local", local

    def _cloud_dispo(self) -> bool:
        if any(a <= self.t < b for a, b in self.pannes_cloud):
            return False
        return self.cloud_jour.get(int(self.t // JOUR), 0.0) < self.P["cloud.quota_tokens_jour"]

    def _lancer_appel(self, m: Mission, role: str, t_in: float, t_out: float):
        P = self.P
        m.nb_appels += 1
        cache_roles = ("prime", "collector", "gate", "directeur", "analyst")
        if self.v2 and role in cache_roles and not m.fantome and self.r_svc.random() < P["v2.cache_taux"]:
            self.cache_hits += 1
            self.pousser(self.t + 0.2, "reprise", (m.id, m.epoch, m.appel,
                                                    {"modele": m.modele_analyst or self.m_princ, "route": "cache",
                                                     "t_in": 0.0, "t_out": 0.0}))
            return
        route, modele = self._route(m, role)
        attente = 0.0
        if route == "cloud" and not self._cloud_dispo():
            route, modele = "local", (self.m_ctrl if role == "checker" else self.m_princ)
            attente = P["cloud.delai_bascule_s"]
        info = {"modele": modele, "route": route, "t_in": t_in, "t_out": t_out}
        if route == "cloud":
            d = P["cloud.latence_s"] + t_in / P["cloud.prefill_tok_s"] + t_out / P["cloud.gen_tok_s"]
            self.pousser(self.t + d, "reprise", (m.id, m.epoch, m.appel, info))
        elif route == "payant":
            tarifs = self.fx["tarifs_usd_par_mtok"][modele]
            prevu = (t_in * tarifs["entree"] + 2 * t_out * tarifs["sortie"]) / 1e6 * self.fx["eur_par_usd"]
            if m.cout + prevu > self.fx["fonctionnement"]["F4"]["cout_max_eur"]:
                self._abandonner(m, "cout")
                return
            d = P[f"payant.{modele}_latence_s"] + t_out / P[f"payant.{modele}_gen_tok_s"]
            self.pousser(self.t + d, "reprise", (m.id, m.epoch, m.appel, info))
        else:
            prefixe = P["v2.cache_prefixe"] if self.v2 else 0.0
            travail = duree_appel_local(P, self.fx, modele, self.cpus, t_in, t_out, prefixe)
            if attente:
                self.pousser(self.t + attente, "local_differe", (m.id, m.epoch, m.appel, modele, travail, info))
            else:
                self._local_enfiler(m, modele, travail, info)

    def _ev_local_differe(self, data):
        mid, epoch, appel, modele, travail, info = data
        m = self.missions[mid]
        if m.etat == "en_cours" and m.epoch == epoch and m.appel == appel:
            self._local_enfiler(m, modele, travail, info)

    def _compter(self, m: Mission, info: dict):
        tok = info["t_in"] + info["t_out"]
        m.tokens += tok
        r = info["route"]
        if r == "local":
            m.tok_local += tok
        elif r == "cloud":
            m.tok_cloud += tok
            j = int(self.t // JOUR)
            self.cloud_jour[j] = self.cloud_jour.get(j, 0.0) + tok
        elif r == "payant":
            tarifs = self.fx["tarifs_usd_par_mtok"][info["modele"]]
            c = (info["t_in"] * tarifs["entree"] + info["t_out"] * tarifs["sortie"]) / 1e6 * self.fx["eur_par_usd"]
            m.cout += c
            m.tok_payant += tok
            self.depense_mois += c
        if m.tokens > self._niveau(m)["budget_tokens"]:
            self._abandonner(m, "budget")

    # ----------------------------------------------------------------- modèle local (partage du CPU)
    def _ps_avancer(self):
        dt = self.t - self.lt
        if dt > 0 and self.ljobs:
            n = len(self.ljobs)
            r = n ** (-self.P["vitesse.expo_partage"])
            for j in self.ljobs.values():
                j[0] -= dt * r
            self.occupe_s += dt
            self.occupe_pond += dt * min(1.0, n * r)
        self.lt = self.t

    def _ps_planifier(self):
        self.lver += 1
        if self.ljobs:
            r = len(self.ljobs) ** (-self.P["vitesse.expo_partage"])
            reste = min(j[0] for j in self.ljobs.values())
            self.pousser(self.t + max(0.0, reste) / r, "ps", self.lver)

    def _local_enfiler(self, m, modele, travail, info):
        self._ps_avancer()
        self.lfile.append((m.id, m.epoch, m.appel, modele, travail, info))
        self._local_dispatch()
        self._ps_planifier()

    def _local_dispatch(self):
        keep = self.P["vitesse.keep_alive_min"] * MINUTE
        for mod, last in list(self.charges.items()):
            if self.t - last > keep and all(j[1] != mod for j in self.ljobs.values()):
                del self.charges[mod]
        restants = deque()
        while self.lfile:
            mid, epoch, appel, modele, travail, info = self.lfile.popleft()
            m = self.missions[mid]
            if m.etat != "en_cours" or m.epoch != epoch or m.appel != appel:
                continue
            en_cours = {j[1] for j in self.ljobs.values()}
            if modele in en_cours or (modele not in en_cours and len(en_cours) >= self.n_charges):
                restants.append((mid, epoch, appel, modele, travail, info))
                continue
            if modele not in self.charges:
                while len(self.charges) >= self.n_charges:
                    libre = [k for k in self.charges if k not in en_cours]
                    if not libre:
                        break
                    del self.charges[min(libre, key=lambda k: self.charges[k])]
                travail += self.P[f"modele.{modele}.ram_go"] / self.P["vitesse.disque_go_s"] + 2.0
            self.charges[modele] = self.t
            ram = self.P["ram.services_go"] + sum(self.P[f"modele.{k}.ram_go"] for k in self.charges)
            self.ram_pic = max(self.ram_pic, ram)
            self.ljobs[mid] = [travail, modele, epoch, appel, info]
        self.lfile = restants

    def _ev_ps(self, ver):
        if ver != self.lver:
            return
        self._ps_avancer()
        finis = [mid for mid, j in self.ljobs.items() if j[0] <= 1e-6]
        a_reprendre = []
        for mid in finis:
            j = self.ljobs.pop(mid)
            self.charges[j[1]] = self.t
            a_reprendre.append((mid, j))
        self._local_dispatch()
        self._ps_planifier()
        for mid, j in a_reprendre:
            m = self.missions[mid]
            if m.etat == "en_cours" and m.epoch == j[2] and m.appel == j[3]:
                self._compter(m, j[4])
                if m.etat == "en_cours":
                    self._avancer(m, j[4])

    def _local_retirer(self, mid):
        self._ps_avancer()
        if mid in self.ljobs:
            del self.ljobs[mid]
        self.lfile = deque(x for x in self.lfile if x[0] != mid)
        self._local_dispatch()
        self._ps_planifier()

    # ----------------------------------------------------------------- logique du pipeline
    def _tokens(self, role, m, entree_extra=0.0, facteur_sortie=1.0):
        P, bruit = self.P, math.exp(self.r_tok.gauss(0, 0.2))
        t_in = (P[f"tokens.{role}.entree"] * m.taille + entree_extra) * bruit
        t_out = P[f"tokens.{role}.sortie"] * m.taille * bruit * facteur_sortie
        return t_in, t_out

    def _q(self, modele, m, bonus=0.0):
        q = self.P[f"modele.{modele}.q"] + self.fx["familles"][m.famille]["dq"] + bonus
        if self.v2:
            q += self.P["v2.gabarit_gain_q"]
        return min(0.98, max(0.02, q))

    def _sortie_analyst(self):
        return self.P["v2.gabarit_sortie"] if self.v2 else 1.0

    def _brouillon(self, m, info, bonus=0.0):
        m.modele_analyst = info["modele"]
        m.sortie_analyst = info["t_out"] or m.sortie_analyst or self.P["tokens.analyst.sortie"] * m.taille
        m.bon = self.r_svc.random() < self._q(info["modele"], m, bonus)

    def _processus(self, m: Mission):
        rng, P = self.r_svc, self.P
        yield ("code", 1.0)  # SENTINEL, PRIME par mots-clés, planchers
        if rng.random() < P["arrivees.p_prime_llm"]:
            yield ("llm", "prime", *self._tokens("prime", m))
        extra = 0.0
        if self.v2:
            extra = P["v2.collector_extra_in"] * m.taille
            yield ("code", 0.5)
        else:
            info = yield ("llm", "collector", *self._tokens("collector", m))
            extra = info["t_out"] if info["t_out"] else P["tokens.collector.sortie"] * m.taille
        info = yield ("llm", "analyst", *self._tokens("analyst", m, extra, self._sortie_analyst()))
        self._brouillon(m, info)
        return (yield from self._boucle(m))

    def _revision(self, m: Mission):
        """« Demander une révision » du Décideur : ANALYST puis boucle qualité."""
        yield ("code", 1.0)
        info = yield ("llm", "analyst", *self._tokens("analyst", m, m.sortie_analyst + 150, self._sortie_analyst()))
        self._brouillon(m, info, self.P["qualite.gain_revision"])
        return (yield from self._boucle(m))

    def _controle(self, m: Mission):
        rng, P = self.r_svc, self.P
        mauvais = not m.bon
        if self.v2:
            yield ("code", 0.5)
            if mauvais and rng.random() < P["v2.detection_code"]:
                return False
        info = yield ("llm", "checker", *self._tokens("checker", m, m.sortie_analyst))
        if not self._verdict(info["modele"], m, mauvais):
            return False
        if self._niveau(m)["double_controle"]:
            info2 = yield ("llm", "checker_local", *self._tokens("checker", m, m.sortie_analyst))
            if not self._verdict(info2["modele"], m, mauvais):
                return False
        return True

    def _verdict(self, modele, m, mauvais) -> bool:
        """True = livrable accepté."""
        if modele not in self.fx["taille_modele_md"] and modele not in ("cloud", "haiku", "sonnet"):
            modele = self.m_princ
        se, fp = self.P[f"modele.{modele}.se"], self.P[f"modele.{modele}.fp"]
        if modele == m.modele_analyst:
            se *= self.P["qualite.auto_biais"]
        return not (self.r_svc.random() < (se if mauvais else fp))

    def _boucle(self, m: Mission):
        rng, P = self.r_svc, self.P
        while True:
            ok = yield from self._controle(m)
            if ok:
                break
            if m.revisions >= self._niveau(m)["revisions_max"]:
                yield ("llm", "directeur", *self._tokens("directeur", m, m.sortie_analyst))
                if m.relances == 0 and m.f in ("F1", "F2") and rng.random() < P["qualite.p_relance_directeur"]:
                    m.relances = 1
                    self._relever(m, ORDRE_F[ORDRE_F.index(m.f) + 1])
                    m.revisions = 0
                    info = yield ("llm", "analyst", *self._tokens("analyst", m, m.sortie_analyst + 120,
                                                                   self._sortie_analyst()))
                    self._brouillon(m, info, P["qualite.gain_revision"])
                    continue
                return "echec_escalade"
            m.revisions += 1
            info = yield ("llm", "analyst", *self._tokens("analyst", m, m.sortie_analyst + 120, self._sortie_analyst()))
            self._brouillon(m, info, P["qualite.gain_revision"])
        if self.v2:
            yield ("code", 0.3)  # GATE par règles seules (contrôles par code)
        else:
            yield ("llm", "gate", *self._tokens("gate", m, m.sortie_analyst))
        if m.f == "F1" and m.n in ("N2", "N3") and not m.preclasse:
            m.preclasse = True
            self._relever(m, "F2")
            return (yield from self._boucle(m))
        return "livre"

    # ----------------------------------------------------------------- fins de mission
    def _liberer(self, m: Mission):
        self.actifs.pop(m.id, None)
        if m.id in self.ljobs or any(x[0] == m.id for x in self.lfile):
            self._local_retirer(m.id)

    def _abandonner(self, m: Mission, cause: str):
        if m.etat != "en_cours":
            return
        m.etat = "echec_" + cause
        m.fin_t = self.t
        self._liberer(m)
        if m.pilote:
            self._plan_fini(m, False)
        self._demarrer()

    def _fin_pipeline(self, m: Mission, issue: str):
        self._liberer(m)
        m.fin_t = self.t
        if issue != "livre":
            m.etat = issue
            if m.pilote:
                self._plan_fini(m, False)
        else:
            if m.livre_t is None:
                m.livre_t = self.t
            if m.fantome:
                m.etat = "fantome_fini"
            elif m.pilote:
                m.etat = "plan_pilote"
                self._plan_fini(m, True)
            elif m.n == "N3":
                m.etat = "n3_en_attente"
                self._creer_decision(m, "fin")
            else:
                m.etat = "executee"
        self._demarrer()

    # ----------------------------------------------------------------- Décideur
    def _creer_decision(self, m: Mission, objet: str):
        j = int(self.t // JOUR)
        if self.dec_crees_jour.get(j, 0) >= self.fx["n3"]["plafond_jour"]:
            if not m.au_dessus_plafond:
                m.au_dessus_plafond = True
            self.dec_plafond.append((m, objet))
            return
        self.dec_crees_jour[j] = self.dec_crees_jour.get(j, 0) + 1
        d = {"m": m, "objet": objet, "cree": self.t, "etat": "attente", "decide": None}
        self.dec_attente.append(d)
        self.decisions.append(d)
        self.pousser(self.t + self.fx["n3"]["expiration_h"] * HEURE, "expire", d)

    def _ev_heure(self, hh):
        while self.dec_plafond and self.dec_crees_jour.get(int(self.t // JOUR), 0) < self.fx["n3"]["plafond_jour"]:
            m, objet = self.dec_plafond.popleft()
            self._creer_decision(m, objet)
        self._demarrer()  # fenêtre de nuit : reprise des missions de nuit
        if hh < self.trace_jours * 24:
            self.trace_file.append(len(self.file))
            self.trace_actifs.append(len(self.actifs))

    def _absent(self):
        a, d = self.sc.get("absence_debut_j", 0), self.sc.get("absence_duree_j", 0)
        return d and a * JOUR <= self.t < (a + d) * JOUR

    def _ev_session(self, _):
        if self._absent():
            return
        week_end = int(self.t // JOUR) % 7 >= 5
        if self.r_dec.random() > self.P["decideur.p_presence"] * (0.85 if week_end else 1.0):
            return
        cap = int(round(self.P["decideur.capacite_session"]))
        traitees = 0
        while self.dec_attente and traitees < cap:
            d = self.dec_attente.pop(0)
            traitees += 1
            d["decide"] = self.t + traitees * 90.0
            self._decider(d)

    def _decider(self, d: dict):
        m, P, x = d["m"], self.P, self.r_dec.random()
        if m.source == "banc":
            choix = "refuser"  # le banc ne valide jamais une décision N3
        elif x < P["decideur.p_valider"]:
            choix = "valider"
        elif x < P["decideur.p_valider"] + P["decideur.p_reviser"] and d["objet"] == "fin" and m.rev_proprio < 2:
            choix = "reviser"
        else:
            choix = "refuser"
        d["etat"] = choix
        if d["objet"] == "lancement_f4":
            if choix == "valider":
                self._enfiler(m)
            else:
                m.etat = "refusee_lancement"
        elif d["objet"] == "plan":
            m.etat = "plan_" + choix
            if choix == "valider":
                n = self.fx["pilote"]["projets_actifs"] * int(round(P["pilote.proposees_par_projet"]))
                for _ in range(n):
                    if self.r_dec.random() < P["pilote.p_coche"]:
                        self._admettre(self._manuel(self.t, self.r_dec))
        else:
            if choix == "valider":
                m.etat = "n3_validee"
            elif choix == "reviser":
                m.rev_proprio += 1
                m.en_revision = True
                self._enfiler(m)
            else:
                m.etat = "n3_refusee"

    def _ev_expire(self, d):
        if d["etat"] != "attente":
            return
        d["etat"] = "expiree"
        self.dec_attente.remove(d)
        m = d["m"]
        m.etat = {"lancement_f4": "refusee_lancement", "plan": "plan_expire"}.get(d["objet"], "n3_expiree")

    # ----------------------------------------------------------------- pannes serveur
    def _ev_redemarrage(self, duree):
        self.redemarrages += 1
        self._ps_avancer()
        relancer = sorted(self.actifs.values(), key=lambda m: m.debut)
        self.actifs.clear()
        self.ljobs.clear()
        self.lfile.clear()
        self.charges.clear()
        self._ps_planifier()
        self.hors_service_jusqua = self.t + duree
        for m in reversed(relancer):
            m.epoch += 1  # invalide les appels en vol
            m.etat = "en_file"
            self.file.appendleft(m)
        self.pousser(self.t + duree, "reprise_service", None)

    def _ev_reprise_service(self, _):
        self._demarrer()

    # ----------------------------------------------------------------- mesures
    def mesures(self) -> dict:
        P, fx, sc = self.P, self.fx, self.sc
        ms = [m for m in self.missions if m.source != "plan"]
        reelles = [m for m in ms if not m.fantome]
        livrees = [m for m in reelles if m.livre_t is not None]
        delais = {f: [] for f in ORDRE_F}
        for m in livrees:  # délais des missions de jour (manuel, pilote) : la nuit attend sa fenêtre exprès
            if m.source not in SOURCES_NUIT:
                delais[m.f].append(m.livre_t - m.arrivee)
        attentes = [m.debut_premier - m.arrivee for m in ms
                    if m.debut_premier is not None and m.source not in SOURCES_NUIT]
        attentes_nuit = [m.debut_premier - m.arrivee for m in ms
                         if m.debut_premier is not None and m.source in SOURCES_NUIT]
        demarrees = [m for m in ms if m.debut_premier is not None]
        etats = {}
        for m in self.missions:
            etats[m.etat] = etats.get(m.etat, 0) + 1
        plafonds = sum(1 for m in demarrees if m.etat in ("echec_budget", "echec_delai", "echec_cout"))
        bons = sum(1 for m in livrees if m.bon)
        tok_local = sum(m.tok_local for m in ms)
        tok_cloud = sum(m.tok_cloud for m in ms)
        tok_payant = sum(m.tok_payant for m in ms)
        api = sum(m.cout for m in ms)
        serveur = P[f"offre.{sc['offre']}.prix_eur_mois"] + (P["offre.KVM2.prix_eur_mois"] if sc["vitrine_kvm2"] else 0)
        echelle = 30.0 / self.jours
        cout_total = serveur + api * echelle
        n3 = self.decisions
        decides = [d for d in n3 if d["decide"] is not None]
        au_dessus = sum(1 for m in self.missions if m.au_dessus_plafond)
        delai_dec = [d["decide"] - d["cree"] for d in decides]
        ratio = len(livrees) / max(1, len(reelles))
        p90_f2 = pct(delais["F2"], 0.9)
        r = {
            "arrivees": len(ms), "arrivees_reelles": len(reelles), "livrees": len(livrees),
            "livrees_jour": len(livrees) / self.jours, "ratio_livraison": ratio,
            "executees": etats.get("executee", 0), "n3_validees": etats.get("n3_validee", 0),
            "echecs_escalade": etats.get("echec_escalade", 0),
            "delai_p50": {f: pct(v, 0.5) for f, v in delais.items()},
            "delai_p90": {f: pct(v, 0.9) for f, v in delais.items()},
            "nb_par_f": {f: len(v) for f, v in delais.items()},
            "attente_moy_s": sum(attentes) / len(attentes) if attentes else 0.0,
            "attente_p90_s": pct(attentes, 0.9) or 0.0,
            "attente_nuit_moy_s": sum(attentes_nuit) / len(attentes_nuit) if attentes_nuit else 0.0,
            "cpu_llm": self.occupe_s / self.T,
            "cpu_total": min(1.0, (self.occupe_pond / self.T * self.cpus + 0.15) / self.vcpu),
            "ram_pic_go": self.ram_pic, "ram_limite_go": self.ram_limite,
            "ram_ok": (self.ram_pic <= self.ram_limite + 1e-9) and not self.ram_depasse,
            "modeles_simultanes": self.n_charges,
            "taux_plafond": plafonds / max(1, len(demarrees)),
            "echecs_budget": etats.get("echec_budget", 0), "echecs_delai": etats.get("echec_delai", 0),
            "echecs_cout": etats.get("echec_cout", 0),
            "n3_jour": len(n3) / self.jours,
            "part_au_dessus_plafond": au_dessus / max(1, len(n3) + len(self.dec_plafond)),
            "decisions_expirees": sum(1 for d in n3 if d["etat"] == "expiree"),
            "delai_decision_p50_h": (pct(delai_dec, 0.5) or 0.0) / HEURE,
            "tokens_mois_local": tok_local * echelle, "tokens_mois_cloud": tok_cloud * echelle,
            "tokens_mois_payant": tok_payant * echelle,
            "cout_api_eur": api * echelle, "cout_serveur_eur": serveur, "cout_total_eur": cout_total,
            "cout_par_mission_eur": cout_total / max(1, len(livrees) * echelle),
            "qualite": bons / max(1, len(livrees)),
            "redemarrages": self.redemarrages, "cache_hits": self.cache_hits,
            "etats": etats,
            "trace_file": self.trace_file, "trace_actifs": self.trace_actifs,
        }
        r["score"] = score(r, fx["score"])
        r["delai_p90_f2"] = p90_f2
        return r


def score(r: dict, cfg: dict) -> float:
    """Score composite 0–100 (documenté dans hypotheses.json → fixes.score et README)."""
    w = cfg["poids"]
    debit = min(1.0, r["ratio_livraison"])
    p90 = r["delai_p90"].get("F2")
    if p90 is None:
        delai = 0.5
    elif p90 <= cfg["delai_bon_s"]:
        delai = 1.0
    elif p90 >= cfg["delai_nul_s"]:
        delai = 0.0
    else:
        delai = 1 - math.log(p90 / cfg["delai_bon_s"]) / math.log(cfg["delai_nul_s"] / cfg["delai_bon_s"])
    cout = max(0.0, min(1.0, 1 - r["cout_total_eur"] / cfg["cout_nul_eur"]))
    s = 100 * (w["debit"] * debit + w["delai"] * delai + w["qualite"] * r["qualite"] + w["cout"] * cout)
    return s * (1.0 if r["ram_ok"] else 0.5)


# --------------------------------------------------------------------------- Monte Carlo

def simuler(sc: dict, hyp: dict, tirage: int, base: int = 2026, jours: int = 30, probable: bool = False,
            surcharges: dict | None = None) -> dict:
    rng_p = None if probable else random.Random(graine(base, tirage, 0))
    s = dict(sc.get("surcharges") or {})
    s.update(surcharges or {})
    P = tirer_parametres(hyp, rng_p, s)
    return Simulation(sc, P, hyp, base, tirage, jours).executer()


def _tache(args):
    sc, hyp, tirage, base, jours, surch = args
    r = simuler(sc, hyp, tirage, base, jours, surcharges=surch)
    if sc["id"] not in ("S4", "S8", "S11", "S13", "S15"):
        r.pop("trace_file"), r.pop("trace_actifs")
    return r


def monte_carlo(sc: dict, hyp: dict, tirages: int = 200, base: int = 2026, jours: int = 30, pool=None,
                surcharges: dict | None = None) -> list[dict]:
    args = [(sc, hyp, i, base, jours, surcharges) for i in range(tirages)]
    return list(pool.map(_tache, args, chunksize=4)) if pool else [_tache(a) for a in args]


INDICATEURS = ["livrees_jour", "ratio_livraison", "attente_moy_s", "attente_p90_s", "attente_nuit_moy_s", "cpu_llm", "cpu_total",
               "ram_pic_go", "taux_plafond", "n3_jour", "part_au_dessus_plafond", "decisions_expirees",
               "delai_decision_p50_h", "tokens_mois_local", "tokens_mois_cloud", "tokens_mois_payant",
               "cout_api_eur", "cout_total_eur", "cout_par_mission_eur", "qualite", "score", "echecs_escalade",
               "echecs_budget", "echecs_delai", "redemarrages"]


def resumer(runs: list[dict]) -> dict:
    def stat(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {"moy": sum(vals) / len(vals), "p10": pct(vals, 0.1), "p90": pct(vals, 0.9)}

    res = {k: stat([r[k] for r in runs]) for k in INDICATEURS}
    for q in ("delai_p50", "delai_p90"):
        res[q] = {f: stat([r[q][f] for r in runs]) for f in ORDRE_F}
    res["ram_ok_part"] = sum(1 for r in runs if r["ram_ok"]) / len(runs)
    res["ram_limite_go"] = runs[0]["ram_limite_go"]
    res["modeles_simultanes"] = runs[0]["modeles_simultanes"]
    res["nb_par_f"] = {f: sum(r["nb_par_f"][f] for r in runs) / len(runs) for f in ORDRE_F}
    if "trace_file" in runs[0]:
        n = len(runs[0]["trace_file"])
        res["trace_file"] = {
            "moy": [sum(r["trace_file"][i] for r in runs) / len(runs) for i in range(n)],
            "p10": [pct([r["trace_file"][i] for r in runs], 0.1) for i in range(n)],
            "p90": [pct([r["trace_file"][i] for r in runs], 0.9) for i in range(n)]}
    return res
