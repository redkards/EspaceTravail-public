# Livre « Poker Feeling » — plan d'emploi des agents NEXUS

Code projet : `poker-feeling` · cockpit : https://srvXXXX.hstgr.cloud/cockpit · modèles : `PF-1` à `PF-6` dans `missions-modeles.json`.
Contexte de référence : `../tests-poker/contexte/poker-feeling.md`.

## Principe
Les agents aident à la réécriture commerciale du manuscrit et préparent le lancement. Aucun prix, aucune date, aucun dépôt sur une plateforme et aucune diffusion sans décision du propriétaire.

## Tâches récurrentes

| Tâche | Service NEXUS | Modèle | Fréquence | Niveau | Ce que le propriétaire valide dans le cockpit |
|---|---|---|---|---|---|
| Première version d'un chapitre (avec « L'essentiel », « Ce que vous saurez faire », questions) | CONTENT-ARENA/redaction | PF-1 | 1 à 2 chapitres par semaine pendant la réécriture | N2 | Relit et intègre ou rejette le texte |
| Évaluation qualité d'un chapitre (grille 6 critères) | AGENT-FACTORY/evaluation | PF-6 | après chaque PF-1 ou réécriture humaine | N1 | Choisit les corrections à appliquer |
| Quatrième de couverture (par format : PDF, EPUB, papier) | CONTENT-ARENA/redaction | PF-2 | ponctuelle (1 par format) | N2 | Choisit la version et l'accroche |
| Plan de lancement (semaines, jalons, page du livre sur Poker Winners) | OPS-CORE/projets | PF-3 | 1 fois, puis mise à jour mensuelle | N1 | Valide jalons, canaux et points de contrôle |
| Conformité ANJ / jeu responsable d'un message | LEX-GUARD/conformite | PF-4 | **avant chaque** message promotionnel | N1 | Valide la version corrigée |
| Proposition de collaboration (librairie, club, créateur) | REVENUE-CORE/propositions (+ action `envoyer_client`) | PF-5 | à la demande | **N3** | Fiche de décision : rien n'est transmis sans « Valider » ; l'envoi reste manuel |

## Circuit type d'un message de lancement
PF-4 (conformité) → post rédigé avec le modèle libre ou RK-3 adapté (action `publier`, N3) → décision dans le cockpit → publication manuelle.

## Garde-fous
- Mention obligatoire sur tout support : « Réservé aux majeurs » + Joueurs Info Service 09 74 75 13 13 (appel non surtaxé).
- Aucune promesse de gain ou de résultat ; vouvoiement constant.
- Prix et date : toujours « À COMPLÉTER » tant que le propriétaire ne les a pas fixés.
