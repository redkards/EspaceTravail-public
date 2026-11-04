"""Rapport PDF professionnel (français) du SYFER Test System v1 — reportlab + DejaVu, graphiques matplotlib
(ou dessin reportlab si matplotlib manque)."""
from __future__ import annotations

import io
import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from xml.sax.saxutils import escape

from . import NOM, VERSION

POLICES = Path("/usr/share/fonts/truetype/dejavu")
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
ENCRE, ENCRE2, GRILLE, FOND = "#0b0b0b", "#52514e", "#e6e5e0", "#f6f5f1"
VERT, ROUGE, ORANGE = "#1a7f37", "#c62828", "#b26a00"
STATUT = {"reussi": ("Réussie", VERT), "echoue": ("Échec", ROUGE), "saute": ("Sautée", ENCRE2),
          "erreur": ("Erreur", ROUGE), "delai": ("Délai dépassé", ORANGE)}
GRAV = {"critique": ROUGE, "majeure": ORANGE, "mineure": "#52514e", "info": "#8a8984"}
LARGEUR = A4[0] - 30 * mm


def _polices() -> tuple[str, str]:
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", str(POLICES / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(POLICES / "DejaVuSans-Bold.ttf")))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu", boldItalic="DejaVu-Bold")
        return "DejaVu", "DejaVu-Bold"
    except Exception:  # noqa: BLE001
        return "Helvetica", "Helvetica-Bold"


N, B = _polices()
ST = {
    "titre": ParagraphStyle("titre", fontName=B, fontSize=20, leading=24, textColor=colors.HexColor(ENCRE), spaceAfter=4),
    "sous": ParagraphStyle("sous", fontName=N, fontSize=9.5, leading=13, textColor=colors.HexColor(ENCRE2)),
    "h1": ParagraphStyle("h1", fontName=B, fontSize=14, leading=18, spaceBefore=6, spaceAfter=6, textColor=colors.HexColor(ENCRE)),
    "h2": ParagraphStyle("h2", fontName=B, fontSize=11, leading=14, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor(ENCRE)),
    "p": ParagraphStyle("p", fontName=N, fontSize=9, leading=12.5, textColor=colors.HexColor(ENCRE)),
    "pp": ParagraphStyle("pp", fontName=N, fontSize=7.6, leading=9.6, textColor=colors.HexColor(ENCRE)),
    "ppb": ParagraphStyle("ppb", fontName=B, fontSize=7.6, leading=9.6, textColor=colors.HexColor(ENCRE)),
    "th": ParagraphStyle("th", fontName=B, fontSize=7.8, leading=9.6, textColor=colors.white),
    "thp": ParagraphStyle("thp", fontName=B, fontSize=7, leading=8.6, textColor=colors.white),
    "gros": ParagraphStyle("gros", fontName=B, fontSize=26, leading=30, alignment=TA_CENTER),
    "centre": ParagraphStyle("centre", fontName=N, fontSize=8.5, leading=11, alignment=TA_CENTER,
                             textColor=colors.HexColor(ENCRE2)),
}


def P(t, s="p", brut=False):
    """Paragraphe ; le texte est échappé sauf brut=True (balisage reportlab déjà construit)."""
    return Paragraph(t if brut else escape(str(t if t is not None else "—")), ST[s])


def Pc(t, couleur, s="ppb"):
    return Paragraph(f'<font color="{couleur}">{escape(str(t))}</font>', ST[s])


def tableau(lignes, largeurs, entete=True, zebre=True):
    t = Table(lignes, colWidths=largeurs, repeatRows=1 if entete else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(GRILLE))]
    if entete:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b2b29"))]
    if zebre:
        for i in range(1 if entete else 0, len(lignes)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(FOND)))
    t.setStyle(TableStyle(style))
    return t


def _f(v, suff=""):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.1f}{suff}".replace(".", ",")
    return f"{v}{suff}"


def _couleur_score(s):
    if s is None:
        return ENCRE2
    return VERT if s >= 85 else (ORANGE if s >= 65 else ROUGE)


# --------------------------------------------------------------------------- graphiques

def _png(fig) -> io.BytesIO:
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=170, bbox_inches="tight", facecolor="white")
    b.seek(0)
    return b


def graphique_versions(vers: dict, axes_lib: dict):
    codes = vers["classement"]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": GRILLE,
                             "axes.labelcolor": ENCRE2, "xtick.color": ENCRE2, "ytick.color": ENCRE2})
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.3), gridspec_kw={"width_ratios": [1, 2.4]})
        ordre = list(codes)[::-1]
        vals = [vers["versions"][c]["score"]["global"] or 0 for c in ordre]
        a1.barh([f"{c} · {vers['versions'][c]['profil']['nom']}" for c in ordre], vals, color=SERIE[0], height=0.55)
        for i, v in enumerate(vals):
            a1.text(v + 1, i, f"{v:.1f}", va="center", fontsize=8, color=ENCRE)
        a1.set_xlim(0, 110)
        a1.set_title("Score global /100", fontsize=9, color=ENCRE, loc="left")
        a1.grid(axis="x", color=GRILLE, lw=0.6)
        a1.set_axisbelow(True)
        for s in ("top", "right"):
            a1.spines[s].set_visible(False)
        axes = [a for a in axes_lib if any(vers["versions"][c]["score"]["axes"][a]["score"] is not None for c in codes)]
        n = len(codes)
        w = 0.8 / n
        for i, c in enumerate(sorted(codes)):
            ys = [vers["versions"][c]["score"]["axes"][a]["score"] or 0 for a in axes]
            xs = [k + (i - (n - 1) / 2) * w for k in range(len(axes))]
            a2.bar(xs, ys, width=w * 0.9, color=SERIE[i], label=f"{c} {vers['versions'][c]['profil']['nom']}")
        a2.set_xticks(range(len(axes)))
        a2.set_xticklabels([axes_lib[a] for a in axes], fontsize=7.5)
        a2.set_ylim(0, 105)
        a2.set_title("Score par axe /100 (axes dépendant de la configuration)", fontsize=9, color=ENCRE, loc="left")
        a2.grid(axis="y", color=GRILLE, lw=0.6)
        a2.set_axisbelow(True)
        for s in ("top", "right"):
            a2.spines[s].set_visible(False)
        a2.legend(fontsize=7, frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.12))
        fig.tight_layout()
        b = _png(fig)
        plt.close(fig)
        return Image(b, width=LARGEUR, height=LARGEUR * 3.3 / 8.6 * 1.08)
    except ImportError:
        return _dessin_versions(vers)


def _dessin_versions(vers):
    """Repli sans matplotlib : barres horizontales dessinées avec reportlab."""
    from reportlab.graphics.shapes import Drawing, Rect, String
    codes = vers["classement"]
    d = Drawing(LARGEUR, 22 * len(codes) + 20)
    for i, c in enumerate(codes):
        v = vers["versions"][c]["score"]["global"] or 0
        y = d.height - 20 - 22 * (i + 1)
        d.add(String(0, y + 5, f"{c} {vers['versions'][c]['profil']['nom']}", fontName=N, fontSize=8))
        d.add(Rect(110, y, (LARGEUR - 160) * v / 100, 14, fillColor=colors.HexColor(SERIE[0]), strokeColor=None))
        d.add(String(115 + (LARGEUR - 160) * v / 100, y + 4, f"{v:.1f}", fontName=N, fontSize=8))
    return d


def graphique_tendance(points):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8.6, 2.2))
        xs = list(range(len(points)))
        ax.plot(xs, [p[1] for p in points], color=SERIE[0], lw=2, marker="o", ms=4)
        ax.set_xticks(xs)
        ax.set_xticklabels([p[0][5:16].replace("_", " ") for p in points], fontsize=7, rotation=20)
        ax.set_ylim(0, 105)
        ax.grid(axis="y", color=GRILLE, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.set_title("Score global par passage", fontsize=9, loc="left")
        b = _png(fig)
        plt.close(fig)
        return Image(b, width=LARGEUR, height=LARGEUR * 2.2 / 8.6 * 1.1)
    except ImportError:
        return None


# --------------------------------------------------------------------------- contenu

def _resume_suite(r):
    m = r.get("mesures", {})
    n = r["nom"]
    if r["statut"] not in ("reussi", "echoue"):
        return r.get("motif") or ""
    try:
        return {
            "tests": lambda: f"{m['reussis']}/{m['total'] - m['sautes']} tests verts ; dossiers sautés : "
                             f"{', '.join(m['dossiers_sautes']) or 'aucun'}",
            "protocole": lambda: f"{sum(c['ok'] for c in m['controles'])}/{len(m['controles'])} contrôles · "
                                 f"{m['exemples_conformes']}/{m['exemples']} exemples conformes",
            "simulations": lambda: f"{m['reussis']}/{m['executes']} scénarios réussis ({_f(m['taux_reussite'], ' %')}), "
                                   f"{m['sautes']} sauté(s)",
            "iterations": lambda: f"{m.get('reussis')}/{m.get('iterations')} itérations · défauts ouverts {m.get('defauts_ouverts')}"
                                  f" (critiques {m.get('critiques_ouverts')})",
            "attaque": lambda: f"{m['bloquees']}/{m['attaques']} attaques bloquées ({_f(m['taux_blocage_pct'], ' %')}) · "
                               f"faux positifs {m['faux_positifs']}/{m['legitimes']}",
            "banc": lambda: f"{m['missions']} missions {m['fonctionnement']} · note système {_f(m['note_systeme_moy'])} · "
                            f"pièges {_f(m['pieges_reussis_pct'], ' %')} · livrable {_f(m['note_livrable_moy'])} (LLM factice)",
            "charge": lambda: f"{m['reussis']}/{m['scenarios']} scénarios · critères {m['criteres_ok']}/{m['criteres_total']}"
                              f" · pertes de données {len(m['pertes_donnees'])}" + (" · mode court" if m.get("rapide") else ""),
            "jumeau": lambda: (f"score {_f(m['version']['nominal']['score'])} · {_f(m['version']['nominal']['livrees_jour'])} "
                               f"missions/j · {_f(m['version']['nominal']['cout_total_eur'], ' €')}/mois"
                               + (f" · catalogue : {m['catalogue'].get('recommandation')}" if m.get("catalogue") else "")),
            "compaction": lambda: f"rc {m.get('rc')} · " + ", ".join(f"{k}={v}" for k, v in list((m.get('indicateurs') or {}).items())[:4]),
            "statiques": lambda: " · ".join(f"{k} {v.get('ok', '')}/{v.get('total', '')}" if v.get("total") is not None
                                            else f"{k} {v['statut']}" for k, v in m["controles"].items()
                                            if k != "secrets") + f" · secrets suspects {m['secrets_suspects']}",
        }[n]()
    except Exception:  # noqa: BLE001
        return ""


def points_forts(fiche, suites):
    axes = sorted([a for a in fiche["axes"].values() if a["score"] is not None], key=lambda a: -a["score"])
    out = []
    preuves = {
        "Sécurité": lambda: f"attaque {suites['attaque']['mesures']['taux_blocage_pct']} % bloquée, "
                            f"{suites['statiques']['mesures']['secrets_suspects']} secret suspect",
        "Fiabilité": lambda: f"{suites['tests']['mesures']['reussis']} tests verts, "
                             f"{suites['simulations']['mesures']['reussis']} scénarios réussis",
    }
    for a in axes[:3]:
        try:
            pr = preuves[a["libelle"]]()
        except Exception:  # noqa: BLE001
            pr = "composantes : " + ", ".join(f"{k.replace('_', ' ')} {_f(v)}" for k, v in a["composantes"].items()
                                              if v is not None and k != "banc_livrable")
        out.append(f"<b>{escape(a['libelle'])} {_f(a['score'])}/100</b> — {escape(pr)}")
    return out


def _entete_page(c, doc):
    c.saveState()
    c.setFont(N, 7)
    c.setFillColor(colors.HexColor(ENCRE2))
    c.drawString(15 * mm, 10 * mm, f"{NOM} ({VERSION}) — rapport généré le {time.strftime('%d/%m/%Y %H:%M')}")
    c.drawRightString(A4[0] - 15 * mm, 10 * mm, f"page {doc.page}")
    c.setStrokeColor(colors.HexColor(GRILLE))
    c.line(15 * mm, 13 * mm, A4[0] - 15 * mm, 13 * mm)
    c.restoreState()


def produire(base: dict | None, vers: dict | None, precedents: list[dict], cible: Path) -> Path:
    cible.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(cible), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=17 * mm, title=f"{NOM} — rapport", author=NOM)
    E = []
    E.append(P(NOM, "titre"))
    if base:
        E.append(P(f"Passage « {base['mode']} » du {base['horodatage'].replace('_', ' ')} · profil {base['profil']['code']} "
                   f"({base['profil']['nom']}) · graine {base['graine']} · durée {round(base['duree_s'] / 60, 1)} min", "sous"))
    if vers:
        E.append(P(f"Comparaison des versions : passage du {vers['horodatage'].replace('_', ' ')} (graine {vers['graine']}, "
                   "identique pour les 5 versions)", "sous"))
    E.append(Spacer(1, 8))

    if base:
        fiche, suites, porte = base["score"], base["suites"], base["porte"]
        coul = VERT if porte["verdict"] == "VERT" else ROUGE
        bloc = Table([[Paragraph(f'<font color="{coul}">PORTE {porte["verdict"]}</font>', ST["gros"]),
                       Paragraph(f'<font color="{_couleur_score(fiche["global"])}">{_f(fiche["global"])}</font>'
                                 f'<font size="12" color="{ENCRE2}"> /100</font>', ST["gros"])],
                      [P("Déploiement " + ("AUTORISÉ" if porte["deploiement_autorise"] else "REFUSÉ"), "centre"),
                       P(f"Score global (couverture {int(100 * fiche['couverture_globale'])} %)", "centre")]],
                     colWidths=[LARGEUR / 2] * 2)
        bloc.setStyle(TableStyle([("BOX", (0, 0), (0, -1), 1.2, colors.HexColor(coul)),
                                  ("BOX", (1, 0), (1, -1), 0.6, colors.HexColor(GRILLE)),
                                  ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 8)]))
        E += [bloc, Spacer(1, 8)]
        lignes = [[P("Axe", "thp")] + [P(a["libelle"], "thp") for a in fiche["axes"].values()]]
        lignes.append([P("Score /100", "ppb")] + [Pc(_f(a["score"]), _couleur_score(a["score"])) for a in fiche["axes"].values()])
        E += [tableau(lignes, [LARGEUR * 0.12] + [LARGEUR * 0.88 / len(fiche["axes"])] * len(fiche["axes"])), Spacer(1, 8)]
        if porte["raisons"]:
            E.append(P("Raisons du verdict", "h2"))
            E += [P("• " + escape(r), brut=True) for r in porte["raisons"]]
        E.append(P("3 points forts", "h2"))
        E += [P("• " + x, brut=True) for x in points_forts(fiche, suites)]
        E.append(P("3 défauts majeurs", "h2"))
        top = base["defauts"][:3]
        E += [P(f"• <b>[{d['gravite']}]</b> {escape(d['titre'])} — <i>{escape(d['correction'])}</i> "
                f"({escape(d['responsable'])})", brut=True) for d in top] or [P("Aucun défaut.")]
        sautes = [f"{s['nom']} : {s['motif']}" for s in suites.values() if s["statut"] == "saute"]
        sautes += [f"tests/{x}" for x in suites.get("tests", {}).get("mesures", {}).get("dossiers_sautes", [])]
        if sautes:
            E.append(P("Épreuves sautées (intégrées automatiquement dès que leur dossier apparaît)", "h2"))
            E += [P("• " + escape(s), "pp", brut=True) for s in sautes]
        E.append(PageBreak())

        # ---- tableau par suite
        E.append(P("1. Résultats par épreuve", "h1"))
        lignes = [[P(x, "th") for x in ("Épreuve", "Statut", "Durée", "Résultat")]]
        for s in suites.values():
            lib, c = STATUT[s["statut"]]
            lignes.append([P(s["titre"], "ppb"), Pc(lib, c), P(f"{_f(s['duree_s'])} s", "pp"),
                           P(_resume_suite(s) + (f" — {s['motif']}" if s.get("motif") and s["statut"] in ("reussi", "echoue") else ""), "pp")])
        E += [tableau(lignes, [LARGEUR * 0.2, LARGEUR * 0.1, LARGEUR * 0.08, LARGEUR * 0.62]), Spacer(1, 6)]
        t = suites.get("tests")
        if t and t["mesures"].get("par_dossier"):
            E.append(P("Tests unitaires par dossier", "h2"))
            lignes = [[P(x, "th") for x in ("Dossier", "Statut", "Verts", "Rouges", "Sautés", "Durée")]]
            for d, v in t["mesures"]["par_dossier"].items():
                lib, c = STATUT[v["statut"]]
                lignes.append([P(d, "pp"), Pc(lib, c), P(_f(v.get("reussis")), "pp"),
                               P(_f((v.get("echoues") or 0) + (v.get("erreurs") or 0)) if "total" in v else "—", "pp"),
                               P(_f(v.get("sautes")) if "total" in v else (v.get("motif") or ""), "pp"),
                               P(f"{_f(v.get('duree_s'))} s" if v.get("duree_s") is not None else "—", "pp")])
            E.append(tableau(lignes, [LARGEUR * 0.22, LARGEUR * 0.13, LARGEUR * 0.1, LARGEUR * 0.1, LARGEUR * 0.33, LARGEUR * 0.12]))
        E.append(P("2. Porte de qualité", "h1"))
        lignes = [[P(x, "th") for x in ("Critère", "État", "Mesure", "Raison")]]
        for c in porte["criteres"]:
            col = VERT if c["etat"] == "OK" else (ROUGE if c["bloque"] else ORANGE)
            lignes.append([P(c["libelle"], "pp"), Pc(c["etat"], col), P(c["mesure"] or "—", "pp"), P(c["raison"] or "", "pp")])
        E.append(KeepTogether([tableau(lignes, [LARGEUR * 0.33, LARGEUR * 0.13, LARGEUR * 0.24, LARGEUR * 0.3])]))
        E.append(P("Un critère NON ÉVALUÉ est bloquant par défaut (« pas de preuve, pas de déploiement » ; "
                   "réglable dans config/porte.json, champ si_absent).", "pp"))
        E.append(PageBreak())

        # ---- fiches de score
        E.append(P("3. Fiches de score", "h1"))
        E.append(P("Chaque axe est la moyenne pondérée de ses composantes disponibles (0–100) ; une composante absente "
                   "est retirée et les poids renormalisés (la couverture l'indique). Score global = moyenne pondérée des "
                   "axes. Poids modifiables dans config/ponderation.json.", "pp"))
        from . import commun as Cm
        conf = Cm.lire_json(Cm.CONFIG / "ponderation.json")
        for nom, a in fiche["axes"].items():
            poids = conf["axes"][nom]["composantes"]
            lignes = [[P(f"{a['libelle']} — {_f(a['score'])}/100 · poids {conf['axes'][nom]['poids']} · couverture "
                         f"{int(100 * a['couverture'])} %", "th"), P("Valeur", "th"), P("Poids", "th")]]
            for k, v in a["composantes"].items():
                lignes.append([P(k.replace("_", " "), "pp"), P(_f(v), "pp"), P(_f(poids.get(k)), "pp")])
            E.append(KeepTogether([tableau(lignes, [LARGEUR * 0.6, LARGEUR * 0.2, LARGEUR * 0.2]), Spacer(1, 5)]))

    # ---- versions
    if vers:
        E.append(PageBreak())
        E.append(P("4. Comparaison des 5 versions", "h1"))
        E.append(P("Pour chaque version, les épreuves qui dépendent de la configuration (" +
                   ", ".join(vers.get("suites_comparees") or []) + ") sont rejouées avec la MÊME graine. Les axes qui "
                   "ne dépendent pas de la configuration (tests unitaires, attaque, secrets, banc) sont communs et "
                   "n'entrent pas dans ce classement.", "pp"))
        axes_lib = {k: v["libelle"] for k, v in next(iter(vers["versions"].values()))["score"]["axes"].items()}
        E += [Spacer(1, 4), graphique_versions(vers, axes_lib), Spacer(1, 4)]
        codes = vers["classement"]
        lignes = [[P("Axe", "th")] + [P(f"{c} {vers['versions'][c]['profil']['nom']}", "th") for c in codes]]
        for ax, lib in axes_lib.items():
            lignes.append([P(lib, "pp")] + [Pc(_f(vers["versions"][c]["score"]["axes"][ax]["score"]),
                                                _couleur_score(vers["versions"][c]["score"]["axes"][ax]["score"]), "pp")
                                             for c in codes])
        lignes.append([P("Global", "ppb")] + [Pc(_f(vers["versions"][c]["score"]["global"]),
                                                 _couleur_score(vers["versions"][c]["score"]["global"])) for c in codes])
        lignes.append([P("Coût simulé €/mois", "pp")] + [P(_f((vers["versions"][c]["suites"].get("jumeau", {}).get("mesures", {})
                                                               .get("version") or {}).get("nominal", {}).get("cout_total_eur")), "pp") for c in codes])
        lignes.append([P("Missions livrées/jour", "pp")] + [P(_f((vers["versions"][c]["suites"].get("jumeau", {}).get("mesures", {})
                                                                  .get("version") or {}).get("nominal", {}).get("livrees_jour")), "pp") for c in codes])
        lignes.append([P("N3 par jour", "pp")] + [P(_f((vers["versions"][c]["suites"].get("jumeau", {}).get("mesures", {})
                                                        .get("version") or {}).get("nominal", {}).get("n3_jour")), "pp") for c in codes])
        lignes.append([P("Simulations réussies", "pp")] + [P(_f(vers["versions"][c]["suites"].get("simulations", {}).get("mesures", {})
                                                                 .get("taux_reussite"), " %"), "pp") for c in codes])
        lignes.append([P("Charge : critères tenus", "pp")] + [P(_f(vers["versions"][c]["suites"].get("charge", {}).get("mesures", {})
                                                                    .get("taux_criteres"), " %"), "pp") for c in codes])
        w = (LARGEUR * 0.75) / len(codes)
        E += [tableau(lignes, [LARGEUR * 0.25] + [w] * len(codes)), Spacer(1, 6)]
        E.append(P("Profils", "h2"))
        lignes = [[P(x, "th") for x in ("Version", "Profil", "Machine / modèles", "Sécurité · autonomie")]]
        for c in sorted(vers["versions"]):
            p = vers["versions"][c]["profil"]
            lignes.append([P(f"{c} {p['nom']}", "ppb"), P(p["resume"], "pp"), P(f"{p['materiel']} · {p['modele']}", "pp"),
                           P(f"{p['securite']} · {p['autonomie']} · {p['roles']} rôles", "pp")])
        E.append(tableau(lignes, [LARGEUR * 0.14, LARGEUR * 0.36, LARGEUR * 0.28, LARGEUR * 0.22]))

    # ---- défauts
    if base:
        E.append(PageBreak())
        defs = list(base["defauts"])
        if vers:
            vus = {d["id"] for d in defs}
            for c in vers["classement"]:
                for d in vers["versions"][c]["defauts"]:
                    if d["id"] not in vus:
                        vus.add(d["id"])
                        defs.append({**d, "titre": f"[version {c}] {d['titre']}"})
        ordre = {"critique": 0, "majeure": 1, "mineure": 2, "info": 3}
        defs.sort(key=lambda d: (ordre.get(d["gravite"], 9), d["suite"]))
        cpt = {g: sum(1 for d in defs if d["gravite"] == g) for g in ordre}
        E.append(P("5. Défauts classés", "h1"))
        E.append(P(f"{len(defs)} défaut(s) : " + " · ".join(f"{g} {n}" for g, n in cpt.items()) +
                   (". Les 80 premiers sont détaillés ; la liste complète est dans syfer_test.json." if len(defs) > 80 else "."), "pp"))
        lignes = [[P(x, "th") for x in ("Gravité", "Épreuve", "Défaut et preuve", "Correction suggérée", "Responsable")]]
        for d in defs[:80]:
            lignes.append([Pc(d["gravite"], GRAV.get(d["gravite"], ENCRE2)), P(d["suite"], "pp"),
                           P(f"<b>{escape(d['titre'])}</b><br/>{escape(d['preuve'] or '')}", "pp", brut=True),
                           P(d["correction"], "pp"), P(d["responsable"], "pp")])
        E.append(tableau(lignes, [LARGEUR * 0.09, LARGEUR * 0.1, LARGEUR * 0.42, LARGEUR * 0.24, LARGEUR * 0.15]))

        # ---- tendance
        E.append(P("6. Tendance", "h1"))
        pts = [(p["horodatage"], p["score"]["global"]) for p in precedents if (p.get("score") or {}).get("global") is not None]
        pts.append((base["horodatage"], base["score"]["global"]))
        if len(pts) >= 2:
            g = graphique_tendance(pts[-12:])
            if g:
                E.append(g)
            lignes = [[P(x, "th") for x in ("Passage", "Mode", "Global", "Porte")]]
            for p in (precedents[-8:] + [base]):
                lignes.append([P(p["horodatage"], "pp"), P(p["mode"], "pp"), P(_f((p.get("score") or {}).get("global")), "pp"),
                               P((p.get("porte") or {}).get("verdict"), "pp")])
            E.append(tableau(lignes, [LARGEUR * 0.35, LARGEUR * 0.2, LARGEUR * 0.2, LARGEUR * 0.25]))
        else:
            E.append(P("Premier passage enregistré : la tendance apparaîtra au prochain passage.", "pp"))

    # ---- limites
    E.append(P("7. Limites", "h1"))
    lim = [
        "Banc d'essai : exécuté contre un nexus-core LOCAL avec LLM FACTICE. La note système (routage et niveau de "
        "décision) et les pièges sont réels ; la note livrable ne mesure pas la qualité rédactionnelle (poids 0). "
        "Le banc réel se lance sur le VPS (banc-essai/lancer.sh).",
        "Jumeau numérique : modèle Monte Carlo fondé sur des HYPOTHÈSES (hypotheses.json) calées sur 2 mesures réelles ; "
        "les coûts, débits et charges Décideur sont des estimations.",
        "Versions : zones isolées, administration Tailscale et nombre de rôles (30 / 93) ne sont pas simulables hors VPS ; "
        "ils sont décrits mais n'influencent pas les scores. La Forteresse (D) est supposée sur KVM 8.",
        "Charge 200 % : mode court (durées ÷ 3, temps compressé) ; le surcoût propre de la plateforme est surreprésenté.",
        "Épreuves en construction (dossiers absents) : sautées proprement, la porte les compte NON ÉVALUÉES.",
        "Recherche de secrets : motifs du filtre anti-secret de nexus-core ; les valeurs factices (tests, corpus, "
        "résultats) sont classées « factices » via config/secrets_autorises.json.",
        "Tout s'exécute dans une copie jetable du dépôt : aucun fichier du dépôt n'est modifié.",
    ]
    E += [P("• " + escape(x), "pp", brut=True) for x in lim]
    doc.build(E, onFirstPage=_entete_page, onLaterPages=_entete_page)
    return cible
