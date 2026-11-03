"""Page /bridge : lecture seule, en français, lisible sur téléphone, sans JavaScript ni ressource externe.
Protégée par le basic auth de Caddy (mêmes identifiants que le cockpit)."""
from html import escape

from . import db

_CSS = """
:root{--fond:#f6f7f9;--carte:#fff;--texte:#1b1f24;--doux:#5b6470;--bord:#dde1e6;--accent:#2457c5;
--ok:#1d7a46;--alerte:#a35a00;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--fond:#111418;--carte:#1a1f25;--texte:#e8ebef;--doux:#9aa4b0;
--bord:#2c333b;--accent:#7aa2ff;--ok:#5fcf8f;--alerte:#f0b35a}}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--texte);
font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:16px;border-bottom:1px solid var(--bord);background:var(--carte)}
h1{font-size:1.2rem;margin:0}header p{margin:4px 0 0;color:var(--doux);font-size:.9rem}
nav{display:flex;gap:8px;overflow-x:auto;padding:10px 16px}
nav a{white-space:nowrap;text-decoration:none;color:var(--accent);border:1px solid var(--bord);
border-radius:999px;padding:6px 12px;font-size:.9rem;background:var(--carte)}
main{padding:0 16px 32px;max-width:860px;margin:0 auto}
h2{font-size:1.05rem;margin:22px 0 8px}
.c{background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:12px;margin:0 0 10px;
overflow-wrap:anywhere}
.t{font-weight:600}.m{color:var(--doux);font-size:.82rem;margin-top:2px}
.x{margin-top:6px;white-space:pre-wrap;font-size:.93rem}
.b{display:inline-block;border:1px solid var(--bord);border-radius:6px;padding:0 6px;font-size:.78rem;
margin-right:4px;color:var(--doux)}
.b.u{color:var(--alerte);border-color:var(--alerte)}.b.f{color:var(--ok);border-color:var(--ok)}
.v{color:var(--doux);font-style:italic}
details summary{cursor:pointer;color:var(--accent);font-size:.9rem;margin-top:6px}
"""

_NOMS = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini", "proprietaire": "Propriétaire", "tous": "Tous"}
_STATUTS = {"a_faire": "à faire", "en_cours": "en cours", "a_valider": "à valider", "fait": "fait"}


def _n(x) -> str:
    return escape(_NOMS.get(x, str(x or "—")))


def _date(iso: str | None) -> str:
    if not iso:
        return ""
    return escape(iso[:16].replace("T", " ")) + " UTC"


def _long(texte: str, limite: int = 400) -> str:
    texte = texte or ""
    if len(texte) <= limite:
        return f'<div class="x">{escape(texte)}</div>'
    return (f'<div class="x">{escape(texte[:limite])}…</div>'
            f'<details><summary>Lire la suite</summary><div class="x">{escape(texte)}</div></details>')


def page_bridge() -> str:
    with db.connexion() as con:
        memoires = con.execute("SELECT * FROM memoires WHERE statut='active' ORDER BY cree_le DESC LIMIT 25").fetchall()
        taches = con.execute(
            "SELECT * FROM taches WHERE statut<>'fait' ORDER BY CASE priorite WHEN 'urgente' THEN 0 WHEN 'haute' THEN 1 "
            "WHEN 'normale' THEN 2 ELSE 3 END, maj_le DESC LIMIT 40").fetchall()
        faites = con.execute("SELECT * FROM taches WHERE statut='fait' ORDER BY maj_le DESC LIMIT 10").fetchall()
        messages = con.execute("SELECT * FROM messages ORDER BY cree_le DESC LIMIT 25").fetchall()
        passations = con.execute(
            "SELECT p.* FROM passations p JOIN (SELECT projet, MAX(id) AS mid FROM passations GROUP BY projet) d "
            "ON p.id = d.mid ORDER BY p.cree_le DESC LIMIT 20").fetchall()
        journal = con.execute("SELECT * FROM journal ORDER BY id DESC LIMIT 20").fetchall()

    h = ['<!doctype html><html lang="fr"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<meta name="robots" content="noindex"><title>Passerelle NEXUS</title>',
         f"<style>{_CSS}</style></head><body>",
         "<header><h1>Passerelle NEXUS</h1><p>Mémoire commune Claude · ChatGPT · Gemini — lecture seule. "
         f"Page générée le {_date(db.maintenant())}.</p></header>",
         '<nav><a href="#taches">Tâches</a><a href="#passations">Passations</a><a href="#messages">Messages</a>'
         '<a href="#memoire">Mémoire</a><a href="#journal">Journal</a><a href="/cockpit">Cockpit</a></nav><main>']

    h.append(f'<h2 id="taches">Tâches en cours ({len(taches)})</h2>')
    if not taches:
        h.append('<p class="v">Aucune tâche ouverte.</p>')
    for t in taches:
        urg = " u" if t["priorite"] in ("haute", "urgente") else ""
        h.append(f'<div class="c"><div class="t">#{t["id"]} · {escape(t["titre"])}</div>'
                 f'<div class="m"><span class="b{urg}">{escape(t["priorite"])}</span>'
                 f'<span class="b">{escape(_STATUTS.get(t["statut"], t["statut"]))}</span>'
                 f'pour {_n(t["assigne_a"])}'
                 + (f' · prise par {_n(t["pris_par"])}' if t["pris_par"] else "")
                 + (f' · {escape(t["projet"])}' if t["projet"] else "")
                 + f' · créée par {_n(t["cree_par"])} · maj {_date(t["maj_le"])}</div>'
                 + (_long(t["description"], 250) if t["description"] else "") + "</div>")
    if faites:
        h.append("<details><summary>Dernières tâches terminées</summary>")
        for t in faites:
            h.append(f'<div class="c"><span class="b f">fait</span> #{t["id"]} · {escape(t["titre"])}'
                     f'<div class="m">{_n(t["pris_par"] or t["assigne_a"])} · {_date(t["maj_le"])}</div></div>')
        h.append("</details>")

    h.append(f'<h2 id="passations">Dernière passation par projet ({len(passations)})</h2>')
    if not passations:
        h.append('<p class="v">Aucune passation.</p>')
    for p in passations:
        h.append(f'<div class="c"><div class="t">{escape(p["projet"])}</div>'
                 f'<div class="m">par {_n(p["auteur"])} · {_date(p["cree_le"])}</div>'
                 f'<div class="x"><b>Résumé</b> — {escape(p["resume"])}</div>'
                 f'<div class="x"><b>État</b> — {escape(p["etat"])}</div>'
                 f'<div class="x"><b>Prochaines étapes</b> — {escape(p["prochaines_etapes"])}</div></div>')

    h.append(f'<h2 id="messages">Derniers messages ({len(messages)})</h2>')
    if not messages:
        h.append('<p class="v">Aucun message.</p>')
    for m in messages:
        h.append(f'<div class="c"><div class="t">{escape(m["sujet"])}</div>'
                 f'<div class="m">{_n(m["expediteur"])} → {_n(m["destinataire"])} · {_date(m["cree_le"])}</div>'
                 f'{_long(m["contenu"], 300)}</div>')

    h.append(f'<h2 id="memoire">Mémoire commune — dernières entrées ({len(memoires)})</h2>')
    if not memoires:
        h.append('<p class="v">La mémoire est vide.</p>')
    for m in memoires:
        etiq = "".join(f'<span class="b">{escape(e)}</span>' for e in (m["etiquettes"] or "").split(",") if e)
        h.append(f'<div class="c"><div class="t">#{m["id"]} · {escape(m["sujet"])}</div>'
                 f'<div class="m">{_n(m["auteur"])} · {_date(m["cree_le"])}'
                 + (f' · {escape(m["projet"])}' if m["projet"] else "")
                 + (f' · v{m["version"]}' if m["version"] > 1 else "")
                 + f"</div>{_long(m['contenu'])}"
                 + (f'<div class="m">{etiq}</div>' if etiq else "") + "</div>")

    h.append('<h2 id="journal">Journal des écritures (20 dernières)</h2><div class="c">')
    if not journal:
        h.append('<span class="v">Vide.</span>')
    for j in journal:
        h.append(f'<div class="m">{_date(j["horodatage"])} · {_n(j["auteur"])} · {escape(j["outil"])} '
                 f'{escape(j["objet"])}' + (f' · <b>{escape(j["resultat"])}</b>' if j["resultat"] != "ok" else "") + "</div>")
    h.append("</div></main></body></html>")
    return "".join(h)
