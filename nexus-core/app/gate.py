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
    r"achat", r"achats", r"acheter", r"abonnement", r"abonnements", r"commande", r"commandes", r"commander",
    # Engagement juridique
    r"contrat", r"contrats", r"signature", r"signatures", r"signer", r"signez",
    # Sécurité / données
    r"mot de passe", r"mots de passe", r"donnees personnelles",
    r"supprimer", r"supprimez", r"suppression",
    # Production
    r"mise en production", r"mettre en production", r"deployer", r"deployez", r"deploiement",
]
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


def _contient(texte: str, motifs: list[str]) -> str | None:
    for m in motifs:
        if contient_mot(texte, m):
            return m
    return None


def _sans_envois_internes(texte: str) -> str:
    """Neutralise « envoyez-moi », « envoie-nous », « envoyer à moi »… (envoi au propriétaire)."""
    texte = re.sub(rf"(?<![a-z0-9]){VERBES_ENVOI}{DESTINATAIRE_INTERNE}(?![a-z0-9])", " ", texte)
    return re.sub(rf"(?<![a-z0-9]){PRONOM_INTERNE}{VERBES_ENVOI}(?![a-z0-9])", " ", texte)


def _n3_texte(texte: str) -> str | None:
    return _contient(_sans_envois_internes(texte), MOTS_N3)


def classer_regles(titre: str, consigne: str, service: str | None = None,
                   montant_eur: float | None = None, action: str | None = None,
                   livrable: str | None = None) -> tuple[str, str]:
    """Renvoie (niveau, motif) selon les règles déterministes (consigne, puis livrable)."""
    texte = normaliser(f"{titre} {consigne}")
    if montant_eur and montant_eur > 0:
        return "N3", f"montant engagé : {montant_eur} €"
    if action and action in ACTIONS_N3:
        return "N3", f"action engageante : {action}"
    m = _n3_texte(texte)
    if m:
        return "N3", f"mot-clé sensible dans la consigne : {m}"
    if livrable:
        m = _n3_texte(normaliser(livrable))
        if m:
            return "N3", f"mot-clé sensible dans le livrable : {m}"
    # Règles propres aux services spécialisés.
    srv = service or ""
    if srv.startswith("LEX-GUARD/droit-"):
        m = _contient(texte, MOTS_TIERS)
        if m:
            return "N3", f"avis juridique destiné à un tiers : {m}"
        return "N2", f"avis juridique ({srv}) : relecture humaine requise"
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
            livrable: str | None = None) -> tuple[str, str]:
    """Combine règles et avis LLM : le résultat n'est jamais inférieur aux règles."""
    niveau, motif = classer_regles(titre, consigne, service, montant_eur, action, livrable)
    final = niveau_max(niveau, niveau_llm)
    if final != niveau:
        motif = f"{motif} ; relevé à {final} par l'avis du GATE"
    return final, motif
