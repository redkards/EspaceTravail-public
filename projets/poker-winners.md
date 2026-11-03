# Site « Poker Winners » (Poker Vitrine) — plan d'emploi des agents NEXUS

Code projet : `poker-winners` · cockpit : https://srvXXXX.hstgr.cloud/cockpit · modèles : `PW-1` à `PW-6` dans `missions-modeles.json`.
Dépôt : redkards/poker-vitrine (lecture seule pour les agents). Contexte : `../tests-poker/contexte/poker-winners.md`.

## Principe
Le site est en bêta privée (pilote PARADOXX). Les agents relisent, contrôlent et rédigent ; ils ne poussent aucun code, ne déploient rien et ne contactent personne. La mise en ligne publique (v1.0) reste une décision explicite du propriétaire.

## Tâches récurrentes

| Tâche | Service NEXUS | Modèle | Fréquence | Niveau | Ce que le propriétaire valide dans le cockpit |
|---|---|---|---|---|---|
| Revue de code d'un fichier ou d'une modification (Symfony / Angular) | CODE-CORE/revue | PW-1 | à chaque modification significative avant fusion | N2 | Décide des corrections ; la fusion et le déploiement restent manuels |
| Conformité RGPD et jeu responsable d'une page (CGU, confidentialité, Premium) | LEX-GUARD/conformite | PW-2 | à chaque nouvelle page légale, puis 1 fois avant la v1.0 | N2 | Complète les champs « À COMPLÉTER » et valide les textes |
| Checklist de bêta d'une version / d'un parcours | OPS-CORE/projets | PW-3 | à chaque version (0.8.x → 1.0.0) | N3 (« suppression » de compte RGPD) | Exécute la checklist et trie les anomalies |
| Contenu d'une leçon + quiz + SEO | CONTENT-ARENA/redaction | PW-4 | 1 à 3 par semaine | N2 | Relit avant intégration dans le back-office |
| Proposition de partenariat (club, association, créateur) | REVENUE-CORE/propositions (+ action `envoyer_client`) | PW-5 | à la demande | **N3** | Fiche de décision ; aucun envoi automatique |
| Note de veille (encadrement des contenus poker, RGPD, technique) | R&D-PARADOX/veille | PW-6 | 1 par mois (textes fournis, pas d'accès web) | N1 | Retient les actions à planifier |

## Circuit type d'une version
PW-1 revue de code → PW-3 checklist → PW-2 conformité des pages touchées → recette humaine → décision de mise en ligne (hors NEXUS, confirmation explicite du propriétaire).

## Garde-fous
- Aucun secret, mot de passe, clé ou donnée de membre dans `{{code}}` ou `{{texte}}`.
- Site éducatif : aucun opérateur de jeux, aucune promesse de gain.
- Mention du pied de page (risques, 09 74 75 13 13, interdit aux moins de 18 ans) vérifiée à chaque checklist.
