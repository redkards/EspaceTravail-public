"""GATE : classement N0–N3 par règles déterministes.

Le LLM peut seulement proposer un niveau plus élevé ; il ne descend jamais
le niveau calculé par les règles.
"""
import re
import unicodedata

NIVEAUX = ["N0", "N1", "N2", "N3"]

ACTIONS_N3 = {"envoyer_client", "publier", "signer", "mise_en_production", "depense",
              "supprimer", "donnees_sensibles"}

# Mots-clés N3 (texte normalisé : minuscules, sans accents).
MOTS_N3 = [
    r"contrat", r"devis", r"paiement", r"payer", r"factur\w*", r"mot de passe",
    r"donnees personnelles", r"publi(?:er|e|ez|ons|era)", r"envoy\w*", r"envoi\w*",
]
# Mots-clés N2 : publication selon la charte, production de code.
MOTS_N2 = [
    r"charte", r"code", r"script", r"programme", r"fonction python", r"requete sql",
    r"post (?:linkedin|instagram|facebook)", r"newsletter", r"article de blog",
]
SERVICES_N2 = {"CONTENT-ARENA/redaction"}
# Mots-clés N0 : simple lecture / synthèse interne.
MOTS_N0 = [r"synthese", r"resume", r"resumer", r"lis\b", r"lecture", r"note interne", r"recapitul\w*"]


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower())


def _contient(texte: str, motifs: list[str]) -> str | None:
    for m in motifs:
        if re.search(rf"\b{m}\b", texte):
            return m
    return None


def classer_regles(titre: str, consigne: str, service: str | None = None,
                   montant_eur: float | None = None, action: str | None = None) -> tuple[str, str]:
    """Renvoie (niveau, motif) selon les règles déterministes."""
    texte = normaliser(f"{titre} {consigne}")
    if montant_eur and montant_eur > 0:
        return "N3", f"montant engagé : {montant_eur} €"
    if action and action in ACTIONS_N3:
        return "N3", f"action engageante : {action}"
    m = _contient(texte, MOTS_N3)
    if m:
        return "N3", f"mot-clé sensible : {m}"
    if service in SERVICES_N2:
        return "N2", f"service de publication : {service}"
    m = _contient(texte, MOTS_N2)
    if m:
        return "N2", f"publication ou code : {m}"
    if _contient(texte, MOTS_N0):
        return "N0", "simple lecture ou synthèse interne"
    return "N1", "livrable interne"


def niveau_max(a: str, b: str | None) -> str:
    if b not in NIVEAUX:
        return a
    return a if NIVEAUX.index(a) >= NIVEAUX.index(b) else b


def classer(titre: str, consigne: str, service: str | None = None, montant_eur: float | None = None,
            action: str | None = None, niveau_llm: str | None = None) -> tuple[str, str]:
    """Combine règles et avis LLM : le résultat n'est jamais inférieur aux règles."""
    niveau, motif = classer_regles(titre, consigne, service, montant_eur, action)
    final = niveau_max(niveau, niveau_llm)
    if final != niveau:
        motif = f"{motif} ; relevé à {final} par l'avis du GATE"
    return final, motif
