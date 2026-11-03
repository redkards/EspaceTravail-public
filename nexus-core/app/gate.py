"""GATE : classement N0–N3 par règles déterministes.

- Les règles portent sur la consigne ET sur le livrable final.
- Les mots-clés sont cherchés en mots entiers, sans casse ni accents.
- L'avis du LLM ne peut que MONTER le niveau, jamais le descendre.
"""
import re
import unicodedata

NIVEAUX = ["N0", "N1", "N2", "N3"]

ACTIONS_N3 = {"envoyer_client", "publier", "signer", "mise_en_production", "depense",
              "supprimer", "donnees_sensibles"}

# Déclencheurs N3 (texte normalisé : minuscules, sans accents ; motifs en mots entiers).
MOTS_N3 = [
    # Publication / diffusion
    r"publication", r"publications", r"publier", r"publie", r"publiez", r"publions", r"publiera",
    r"mise en ligne", r"mettre en ligne", r"mettez en ligne", r"poster", r"postez",
    r"diffuser", r"diffusez", r"diffusion",
    # Envoi
    r"envoyer", r"envoyez", r"envoie", r"envoi", r"envois", r"envoyons", r"enverra",
    # Argent
    r"virement", r"virements", r"paiement", r"paiements", r"payer", r"payez",
    r"facture", r"factures", r"facturer", r"facturation", r"devis",
    r"achat", r"achats", r"acheter", r"abonnement", r"abonnements",
    # « commande » seule est ambiguë (ligne de commande) : seul le sens achat déclenche N3.
    r"commander", r"commandez", r"commandons", r"commandera",
    r"passer (?:une |la |des |les |cette |ma |sa |notre )?commandes?", r"passez (?:une |la |des |les )?commandes?",
    r"passe (?:une |la |des |les )?commandes?", r"passera (?:une |la |des |les )?commandes?",
    r"bons? de commandes?", r"commandes? (?:de|d') (?:materiel|produits?|marchandises?|fournitures?|stock)",
    r"commandes? (?:fournisseur|client)s?",
    # Engagement juridique
    r"contrat", r"contrats", r"signature", r"signatures", r"signer", r"signez",
    # Sécurité / données
    r"mot de passe", r"mots de passe", r"donnees personnelles",
    r"supprimer", r"supprimez", r"suppression",
    # Production
    r"mise en production", r"mettre en production", r"deployer", r"deployez", r"deploiement",
    # Mouvements d'argent et engagements (audit)
    r"transferer", r"transferez", r"transfere", r"transferons", r"verser", r"versez", r"versement",
    r"versements", r"rembourser", r"remboursez", r"remboursement", r"remboursements",
    r"resilier", r"resiliez", r"resiliation", r"expedier", r"expediez", r"expedition",
    # Équivalents anglais (« pays » exclu : nom commun français)
    r"send", r"sends", r"sent", r"sending", r"transfer", r"transfers", r"transferred",
    r"pay", r"paid", r"paying", r"payment", r"payments", r"wire", r"refund", r"refunds", r"refunded",
    r"publish", r"publishes", r"published", r"publishing",
    r"deploy", r"deploys", r"deployed", r"deploying", r"deployment",
]
# Verbes engageants par RACINE (lemmes) : toutes les formes conjuguées et impératives courantes
# (texte normalisé sans accents). « paie », « vire », « efface », « deploie », « mets en ligne »…
_TERMINAISONS = r"(?:e|es|ent|er|ez|ons|ions|iez|era|eras|erai|erait|eraient|erons|erez|eront|ait|aient|ee|ees)"
_RACINES_N3 = [
    r"pa[yi]", r"vir", r"supprim", r"effac", r"deplo[yi]", r"publi", r"envo[yi]", r"resili", r"transfer",
    r"rembours", r"expedi", r"achet", r"diffus", r"liquid", r"detrui", r"detruis",
]
MOTS_N3 += [rf"{r}{_TERMINAISONS}" for r in _RACINES_N3] + [
    r"enverr\w*", r"vers(?:e|ent|er|ez|ons|era\w*)", r"sign(?:e|ent|er|ez|ons|era\w*)",
    r"(?:mets|met|mettez|mettons|mettent|mettre|mettra\w*|mis|mise|mettrai\w*) en (?:ligne|production)",
    r"detruire", r"detruisez", r"effacement", r"reglez? (?:la |les |cette )?(?:facture|somme|note)s?",
]
# Expressions à neutraliser avant la recherche (faux positifs : « ligne de commande »…).
NEUTRES = [
    r"lignes? de commandes?", r"invites? de commandes?",
    r"commandes? (?:shell|bash|linux|unix|docker|git|terminal|systeme|sql|suivantes?|ci-dessous)",
]
# Négation proche : le mot-clé qui suit n'est pas compté (« aucun paiement », « ne pas publier »).
_NEG_DIRECTE = {"aucun", "aucune", "sans"}
_DETERMINANTS = {"le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "ce", "cet", "cette", "ces"}
_PRONOMS = {"le", "la", "les", "l", "lui", "leur", "y", "en", "me", "m", "te", "t", "se", "s", "nous", "vous"}
# Montants : « 1 500 € », « 300€ », « 20 euros », « $50 », « 12,5 USD »… (texte brut, avant normalisation).
_NOMBRE = r"\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_MONTANT = re.compile(
    rf"(?:(?P<n1>{_NOMBRE})\s*(?:k\s*)?(?:€|eur\b|euros?\b|\$|usd\b|dollars?\b))"
    rf"|(?:(?:€|\$)\s*(?P<n2>{_NOMBRE}))", re.I)
# Verbes d'envoi pour lesquels un destinataire « moi / nous » n'engage personne d'extérieur.
VERBES_ENVOI = r"(?:envoyer|envoyez|envoie|envoyons|enverra|envoi|envois)"
DESTINATAIRE_INTERNE = r"(?:-?\s*(?:moi|nous)|\s+a\s+(?:moi|nous)|\s+au\s+proprietaire)"
# Pronom placé avant le verbe : « m'envoyer », « me envoyer », « nous envoyer ».
PRONOM_INTERNE = r"(?:m'\s*|me\s+|nous\s+)"

# Mots-clés N2 : publication selon la charte, production de code.
MOTS_N2 = [
    r"charte", r"code", r"script", r"programme", r"fonction python", r"requete sql",
    r"post (?:linkedin|instagram|facebook)", r"newsletter", r"article de blog",
]
SERVICES_N2 = {"CONTENT-ARENA/redaction"}

# Règles par service (texte normalisé, mots entiers).
# Droit : au minimum N2 ; N3 si le livrable est destiné à un tiers.
MOTS_TIERS = [r"client", r"clients", r"tiers", r"partenaire", r"partenaires", r"fournisseur", r"prestataire",
              r"cgv", r"cgu", r"mentions legales", r"conditions generales", r"politique de confidentialite",
              r"grand public", r"a remettre", r"a transmettre"]
# Cybersécurité : N3 si le livrable recommande une action sur la production ou une notification.
MOTS_PRODUCTION_CYBER = [
    r"pare-feu", r"firewall", r"ufw", r"iptables", r"nftables", r"regle de filtrage",
    r"ouvrir le port", r"ouverture (?:de|du|des) ports?", r"fermer le port", r"fermeture (?:de|du|des) ports?",
    r"compte", r"comptes", r"utilisateur root", r"desactiver le compte", r"bloquer le compte",
    r"cle", r"cles", r"cle ssh", r"cles ssh", r"jeton", r"jetons", r"rotation", r"revoquer", r"revocation",
    r"redemarrer", r"redemarrage", r"reboot", r"restart", r"arreter le service", r"couper",
    r"supprimer", r"suppression", r"effacer", r"reinstaller", r"restaurer", r"restauration",
    r"notifier", r"notification", r"declarer", r"declaration", r"signaler", r"signalement",
    r"cnil", r"anssi", r"cert-fr", r"plainte", r"autorite", r"autorites",
]
# Pilotage : N3 si décision financière ou engagement.
MOTS_ENGAGEMENT = [r"investir", r"investissement", r"investissements", r"emprunt", r"emprunter",
                   r"pret", r"prets", r"levee de fonds", r"financement", r"financer", r"recruter",
                   r"recrutement", r"embaucher", r"embauche", r"engager", r"engagement", r"engagements",
                   r"budget alloue", r"allouer", r"augmenter les prix", r"baisser les prix", r"decision financiere",
                   r"depenser", r"depense", r"depenses"]
# RSE : N3 si communication / publication externe (risque de greenwashing).
MOTS_EXTERNE = [r"externe", r"communication", r"communiquer", r"communique", r"campagne", r"site web",
                r"site internet", r"reseaux sociaux", r"rapport public", r"label", r"slogan", r"publicite",
                r"clients", r"grand public"]
# Mots-clés N0 : simple lecture / synthèse interne.
MOTS_N0 = [r"synthese", r"resume", r"resumer", r"lis", r"lecture", r"note interne", r"recapitul\w*"]


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower())


def contient_mot(texte: str, motif: str) -> bool:
    """Recherche en mot entier dans un texte déjà normalisé."""
    return re.search(rf"(?<![a-z0-9]){motif}(?![a-z0-9])", texte) is not None


def _nie(texte: str, debut: int, fin: int) -> bool:
    """Négation simple dans les 3 mots précédents (cas étroits, pour ne pas ouvrir de contournement).

    Comptent : « aucun/aucune/sans X », « pas de X », « ne pas X », « sans le/aucun X »,
    « ne X pas », « ne le X pas », « ne jamais X ». « Ne pas oublier de payer » reste détecté.
    """
    avant = re.findall(r"[a-z0-9]+", texte[:debut])[-3:]
    apres = re.findall(r"[a-z0-9]+", texte[fin:])[:2]
    w1 = avant[-1] if avant else ""
    w2 = avant[-2] if len(avant) > 1 else ""
    if w1 in _NEG_DIRECTE:
        return True
    if w1 in ("de", "d") and w2 == "pas":
        return True
    if w1 in ("pas", "jamais") and w2 in ("ne", "n"):
        return True
    if w1 in _DETERMINANTS and w2 in _NEG_DIRECTE:
        return True
    if (w1 in ("ne", "n") or (w1 in _PRONOMS and w2 in ("ne", "n"))) and apres and apres[0] in ("pas", "jamais"):
        return True
    return False


def _contient(texte: str, motifs: list[str]) -> str | None:
    """Premier motif présent en mot entier et non nié."""
    for m in motifs:
        for r in re.finditer(rf"(?<![a-z0-9]){m}(?![a-z0-9])", texte):
            if not _nie(texte, r.start(), r.end()):
                return m
    return None


def _neutraliser(texte: str) -> str:
    for motif in NEUTRES:
        texte = re.sub(rf"(?<![a-z0-9]){motif}(?![a-z0-9])", " ", texte)
    return texte


def detecter_montant(texte_brut: str) -> str | None:
    """Montant non nul en €, euros, $, USD ou dollars ; None sinon."""
    for m in _MONTANT.finditer(texte_brut or ""):
        chiffres = re.sub(r"\D", "", m.group("n1") or m.group("n2") or "")
        if chiffres and int(chiffres) > 0:
            return m.group(0).strip()
    return None


def _sans_envois_internes(texte: str) -> str:
    """Neutralise « envoyez-moi », « envoie-nous », « envoyer à moi »… (envoi au propriétaire)."""
    texte = re.sub(rf"(?<![a-z0-9]){VERBES_ENVOI}{DESTINATAIRE_INTERNE}(?![a-z0-9])", " ", texte)
    return re.sub(rf"(?<![a-z0-9]){PRONOM_INTERNE}{VERBES_ENVOI}(?![a-z0-9])", " ", texte)


def _n3_texte(texte: str) -> str | None:
    return _contient(_neutraliser(_sans_envois_internes(texte)), MOTS_N3)


def classer_regles(titre: str, consigne: str, service: str | None = None,
                   montant_eur: float | None = None, action: str | None = None,
                   livrable: str | None = None) -> tuple[str, str]:
    """Renvoie (niveau, motif) selon les règles déterministes (consigne, puis livrable)."""
    texte = normaliser(f"{titre} {consigne}")
    if montant_eur and montant_eur > 0:
        return "N3", f"montant engagé : {montant_eur} €"
    if action and action in ACTIONS_N3:
        return "N3", f"action engageante : {action}"
    # Montant écrit dans la consigne (pas dans le livrable : une étude chiffrée reste interne).
    m = detecter_montant(f"{titre} {consigne}")
    if m:
        return "N3", f"montant détecté dans la consigne : {m}"
    m = _n3_texte(texte)
    if m:
        return "N3", f"mot-clé sensible dans la consigne : {m}"
    if livrable:
        m = _n3_texte(normaliser(livrable))
        if m:
            return "N3", f"mot-clé sensible dans le livrable : {m}"
    # Règles propres aux services spécialisés.
    srv = service or ""
    if srv.startswith("LEX-GUARD/"):  # droit-* et conformité : N2 minimum
        m = _contient(texte, MOTS_TIERS)
        if m:
            return "N3", f"avis juridique destiné à un tiers : {m}"
        return "N2", f"avis juridique ({srv}) : relecture humaine requise (plancher N2)"
    if srv.startswith("CYBER-FORTRESS/"):
        # Cybersécurité : N2 minimum ; N3 si action sur la production ou notification à une autorité.
        for source, contenu in (("consigne", texte), ("livrable", normaliser(livrable or ""))):
            m = _contient(contenu, MOTS_PRODUCTION_CYBER)
            if m:
                return "N3", f"cybersécurité : action sur la production ou notification ({source} : {m})"
        return "N2", f"cybersécurité ({srv}) : relecture humaine requise"
    if srv.startswith("PILOT-CORE/"):
        m = _contient(texte, MOTS_ENGAGEMENT)
        if m:
            return "N3", f"décision financière ou engagement : {m}"
    if srv == "GREEN-CORE/rse":
        m = _contient(texte, MOTS_EXTERNE)
        if m:
            return "N3", f"communication RSE externe (risque de greenwashing) : {m}"
    if service in SERVICES_N2:
        return "N2", f"service de publication : {service}"
    m = _contient(texte, MOTS_N2)
    if m:
        return "N2", f"publication ou code : {m}"
    if livrable:
        m = _contient(normaliser(livrable), MOTS_N2)
        if m:
            return "N2", f"publication ou code dans le livrable : {m}"
    if _contient(texte, MOTS_N0):
        return "N0", "simple lecture ou synthèse interne"
    return "N1", "livrable interne"


def niveau_max(a: str, b: str | None) -> str:
    if b not in NIVEAUX:
        return a
    return a if NIVEAUX.index(a) >= NIVEAUX.index(b) else b


def classer(titre: str, consigne: str, service: str | None = None, montant_eur: float | None = None,
            action: str | None = None, niveau_llm: str | None = None,
            livrable: str | None = None, suspect: bool = False) -> tuple[str, str]:
    """Combine règles et avis LLM : le résultat n'est jamais inférieur aux règles.

    `suspect` (bouclier anti-injection : source ou livrable suspect) → plancher N2."""
    niveau, motif = classer_regles(titre, consigne, service, montant_eur, action, livrable)
    final = niveau_max(niveau, niveau_llm)
    if final != niveau:
        motif = f"{motif} ; relevé à {final} par l'avis du GATE"
    if suspect:
        from . import bouclier  # import local : bouclier importe gate
        plancher = niveau_max(final, bouclier.niveau_minimum_si_suspect())
        if plancher != final:
            final = plancher
            motif += f" ; plancher {plancher} : livrable ou source suspect d'injection"
    return final, motif
