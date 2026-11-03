"""GATE — « commande » : sens achat → N3 ; ligne de commande → rien."""
import pytest

from app import gate


def n(consigne):
    return gate.classer("Tâche", consigne)[0]


@pytest.mark.parametrize("phrase", [
    "Passer une commande chez le fournisseur", "Passer commande de 20 cartes", "Passez la commande demain",
    "Prépare le bon de commande", "Établis les bons de commande", "Commander les fournitures",
    "Commandez le matériel", "Suivi des commandes fournisseurs", "Commande de matériel pour le club",
])
def test_commande_achat_n3(phrase):
    assert n(phrase) == "N3", phrase


@pytest.mark.parametrize("phrase", [
    "Explique les 3 commandes à taper pour redémarrer le conteneur en local", "Liste 5 commandes utiles",
    "Donne la commande suivante pour lister les fichiers", "Quelles commandes shell utiliser ?",
    "Commandes bash et terminal pour vérifier les journaux", "Explique la ligne de commande",
    "Une commande pour afficher la version de Python", "Les commandes du jeu sont expliquées en annexe",
])
def test_commande_technique_pas_n3(phrase):
    assert n(phrase) != "N3", phrase
