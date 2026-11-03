"""Leçons apprises : la mémoire collective qui s'améliore sans dériver.

1. Après chaque mission, extraction DÉTERMINISTE des signaux : refus du CHECKER, violations de
   charte, refus/révisions du Décideur (motif), plafonds atteints, relances et reformulations du
   directeur, avis négatifs du Décideur.
2. Regroupement par signature normalisée (même service, même projet, même idée) : une mission compte
   une seule fois par leçon. Statuts : candidate → proposée (≥ NEXUS_LECONS_SEUIL, défaut 3).
3. Seul le propriétaire accepte ou rejette (carte « Leçons de la semaine » du Décideur). Seules les
   leçons ACCEPTÉES sont appliquées : ≤ 5 leçons et ≤ 800 caractères dans les messages de l'ANALYST
   et du CHECKER du service/projet. Une leçon n'est jamais supprimée : elle est rejetée ou suspendue.
4. Garde-fou de régression : la note du banc d'essai est mémorisée à l'activation ; si la moyenne
   des NEXUS_LECONS_MESURES_MIN (défaut 3) mesures suivantes baisse de plus de NEXUS_LECONS_BAISSE
   (défaut 10) points, la leçon est suspendue automatiquement et signalée.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from sqlalchemy import func, select

from . import cyber, gate, ledger, sentinel
from .config import cfg
from .db import session_scope
from .models import Avis, Decision, Etape, Lecon, Mission, maintenant

log = logging.getLogger("nexus.lecons")
TEXTE_MAX = 200
INJECTION_N = 5
INJECTION_CARACTERES = 800
SOURCES_MAX = 50
MOTS_VIDES = set("""le la les un une des du de d l et ou en au aux a pour par sur dans avec sans ce cette ces son sa
ses leur leurs est sont pas ne se s y il elle on qui que dont plus tres tout tous livrable charte""".split())


def _env_int(nom: str, defaut: int) -> int:
    try:
        return int(os.environ.get(nom, "") or defaut)
    except ValueError:
        return defaut


def seuil() -> int:
    return max(1, _env_int("NEXUS_LECONS_SEUIL", 3))


def mesures_min() -> int:
    return max(1, _env_int("NEXUS_LECONS_MESURES_MIN", 3))


def baisse_max() -> float:
    return float(_env_int("NEXUS_LECONS_BAISSE", 10))


# --- Extraction des signaux -----------------------------------------------------------------

def _nettoyer(texte: str) -> str:
    t = re.sub(r"^\s*\[(charte|double contrôle)\]\s*", "", texte or "", flags=re.I)
    t = cyber.masquer(re.sub(r"\s+", " ", t).strip())
    return t if len(t) <= TEXTE_MAX else t[: TEXTE_MAX - 1].rstrip() + "…"


def type_de(texte: str) -> str:
    t = gate.normaliser(texte)
    if any(m in t for m in ("terme interdit", "marque d'un autre", "ne doit pas", "interdit", "action offensive",
                            "secret present", "retirez", "invente", "ne citez pas", "mauvaise marque")):
        return "interdit"
    if any(m in t for m in ("mention obligatoire", "inacheve", "absent", "manque", "obligatoire", "ajoutez",
                            "incomplet", "completez", "oubli", "il faut", "doit contenir", "preciser")):
        return "obligation"
    return "methode"


def signature(texte: str) -> str:
    mots = [m for m in re.findall(r"[a-z]+", gate.normaliser(texte)) if len(m) > 2 and m not in MOTS_VIDES]
    return " ".join(mots[:12])


def signaux(mid: int) -> list[tuple[str, str]]:
    """[(origine, texte)] tirés de la mission (aucun appel LLM)."""
    res = []
    with session_scope() as s:
        m = s.get(Mission, mid)
        if m is None:
            return []
        for e in s.execute(select(Etape).where(Etape.mission_id == mid, Etape.verdict == "refus")).scalars():
            if e.role not in ("checker", "checker_local"):
                continue
            try:
                problemes = json.loads(e.sortie or "{}").get("problemes", [])
            except ValueError:
                problemes = []
            origine = {"charte du projet": "charte", "garde-fou cybersécurité": "cyber"}.get(e.entree, "checker")
            res += [(origine, p) for p in problemes if isinstance(p, str) and p.strip()]
        for d in s.execute(select(Decision).where(Decision.mission_id == mid,
                                                  Decision.statut.in_(("refusee", "revision")))).scalars():
            if d.commentaire and d.commentaire.strip():
                quoi = "Refus" if d.statut == "refusee" else "Révision demandée"
                res.append(("decideur", f"{quoi} par le Décideur : {d.commentaire.strip()}"))
        if m.statut == "plafond_atteint" and m.message:
            nature = re.search(r"Plafond atteint — (.*?)(?: Livrable partiel|$)", m.message)
            res.append(("plafond", f"Plafond atteint en {m.fonctionnement} : "
                                   f"{(nature.group(1) if nature else m.message)[:120]} Prévoir un niveau supérieur."))
        if m.statut == "a_reformuler" and m.message and "Suggestion du directeur" in m.message:
            res.append(("directeur", "Consigne à préciser : " + m.message.split("Suggestion du directeur :", 1)[1].strip()))
        if m.relance_auto:
            res.append(("directeur", "Relance automatique demandée par le directeur après refus répétés du contrôle."))
        a = s.execute(select(Avis).where(Avis.mission_id == mid, Avis.valeur == "negatif")).scalar_one_or_none()
        if a:
            from .avis import MOTIFS
            res.append(("decideur", f"Avis négatif du Décideur : {MOTIFS.get(a.motif, a.motif)}"
                                    + (f" — {a.texte}" if a.texte else "")))
    return res


def enregistrer_signaux(mid: int) -> dict:
    """Regroupe les signaux de la mission dans les leçons (une occurrence par mission et par leçon)."""
    with session_scope() as s:
        m = s.get(Mission, mid)
        service, projet = (m.service, m.projet) if m else (None, None)
    stats = {"signaux": 0, "nouvelles": 0, "incrementees": 0, "proposees": 0}
    vues = set()
    for origine, brut in signaux(mid):
        texte = _nettoyer(brut)
        sig = signature(texte)
        if not sig:
            continue
        typ = type_de(texte)
        cle = f"{service}|{projet}|{typ}|{sig}"[:200]
        if cle in vues:
            continue
        vues.add(cle)
        stats["signaux"] += 1
        with session_scope() as s:
            l = s.execute(select(Lecon).where(Lecon.cle == cle)).scalar_one_or_none()
            if l is None:
                l = Lecon(cle=cle, service=service, projet=projet, texte=texte, type=typ, origine=origine,
                          statut="candidate", occurrences=0, sources_json="[]", premiere=maintenant())
                s.add(l)
                stats["nouvelles"] += 1
            sources = json.loads(l.sources_json or "[]")
            if mid in sources:
                continue
            l.sources_json = json.dumps((sources + [mid])[-SOURCES_MAX:])
            l.occurrences = (l.occurrences or 0) + 1
            l.derniere = maintenant()
            stats["incrementees"] += 1
            if l.statut == "candidate" and l.occurrences >= seuil():
                l.statut, l.proposee_le = "proposee", maintenant()
                stats["proposees"] += 1
                s.flush()
                lid = l.id
            else:
                lid = None
        if lid:
            ledger.journaliser("NEXUS-PRIME", "lecon_proposee", mid, lecon_id=lid, service=service, projet=projet)
            _reformuler(lid)
    return stats


def _reformuler(lid: int) -> None:
    """Option (NEXUS_LECONS_REFORMULER=1) : reformulation courte par le LLM, marquée comme telle."""
    if os.environ.get("NEXUS_LECONS_REFORMULER", "0").strip() != "1":
        return
    from .llm import ErreurLLM, fournisseur
    with session_scope() as s:
        texte = s.get(Lecon, lid).texte
    try:
        r = fournisseur().appeler("Reformule cette leçon en une règle courte et impérative, en français, "
                                  "200 caractères maximum, sans rien ajouter.", texte, role="prime", temperature=0.0)
    except ErreurLLM:
        return
    propre = _nettoyer(r.texte)
    if propre and not cyber.detecter_secrets(propre):
        with session_scope() as s:
            s.get(Lecon, lid).texte_llm = propre


# --- Lecture, décisions, injection --------------------------------------------------------------

def _dico(l: Lecon) -> dict:
    return {"id": l.id, "service": l.service, "projet": l.projet, "texte": l.texte, "texte_llm": l.texte_llm,
            "type": l.type, "origine": l.origine, "statut": l.statut, "occurrences": l.occurrences,
            "sources": json.loads(l.sources_json or "[]"), "premiere": l.premiere.isoformat(),
            "derniere": l.derniere.isoformat(), "note_activation": l.note_activation,
            "semaine_activation": l.semaine_activation, "motif": l.motif}


def lister(statut: str | None = None, service: str | None = None, projet: str | None = None,
           q: str | None = None, limite: int = 100) -> list[dict]:
    with session_scope() as s:
        req = select(Lecon).order_by(Lecon.occurrences.desc(), Lecon.derniere.desc())
        if statut:
            req = req.where(Lecon.statut == statut)
        if service:
            req = req.where(Lecon.service == service)
        if projet:
            req = req.where(Lecon.projet == projet)
        res = [_dico(l) for l in s.execute(req).scalars()]
    if q:
        mots = [m for m in re.findall(r"[a-z0-9]+", gate.normaliser(q)) if len(m) > 2]
        res = [l for l in res if any(m in gate.normaliser(f"{l['texte']} {l['texte_llm'] or ''}") for m in mots)]
    return res[:limite]


def actives(service: str | None, projet: str | None) -> str:
    """Leçons ACCEPTÉES du service/projet (les plus fréquentes d'abord), ≤ 5 et ≤ 800 caractères."""
    with session_scope() as s:
        req = select(Lecon).where(Lecon.statut == "acceptee").order_by(Lecon.occurrences.desc(), Lecon.id)
        lecons = [l for l in s.execute(req).scalars()
                  if (l.service in (None, service)) and (l.projet in (None, projet))]
        lignes = [f"- [{l.type}] {l.texte_llm or l.texte}" for l in lecons[:INJECTION_N]]
    texte, res = 0, []
    for ligne in lignes:
        if texte + len(ligne) + 1 > INJECTION_CARACTERES:
            break
        res.append(ligne)
        texte += len(ligne) + 1
    return "\n".join(res)


def semaine_iso(t: datetime | None = None) -> str:
    a, s, _ = (t or maintenant()).isocalendar()
    return f"{a}-W{s:02d}"


def chemin_banc() -> Path:
    v = os.environ.get("NEXUS_BANC_RESULTATS", "").strip()
    return Path(v) if v else cfg().data_dir / "banc" / "tableau.json"


def _mesures(service: str | None) -> list[tuple[str, float]]:
    """[(semaine, note)] du tableau du banc : note du service si disponible, sinon note livrable globale."""
    try:
        t = json.loads(chemin_banc().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    res = []
    for ligne in t.get("semaines") or []:
        note = (ligne.get("par_service") or {}).get(service) if service else None
        note = note if note is not None else ligne.get("note_livrable")
        if note is not None and not ligne.get("llm_factice"):
            res.append((ligne.get("semaine", ""), float(note)))
    return sorted(res)


def accepter(lid: int, utilisateur: str, texte: str | None = None, terme_charte: str | None = None,
             confirmation_fantome: bool = False) -> dict:
    with session_scope() as s:
        l = s.get(Lecon, lid)
        if l is None:
            raise LookupError("Leçon introuvable.")
        if l.statut not in ("proposee", "suspendue"):
            raise PermissionError(f"Leçon non acceptable (statut {l.statut}).")
        fantome = json.loads(sentinel.lire(f"fantome:lecon:{lid}") or "null")
        if fantome and fantome.get("gain", 0) < 0 and not confirmation_fantome:
            raise PermissionError(f"Test fantôme défavorable ({fantome['gain']:+.0f} points) : "
                                  "confirmation explicite requise pour accepter.")
        if texte and texte.strip():
            propre = _nettoyer(texte)
            if cyber.detecter_secrets(texte):
                raise ValueError("Texte refusé : il contient un secret.")
            l.texte, l.texte_llm = propre, None
        mesures = _mesures(l.service)
        l.statut, l.decidee_le, l.motif = "acceptee", maintenant(), None
        l.note_activation = mesures[-1][1] if mesures else None
        l.semaine_activation = mesures[-1][0] if mesures else semaine_iso()
        service, projet, regle = l.service, l.projet, l.texte
    if terme_charte:
        ajouter_a_la_charte(projet, terme_charte, regle)
    ledger.journaliser("DECIDEUR", "lecon_acceptee", None, lecon_id=lid, utilisateur=utilisateur,
                       note_activation=l.note_activation, vers_charte=bool(terme_charte))
    return {"id": lid, "statut": "acceptee", "note_activation": l.note_activation}


def rejeter(lid: int, utilisateur: str, motif: str | None = None) -> dict:
    with session_scope() as s:
        l = s.get(Lecon, lid)
        if l is None:
            raise LookupError("Leçon introuvable.")
        if l.statut not in ("proposee", "candidate", "acceptee", "suspendue"):
            raise PermissionError(f"Leçon non modifiable (statut {l.statut}).")
        l.statut, l.decidee_le, l.motif = "rejetee", maintenant(), (motif or "")[:300] or None
    ledger.journaliser("DECIDEUR", "lecon_rejetee", None, lecon_id=lid, utilisateur=utilisateur)
    return {"id": lid, "statut": "rejetee"}


def ajouter_a_la_charte(projet: str | None, terme: str, motif: str) -> None:
    """Ajoute un terme interdit à la charte du projet (fichier d'ajouts dans les données, validé par l'humain)."""
    if not projet or not terme.strip() or cyber.detecter_secrets(terme):
        raise ValueError("Terme de charte invalide (projet requis, aucun secret).")
    f = cfg().data_dir / "chartes_ajouts" / f"{projet}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    d = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else {}
    d = d or {}
    d.setdefault("termes_interdits", []).append({"terme": terme.strip()[:80], "gravite": "bloquant",
                                                 "motif": f"leçon acceptée : {motif[:150]}"})
    f.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ledger.journaliser("DECIDEUR", "charte_terme_ajoute", None, projet=projet, terme=terme.strip()[:80])


# --- Garde-fou de régression -------------------------------------------------------------------

def verifier_regressions() -> list[dict]:
    """Suspend toute leçon acceptée dont la note du banc baisse de plus de baisse_max() points
    (moyenne d'au moins mesures_min() mesures postérieures à l'activation)."""
    suspendues = []
    with session_scope() as s:
        acceptees = s.execute(select(Lecon).where(Lecon.statut == "acceptee",
                                                  Lecon.note_activation.is_not(None))).scalars().all()
        cibles = [(l.id, l.service, l.note_activation, l.semaine_activation) for l in acceptees]
    for lid, service, note0, semaine0 in cibles:
        apres = [n for sem, n in _mesures(service) if sem > (semaine0 or "")]
        if len(apres) < mesures_min():
            continue
        moyenne = sum(apres) / len(apres)
        if moyenne < note0 - baisse_max():
            motif = (f"Régression mesurée : note du banc {moyenne:.1f} sur {len(apres)} mesure(s) après activation, "
                     f"contre {note0:.1f} à l'activation (baisse > {baisse_max():.0f} points).")
            with session_scope() as s:
                l = s.get(Lecon, lid)
                l.statut, l.suspendue_le, l.motif = "suspendue", maintenant(), motif
            ledger.journaliser("NEXUS-PRIME", "lecon_suspendue", None, lecon_id=lid, moyenne=round(moyenne, 1),
                               note_activation=note0, mesures=len(apres))
            suspendues.append({"id": lid, "moyenne": moyenne, "note_activation": note0})
    if suspendues:
        from . import decideur
        decideur._notifier(f"{len(suspendues)} lecon(s) suspendue(s) : baisse de qualite mesuree.", None,
                           "lecon_suspendue")
    return suspendues


def suspendues_depuis(debut: datetime) -> int:
    with session_scope() as s:
        return s.execute(select(func.count(Lecon.id)).where(Lecon.statut == "suspendue",
                                                            Lecon.suspendue_le >= debut)).scalar_one()


# --- Revue hebdomadaire et rapport -----------------------------------------------------------------

def revue_hebdo(maintenant_utc: datetime | None = None) -> dict | None:
    """Lundi à partir de 08:00 (Paris) : une revue par semaine si des leçons sont proposées (notif. générique)."""
    from . import decideur
    t = maintenant_utc or maintenant()
    p = t.replace(tzinfo=timezone.utc).astimezone(decideur.PARIS)
    if p.isoweekday() != 1 or p.hour < 8:
        return None
    cle = f"lecons:revue:{semaine_iso(p)}"
    if sentinel.lire(cle) == "1":
        return None
    sentinel.ecrire(cle, "1")
    n = len(lister("proposee"))
    if n:
        decideur._notifier(f"Lecons de la semaine : {n} a examiner.", None, "revue_lecons")
    ledger.journaliser("NEXUS-PRIME", "revue_lecons_hebdo", None, proposees=n, semaine=semaine_iso(p))
    return {"semaine": semaine_iso(p), "proposees": n}


def rapport(jours: int = 7) -> dict:
    debut = maintenant() - timedelta(days=jours)
    toutes = lister()
    dans = lambda iso: iso and iso >= debut.isoformat()  # noqa: E731
    with session_scope() as s:
        decidees = s.execute(select(Lecon).where(Lecon.decidee_le >= debut)).scalars().all()
        acceptees = [l.id for l in decidees if l.statut == "acceptee"]
        rejetees = [l.id for l in decidees if l.statut == "rejetee"]
        suspendues = [l.id for l in s.execute(select(Lecon).where(Lecon.suspendue_le >= debut)).scalars()]
    mesures = _mesures(None)[-6:]
    return {
        "periode_jours": jours,
        "nouvelles": [l["id"] for l in toutes if dans(l["premiere"])],
        "proposees_en_attente": [l["id"] for l in toutes if l["statut"] == "proposee"],
        "acceptees": acceptees, "rejetees": rejetees, "suspendues": suspendues,
        "actives": len([l for l in toutes if l["statut"] == "acceptee"]),
        "erreurs_frequentes": [{"texte": l["texte"], "occurrences": l["occurrences"], "service": l["service"],
                                "projet": l["projet"]} for l in sorted(toutes, key=lambda x: -x["occurrences"])[:5]],
        "evolution_notes": [{"semaine": s_, "note": n} for s_, n in mesures],
    }
