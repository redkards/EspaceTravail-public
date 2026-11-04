"""Mémoire par projet : base de connaissances (table `connaissances` + index plein texte FTS5).

- Ajout par l'API (clé) ou le cockpit (propriétaire) ; import idempotent au démarrage depuis
  NEXUS_CONNAISSANCES_DIR (défaut /connaissances) ; résumé automatique des livrables validés
  (NEXUS_MEMOIRE_AUTO=1 par défaut).
- Filtre anti-secret (app/cyber.py) avant toute écriture : refus pour un ajout manuel,
  masquage pour l'import et la mémorisation automatique.
- Recherche FTS5 (SQLite) classée par pertinence (bm25) ; repli LIKE sous PostgreSQL.
- `extraits()` fournit au COLLECTOR et au CHECKER les 3 passages les plus pertinents, avec leur
  source, dans un budget de caractères qui dépend du niveau de fonctionnement.
"""
import hashlib
import logging
import os
import re
from pathlib import Path

from sqlalchemy import select, text

from . import bouclier, cyber, gate, ledger
from . import projets as registre
from .db import engine, session_scope
from .models import Connaissance, maintenant

log = logging.getLogger("nexus.memoire")

TAILLE_MORCEAU = 1500          # caractères maximum d'une connaissance importée (découpage par titres)
RESUME_LIVRABLE_MAX = 800
BUDGET_EXTRAITS = {"F1": 800, "F2": 2000, "F3": 2000, "F4": 3000}
MOTS_VIDES = set("""le la les un une des du de d l et ou en au aux a pour par sur dans avec sans ce cette ces
cet son sa ses leur leurs mon ma mes ton ta tes nos vos qui que quoi dont est sont etre fait faire fais
redige redigez donne liste plus moins tres tout tous toute toutes comme mais pas ne se s y il elle on nous
vous ils elles je tu me te lui eux the and for with""".split())


class SecretRefuse(ValueError):
    pass


class InjectionRefusee(ValueError):
    """Connaissance refusée par le bouclier anti-injection (score ≥ bouclier.SEUIL_HAUT) : HTTP 422."""


# --- Index plein texte -----------------------------------------------------------------

def initialiser_fts(eng) -> None:
    """Crée la table FTS5 « contenu externe » et ses déclencheurs (SQLite uniquement)."""
    if eng.dialect.name != "sqlite":
        return
    with eng.begin() as c:
        existe = c.execute(text("SELECT 1 FROM sqlite_master WHERE name='connaissances_fts'")).first()
        c.execute(text("""CREATE VIRTUAL TABLE IF NOT EXISTS connaissances_fts USING fts5(
            titre, contenu, content='connaissances', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2')"""))
        c.execute(text("""CREATE TRIGGER IF NOT EXISTS connaissances_ai AFTER INSERT ON connaissances BEGIN
            INSERT INTO connaissances_fts(rowid, titre, contenu) VALUES (new.id, new.titre, new.contenu); END"""))
        c.execute(text("""CREATE TRIGGER IF NOT EXISTS connaissances_ad AFTER DELETE ON connaissances BEGIN
            INSERT INTO connaissances_fts(connaissances_fts, rowid, titre, contenu)
            VALUES ('delete', old.id, old.titre, old.contenu); END"""))
        c.execute(text("""CREATE TRIGGER IF NOT EXISTS connaissances_au AFTER UPDATE ON connaissances BEGIN
            INSERT INTO connaissances_fts(connaissances_fts, rowid, titre, contenu)
            VALUES ('delete', old.id, old.titre, old.contenu);
            INSERT INTO connaissances_fts(rowid, titre, contenu) VALUES (new.id, new.titre, new.contenu); END"""))
        if not existe:
            c.execute(text("INSERT INTO connaissances_fts(connaissances_fts) VALUES ('rebuild')"))


def _requete_fts(q: str) -> str | None:
    mots = []
    for m in re.findall(r"[a-z0-9]+", gate.normaliser(q)):
        if len(m) >= 3 and m not in MOTS_VIDES and m not in mots:
            mots.append(m)
    return " OR ".join(f'"{m}"*' for m in mots[:16]) or None


# --- Écriture -------------------------------------------------------------------------------

def empreinte(titre: str, contenu: str) -> str:
    return hashlib.sha256(f"{titre}\n{contenu}".encode("utf-8")).hexdigest()


def ajouter(projet: str, titre: str, contenu: str, source: str, auteur: str, origine: str = "manuel",
            masquer: bool = False) -> dict:
    """Ajoute ou met à jour (même projet + source) une connaissance. Idempotent par empreinte.

    `masquer=False` : un secret détecté fait refuser l'écriture (SecretRefuse) ;
    `masquer=True` : le secret est masqué (import, mémorisation automatique).
    """
    projet = registre.resoudre(projet)
    titre, contenu, source = titre.strip()[:200], contenu.strip(), source.strip()[:300]
    secrets_trouves = cyber.detecter_secrets(f"{titre}\n{contenu}")
    if secrets_trouves:
        if not masquer:
            raise SecretRefuse("Connaissance refusée : elle contient un secret (" +
                               ", ".join(sorted(set(secrets_trouves))) + "). Retirez-le puis réessayez.")
        titre, contenu = cyber.masquer(titre), cyber.masquer(contenu)
    # Bouclier anti-injection : une connaissance est relue plus tard par les agents.
    d = bouclier.detecter_injection(f"{titre}\n{contenu}")
    if d.score >= bouclier.SEUIL_HAUT:
        ledger.journaliser("NEXUS-BOUCLIER", "connaissance_rejetee", None, projet=projet, source=source,
                           origine=origine, score=d.score, motifs=d.motifs)
        raise InjectionRefusee(f"Connaissance refusée : elle contient des consignes adressées à l'IA "
                               f"(score {d.score}/100 ; {', '.join(d.motifs)}). Retirez-les puis réessayez.")
    suspect = d.score >= bouclier.SEUIL_MOYEN
    e = empreinte(titre, contenu)
    with session_scope() as s:
        k = s.execute(select(Connaissance).where(Connaissance.projet == projet,
                                                 Connaissance.source == source)).scalar_one_or_none()
        if k and k.empreinte == e:
            return {"id": k.id, "etat": "inchangee", "version": k.version} | ({"suspect": True} if k.suspect else {})
        if k:
            k.titre, k.contenu, k.empreinte, k.version = titre, contenu, e, k.version + 1
            k.date, k.auteur, k.origine, k.suspect = maintenant(), auteur, origine, suspect
            etat = "mise_a_jour"
        else:
            k = Connaissance(projet=projet, titre=titre, contenu=contenu, source=source, auteur=auteur,
                             origine=origine, empreinte=e, version=1, date=maintenant(), suspect=suspect)
            s.add(k)
            etat = "ajoutee"
        s.flush()
        res = {"id": k.id, "etat": etat, "version": k.version} | ({"suspect": True} if suspect else {})
    ledger.journaliser(auteur, f"connaissance_{etat}", None, projet=projet, source=source, origine=origine,
                       secret_masque=bool(secrets_trouves))
    if suspect:  # stockée, mais marquée : encapsulée et signalée au CHECKER à chaque lecture
        ledger.journaliser("NEXUS-BOUCLIER", "connaissance_suspecte", None, projet=projet, source=source,
                           score=d.score, motifs=d.motifs)
    return res


# --- Lecture ----------------------------------------------------------------------------------

def _dico(k: Connaissance, score: float | None = None) -> dict:
    return {"id": k.id, "projet": k.projet, "titre": k.titre, "contenu": k.contenu, "source": k.source,
            "date": k.date.isoformat() if k.date else None, "auteur": k.auteur, "version": k.version,
            "origine": k.origine, "score": score, "suspect": bool(k.suspect)}


def rechercher(projet: str, q: str | None = None, limite: int = 10) -> list[dict]:
    projet = registre.resoudre(projet)
    limite = max(1, min(int(limite), 50))
    requete = _requete_fts(q or "") if q else None
    with session_scope() as s:
        if requete is None:
            rows = s.execute(select(Connaissance).where(Connaissance.projet == projet)
                             .order_by(Connaissance.date.desc(), Connaissance.id.desc()).limit(limite)).scalars()
            return [_dico(k) for k in rows]
        if engine().dialect.name == "sqlite":
            ids = s.execute(text("""SELECT c.id, bm25(connaissances_fts, 2.0, 1.0) AS score
                FROM connaissances_fts JOIN connaissances c ON c.id = connaissances_fts.rowid
                WHERE connaissances_fts MATCH :m AND c.projet = :p ORDER BY score LIMIT :n"""),
                {"m": requete, "p": projet, "n": limite}).all()
            par_id = {k.id: k for k in s.execute(select(Connaissance).where(
                Connaissance.id.in_([i for i, _ in ids]))).scalars()}
            return [_dico(par_id[i], round(-sc, 4)) for i, sc in ids if i in par_id]
        # PostgreSQL (mode complet) : repli simple par mots-clés.
        mots = [m.strip('"*') for m in requete.split(" OR ")]
        cands = s.execute(select(Connaissance).where(Connaissance.projet == projet)).scalars().all()
        notes = []
        for k in cands:
            t = gate.normaliser(f"{k.titre} {k.contenu}")
            n = sum(t.count(m) for m in mots)
            if n:
                notes.append((n, k))
        notes.sort(key=lambda x: -x[0])
        return [_dico(k, float(n)) for n, k in notes[:limite]]


def extraits(projet: str, requete: str, niveau: str = "F2", nombre: int = 3) -> list[dict]:
    """Les `nombre` passages les plus pertinents, bornés au budget de caractères du niveau."""
    budget = BUDGET_EXTRAITS.get(niveau, 2000)
    try:
        trouves = rechercher(projet, requete, nombre)
    except ValueError:
        return []
    if not trouves:
        return []
    part = max(200, budget // len(trouves))
    res, total = [], 0
    for k in trouves:
        extrait = re.sub(r"\s+", " ", k["contenu"]).strip()
        if len(extrait) > part:
            extrait = extrait[: part - 1].rstrip() + "…"
        if total + len(extrait) > budget:
            break
        total += len(extrait)
        res.append({"source": k["source"], "titre": k["titre"], "extrait": extrait, "suspect": k.get("suspect")})
    return res


def filtrer_extraits(trouves: list[dict], mission_id: int | None = None) -> tuple[list[dict], list[str]]:
    """Bouclier sur chaque extrait avant transmission aux agents (bouclier.filtrer_contenu) : rejet si
    score ≥ SEUIL_HAUT (jamais transmis), sinon texte NETTOYÉ (caché, invisibles, HTML retirés).
    L'ensemble retenu est ensuite encapsulé en un seul bloc par `formater_protege` (un seul en-tête
    « données non fiables » : moins de caractères consommés sur le budget du niveau F).
    Renvoie (extraits retenus, alertes à transmettre au CHECKER et à la carte Décideur)."""
    retenus, alertes = [], []
    for e in trouves:
        source = f"mémoire {e['source']}"
        brut = f"{e['titre']} : {e['extrait']}"
        v = bouclier.filtrer_contenu(brut, source, journal=ledger.journaliser, mission_id=mission_id)
        alertes.extend(v.alertes_transmises)
        if e.get("suspect") and v.decision == "accepte":
            alertes.append(f"{source} : connaissance stockée comme suspecte")
        elif v.decision == "accepte" and v.score >= bouclier.SEUIL_BAS:
            alertes.append(f"{bouclier.FAIBLE} {source} : score {v.score}/100")
        if v.decision == "rejete":
            continue
        propre = bouclier.nettoyer_contenu(e["extrait"], source).texte
        retenus.append({**e, "titre": bouclier.nettoyer_contenu(e["titre"], source).texte, "extrait": propre})
    return retenus, alertes


def formater_protege(extraits_: list[dict]) -> str:
    """Extraits formatés dans UN bloc « DONNÉES NON FIABLES » à délimiteurs aléatoires."""
    return bouclier.encapsuler(formater(extraits_), "mémoire du projet") if extraits_ else ""


def formater(extraits_: list[dict]) -> str:
    return "\n".join(f"- [{e['source']}] {e['titre']} : {e['extrait']}" for e in extraits_)


# --- Import de fichiers Markdown ---------------------------------------------------------------

def _projet_du_fichier(chemin: Path, texte: str) -> str | None:
    for ligne in texte.splitlines()[:30]:
        m = re.match(r"^\s*(?:[-*]\s*)?projet\s*:\s*`?([A-Za-z0-9-]+)`?\s*$", ligne, re.I)
        if m:
            try:
                return registre.resoudre(m.group(1))
            except ValueError:
                return None
    try:
        return registre.resoudre(chemin.stem)
    except ValueError:
        return None


def decouper(texte: str) -> list[tuple[str, str]]:
    """Découpe un Markdown par titres (#, ##, ###) en morceaux d'au plus TAILLE_MORCEAU caractères."""
    sections, titre, lignes = [], "", []
    for ligne in texte.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)", ligne)
        if m:
            if "".join(lignes).strip():
                sections.append((titre, "\n".join(lignes).strip()))
            titre, lignes = m.group(1).strip(), []
        else:
            lignes.append(ligne)
    if "".join(lignes).strip():
        sections.append((titre, "\n".join(lignes).strip()))
    morceaux = []
    for titre, contenu in sections:
        while len(contenu) > TAILLE_MORCEAU:
            coupe = contenu.rfind("\n", 0, TAILLE_MORCEAU)
            coupe = coupe if coupe > TAILLE_MORCEAU // 2 else TAILLE_MORCEAU
            morceaux.append((titre, contenu[:coupe].strip()))
            contenu = contenu[coupe:].strip()
        if contenu:
            morceaux.append((titre, contenu))
    return morceaux


def importer(dossier: str | Path | None = None) -> dict:
    """Importe les .md du dossier (récursif). Idempotent : rien ne change si les fichiers sont identiques."""
    racine = Path(dossier or os.environ.get("NEXUS_CONNAISSANCES_DIR", "").strip() or "/connaissances")
    stats = {"fichiers": 0, "ajoutees": 0, "mises_a_jour": 0, "inchangees": 0, "supprimees": 0, "ignores": 0, "rejetees": 0}
    if not racine.is_dir():
        return {**stats, "absent": str(racine)}
    for f in sorted(racine.rglob("*.md")):
        try:
            texte = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stats["ignores"] += 1
            continue
        projet = _projet_du_fichier(f, texte)
        if projet is None:
            stats["ignores"] += 1
            continue
        stats["fichiers"] += 1
        rel = f.relative_to(racine).as_posix()
        sources = set()
        # La ligne « projet: code » est une métadonnée : elle n'est pas importée comme contenu.
        corps = re.sub(r"\A((?:.*\n){0,30}?)\s*(?:[-*]\s*)?projet\s*:\s*`?[A-Za-z0-9-]+`?\s*\n", r"\1",
                       texte + "\n", count=1, flags=re.I)
        for i, (titre, contenu) in enumerate(decouper(corps), 1):
            source = f"{rel}#{i}"
            sources.add(source)
            try:
                r = ajouter(projet, f"{f.stem} — {titre}" if titre else f.stem, contenu, source, "import",
                            origine="import", masquer=True)
            except InjectionRefusee:
                stats["rejetees"] += 1  # morceau non importé (tracé au LEDGER par ajouter)
                continue
            stats[{"ajoutee": "ajoutees", "mise_a_jour": "mises_a_jour", "inchangee": "inchangees"}[r["etat"]]] += 1
        with session_scope() as s:  # morceaux disparus du fichier
            anciens = s.execute(select(Connaissance).where(Connaissance.origine == "import",
                                                           Connaissance.source.like(f"{rel}#%"))).scalars().all()
            for k in anciens:
                if k.source not in sources:
                    s.delete(k)
                    stats["supprimees"] += 1
    if stats["ajoutees"] or stats["mises_a_jour"] or stats["supprimees"]:
        ledger.journaliser("NEXUS-PRIME", "connaissances_importees", None, **stats)
    return stats


# --- Mémorisation automatique des livrables ----------------------------------------------------

def auto_active() -> bool:
    return os.environ.get("NEXUS_MEMOIRE_AUTO", "1").strip() != "0"


def resume_livrable(livrable: str | None) -> str:
    lignes = [l.strip() for l in (livrable or "").splitlines()
              if l.strip() and not l.strip().upper().startswith("BROUILLON")]
    texte = re.sub(r"\s+", " ", " ".join(lignes)).strip()
    return texte if len(texte) <= RESUME_LIVRABLE_MAX else texte[: RESUME_LIVRABLE_MAX - 1].rstrip() + "…"


def memoriser_livrable(mid: int, titre: str, projet: str, livrable: str | None) -> dict | None:
    if not auto_active():
        return None
    resume = resume_livrable(livrable)
    if not resume:
        return None
    # Jamais de mémorisation automatique d'un livrable suspect d'injection réussie (les secrets seuls
    # sont déjà masqués par ajouter(masquer=True) : ils n'empêchent pas la mémorisation).
    motifs = [m for m in bouclier.verifier_sortie(livrable or "")["motifs"] if not m.startswith("secret")]
    if motifs:
        ledger.journaliser("NEXUS-BOUCLIER", "memorisation_refusee", mid, motifs=motifs[:6])
        return None
    try:
        return ajouter(projet, f"livrable #{mid} — {titre}", resume, f"livrable #{mid}", "nexus-core",
                       origine="auto", masquer=True)
    except InjectionRefusee:
        return None
