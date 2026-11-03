"""Audit 4 — GATE : montants, verbes FR/EN, négation simple, « ligne de commande »."""
import pytest

from app import gate


def n(consigne, **kw):
    return gate.classer("Tâche", consigne, **kw)[0]


@pytest.mark.parametrize("phrase", [
    "Prévoir 1 500 € pour l'hébergement", "Budget de 300€", "Coût : 20 euros par mois", "Un abonnement à $50",
    "Environ 12,5 USD", "Montant 2.500 € TTC", "Prix : 40 dollars",
])
def test_montants_n3(phrase):
    niveau, motif = gate.classer("Tâche", phrase)
    assert niveau == "N3" and ("montant" in motif or "abonnement" in motif)


def test_montant_nul_ou_absent():
    assert gate.detecter_montant("Offre gratuite (0 €)") is None
    assert gate.detecter_montant("Version 2.5 et 12 étapes") is None
    assert n("Liste les 12 étapes du démarrage") in ("N0", "N1")


@pytest.mark.parametrize("phrase", [
    "Transférer le dossier au partenaire", "Verser l'acompte", "Rembourser le client", "Résilier le contrat",
    "Expédier le colis", "Envoyer le rapport aux clients", "Send the invoice", "Transfer the funds",
    "Pay the supplier", "Wire the money", "Refund the order", "Publish the post", "Deploy to production",
])
def test_verbes_n3(phrase):
    assert n(phrase) == "N3", phrase


@pytest.mark.parametrize("phrase", [
    "Aucun paiement n'est prévu, fais une synthèse", "Synthèse sans publication",
    "Il n'y a pas de virement à faire", "Ne pas publier : note interne", "Ne publiez pas ce texte",
    "Synthèse, sans aucun envoi", "Ne jamais déployer, juste lister les étapes",
])
def test_negation_ignoree(phrase):
    assert n(phrase) != "N3", phrase


@pytest.mark.parametrize("phrase", [
    "Ne pas oublier de payer le fournisseur", "Aucun retard : envoyer la facture demain",
    "Sans attendre, publier l'article",
])
def test_negation_ne_permet_pas_de_contourner(phrase):
    assert n(phrase) == "N3", phrase


def test_ligne_de_commande_ne_declenche_pas():
    assert n("Explique la ligne de commande pour lister les fichiers") != "N3"
    assert n("Donne les commandes shell utiles et l'invite de commandes") != "N3"
    assert n("Passer la commande chez le fournisseur") == "N3"


def test_pays_n_est_pas_pay():
    assert n("Dans quels pays la solution est-elle disponible ? Fais une synthèse") != "N3"
