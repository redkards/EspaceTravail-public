"""Veille SYFER (méga-base de sources) branchée sur le COLLECTOR, sans aucun appel LLM.

- Code et base montés en lecture seule : NEXUS_VEILLE_DIR (défaut /veille, sinon ../veille du dépôt)
  contient recherche.py ; base : VEILLE_DB (défaut <NEXUS_VEILLE_DIR>/veille.db). NEXUS_VEILLE=0 désactive.
- Fiches : recherche.fiches_pour_mission(consigne, service, projet, max=NEXUS_VEILLE_MAX=5) — recherche
  plein texte locale (premier pas du « mode 100 % local »). La veille ne bloque jamais une mission.
- Chaque fiche passe par le bouclier (filtrer_contenu : rejet ≥ SEUIL_HAUT, alertes transmises),
  le bloc est cité « [veille:<source> · confiance X · date] » et encapsulé « DONNÉES NON FIABLES ».
- Confiance D (réseaux sociaux) : jamais un fait. Consigne à l'ANALYST et au CHECKER, et contrôle
  déterministe `affirmations_d` : une ligne qui cite une fiche D sans formule de prudence est refusée.
"""
import importlib.util
import logging
import os
import re
from pathlib import Path

from . import bouclier, ledger

log = logging.getLogger("nexus.veille")
_module = None
_chemin_module: Path | None = None
PRUDENCE = re.compile(r"selon|d'apr[eè]s|non v[ée]rifi|[àa] recouper|rumeur|affirm|pr[ée]tend|signal[ée]|"
                      r"non confirm|[àa] confirmer|r[ée]seaux? sociaux?|publication sur|indique sur", re.I)


def active() -> bool:
    return os.environ.get("NEXUS_VEILLE", "1").strip() != "0"


def dossier() -> Path:
    v = os.environ.get("NEXUS_VEILLE_DIR", "").strip()
    if v:
        return Path(v)
    return Path("/veille") if Path("/veille/recherche.py").is_file() else \
        Path(__file__).resolve().parents[2] / "veille"


def chemin_db() -> str:
    return os.environ.get("VEILLE_DB", "").strip() or str(dossier() / "veille.db")


def maximum() -> int:
    try:
        return max(1, min(10, int(os.environ.get("NEXUS_VEILLE_MAX", "") or 5)))
    except ValueError:
        return 5


def _recherche():
    """Charge recherche.py par son chemin (montage en lecture seule), sans toucher sys.path."""
    global _module, _chemin_module
    f = dossier() / "recherche.py"
    if _module is None or _chemin_module != f:
        spec = importlib.util.spec_from_file_location("syfer_veille_recherche", f)
        if spec is None or spec.loader is None or not f.is_file():
            raise FileNotFoundError(str(f))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _module, _chemin_module = m, f
    return _module


def fiches(consigne: str, service: str | None, projet: str | None) -> list[dict]:
    if not active():
        return []
    try:
        return _recherche().fiches_pour_mission(consigne, service, projet, max=maximum(), chemin_db=chemin_db())
    except Exception as e:  # la veille ne doit jamais bloquer une mission
        log.warning("veille indisponible : %s", type(e).__name__)
        return []


def _ligne(f: dict) -> str:
    date = (f.get("date") or f.get("collecte_le") or "")[:10]
    return (f"- [veille:{f['source_id']} · confiance {f['confiance']} · {date}] {f['titre']} : {f['resume']}"
            + (f" ({f['url']})" if f.get("url") else ""))


def pour_mission(ctx_mid: int, consigne: str, service: str | None, projet: str | None) -> dict:
    """{"texte": bloc encapsulé ou "", "alertes": [...], "sources_d": [...], "sources": [...]}"""
    res = {"texte": "", "alertes": [], "sources_d": [], "sources": [], "fiches_d": []}
    trouvees = fiches(consigne, service, projet)
    retenues = []
    for f in trouvees:
        source = f"veille:{f['source_id']}"
        v = bouclier.filtrer_contenu(f"{f['titre']} : {f['resume']}", source, journal=ledger.journaliser,
                                     mission_id=ctx_mid)
        res["alertes"].extend(v.alertes_transmises)
        if v.decision == "accepte" and v.score >= bouclier.SEUIL_BAS:
            res["alertes"].append(f"{bouclier.FAIBLE} {source} : score {v.score}/100")
        if v.decision == "rejete":
            continue
        propre = {**f, "titre": bouclier.nettoyer_contenu(f["titre"], source).texte,
                  "resume": bouclier.nettoyer_contenu(f["resume"], source).texte}
        retenues.append(propre)
    if not retenues:
        return res
    res["sources"] = [f["source_id"] for f in retenues]
    res["sources_d"] = sorted({f["source_id"] for f in retenues if f.get("confiance") == "D"})
    res["fiches_d"] = [{"source_id": f["source_id"], "mots": sorted(mots_distinctifs(f"{f['titre']} {f['resume']}"))}
                       for f in retenues if f.get("confiance") == "D"]
    texte = ("Veille SYFER (fiches courtes à recouper ; confiance A = officielle … D = réseau social, "
             "JAMAIS un fait) :\n" + "\n".join(_ligne(f) for f in retenues))
    res["texte"] = bouclier.encapsuler(texte, "veille SYFER")
    ledger.journaliser("NEXUS-PRIME", "veille_fournie", ctx_mid, projet=projet, sources=res["sources"],
                       confiance_d=res["sources_d"])
    return res


CONSIGNE_D = ("Une fiche de confiance D (réseau social) n'est JAMAIS un fait : ne la reprenez qu'avec une formule "
              "de prudence explicite (« selon <source>, non vérifié »), ou pas du tout.")


_VIDES = set("""avec dans pour par sur sous une des les aux du de la le un et ou est sont serait seraient
etait sera cette ces son sa ses leur leurs plus moins tres tout tous toute toutes comme mais pas que qui quoi
dont rumeur selon fait faits vers chez entre depuis apres avant source sources veille confiance""".split())
SEUIL_RECOUVREMENT = 3  # mots distinctifs communs avec une fiche D pour la reconnaître reformulée


def _norm(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def mots_distinctifs(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z0-9]{4,}", _norm(texte)) if m not in _VIDES}


def affirmations_d(livrable: str, sources_d: list[str], fiches_d: list[dict] | None = None,
                   sujet: str = "") -> list[str]:
    """Lignes du livrable reprenant une fiche D sans formule de prudence (contrôle déterministe) :
    citation « veille:<source> », simple mention de la source, ou contenu reformulé (au moins
    SEUIL_RECOUVREMENT mots distinctifs de la fiche, ou la moitié d'entre eux, hors mots du sujet de
    la mission : `sujet` = titre + consigne, dont les mots ne prouvent rien)."""
    du_sujet = mots_distinctifs(sujet)
    if not sources_d and not fiches_d:
        return []
    fiches = fiches_d or [{"source_id": s, "mots": []} for s in sources_d]
    problemes = []
    for ligne in (livrable or "").splitlines():
        if not ligne.strip() or PRUDENCE.search(ligne):
            continue
        mots = mots_distinctifs(ligne)
        for f in fiches:
            s, distinctifs = f["source_id"], set(f.get("mots") or []) - du_sujet
            communs = mots & distinctifs
            cite = f"veille:{s}" in ligne or re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", ligne)
            reformule = len(distinctifs) >= 2 and \
                len(communs) >= min(SEUIL_RECOUVREMENT, max(2, (len(distinctifs) + 1) // 2))
            if cite or reformule:
                problemes.append(f"[veille] fiche de confiance D ({s}) présentée comme un fait : "
                                 f"« {ligne.strip()[:120]} » — ajoutez « selon …, non vérifié » ou retirez-la")
                break
    return problemes
