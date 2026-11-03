"""Outils MCP de la passerelle : mémoire commune, tâches, messages, passations,
liaison avec nexus-core (lecture + création de missions, JAMAIS de validation) et journal.

Chaque outil = (nom, description FR, schéma JSON des arguments, fonction(auteur, args) -> dict).
Une erreur métier lève OutilErreur : elle est renvoyée à l'IA avec isError=true.
"""
import json
import re
from dataclasses import dataclass
from typing import Callable

import httpx

from . import db
from .config import IAS, IDENTITES, PROJETS_PAR_DEFAUT, cfg
from .garde import MESSAGE_SECRET, detecter_secret, taille_octets

TAILLE_MAX = 8192  # octets UTF-8 par champ de contenu


class OutilErreur(Exception):
    pass


@dataclass
class Outil:
    nom: str
    titre: str
    description: str
    schema: dict
    fonction: Callable[[str, dict], dict]
    ecriture: bool = False  # True : l'appel est inscrit au journal


_OUTILS: dict[str, Outil] = {}


def outil(nom: str, titre: str, description: str, schema: dict, ecriture: bool = False):
    def deco(f):
        _OUTILS[nom] = Outil(nom, titre, description, schema, f, ecriture)
        return f
    return deco


def outils() -> list[Outil]:
    return list(_OUTILS.values())


def trouver(nom: str) -> Outil | None:
    return _OUTILS.get(nom)


# --- Briques de schéma -------------------------------------------------------------------
def _projet(desc: str = "Code du projet concerné (voir l'outil projets_lister).") -> dict:
    return {"type": "string", "enum": cfg().projets, "description": desc}


def _texte(desc: str, maxi: int = TAILLE_MAX, mini: int = 1) -> dict:
    return {"type": "string", "minLength": mini, "maxLength": maxi, "description": desc}


def _id(desc: str) -> dict:
    return {"type": "integer", "minimum": 1, "description": desc}


def _objet(props: dict, requis: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": requis, "additionalProperties": False}


# --- Contrôles communs -------------------------------------------------------------------
def _secrets_connus() -> list[str]:
    c = cfg()
    return list(c.jetons.values()) + ([c.nexus_api_key] if c.nexus_api_key else [])


def _controler(**champs: str | None) -> None:
    """Taille max (8 Ko par champ) et refus des contenus qui ressemblent à des secrets."""
    connus = _secrets_connus()
    for nom, val in champs.items():
        if val is None:
            continue
        if taille_octets(val) > TAILLE_MAX:
            raise OutilErreur(f"Refusé : « {nom} » fait {taille_octets(val)} octets (maximum {TAILLE_MAX}, soit 8 Ko). "
                              "Résumez ou découpez en plusieurs entrées.")
        type_secret = detecter_secret(val, connus)
        if type_secret:
            raise OutilErreur(MESSAGE_SECRET.format(type=type_secret))


def _ligne(r) -> dict:
    return {k: r[k] for k in r.keys()}


def _memoire(r) -> dict:
    d = _ligne(r)
    d["etiquettes"] = [e for e in (d.get("etiquettes") or "").split(",") if e]
    return d


# =========================================================================================
#  Mémoire commune
# =========================================================================================
@outil(
    "memoire_ecrire", "Écrire dans la mémoire commune",
    "Enregistre un fait, une décision ou une préférence du propriétaire dans la mémoire commune "
    "partagée par Claude, ChatGPT et Gemini. La mémoire est versionnée : rien n'est effacé. Pour "
    "corriger une entrée, passez son id dans « remplace_id » (ou réutilisez exactement le même sujet "
    "et projet) : une nouvelle version liée est créée et l'ancienne passe en « remplacee ». "
    "N'y écrivez JAMAIS de secret (clé API, mot de passe, carte bancaire) : ce sera refusé.",
    _objet({
        "sujet": _texte("Titre court et précis (ex. « Ton des vidéos YouTube »).", 200),
        "contenu": _texte("Le fait, la décision ou la préférence, en phrases complètes (8 Ko max)."),
        "etiquettes": {"type": "array", "maxItems": 10, "description": "Mots-clés (ex. [\"decision\", \"preference\"]).",
                       "items": {"type": "string", "minLength": 1, "maxLength": 40, "pattern": r"^[^,]+$"}},
        "projet": _projet(),
        "remplace_id": _id("Optionnel : id de l'entrée que cette nouvelle version remplace."),
    }, ["sujet", "contenu", "etiquettes"]),
    ecriture=True,
)
def memoire_ecrire(auteur: str, a: dict) -> dict:
    etiquettes = [e.strip().lower() for e in a.get("etiquettes") or [] if e.strip()]
    _controler(sujet=a["sujet"], contenu=a["contenu"], etiquettes=" ".join(etiquettes))
    projet = a.get("projet")
    with db.connexion(ecriture=True) as con:
        precedente = None
        if a.get("remplace_id"):
            precedente = con.execute("SELECT * FROM memoires WHERE id=?", (a["remplace_id"],)).fetchone()
            if not precedente:
                raise OutilErreur(f"Mémoire {a['remplace_id']} introuvable : rien n'a été écrit.")
            if precedente["statut"] != "active":
                raise OutilErreur(f"La mémoire {precedente['id']} est déjà « {precedente['statut']} » "
                                  f"(version suivante : {precedente['remplacee_par'] or 'aucune'}). "
                                  "Remplacez la version active.")
        else:
            precedente = con.execute(
                "SELECT * FROM memoires WHERE statut='active' AND lower(sujet)=lower(?) AND projet IS ? "
                "ORDER BY id DESC LIMIT 1", (a["sujet"].strip(), projet)).fetchone()
        version = (precedente["version"] + 1) if precedente else 1
        cur = con.execute(
            "INSERT INTO memoires(sujet, contenu, etiquettes, projet, auteur, cree_le, version, racine_id, remplace_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (a["sujet"].strip(), a["contenu"], ",".join(etiquettes), projet, auteur, db.maintenant(), version,
             (precedente["racine_id"] or precedente["id"]) if precedente else None,
             precedente["id"] if precedente else None))
        nid = cur.lastrowid
        if not precedente:
            con.execute("UPDATE memoires SET racine_id=? WHERE id=?", (nid, nid))
        else:
            con.execute("UPDATE memoires SET statut='remplacee', remplacee_par=? WHERE id=?", (nid, precedente["id"]))
        db.journaliser(con, auteur, "memoire_ecrire", f"memoire:{nid}")
    return {"id": nid, "version": version, "remplace_id": precedente["id"] if precedente else None,
            "auteur": auteur, "message": "Mémoire enregistrée" + (f" (version {version})" if precedente else "") + "."}


def _requete_fts(texte: str) -> list[str]:
    """Transforme une phrase libre en termes FTS5 sûrs (aucun opérateur injecté)."""
    mots = re.findall(r"[\w'’-]+", texte, flags=re.UNICODE)
    termes = []
    for m in mots:
        m = m.strip("'’-")
        if len(m) >= 2:
            termes.append('"' + m.replace('"', "") + '"*')
    return termes[:12]


@outil(
    "memoire_chercher", "Chercher dans la mémoire commune",
    "Recherche plein texte (accents ignorés, préfixes acceptés) dans la mémoire commune active. "
    "Renvoie les entrées les plus pertinentes puis les plus récentes, avec auteur et date. "
    "Utilisez « * » comme requête pour lister simplement les dernières entrées.",
    _objet({
        "requete": _texte("Mots à chercher (ex. « tarif coaching poker »), ou « * ».", 300),
        "projet": _projet("Optionnel : limite la recherche à ce projet."),
        "limite": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10,
                   "description": "Nombre maximum de résultats (10 par défaut)."},
    }, ["requete"]),
)
def memoire_chercher(auteur: str, a: dict) -> dict:
    limite, projet = a.get("limite") or 10, a.get("projet")
    cond_projet, params_projet = ("AND m.projet = ?", [projet]) if projet else ("", [])
    with db.connexion() as con:
        if a["requete"].strip() == "*":
            lignes = con.execute(
                f"SELECT m.* FROM memoires m WHERE m.statut='active' {cond_projet} ORDER BY m.cree_le DESC LIMIT ?",
                [*params_projet, limite]).fetchall()
        else:
            termes = _requete_fts(a["requete"])
            if not termes:
                raise OutilErreur("Requête vide : donnez au moins un mot de 2 lettres.")
            sql = (f"SELECT m.*, bm25(memoires_fts, 5.0, 1.0, 2.0) AS score FROM memoires_fts "
                   f"JOIN memoires m ON m.id = memoires_fts.rowid "
                   f"WHERE memoires_fts MATCH ? AND m.statut='active' {cond_projet} "
                   f"ORDER BY score ASC, m.cree_le DESC LIMIT ?")
            # D'abord tous les mots (ET) ; si rien, n'importe lequel (OU).
            lignes = con.execute(sql, [" ".join(termes), *params_projet, limite]).fetchall()
            if not lignes and len(termes) > 1:
                lignes = con.execute(sql, [" OR ".join(termes), *params_projet, limite]).fetchall()
    resultats = []
    for r in lignes:
        d = _memoire(r)
        d.pop("score", None)
        d["extrait"] = d.pop("contenu")[:600]
        resultats.append({k: d[k] for k in ("id", "sujet", "extrait", "etiquettes", "projet", "auteur", "cree_le", "version")})
    return {"nombre": len(resultats), "resultats": resultats,
            "conseil": "Lisez une entrée complète avec memoire_lire {id}." if resultats else "Aucun résultat."}


@outil(
    "memoire_lire", "Lire une entrée de mémoire",
    "Lit une entrée complète de la mémoire commune, avec son historique de versions.",
    _objet({"id": _id("Identifiant de l'entrée.")}, ["id"]),
)
def memoire_lire(auteur: str, a: dict) -> dict:
    with db.connexion() as con:
        r = con.execute("SELECT * FROM memoires WHERE id=?", (a["id"],)).fetchone()
        if not r:
            raise OutilErreur(f"Mémoire {a['id']} introuvable.")
        racine = r["racine_id"] or r["id"]
        hist = con.execute("SELECT id, version, auteur, cree_le, statut FROM memoires "
                           "WHERE racine_id=? OR id=? ORDER BY version", (racine, racine)).fetchall()
    d = _memoire(r)
    d["historique"] = [_ligne(h) for h in hist]
    return d


@outil(
    "memoire_oublier", "Archiver une entrée de mémoire",
    "Archive une entrée de la mémoire commune (elle n'apparaît plus dans les recherches mais reste "
    "consultable et rien n'est supprimé). Réservé à l'auteur de l'entrée ou au propriétaire.",
    _objet({
        "id": _id("Identifiant de l'entrée à archiver."),
        "raison": _texte("Pourquoi l'entrée est archivée (ex. « information périmée »).", 500),
    }, ["id", "raison"]),
    ecriture=True,
)
def memoire_oublier(auteur: str, a: dict) -> dict:
    _controler(raison=a["raison"])
    with db.connexion(ecriture=True) as con:
        r = con.execute("SELECT * FROM memoires WHERE id=?", (a["id"],)).fetchone()
        if not r:
            raise OutilErreur(f"Mémoire {a['id']} introuvable.")
        if auteur != "proprietaire" and auteur != r["auteur"]:
            raise OutilErreur(f"Refusé : seule l'IA autrice ({r['auteur']}) ou le propriétaire peut archiver "
                              "cette entrée. Envoyez-lui un message (message_envoyer) pour le demander.")
        if r["statut"] == "archivee":
            return {"id": r["id"], "statut": "archivee", "message": "Entrée déjà archivée."}
        con.execute("UPDATE memoires SET statut='archivee', archive_par=?, archive_raison=?, archive_le=? WHERE id=?",
                    (auteur, a["raison"], db.maintenant(), r["id"]))
        db.journaliser(con, auteur, "memoire_oublier", f"memoire:{r['id']}")
    return {"id": r["id"], "statut": "archivee", "message": "Entrée archivée (conservée, mais exclue des recherches)."}


# =========================================================================================
#  Tâches
# =========================================================================================
STATUTS_TACHE = ["a_faire", "en_cours", "a_valider", "fait"]
PRIORITES = ["basse", "normale", "haute", "urgente"]


@outil(
    "tache_creer", "Créer une tâche",
    "Crée une tâche partagée et l'assigne à une IA (claude, chatgpt, gemini) ou au propriétaire humain.",
    _objet({
        "titre": _texte("Titre court de la tâche.", 200),
        "description": _texte("Ce qu'il faut faire, le résultat attendu, les liens utiles.", mini=0),
        "assigne_a": {"type": "string", "enum": IDENTITES, "description": "Qui doit faire la tâche."},
        "projet": _projet(),
        "priorite": {"type": "string", "enum": PRIORITES, "default": "normale", "description": "Priorité."},
    }, ["titre", "description", "assigne_a"]),
    ecriture=True,
)
def tache_creer(auteur: str, a: dict) -> dict:
    _controler(titre=a["titre"], description=a["description"])
    t = db.maintenant()
    with db.connexion(ecriture=True) as con:
        cur = con.execute(
            "INSERT INTO taches(titre, description, assigne_a, projet, priorite, statut, cree_par, cree_le, maj_le) "
            "VALUES (?,?,?,?,?,'a_faire',?,?,?)",
            (a["titre"], a["description"], a["assigne_a"], a.get("projet"), a.get("priorite") or "normale", auteur, t, t))
        db.journaliser(con, auteur, "tache_creer", f"tache:{cur.lastrowid}")
    return {"id": cur.lastrowid, "statut": "a_faire", "assigne_a": a["assigne_a"], "message": "Tâche créée."}


@outil(
    "tache_lister", "Lister les tâches",
    "Liste les tâches partagées (les plus prioritaires et récentes d'abord). Sans filtre de statut, "
    "les tâches « fait » sont exclues.",
    _objet({
        "statut": {"type": "string", "enum": STATUTS_TACHE, "description": "Optionnel : filtre par statut."},
        "assigne_a": {"type": "string", "enum": IDENTITES, "description": "Optionnel : filtre par personne assignée."},
        "projet": _projet("Optionnel : filtre par projet."),
    }, []),
)
def tache_lister(auteur: str, a: dict) -> dict:
    conds, params = [], []
    if a.get("statut"):
        conds.append("statut=?"); params.append(a["statut"])
    else:
        conds.append("statut<>'fait'")
    for champ in ("assigne_a", "projet"):
        if a.get(champ):
            conds.append(f"{champ}=?"); params.append(a[champ])
    ordre = "CASE priorite WHEN 'urgente' THEN 0 WHEN 'haute' THEN 1 WHEN 'normale' THEN 2 ELSE 3 END, maj_le DESC"
    with db.connexion() as con:
        lignes = con.execute(f"SELECT * FROM taches WHERE {' AND '.join(conds)} ORDER BY {ordre} LIMIT 100", params).fetchall()
    return {"nombre": len(lignes), "taches": [_ligne(r) for r in lignes]}


@outil(
    "tache_prendre", "Prendre une tâche",
    "Prend une tâche (verrou) : elle passe « en_cours » à votre nom. Refusé si une autre IA l'a déjà prise "
    "ou si elle est terminée.",
    _objet({"id": _id("Identifiant de la tâche.")}, ["id"]),
    ecriture=True,
)
def tache_prendre(auteur: str, a: dict) -> dict:
    with db.connexion(ecriture=True) as con:
        r = con.execute("SELECT * FROM taches WHERE id=?", (a["id"],)).fetchone()
        if not r:
            raise OutilErreur(f"Tâche {a['id']} introuvable.")
        if r["statut"] == "fait":
            raise OutilErreur(f"Refusé : la tâche {r['id']} est déjà terminée.")
        if r["pris_par"] and r["pris_par"] != auteur:
            raise OutilErreur(f"Refusé : la tâche {r['id']} est déjà prise par {r['pris_par']} "
                              f"(statut {r['statut']}). Envoyez-lui un message si besoin.")
        # Mise à jour conditionnelle : protège contre deux prises simultanées.
        cur = con.execute("UPDATE taches SET pris_par=?, statut='en_cours', maj_le=? "
                          "WHERE id=? AND (pris_par IS NULL OR pris_par=?)", (auteur, db.maintenant(), r["id"], auteur))
        if cur.rowcount != 1:
            raise OutilErreur("Refusé : la tâche vient d'être prise par une autre IA.")
        con.execute("INSERT INTO taches_notes(tache_id, auteur, statut, note, cree_le) VALUES (?,?,?,?,?)",
                    (r["id"], auteur, "en_cours", "Tâche prise", db.maintenant()))
        db.journaliser(con, auteur, "tache_prendre", f"tache:{r['id']}")
    return {"id": r["id"], "statut": "en_cours", "pris_par": auteur, "message": "Tâche prise."}


@outil(
    "tache_mettre_a_jour", "Mettre à jour une tâche",
    "Change le statut d'une tâche et ajoute une note de suivi. Réservé à l'IA qui l'a prise, au "
    "propriétaire, ou (si personne ne l'a prise) à la personne assignée ou au créateur. Utilisez "
    "« a_valider » quand le propriétaire doit vérifier le résultat.",
    _objet({
        "id": _id("Identifiant de la tâche."),
        "statut": {"type": "string", "enum": STATUTS_TACHE, "description": "Nouveau statut."},
        "note": _texte("Ce qui a été fait, où trouver le résultat, ce qui bloque.", mini=0),
    }, ["id", "statut", "note"]),
    ecriture=True,
)
def tache_mettre_a_jour(auteur: str, a: dict) -> dict:
    _controler(note=a["note"])
    with db.connexion(ecriture=True) as con:
        r = con.execute("SELECT * FROM taches WHERE id=?", (a["id"],)).fetchone()
        if not r:
            raise OutilErreur(f"Tâche {a['id']} introuvable.")
        if r["pris_par"]:
            autorise = auteur in (r["pris_par"], "proprietaire")
        else:
            autorise = auteur in (r["assigne_a"], r["cree_par"], "proprietaire")
        if not autorise:
            qui = r["pris_par"] or r["assigne_a"]
            raise OutilErreur(f"Refusé : la tâche {r['id']} est gérée par {qui}. Prenez-la d'abord (tache_prendre) "
                              "si elle est libre, ou envoyez un message.")
        pris_par = r["pris_par"]
        if a["statut"] == "en_cours" and not pris_par:
            pris_par = auteur
        if a["statut"] == "a_faire" and auteur in (r["pris_par"], "proprietaire"):
            pris_par = None  # remise à disposition
        con.execute("UPDATE taches SET statut=?, pris_par=?, maj_le=? WHERE id=?",
                    (a["statut"], pris_par, db.maintenant(), r["id"]))
        con.execute("INSERT INTO taches_notes(tache_id, auteur, statut, note, cree_le) VALUES (?,?,?,?,?)",
                    (r["id"], auteur, a["statut"], a["note"], db.maintenant()))
        db.journaliser(con, auteur, "tache_mettre_a_jour", f"tache:{r['id']}", a["statut"])
    return {"id": r["id"], "statut": a["statut"], "pris_par": pris_par, "message": "Tâche mise à jour."}


# =========================================================================================
#  Messages
# =========================================================================================
@outil(
    "message_envoyer", "Envoyer un message",
    "Envoie un message à une autre IA (claude, chatgpt, gemini), au propriétaire, ou à tous.",
    _objet({
        "destinataire": {"type": "string", "enum": IAS + ["proprietaire", "tous"], "description": "Destinataire."},
        "sujet": _texte("Objet du message.", 200),
        "contenu": _texte("Texte du message (8 Ko max)."),
    }, ["destinataire", "sujet", "contenu"]),
    ecriture=True,
)
def message_envoyer(auteur: str, a: dict) -> dict:
    _controler(sujet=a["sujet"], contenu=a["contenu"])
    with db.connexion(ecriture=True) as con:
        cur = con.execute("INSERT INTO messages(expediteur, destinataire, sujet, contenu, cree_le) VALUES (?,?,?,?,?)",
                          (auteur, a["destinataire"], a["sujet"], a["contenu"], db.maintenant()))
        db.journaliser(con, auteur, "message_envoyer", f"message:{cur.lastrowid}→{a['destinataire']}")
    return {"id": cur.lastrowid, "message": f"Message envoyé à {a['destinataire']}."}


@outil(
    "messages_lire", "Lire mes messages",
    "Lit les messages qui vous sont adressés (ou adressés à « tous ») et les marque comme lus pour vous. "
    "Par défaut : seulement les non lus.",
    _objet({
        "depuis": {"type": "string", "maxLength": 40, "pattern": r"^\d{4}-\d{2}-\d{2}",
                   "description": "Optionnel : horodatage ISO 8601 (ex. 2026-11-03T08:00:00+00:00) ; messages plus récents seulement."},
        "non_lus_seulement": {"type": "boolean", "default": True, "description": "Seulement les messages non lus (oui par défaut)."},
    }, []),
    ecriture=True,
)
def messages_lire(auteur: str, a: dict) -> dict:
    conds = ["(m.destinataire=? OR (m.destinataire='tous' AND m.expediteur<>?))"]
    params: list = [auteur, auteur]
    if a.get("depuis"):
        conds.append("m.cree_le > ?"); params.append(a["depuis"])
    if a.get("non_lus_seulement", True):
        conds.append("l.message_id IS NULL")
    with db.connexion(ecriture=True) as con:
        lignes = con.execute(
            "SELECT m.*, l.lu_le FROM messages m LEFT JOIN messages_lus l ON l.message_id=m.id AND l.lecteur=? "
            f"WHERE {' AND '.join(conds)} ORDER BY m.cree_le ASC LIMIT 50", [auteur, *params]).fetchall()
        t = db.maintenant()
        for r in lignes:
            con.execute("INSERT OR IGNORE INTO messages_lus(message_id, lecteur, lu_le) VALUES (?,?,?)", (r["id"], auteur, t))
        if lignes:
            db.journaliser(con, auteur, "messages_lire", f"{len(lignes)} message(s)")
    return {"nombre": len(lignes), "messages": [
        {"id": r["id"], "de": r["expediteur"], "a": r["destinataire"], "sujet": r["sujet"], "contenu": r["contenu"],
         "cree_le": r["cree_le"], "deja_lu": r["lu_le"] is not None} for r in lignes]}


# =========================================================================================
#  Passations
# =========================================================================================
@outil(
    "passation_ecrire", "Écrire une passation",
    "Laisse une note de passation sur un projet pour qu'une autre IA reprenne le travail : résumé, "
    "état actuel, prochaines étapes.",
    _objet({
        "projet": _projet("Code du projet (obligatoire)."),
        "resume": _texte("Ce qui a été fait pendant cette session."),
        "etat": _texte("Où en est le projet : ce qui marche, ce qui bloque, fichiers et liens."),
        "prochaines_etapes": _texte("Liste des prochaines actions, dans l'ordre."),
    }, ["projet", "resume", "etat", "prochaines_etapes"]),
    ecriture=True,
)
def passation_ecrire(auteur: str, a: dict) -> dict:
    _controler(resume=a["resume"], etat=a["etat"], prochaines_etapes=a["prochaines_etapes"])
    with db.connexion(ecriture=True) as con:
        cur = con.execute("INSERT INTO passations(projet, auteur, resume, etat, prochaines_etapes, cree_le) VALUES (?,?,?,?,?,?)",
                          (a["projet"], auteur, a["resume"], a["etat"], a["prochaines_etapes"], db.maintenant()))
        db.journaliser(con, auteur, "passation_ecrire", f"passation:{cur.lastrowid}:{a['projet']}")
    return {"id": cur.lastrowid, "projet": a["projet"], "message": "Passation enregistrée."}


@outil(
    "passation_derniere", "Lire la dernière passation",
    "Renvoie la dernière note de passation d'un projet (à lire en début de session pour reprendre le travail).",
    _objet({"projet": _projet("Code du projet.")}, ["projet"]),
)
def passation_derniere(auteur: str, a: dict) -> dict:
    with db.connexion() as con:
        r = con.execute("SELECT * FROM passations WHERE projet=? ORDER BY cree_le DESC, id DESC LIMIT 1", (a["projet"],)).fetchone()
    if not r:
        return {"projet": a["projet"], "passation": None, "message": "Aucune passation pour ce projet."}
    return {"projet": a["projet"], "passation": _ligne(r)}


# =========================================================================================
#  Liaison avec nexus-core (Mothership)
# =========================================================================================
_transport: httpx.BaseTransport | None = None  # remplacé par un faux nexus-core dans les tests


def _client() -> httpx.Client:
    c = cfg()
    if not c.nexus_api_key:
        raise OutilErreur("NEXUS_API_KEY absente de la configuration de nexus-bridge : liaison au Mothership impossible.")
    return httpx.Client(base_url=c.nexus_core_url, headers={"X-Nexus-Key": c.nexus_api_key},
                        timeout=httpx.Timeout(20.0, connect=5.0), transport=_transport)


def _appel_core(methode: str, chemin: str, **kw) -> httpx.Response:
    try:
        with _client() as cl:
            rep = cl.request(methode, chemin, **kw)
    except httpx.HTTPError as e:
        raise OutilErreur(f"nexus-core injoignable ({type(e).__name__}). Le Mothership est-il démarré ?") from None
    if rep.status_code == 401:
        raise OutilErreur("nexus-core refuse la clé (401) : vérifiez NEXUS_API_KEY.")
    return rep


def _detail(rep: httpx.Response) -> str:
    try:
        return str(rep.json().get("detail", ""))[:300]
    except Exception:
        return rep.text[:300]


RAPPEL_N3 = ("Les décisions N3 se valident UNIQUEMENT par le propriétaire, dans le cockpit "
             "(https://{hote}/cockpit). Aucun outil de la passerelle ne peut valider, refuser ou réviser.")


def _rappel() -> str:
    return RAPPEL_N3.format(hote=cfg().nexus_host or "VOTRE_VPS")


@outil(
    "projets_lister", "Lister les projets",
    "Liste les codes projets reconnus (paradoxx, nexus, poker-winners…), à utiliser dans le paramètre « projet ».",
    _objet({}, []),
)
def projets_lister(auteur: str, a: dict) -> dict:
    source = "nexus-core"
    try:
        rep = _appel_core("GET", "/api/projets")
        if rep.status_code != 200:
            raise OutilErreur("statut")
        brut = rep.json()
        if isinstance(brut, dict):
            brut = brut.get("projets", [])
        projets = []
        for p in brut:
            if isinstance(p, str):
                projets.append({"code": p})
            elif isinstance(p, dict) and (p.get("code") or p.get("id")):
                projets.append({"code": p.get("code") or p.get("id"),
                                **({"nom": p["nom"]} if p.get("nom") else {})})
        if not projets:
            raise OutilErreur("vide")
    except (OutilErreur, ValueError):
        source = "liste par défaut (nexus-core indisponible)"
        projets = [{"code": p} for p in cfg().projets]
    return {"source": source, "projets": projets}


@outil(
    "projet_connaissances", "Mémoire d'un projet (lecture)",
    "Recherche dans la mémoire du projet tenue par le Mothership (fiches de contexte, connaissances ajoutées "
    "par le propriétaire, résumés des livrables validés). Lecture seule : l'écriture est réservée à "
    "nexus-core et au propriétaire (cockpit).",
    _objet({
        "projet": _projet("Code du projet dont on lit la mémoire."),
        "q": {"type": "string", "maxLength": 300, "description": "Optionnel : mots-clés de recherche (plein texte)."},
        "limite": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5,
                   "description": "Nombre maximal de résultats."},
    }, ["projet"]),
)
def projet_connaissances(auteur: str, a: dict) -> dict:
    params = {"limite": a.get("limite") or 5}
    if (a.get("q") or "").strip():
        params["q"] = a["q"].strip()
    rep = _appel_core("GET", f"/api/projets/{a['projet']}/connaissances", params=params)
    if rep.status_code == 404:
        raise OutilErreur(f"Projet inconnu du Mothership : {a['projet']}.")
    if rep.status_code != 200:
        raise OutilErreur(f"nexus-core a répondu HTTP {rep.status_code} : {_detail(rep)}")
    resultats = []
    for k in rep.json():
        contenu = k.get("contenu") or ""
        resultats.append({"titre": k.get("titre"), "source": k.get("source"), "date": k.get("date"),
                          "auteur": k.get("auteur"), "version": k.get("version"),
                          "contenu": contenu if len(contenu) <= 1500 else contenu[:1500] + " […]"})
    return {"projet": a["projet"], "nombre": len(resultats), "connaissances": resultats,
            "note": "Lecture seule : pour ajouter une connaissance, passez par le cockpit du propriétaire."}


@outil(
    "mothership_mission", "Confier une mission au Mothership",
    "Envoie une mission aux agents du Mini NEXUS MOTHERSHIP (nexus-core) et renvoie son id. "
    "Le Mothership classe la mission (N0 à N3) ; tout ce qui engage (argent, publication, envoi, "
    "contrat…) attend la validation humaine dans le cockpit. Suivez-la avec mothership_statut. "
    "Niveau de fonctionnement facultatif : F1 Éclair (local, rapide), F2 Standard, F3 Renforcé "
    "(double contrôle), F4 Expert (payant : crée une demande de lancement que SEUL le propriétaire "
    "peut valider dans le cockpit ; la passerelle ne peut jamais l'approuver).",
    _objet({
        "titre": _texte("Titre de la mission.", 200),
        "consigne": _texte("Consigne complète pour les agents (contexte, livrable attendu)."),
        "service": {"type": "string", "maxLength": 80,
                    "description": "Optionnel : service cible (ex. « CONTENT-ARENA/redaction », « OPS-CORE/projets »)."},
        "projet": _projet("Optionnel : projet concerné."),
        "fonctionnement": {"type": "string", "enum": ["F1", "F2", "F3", "F4"],
                           "description": "Optionnel : niveau de fonctionnement (effort, tokens, coût, délai). "
                                          "Défaut : celui du serveur (F2)."},
    }, ["titre", "consigne"]),
    ecriture=True,
)
def mothership_mission(auteur: str, a: dict) -> dict:
    _controler(titre=a["titre"], consigne=a["consigne"])
    corps = {"titre": a["titre"], "consigne": f"{a['consigne']}\n\n(Mission envoyée par {auteur} via nexus-bridge.)"}
    if a.get("service"):
        corps["service"] = a["service"]
    if a.get("projet"):
        corps["projet"] = a["projet"]
    if a.get("fonctionnement"):
        corps["fonctionnement"] = a["fonctionnement"]  # transmis tel quel ; F4 attend l'accord humain
    rep = _appel_core("POST", "/api/missions", json=corps)
    if rep.status_code not in (200, 201, 202):
        db.journaliser_seul(auteur, "mothership_mission", "mission:refusee", f"http {rep.status_code}")
        raise OutilErreur(f"nexus-core a refusé la mission (HTTP {rep.status_code}) : {_detail(rep)}")
    d = rep.json()
    db.journaliser_seul(auteur, "mothership_mission", f"mission:{d.get('id')}")
    res = {"id": d.get("id"), "statut": d.get("statut"), "projet": a.get("projet"),
           "fonctionnement": d.get("fonctionnement"), "message": "Mission transmise au Mothership. " + _rappel()}
    if d.get("message"):
        res["note_mothership"] = d["message"]
    if d.get("fonctionnement_demande") == "F4" and d.get("statut") == "en_attente_n3":
        res["message"] = ("Lancement F4 demandé : la mission ne démarrera qu'après validation du propriétaire "
                          "dans le cockpit (coût estimé indiqué dans la décision). " + _rappel())
    return res


@outil(
    "mothership_statut", "Statut d'une mission",
    "Renvoie le statut d'une mission du Mothership (niveau N0–N3, étapes, livrable s'il est prêt).",
    _objet({"id": _id("Identifiant de la mission (renvoyé par mothership_mission).")}, ["id"]),
)
def mothership_statut(auteur: str, a: dict) -> dict:
    rep = _appel_core("GET", f"/api/missions/{a['id']}")
    if rep.status_code == 404:
        raise OutilErreur(f"Mission {a['id']} introuvable dans le Mothership.")
    if rep.status_code != 200:
        raise OutilErreur(f"nexus-core a répondu HTTP {rep.status_code} : {_detail(rep)}")
    m = rep.json()
    res = {k: m.get(k) for k in ("id", "titre", "service", "directeur", "statut", "niveau", "message", "cree_le", "maj_le", "projet",
                                 "fonctionnement_demande", "fonctionnement", "fonctionnement_raison", "tokens", "cout_eur", "duree_s")}
    livrable = m.get("livrable_texte")
    res["livrable"] = (livrable[:6000] + " […]") if livrable and len(livrable) > 6000 else livrable
    res["etapes"] = [{"agent": e.get("agent_id"), "role": e.get("role"), "verdict": e.get("verdict")} for e in m.get("etapes") or []]
    if m.get("statut") == "en_attente_n3":
        res["rappel"] = _rappel()
    return res


@outil(
    "mothership_decisions_en_attente", "Décisions N3 en attente",
    "Liste (en lecture seule) les décisions N3 qui attendent la validation du propriétaire. "
    "Ces outils ne peuvent RIEN valider : la validation se fait uniquement dans le cockpit humain.",
    _objet({}, []),
)
def mothership_decisions_en_attente(auteur: str, a: dict) -> dict:
    rep = _appel_core("GET", "/api/decisions", params={"statut": "en_attente"})
    if rep.status_code != 200:
        raise OutilErreur(f"nexus-core a répondu HTTP {rep.status_code} : {_detail(rep)}")
    decisions = [{k: d.get(k) for k in ("id", "mission_id", "mission_titre", "niveau", "resume", "recommandation",
                                        "cout_estime_eur", "risque", "cree_le")} for d in rep.json()]
    return {"nombre": len(decisions), "decisions": decisions, "rappel": _rappel()}


# =========================================================================================
#  Journal
# =========================================================================================
@outil(
    "journal_lister", "Lire le journal",
    "Journal en ajout seul de toutes les écritures faites via la passerelle (qui, quel outil, quand). "
    "Ne contient aucun contenu.",
    _objet({"limite": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30,
                       "description": "Nombre de lignes (30 par défaut)."}}, []),
)
def journal_lister(auteur: str, a: dict) -> dict:
    with db.connexion() as con:
        lignes = con.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (a.get("limite") or 30,)).fetchall()
    return {"nombre": len(lignes), "journal": [_ligne(r) for r in lignes]}


def resultat_texte(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)


__all__ = ["Outil", "OutilErreur", "outils", "trouver", "resultat_texte", "PROJETS_PAR_DEFAUT"]
