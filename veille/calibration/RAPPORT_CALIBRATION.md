# Calibration du classement — rapport

Version des poids : **2026-11-04.1** — 60 requêtes (10 « tendances / médias »), corpus de 165 fiches (empreinte 90965e0106a9).

| Mesure | Avant (formule d'origine) | Après — validation croisée 5 plis | Après — sur les 60 requêtes (entraînement) |
|---|---|---|---|
| precision@5 | 0.3133 | 0.3533 | 0.3833 |
| nDCG@10 | 0.7948 | 0.8565 | 0.8671 |
| objectif (moyenne) | 0.5541 | 0.6049 | 0.6252 |

Le chiffre à retenir est la **validation croisée** : poids appris sans voir les requêtes mesurées.

Par catégorie (avant → après, sur les 60 requêtes) :

- normale (50 requêtes) : precision@5 0.3 → 0.376, nDCG@10 0.7722 → 0.8635
- tendances (10 requêtes) : precision@5 0.38 → 0.42, nDCG@10 0.9081 → 0.8852

## Poids retenus

```json
{
 "alpha": 2.0,
 "conf": {
  "A": 1.0,
  "B": 0.6,
  "C": 0.5,
  "D": 0.3
 },
 "w_type": 2.0,
 "w_autorite": 0.0,
 "plancher_fraicheur": 0.8,
 "mult_demi_vie": 0.5,
 "demi_vie_uniforme": 60,
 "expansion": true,
 "canal": {
  "flux": 1.0,
  "document": 1.2,
  "media": 1.0,
  "social": 1.0,
  "web": 1.0
 }
}
```

## Limites

- Corpus d'évaluation rédigé pour l'occasion (paraphrases courtes) et jugements de pertinence posés à la main : à refaire sur la base réelle après quelques semaines de collecte (`--db`).
- 60 requêtes, c'est peu : les écarts de quelques centièmes ne sont pas significatifs.
- La tonalité et les signaux sociaux restent des indications (confiance D), jamais des faits.
