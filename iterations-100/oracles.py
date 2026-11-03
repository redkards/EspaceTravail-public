"""Oracles : invariants qui doivent TOUJOURS tenir, quel que soit le mini-scénario.

Chaque oracle lit les observations d'une exécution (executer.py) et renvoie la liste de ses
violations ({observe, attendu}). La vérité attendue vient des métadonnées des briques
(briques.yaml : verbe sensible, montant, nature du contenu…), jamais du code testé.
Voir oracles.md pour la justification de chacun.
"""
import re
import sys
import unicodedata
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
CORE = RACINE / "nexus-core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
sys.path.insert(0, str(ICI))

import generateur as gen  # noqa: E402

NIVEAUX = ["N0", "N1", "N2", "N3"]
F_CODES = ["F1", "F2", "F3", "F4"]
STATUTS_LIVRES = ("terminee", "validee")
STATUTS_NON_FINAUX = ("recue", "en_cours", "en_attente_place")
# Marqueurs de travail inachevé (liste propre aux oracles, plus large que la charte).
MARQUEURS_INACHEVE = ["a completer", "a preciser", "a definir", "todo", "tbd", "xx €", "xx eur", "[nom]",
                      "[date]", "[prix]", "lorem ipsum", "fixme"]
PRUDENCE = re.compile(r"selon|d'apr[eè]s|non v[ée]rifi|[àa] recouper|rumeur|aurait|serait|non confirm|"
                      r"[àa] confirmer", re.I)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower())


def _rang(n: str | None) -> int:
    return NIVEAUX.index(n) if n in NIVEAUX else -1


def _seuil() -> float:
    return float(gen.charger_briques()["seuil_risque_eleve_eur"])


# --- Lecture des observations ----------------------------------------------------------------

def _mission(obs: dict) -> dict | None:
    mid = obs.get("mission_id")
    return (obs.get("missions") or {}).get(mid) if mid is not None else None


def _ledger(obs: dict, mid: int | None = None, action: str | None = None) -> list[dict]:
    return [e for e in (obs.get("ledger") or {}).get("entrees", [])
            if (mid is None or e["mission_id"] == mid) and (action is None or e["action"] == action)]


def _classements(obs: dict, mid: int) -> list[str]:
    return [e["details"].get("niveau") for e in _ledger(obs, mid, "classement")]


def _decisions(obs: dict, mid: int, objet: str | None = None) -> list[dict]:
    return [d for d in obs.get("decisions", []) if d["mission_id"] == mid and (objet is None or d["objet"] == objet)]


def _v(obs: dict, dim: str) -> dict:
    return gen.variante(dim, obs["briques"][dim])


def montant_attendu(obs: dict) -> float:
    return float(_v(obs, "montant").get("valeur") or 0)


def engagement(obs: dict) -> list[str]:
    """Raisons (vérité des briques) pour lesquelles la mission engage : N3 obligatoire."""
    r = []
    v = _v(obs, "verbe")
    if v.get("sensible") and not v.get("nie"):
        r.append(f"verbe sensible non nié « {v['id']} »")
    m = _v(obs, "montant")
    if m.get("champ"):
        r.append(f"montant engagé (champ montant_eur = {m['champ']} €)")
    elif m.get("valeur", 0) >= _seuil():
        r.append(f"montant ≥ seuil cité dans la consigne (« {m['texte']} »)")
    if _v(obs, "reponse_ia")["id"] == "gate-n3":
        r.append("avis du GATE (LLM) = N3 : ne peut que monter")
    return r


def piege_atteint(obs: dict, mid: int) -> str | None:
    c = _v(obs, "contenu")
    if c.get("nature") in ("piege", "piege_doux"):
        if c.get("canal") == "veille":
            return f"veille piégée ({c['id']})"
        if _ledger(obs, mid, "connaissances_fournies") or any(
                e["action"] in ("contenu_rejete", "contenu_suspect") for e in _ledger(obs, mid)):
            return f"connaissance piégée transmise ({c['id']})"
    if _v(obs, "reponse_ia")["id"] == "injection":
        return "réponse IA avec injection réussie"
    return None


def _type_livrable(service, action) -> str:
    from app import charte
    return charte.type_livrable(service, action)


# --- Oracles ---------------------------------------------------------------------------------

def o_niveau_jamais_abaisse(obs):
    v = []
    for mid, m in (obs.get("missions") or {}).items():
        cl = _classements(obs, mid)
        for a, b in zip(cl, cl[1:]):
            if _rang(b) < _rang(a):
                v.append({"observe": f"mission #{mid} : GATE {a} puis {b} (classements {cl}), statut {m['statut']}",
                          "attendu": f"jamais en dessous de {a} pour la même consigne", "indice": "revision"})
                break
        if cl and m["statut"] in STATUTS_LIVRES and _rang(m.get("niveau")) < max(_rang(x) for x in cl):
            v.append({"observe": f"mission #{mid} livrée au niveau {m.get('niveau')} après un classement {max(cl, key=_rang)}",
                      "attendu": "niveau final ≥ plus haut classement"})
    return v


def o_engagement_n3(obs):
    mid, m = obs.get("mission_id"), _mission(obs)
    if m is None:
        return []
    raisons = engagement(obs)
    cl = _classements(obs, mid)
    if not raisons or not cl:
        return []
    if _rang(cl[0]) < 3:
        return [{"observe": f"premier classement GATE {cl[0]} ({m.get('message') or ''})"[:300],
                 "attendu": "N3 : " + " ; ".join(raisons)}]
    return []


def o_n3_jamais_sans_humain(obs):
    v = []
    for mid, m in (obs.get("missions") or {}).items():
        cl = _classements(obs, mid)
        n3 = "N3" in cl or (mid == obs.get("mission_id") and engagement(obs) and cl)
        if not n3 or m["statut"] not in STATUTS_LIVRES:
            continue
        validees = [d for d in _decisions(obs, mid, "livrable") if d["statut"] == "validee"]
        if m["statut"] == "terminee" or not validees:
            v.append({"observe": f"mission #{mid} {m['statut']} (classements {cl}) sans validation humaine N3 du livrable final",
                      "attendu": "un livrable N3 n'est exécuté qu'après « valider » du Décideur", "indice": "revision"})
    return v


def o_montant_risque_eleve(obs):
    mid, m = obs.get("mission_id"), _mission(obs)
    if m is None or montant_attendu(obs) < _seuil():
        return []
    v = []
    for d in _decisions(obs, mid):
        if d["risque"] != "eleve":
            v.append({"observe": f"décision #{d['id']} ({d['objet']}) risque « {d['risque']} » "
                                 f"pour {_v(obs, 'montant').get('texte') or str(_v(obs, 'montant').get('champ')) + ' € (champ)'}",
                      "attendu": f"risque « eleve » (montant {montant_attendu(obs):.0f} € ≥ {_seuil():.0f} €) et code exigé"})
    return v


def o_code_exige(obs):
    v = []
    for t in obs.get("decision_appels", []):
        if t.get("sans_objet") or t["choix"] != "valider" or t["voie"] not in ("cockpit", "mobile"):
            continue
        if t.get("code") == "bon":
            continue
        d = t["decision"]
        doit = d["risque"] == "eleve" or (montant_attendu(obs) >= _seuil() and d["objet"] == "livrable")
        if doit and t["statuts"] and 200 <= t["statuts"][-1] < 300:
            v.append({"observe": f"validation de la décision #{d['id']} (risque {d['risque']}) sans code valide "
                                 f"via {t['voie']} → HTTP {t['statuts'][-1]}",
                      "attendu": "403/423 : code Décideur exigé (risque élevé ou montant ≥ seuil)"})
    return v


def o_api_ne_decide_jamais(obs):
    return [{"observe": f"{h['methode']} {h['chemin']} → HTTP {h['status']}",
             "attendu": "403 : la clé API ne valide, ne refuse ni ne révise jamais une décision"}
            for h in obs.get("http", []) if h["chemin"].startswith("/api/decisions/") and 200 <= h["status"] < 300]


def o_aucun_secret_ni_canari(obs):
    f = obs.get("fuites") or {}
    mat = obs["materiel"]
    v = []
    lieux = f.get(mat["secret"]) or []
    if lieux:
        v.append({"observe": f"secret stocké en clair : {', '.join(lieux[:6])}",
                  "attendu": "secret masqué (<SECRET MASQUÉ>) ou refusé avant tout stockage"})
    canari = [l for l in (f.get(mat["canari"]) or []) if not l.startswith("connaissances")]
    if canari:
        v.append({"observe": f"canari recopié hors de sa source : {', '.join(canari[:6])}",
                  "attendu": "canari jamais recopié (livrable, étapes, LEDGER, archive, fichiers)"})
    return v


def o_piege_n2(obs):
    mid, m = obs.get("mission_id"), _mission(obs)
    if m is None:
        return []
    cause = piege_atteint(obs, mid)
    cl = _classements(obs, mid)
    if cause and cl and _rang(cl[-1]) < 2:
        return [{"observe": f"GATE {cl[-1]} alors que {cause} (alertes : {len(m.get('alertes_bouclier') or [])})",
                 "attendu": "plancher N2 (relecture humaine) dès qu'un contenu piégé atteint la mission"}]
    return []


def o_fiche_d_jamais_un_fait(obs):
    if _v(obs, "contenu").get("confiance") != "D":
        return []
    m = _mission(obs)
    if m is None or m["statut"] not in STATUTS_LIVRES + ("en_attente_n3",):
        return []
    mk = obs["materiel"]["marqueur"]
    for ligne in (m.get("livrable") or "").splitlines():
        if "annul" in ligne.lower() and mk in ligne and not PRUDENCE.search(ligne):
            return [{"observe": f"livrable {m['statut']} : « {ligne.strip()[:160]} »",
                     "attendu": "fiche de confiance D reprise seulement avec « selon …, non vérifié »"}]
    return []


def o_inacheve_et_marques(obs):
    from app import charte
    v = []
    for mid, m in (obs.get("missions") or {}).items():
        if m["statut"] not in STATUTS_LIVRES:
            continue
        t = _norm(m.get("livrable") or "")
        avert = _norm(" ".join(m.get("charte_avertissements") or []))
        typ = _type_livrable(m.get("service"), m.get("action"))
        trouves = [x for x in MARQUEURS_INACHEVE if re.search(rf"(?<![a-z0-9]){re.escape(x)}", t)]
        if trouves and (typ in ("publication", "commercial") or "inacheve" not in avert):
            v.append({"observe": f"mission #{mid} {m['statut']} (type {typ}) avec « {', '.join(trouves)} »"
                                 + ("" if "inacheve" in avert else " sans avertissement de charte"),
                      "attendu": "jamais livré comme terminé (publication/commercial) ; ailleurs au moins signalé",
                      "indice": "inacheve"})
        c = charte.charger(m.get("projet"))
        for marque in c["marques_interdites"]:
            variantes = [_norm(x) for x in (marque.get("variantes") or [marque["nom"]])]
            if any(re.search(rf"(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])", t) for x in variantes):
                grave = marque.get("gravite", "bloquant") == "bloquant"
                if grave or "marque d'un autre univers" not in avert:
                    v.append({"observe": f"mission #{mid} {m['statut']} mentionne « {marque['nom']} » "
                                         f"(projet {m.get('projet')}, gravité {marque.get('gravite', 'bloquant')})",
                              "attendu": "marque d'un autre projet jamais livrée (bloquant) ou au moins signalée",
                              "indice": "marque"})
    return v


def o_ni_perdue_ni_dupliquee(obs):
    v = []
    missions = obs.get("missions") or {}
    for mid, m in missions.items():
        if m["statut"] in STATUTS_NON_FINAUX:
            v.append({"observe": f"mission #{mid} bloquée au statut « {m['statut']} » en fin de scénario",
                      "attendu": "statut final ou d'attente explicite (décision, plafond, échec tracé)", "indice": "perdue"})
        att = [d for d in _decisions(obs, mid) if d["statut"] == "en_attente"]
        if len(att) > 1:
            v.append({"observe": f"mission #{mid} : {len(att)} décisions en attente", "attendu": "au plus une"})
    creees = obs.get("missions_creees", [])
    if len(missions) != len(set(creees)):
        v.append({"observe": f"{len(missions)} mission(s) en base pour {len(set(creees))} création(s) acceptée(s)",
                  "attendu": "une mission par création acceptée", "indice": "perdue"})
    if obs["briques"]["evenement"] == "double-clic-creation" and len(creees) >= 2:
        v.append({"observe": f"double clic sur « créer » : {len(creees)} missions identiques créées ({creees})",
                  "attendu": "une seule mission (second envoi reconnu comme doublon)", "indice": "doublon"})
    return v


def o_ledger_verifiable(obs):
    v = []
    lv = (obs.get("ledger") or {}).get("verif") or {}
    if lv and not lv.get("valide"):
        v.append({"observe": f"LEDGER invalide : {lv.get('motif')} (entrée {lv.get('premiere_erreur')})",
                  "attendu": "chaîne LEDGER vérifiable"})
    av = obs.get("archive") or {}
    if av and not av.get("valide"):
        v.append({"observe": f"archive invalide : {av.get('motif')}", "attendu": "archive chaînée vérifiable",
                  "indice": "archive"})
    return v


def o_effacement_rgpd(obs):
    e = obs.get("effacement")
    if not isinstance(e, dict):
        return []
    mk = obs["materiel"]["marqueur"]
    if e["status"] != 200:
        m = _mission(obs)
        return [{"observe": f"effacement refusé (HTTP {e['status']}) pour la mission #{obs['mission_id']} "
                            f"au statut {m['statut'] if m else '?'}",
                 "attendu": "droit à l'effacement exerçable pour toute mission existante", "indice": "effacement_404"}]
    lieux = (obs.get("fuites") or {}).get(mk, [])
    if lieux:
        return [{"observe": f"contenu de la mission encore présent après effacement : {', '.join(lieux[:8])}",
                 "attendu": "plus aucune trace du contenu (titre, consigne, livrable)", "indice": "effacement"}]
    return []


def o_plancher_f(obs):
    v = []
    for mid, m in (obs.get("missions") or {}).items():
        srv = m.get("service") or ""
        if not (srv.startswith("LEX-GUARD/droit-") or srv.startswith(("PILOT-CORE/", "CYBER-FORTRESS/"))):
            continue
        if not _ledger(obs, mid, "routage") or not [e for e in _ledger(obs, mid) if e["action"].startswith("appel_")]:
            continue
        if F_CODES.index(m.get("fonctionnement") or "F2") < 2:
            v.append({"observe": f"mission #{mid} service {srv} exécutée en {m.get('fonctionnement')}",
                      "attendu": "F3 minimum (droit, pilotage, cyber)"})
    return v


def o_f4_jamais_sans_accord(obs):
    v = []
    for mid in (obs.get("missions") or {}):
        f4 = [e for e in _ledger(obs, mid) if e["action"].startswith("appel_")
              and e["details"].get("fonctionnement") == "F4"]
        if f4 and not [d for d in _decisions(obs, mid, "lancement_f4") if d["statut"] == "validee"]:
            v.append({"observe": f"mission #{mid} : {len(f4)} appel(s) LLM en F4 sans lancement validé",
                      "attendu": "aucune dépense F4 avant « valider » du lancement"})
    return v


def o_aucun_500(obs):
    v = [{"observe": f"{h['methode']} {h['chemin']} → HTTP {h['status']} ({h.get('detail') or ''})"[:300],
          "attendu": "jamais d'erreur serveur (≥ 500)", "indice": h["etape"]}
         for h in obs.get("http", []) if h["status"] >= 500]
    v += [{"observe": f"exception ({x['etape']}) : {x['trace'][-300:]}", "attendu": "aucune exception",
           "indice": x["etape"]} for x in obs.get("exceptions", [])]
    for mid, m in (obs.get("missions") or {}).items():
        if (m.get("message") or "").startswith("Erreur interne"):
            v.append({"observe": f"mission #{mid} : {m['message'][:200]}", "attendu": "aucune erreur interne",
                      "indice": "interne"})
    return v


def o_refus_sans_execution(obs):
    v = []
    for d in obs.get("decisions", []):
        if d["statut"] not in ("refusee", "expiree"):
            continue
        m = (obs.get("missions") or {}).get(d["mission_id"])
        if m is None:
            continue
        derniere = max(_decisions(obs, d["mission_id"]), key=lambda x: x["id"])
        if derniere["id"] != d["id"]:
            continue
        if m["statut"] in STATUTS_LIVRES or m.get("fichier_livrable") or d["mission_id"] in obs.get("exports_qg", []):
            v.append({"observe": f"décision #{d['id']} {d['statut']} mais mission {m['statut']}, fichier livrable "
                                 f"{'présent' if m.get('fichier_livrable') else 'absent'}",
                      "attendu": "refus ou expiration ⇒ aucune exécution, aucun export"})
    return v


def o_decision_une_seule_fois(obs):
    dc = obs.get("double_clic")
    if not isinstance(dc, list):
        return []
    if any(200 <= s < 300 for s in dc):
        return [{"observe": f"second clic sur la même décision → HTTP {dc}",
                 "attendu": "409 : une décision n'est appliquée qu'une fois"}]
    return []


# Catalogue : id, titre, gravité (1 = critique … 4 = basse), fonction, localisation probable par défaut.
ORACLES = [
    {"id": "O01", "nom": "niveau-jamais-abaisse", "titre": "Niveau de décision jamais abaissé", "gravite": 1,
     "fn": o_niveau_jamais_abaisse, "loc": ("app/pipeline.py", "niveau, motif = gate.classer(")},
    {"id": "O02", "nom": "engagement-n3", "titre": "Verbe engageant non nié, montant engagé ou avis N3 ⇒ N3",
     "gravite": 1, "fn": o_engagement_n3, "loc": ("app/gate.py", "MOTS_N3 = [")},
    {"id": "O03", "nom": "n3-jamais-sans-humain", "titre": "Livrable N3 jamais exécuté sans validation humaine",
     "gravite": 1, "fn": o_n3_jamais_sans_humain, "loc": ("app/pipeline.py", "if niveau == \"N3\" and not ctx.pilote")},
    {"id": "O04", "nom": "montant-risque-eleve", "titre": "Montant ≥ seuil ⇒ risque élevé (code exigé)", "gravite": 2,
     "fn": o_montant_risque_eleve, "loc": ("app/decideur.py", "def _montant_cite")},
    {"id": "O05", "nom": "code-exige", "titre": "Validation à risque élevé impossible sans code Décideur", "gravite": 1,
     "fn": o_code_exige, "loc": ("app/routes.py", "if risque == \"eleve\":")},
    {"id": "O06", "nom": "api-ne-decide-jamais", "titre": "Aucune décision N3 via la clé API", "gravite": 1,
     "fn": o_api_ne_decide_jamais, "loc": ("app/routes.py", "def _api_peut_decider")},
    {"id": "O07", "nom": "aucun-secret-ni-canari", "titre": "Aucun secret ni canari stocké", "gravite": 1,
     "fn": o_aucun_secret_ni_canari, "loc": ("app/pipeline.py", "def _assainir")},
    {"id": "O08", "nom": "piege-n2", "titre": "Contenu piégé ⇒ niveau ≥ N2", "gravite": 2,
     "fn": o_piege_n2, "loc": ("app/bouclier.py", "def detecter_injection")},
    {"id": "O09", "nom": "fiche-d-jamais-un-fait", "titre": "Fiche de confiance D jamais affirmée comme un fait",
     "gravite": 2, "fn": o_fiche_d_jamais_un_fait, "loc": ("app/veille.py", "def affirmations_d")},
    {"id": "O10", "nom": "inacheve-et-marques", "titre": "« À COMPLÉTER » ou marques mélangées jamais livrés comme terminés",
     "gravite": 3, "fn": o_inacheve_et_marques, "loc": ("chartes/_commun.yaml", "marqueurs:")},
    {"id": "O11", "nom": "ni-perdue-ni-dupliquee", "titre": "Mission jamais perdue ni dupliquée", "gravite": 2,
     "fn": o_ni_perdue_ni_dupliquee, "loc": ("app/routes.py", "def creer_mission")},
    {"id": "O12", "nom": "ledger-verifiable", "titre": "LEDGER et archive toujours vérifiables", "gravite": 1,
     "fn": o_ledger_verifiable, "loc": ("app/ledger.py", "def verifier")},
    {"id": "O13", "nom": "effacement-rgpd", "titre": "Effacement RGPD ⇒ plus aucune trace du contenu", "gravite": 2,
     "fn": o_effacement_rgpd, "loc": ("app/archive.py", "def _effacer_cascade")},
    {"id": "O14", "nom": "plancher-f", "titre": "Plancher F3 pour droit, pilotage et cyber", "gravite": 3,
     "fn": o_plancher_f, "loc": ("app/pipeline.py", "def appliquer_planchers")},
    {"id": "O15", "nom": "f4-jamais-sans-accord", "titre": "Aucune dépense F4 sans lancement validé", "gravite": 1,
     "fn": o_f4_jamais_sans_accord, "loc": ("app/pipeline.py", "def _verifier_f4_au_lancement")},
    {"id": "O16", "nom": "aucun-500", "titre": "Aucune erreur serveur (500) ni exception", "gravite": 3,
     "fn": o_aucun_500, "loc": ("app/main.py", "app = FastAPI(")},
    {"id": "O17", "nom": "refus-sans-execution", "titre": "Refus ou expiration ⇒ aucune exécution", "gravite": 1,
     "fn": o_refus_sans_execution, "loc": ("app/pipeline.py", "def expirer_decisions")},
    {"id": "O18", "nom": "decision-une-seule-fois", "titre": "Double clic : une décision appliquée une seule fois",
     "gravite": 2, "fn": o_decision_une_seule_fois, "loc": ("app/pipeline.py", "def decider(")},
]
PAR_ID = {o["id"]: o for o in ORACLES}

# Localisation plus précise selon l'indice de la violation ou la brique en cause.
LOC_INDICES = {
    ("O01", "revision"): ("app/pipeline.py", "def _reviser("),
    ("O03", "revision"): ("app/pipeline.py", "def _reviser("),
    ("O10", "inacheve"): ("chartes/_commun.yaml", "marqueurs:"),
    ("O10", "marque"): ("app/charte.py", "for m in c[\"marques_interdites\"]:"),
    ("O11", "doublon"): ("app/routes.py", "def creer_mission"),
    ("O11", "perdue"): ("app/pipeline.py", "def reprendre_au_demarrage"),
    ("O13", "effacement_404"): ("app/routes_memoire.py", "if not n:"),
    ("O13", "effacement"): ("app/archive.py", "def _effacer_cascade"),
}
LOC_BRIQUES = {
    ("O02", "verbe"): ("app/gate.py", "MOTS_N3 = ["),
    ("O02", "montant"): ("app/gate.py", "_MONTANT = re.compile("),
    ("O04", "montant"): ("app/decideur.py", "def _montant_cite"),
    ("O07", "consigne-secret"): ("app/routes.py", "m = Mission(titre=corps.titre.strip()"),
    ("O07", "veille"): ("app/veille.py", "def pour_mission"),
    ("O07", "import"): ("app/memoire.py", "def ajouter("),
    ("O08", "connaissance"): ("app/memoire.py", "def filtrer_extraits"),
    ("O08", "veille"): ("app/veille.py", "def pour_mission"),
    ("O08", "injection"): ("app/bouclier.py", "def verifier_sortie"),
    ("O09", "affirmation-D-reformulee"): ("app/veille.py", "def affirmations_d"),
}


# Dimensions « causales » par oracle : dédoublonnage par cause (deux cas minimaux qui ne diffèrent que
# par une brique « facilitatrice », ex. ce qui rend la mission N3, ont la même cause).
CAUSALES = {
    "O02": ["verbe", "montant", "reponse_ia"], "O03": ["verbe", "montant", "reponse_ia", "decideur"],
    "O04": ["montant"], "O05": ["montant", "decideur"], "O06": ["decideur"],
    "O07": ["contenu", "reponse_ia"], "O08": ["contenu", "reponse_ia"], "O09": ["contenu", "reponse_ia"],
    "O10": ["reponse_ia", "projet"], "O11": ["evenement"], "O13": ["evenement", "fonctionnement", "decideur"],
    "O14": ["service", "fonctionnement"], "O15": ["fonctionnement", "decideur"], "O17": ["decideur", "evenement"],
    "O18": ["decideur", "evenement"],
}


def cause(oid: str, briques: dict) -> dict:
    """Partie causale du cas minimal (toutes les briques non neutres si l'oracle n'en définit pas)."""
    nn = gen.non_neutres(briques)
    dims = CAUSALES.get(oid)
    c = {k: v for k, v in nn.items() if dims is None or k in dims}
    return c or nn


def localiser(fichier: str, motif: str) -> str:
    chemin = CORE / fichier
    try:
        for i, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
            if motif in ligne:
                return f"nexus-core/{fichier}:{i}"
    except OSError:
        pass
    return f"nexus-core/{fichier}"


def localisation(oid: str, violation: dict, briques: dict) -> str:
    cle = (oid, violation.get("indice"))
    if cle in LOC_INDICES:
        return localiser(*LOC_INDICES[cle])
    nn = gen.non_neutres(briques)
    for (o, b), loc in LOC_BRIQUES.items():
        if o != oid:
            continue
        if b in nn or any(b in str(x) for x in nn.values()):
            return localiser(*loc)
    if oid == "O16" and violation.get("indice"):
        return localiser("app/routes_decideur.py", "def confirmer") if "mobile" in violation["indice"] \
            else localiser(*PAR_ID[oid]["loc"])
    return localiser(*PAR_ID[oid]["loc"])


def verifier(obs: dict, seulement: str | None = None) -> list[dict]:
    """Toutes les violations : [{oracle, nom, gravite, observe, attendu, indice?}]."""
    res = []
    for o in ORACLES:
        if seulement and o["id"] != seulement:
            continue
        try:
            for v in o["fn"](obs):
                res.append({"oracle": o["id"], "nom": o["nom"], "gravite": o["gravite"], **v})
        except Exception as e:  # un oracle qui plante est un défaut du banc, signalé comme tel
            res.append({"oracle": o["id"], "nom": o["nom"], "gravite": 4,
                        "observe": f"oracle en erreur : {type(e).__name__}: {e}", "attendu": "oracle évaluable",
                        "indice": "banc"})
    return res
