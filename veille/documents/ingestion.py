"""VEILLE SYFER — ingestion de DOCUMENTS LONGS (normes, guides, RFC, documentation, cahiers des charges).

Chaque document listé dans documents.yaml est téléchargé (accès autorisé : robots.txt, délai poli, User-Agent
SYFER), découpé en SECTIONS (titre, numéro, ancre) et rangé dans veille.db comme fiches « document » citables
précisément : « NIST SP 800-63B-4 §3.1.1.2 », « RFC 9110 §15.5.4 », « RGPD art. 28 », « RGAA 4.1 critère 11.1 ».

Politique selon la licence (collecteur.stockage_autorise) — appliquée ICI, pas seulement déclarée :
- integral    (Licence Ouverte Etalab, domaine public, CC BY / BY-SA, licence RFC/IETF, W3C, MIT, Apache, UE) :
                texte des sections conservé (≤ 6 000 caractères par partie) + résumé ;
- extrait     (droits réservés, licence inconnue) : titre de section + résumé ≤ 500 caractères + lien ;
- metadonnees (normes payantes ISO, ETSI à reproduction restreinte) : une seule fiche titre + lien, sans texte.
Chaque section passe par le bouclier anti-injection (rejet si score ≥ 60), l'anonymisation et le filtre à secrets.

Formats : HTML (html.parser de la bibliothèque standard), texte brut (RFC), Markdown, PDF.
PDF : la bibliothèque standard ne lit pas le PDF. Si le paquet facultatif `pypdf` est installé, le texte est
extrait ; sinon le document est enregistré en MÉTADONNÉES + lien, et le journal le dit clairement.

Commandes
    python documents/ingestion.py                 # tous les documents de documents.yaml
    python documents/ingestion.py --id rfc9110    # un seul
    python documents/ingestion.py --lister        # liste et politique appliquée, sans réseau
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import io
import logging
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))
import collecteur as C  # noqa: E402

log = logging.getLogger("syfer.veille.documents")
MAX_PARTIE = 6000
MAX_SECTIONS = 400
TITRES = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
IGNORER = {"script", "style", "nav", "header", "footer", "noscript", "svg", "template", "form", "button", "aside"}
BLOCS = {"p", "li", "td", "th", "dd", "dt", "pre", "blockquote", "figcaption", "caption", "div", "section", "tr", "br"}


# --------------------------------------------------------------------------------------------- découpage
class _Decoupeur(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[dict] = []
        self.pile_ignorer = 0
        self.titre_niveau = 0
        self.titre_buf: list[str] = []
        self.ancre_titre = ""
        self.ancre_courante = ""
        self.buf: list[str] = []
        self.courante = {"niveau": 0, "titre": "", "ancre": "", "texte": []}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in IGNORER:
            self.pile_ignorer += 1
            return
        if a.get("id") and not self.titre_niveau:
            self.ancre_courante = a["id"]
        if tag in TITRES:
            self._vider()
            self.titre_niveau = TITRES[tag]
            self.titre_buf = []
            self.ancre_titre = a.get("id") or self.ancre_courante
        elif tag in BLOCS:
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in IGNORER:
            self.pile_ignorer = max(0, self.pile_ignorer - 1)
            return
        if tag in TITRES and self.titre_niveau:
            titre = re.sub(r"\s+", " ", "".join(self.titre_buf)).strip()
            self._clore()
            self.courante = {"niveau": self.titre_niveau, "titre": titre, "ancre": self.ancre_titre, "texte": []}
            self.titre_niveau = 0
        elif tag in BLOCS:
            self.buf.append("\n")

    def handle_data(self, data):
        if self.pile_ignorer:
            return
        (self.titre_buf if self.titre_niveau else self.buf).append(data)

    def _vider(self):
        self.courante["texte"].append("".join(self.buf))
        self.buf = []

    def _clore(self):
        self._vider()
        texte = _propre("\n".join(self.courante["texte"]))
        if self.courante["titre"] or texte:
            self.sections.append({"titre": self.courante["titre"], "ancre": self.courante["ancre"], "texte": texte,
                                  "niveau": self.courante["niveau"]})

    def fin(self) -> list[dict]:
        self._clore()
        return self.sections


def _propre(t: str) -> str:
    t = html.unescape(t or "").replace("\xa0", " ")
    lignes = [re.sub(r"[ \t]+", " ", l).strip() for l in t.splitlines()]
    t = "\n".join(l for l in lignes if l)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def decouper_html(contenu: str) -> list[dict]:
    d = _Decoupeur()
    d.feed(contenu)
    d.close()
    return d.fin()


RE_TITRE_RFC = re.compile(r"^(?P<num>(?:\d+(?:\.\d+)*\.?|Appendix [A-Z](?:\.\d+)*\.?))\s+(?P<titre>\S.{0,120})$")
RE_PAGE_RFC = re.compile(r"^(RFC \d+ .* \w+ \d{4}|.*\[Page \d+\])$")


def decouper_texte(contenu: str) -> list[dict]:
    """Texte brut (RFC) : titres non indentés « 5.1.1.  Titre » ; en-têtes/pieds de page retirés."""
    sections, cour = [], {"titre": "", "ancre": "", "texte": [], "niveau": 0}
    for ligne in contenu.replace("\f", "\n").splitlines():
        if RE_PAGE_RFC.match(ligne.strip()):
            continue
        m = RE_TITRE_RFC.match(ligne) if ligne and not ligne[0].isspace() else None
        if m and not ligne.rstrip().endswith("."):
            if cour["titre"] or "".join(cour["texte"]).strip():
                sections.append({**cour, "texte": _propre("\n".join(cour["texte"]))})
            num = m.group("num").rstrip(".")
            ancre = "section-" + num.replace("Appendix ", "appendix-").replace(" ", "-")
            cour = {"titre": f"{m.group('num')} {m.group('titre').strip()}", "ancre": ancre, "texte": [],
                    "niveau": num.count(".") + 1}
        else:
            cour["texte"].append(ligne)
    sections.append({**cour, "texte": _propre("\n".join(cour["texte"]))})
    return [s for s in sections if s["titre"] or s["texte"]]


def decouper_markdown(contenu: str) -> list[dict]:
    sections, cour = [], {"titre": "", "ancre": "", "texte": [], "niveau": 0}
    dans_code = False
    for ligne in contenu.splitlines():
        if ligne.strip().startswith("```"):
            dans_code = not dans_code
        m = None if dans_code else re.match(r"^(#{1,6})\s+(.*\S)\s*#*$", ligne)
        if m:
            if cour["titre"] or "".join(cour["texte"]).strip():
                sections.append({**cour, "texte": _propre("\n".join(cour["texte"]))})
            titre = m.group(2)
            ancre = re.sub(r"[^\w\s-]", "", titre.lower()).strip().replace(" ", "-")
            cour = {"titre": titre, "ancre": ancre, "texte": [], "niveau": len(m.group(1))}
        else:
            cour["texte"].append(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", ligne)))
    sections.append({**cour, "texte": _propre("\n".join(cour["texte"]))})
    return [s for s in sections if s["titre"] or s["texte"]]


def lecteur_pdf_disponible() -> bool:
    return importlib.util.find_spec("pypdf") is not None


def texte_pdf(octets: bytes) -> str | None:
    """Texte d'un PDF si `pypdf` est installé, sinon None (aucun lecteur PDF dans la bibliothèque standard)."""
    if not lecteur_pdf_disponible():
        return None
    import pypdf  # type: ignore
    lecteur = pypdf.PdfReader(io.BytesIO(octets))
    return "\n".join((p.extract_text() or "") for p in lecteur.pages[:300])


RE_NUM = [
    (re.compile(r"^(?:Section\s+|§\s*)?(\d+(?:\.\d+)*)\.?\s"), "§{}"),
    (re.compile(r"^Appendix\s+([A-Z](?:\.\d+)*)\.?\s", re.I), "annexe {}"),
    (re.compile(r"^Article\s+(\d+[a-z]*)\b", re.I), "art. {}"),
    (re.compile(r"^Crit(?:è|e)re\s+(\d+\.\d+)\b", re.I), "critère {}"),
    (re.compile(r"^(?:Success Criterion|Crit(?:è|e)re de succ(?:è|e)s)\s+(\d+\.\d+\.\d+)\b", re.I), "SC {}"),
    (re.compile(r"^(?:Recommandation|R)\s*(\d+)\b"), "R{}"),
]


def numero_et_ref(titre: str, ref_court: str, rang: int) -> tuple[str, str]:
    for motif, gabarit in RE_NUM:
        m = motif.match(titre.strip())
        if m:
            num = gabarit.format(m.group(1))
            return num, f"{ref_court} {num}"
    return "", f"{ref_court} — {titre[:80]}" if titre else f"{ref_court} (partie {rang})"


# --------------------------------------------------------------------------------------------- ingestion
def charger_documents(chemin: Path | None = None) -> list[dict]:
    import yaml
    d = yaml.safe_load((chemin or ICI / "documents.yaml").read_text(encoding="utf-8")) or {}
    return d.get("documents", [])


def politique(doc: dict, source: dict | None) -> str:
    """Stockage effectif d'un document : le plus restrictif entre la demande et la licence."""
    licence = doc.get("licence") or (source or {}).get("licence", "droits-reserves")
    demande = doc.get("stockage") or (source or {}).get("stockage", "extrait")
    return C.stockage_effectif({"licence": licence, "stockage": demande})


def detecter_format(doc: dict, reponse: C.Reponse) -> str:
    f = doc.get("format", "auto")
    if f != "auto":
        return f
    ct = reponse.entetes.get("content-type", "")
    if reponse.corps[:5] == b"%PDF-" or "pdf" in ct:
        return "pdf"
    if "html" in ct or reponse.corps.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        return "html"
    if doc["url"].endswith(".md") or "markdown" in ct:
        return "md"
    return "txt"


def sections_de(fmt: str, octets: bytes) -> tuple[list[dict], str]:
    if fmt == "pdf":
        texte = texte_pdf(octets)
        if texte is None:
            return [], "PDF non lu : aucun lecteur PDF disponible (bibliothèque standard) → métadonnées + lien"
        return decouper_texte(texte) or [{"titre": "", "ancre": "", "texte": _propre(texte), "niveau": 0}], "pdf (pypdf)"
    contenu = octets.decode("utf-8", "replace")
    if fmt == "html":
        return decouper_html(contenu), "html"
    if fmt == "md":
        return decouper_markdown(contenu), "markdown"
    return decouper_texte(contenu), "texte"


def fiches_document(doc: dict, source: dict, sections: list[dict], stockage: str, col: C.Collecteur,
                    note_format: str = "") -> tuple[list[dict], dict]:
    """Construit les fiches (une par section, ou une seule en métadonnées). Renvoie (fiches, bilan)."""
    bilan = {"sections": 0, "rejetees": 0, "stockage": stockage, "format": note_format}
    base = {
        "source_id": source["id"], "domaines": " ".join(doc.get("domaines") or source.get("domaines") or []),
        "services": C._liste(source.get("services_syfer") or []), "projets": C._liste(source.get("projets") or []),
        "confiance": source["confiance"], "type": source["type"], "langue": doc.get("langue", source.get("langue", "")),
        "collecte_le": C._iso(col.horloge()), "date": C._date_iso(doc.get("date")),
        "type_doc": doc.get("type_doc", source.get("type_doc", "guide")), "canal": "document",
        "licence": doc.get("licence") or source.get("licence", ""), "stockage": stockage, "document": doc["id"],
        "autorite": float(doc.get("autorite", source.get("autorite", C.AUTORITE_PAR_TYPE.get(source["type"], 0.5)))),
    }
    url_doc = doc["url"]
    if stockage == "metadonnees" or not sections:
        resume = doc.get("description", "")
        if note_format.startswith("PDF non lu"):
            resume = (resume + " " if resume else "") + "Texte non extrait (PDF, pas de lecteur disponible) : consulter le lien."
        f = base | {"titre": f"{doc['ref_court']} — {doc['titre']}", "resume": C.tronquer(resume, C.MAX_RESUME),
                    "url": url_doc, "url_canonique": C.url_canonique(url_doc), "ref": doc["ref_court"], "texte": "",
                    "stockage": "metadonnees"}
        f["empreinte"] = C.empreinte(f["titre"], f["url_canonique"])
        return [f], bilan
    fiches, vus = [], set()
    for rang, sec in enumerate(sections[:MAX_SECTIONS], start=1):
        n_titre = col.nettoyeur.nettoyer(sec["titre"], source["id"])
        n_texte = col.nettoyeur.nettoyer(sec["texte"], source["id"])
        score = max(n_titre.score, n_texte.score)
        if score >= C.SEUIL_REJET or col.nettoyeur.secrets(n_texte.texte):
            bilan["rejetees"] += 1
            continue
        titre_sec = C.anonymiser(n_titre.texte)
        texte = C.anonymiser(n_texte.texte)
        if not titre_sec and len(texte) < 40:
            continue
        num, ref = numero_et_ref(titre_sec, doc["ref_court"], rang)
        ancre = sec.get("ancre") or ("s" + hashlib.sha1(f"{rang}{titre_sec}".encode()).hexdigest()[:8])
        parties = [texte[i:i + MAX_PARTIE] for i in range(0, max(1, len(texte)), MAX_PARTIE)] if stockage == "integral" else [texte]
        for k, partie in enumerate(parties, start=1):
            ref_p = ref if len(parties) == 1 else f"{ref} ({k}/{len(parties)})"
            cle = f"{ancre}" if len(parties) == 1 else f"{ancre}-{k}"
            if cle in vus:
                cle = f"{cle}-{rang}"
            vus.add(cle)
            f = base | {"titre": C.tronquer(f"{doc['ref_court']} · {titre_sec}" if titre_sec else ref_p, C.MAX_TITRE),
                        "resume": C.tronquer(partie, C.MAX_RESUME), "url": f"{url_doc}#{urllib.parse.quote(ancre)}",
                        "url_canonique": C.url_canonique(url_doc) + "#" + cle, "ref": ref_p,
                        "texte": partie if stockage == "integral" else "", "score_injection": int(score)}
            f["empreinte"] = C.empreinte(f"{doc['id']} {ref_p} {f['titre']}", partie[:200])
            fiches.append(f)
        bilan["sections"] += 1
    return fiches, bilan


def ingerer(doc: dict, sources: dict, col: C.Collecteur) -> dict:
    source = sources.get(doc["source"])
    if source is None:
        return {"id": doc["id"], "erreur": f"source inconnue {doc['source']}"}
    stockage = politique(doc, source)
    url = doc["url"]
    if not col.robots.autorise(url):
        return {"id": doc["id"], "erreur": col.robots.motif(url)}
    col.politesse.attendre(url)
    r = col.transport.get(url, {"User-Agent": C.USER_AGENT, "Accept-Encoding": "gzip"})
    if r.statut != 200:
        return {"id": doc["id"], "erreur": f"HTTP {r.statut}"}
    fmt = detecter_format(doc, r)
    sections, note = sections_de(fmt, r.corps) if stockage != "metadonnees" else ([], "métadonnées (licence)")
    fiches, bilan = fiches_document(doc, source, sections, stockage, col, note)
    # nouvelle version : on remplace l'ancienne (même document)
    col.conn.execute("DELETE FROM fiches WHERE document = ?", (doc["id"],))
    bilan["enregistrees"] = sum(1 for f in fiches if col.enregistrer(f))
    col.conn.commit()
    log.info("document %s : %s, %d section(s), %d enregistrée(s), stockage %s", doc["id"], note,
             bilan["sections"], bilan["enregistrees"], stockage)
    return {"id": doc["id"], **bilan}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingestion des documents de référence (sections citables)")
    ap.add_argument("--id", action="append")
    ap.add_argument("--lister", action="store_true")
    ap.add_argument("--db", default=str(C.DB_DEFAUT))
    a = ap.parse_args(argv)
    C.configurer_journal()
    cat = C.charger_catalogue()
    sources = {s["id"]: s for s in cat["sources"]}
    docs = [d for d in charger_documents() if not a.id or d["id"] in a.id]
    if a.lister:
        print(f"Lecteur PDF disponible : {'oui (pypdf)' if lecteur_pdf_disponible() else 'non → PDF en métadonnées + lien'}")
        for d in docs:
            s = sources.get(d["source"], {})
            print(f"- {d['id']:<28} {d['ref_court']:<24} licence={d.get('licence') or s.get('licence')} "
                  f"→ stockage {politique(d, s)}")
        return 0
    with C.base_de_travail(a.db) as conn:
        col = C.Collecteur(conn)
        for d in docs:
            try:
                print(ingerer(d, sources, col))
            except Exception as e:  # un document en échec n'arrête pas les autres
                print({"id": d["id"], "erreur": f"{type(e).__name__}: {str(e)[:120]}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
