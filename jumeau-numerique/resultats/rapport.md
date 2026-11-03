# Jumeau numérique SYFER V2 — rapport de simulation

19 scénarios × 20 tirages Monte Carlo × 30 jours simulés, graine 2026. Toutes les valeurs : moyenne [p10 – p90] sur les tirages. Les délais concernent les missions de jour (manuelles et pilote) : les missions de nuit attendent volontairement leur fenêtre.

## Calage sur les mesures réelles (KVM 2, qwen2.5:3b, 1,1 vCPU)

| Mission | Durée simulée | Mesurée | Tokens simulés | Mesurés |
|---|---|---|---|---|
| checklist N1 | 124 s (-5%) | 131 s | 1596 (-1%) | 1611 |
| post Poker Feeling | 486 s (+1%) | 480 s | 6412 (+0%) | 6396 |

## Tableau des scénarios

| Scénario | Livrées/j | p50 F2 | p90 F2 | p90 F3 | Attente file moy. | CPU LLM | RAM pic / P1 | Plafond atteint | N3/j | Expirées | Tokens/mois local · cloud · payant | Coût €/mois | €/mission | Qualité | Score | Score panne cloud · robuste |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **S1** V1 actuelle | 10.1 [8.4–12.4] | 24 s | 73 s [33 s–3 min] | 6 min | 27 s | 1% | 3.1 / 5 Go | 3.3% | 2.8 | 4.0 | 0.42 M · 2.15 M · 0.00 M | 10 [9–13] | 0.04 | 90% | **93.7** [92–95] | 86.9 · **92.0** |
| **S1L** V1 locale (mesurée) | 8.7 [7.2–10.7] | 5 min | 15 min [8 min–29 min] | 33 min | 5 min | 7% | 3.1 / 5 Go | 12.6% | 2.4 | 2.4 | 2.55 M · 0.00 M · 0.00 M | 10 [9–13] | 0.04 | 55% | **76.6** [70–81] | 76.6 · **76.6** |
| **S2** KVM 2 + optim. V2 | 10.4 [9.0–12.7] | 16 s | 82 s [30 s–4 min] | 4 min | 21 s | 1% | 3.1 / 5 Go | 1.3% | 2.8 | 2.5 | 0.39 M · 1.33 M · 0.00 M | 10 [9–13] | 0.03 | 95% | **95.7** [94–97] | 91.9 · **94.7** |
| **S2L** KVM 2 V2 locale | 9.3 [7.6–11.3] | 3 min | 10 min [5 min–15 min] | 21 min | 3 min | 5% | 3.1 / 5 Go | 3.2% | 2.6 | 3.2 | 1.88 M · 0.00 M · 0.00 M | 10 [9–13] | 0.04 | 71% | **84.4** [81–87] | 84.4 · **84.4** |
| **S3** KVM 4 + 7B | 10.5 [8.9–12.7] | 15 s | 71 s [24 s–3 min] | 5 min | 23 s | 1% | 6.4 / 10 Go | 1.9% | 2.9 | 1.9 | 0.36 M · 1.28 M · 0.00 M | 16 [12–22] | 0.05 | 96% | **95.6** [94–97] | 93.5 · **95.1** |
| **S4** KVM 8 + 7B local seul | 9.9 [8.2–12.0] | 2 min | 7 min [3 min–13 min] | 14 min | 79 s | 3% | 6.4 / 22 Go | 4.3% | 2.8 | 4.0 | 1.69 M · 0.00 M · 0.00 M | 33 [24–40] | 0.11 | 89% | **90.0** [88–93] | 90.0 · **90.0** |
| **S5** KVM 8 double modèle | 9.8 [8.2–12.3] | 2 min | 6 min [4 min–10 min] | 15 min | 81 s | 3% | 12.6 / 22 Go | 4.8% | 2.7 | 3.7 | 1.76 M · 0.00 M · 0.00 M | 33 [24–40] | 0.11 | 94% | **91.2** [89–93] | 91.2 · **91.2** |
| **S6** S5 + F4 payant 30 € | 9.7 [8.2–12.1] | 2 min | 7 min [4 min–11 min] | 14 min | 18 min | 3% | 12.6 / 22 Go | 4.7% | 3.1 | 4.7 | 1.72 M · 0.00 M · 0.03 M | 33 [24–40] | 0.12 | 94% | **90.6** [89–93] | 90.6 · **90.6** |
| **S7** Max perf ≤ 150 € | 10.5 [8.5–13.1] | 15 s | 49 s [24 s–2 min] | 3 min | 18 min | 1% | 12.6 / 22 Go | 0.9% | 3.3 | 4.3 | 0.36 M · 0.39 M · 0.85 M | 43 [35–52] | 0.14 | 97% | **93.2** [92–94] | 92.7 · **93.1** |
| **S8** S5 charge ×3 | 20.3 [13.9–25.3] | 2 min | 5 min [4 min–6 min] | 10 min | 37 s | 6% | 12.6 / 22 Go | 3.6% | 6.0 | 7.2 | 3.15 M · 0.00 M · 0.00 M | 33 [24–40] | 0.06 | 93% | **91.3** [90–93] | test de stress |
| **S9** S3 panne cloud 10 j | 10.0 [8.3–11.8] | 20 s | 6 min [4 min–8 min] | 12 min | 70 s | 2% | 6.4 / 10 Go | 7.0% | 2.7 | 2.9 | 0.78 M · 0.81 M · 0.00 M | 16 [12–22] | 0.06 | 94% | **93.5** [92–95] | test de stress |
| **S10** S5 Décideur absent 3 j | 9.8 [8.1–12.4] | 2 min | 7 min [4 min–13 min] | 15 min | 85 s | 3% | 12.6 / 22 Go | 4.6% | 2.7 | 10.1 | 1.76 M · 0.00 M · 0.00 M | 33 [24–40] | 0.11 | 93% | **90.7** [88–93] | test de stress |
| **S11** S5 pic du lundi | 11.9 [10.2–14.1] | 2 min | 7 min [5 min–10 min] | 14 min | 76 s | 4% | 12.6 / 22 Go | 5.0% | 3.4 | 3.5 | 2.02 M · 0.00 M · 0.00 M | 33 [24–40] | 0.09 | 93% | **91.2** [90–93] | test de stress |
| **S12** S5 nuit chargée | 12.6 [11.0–14.9] | 2 min | 7 min [4 min–9 min] | 14 min | 77 s | 4% | 12.6 / 22 Go | 8.9% | 3.5 | 6.3 | 2.25 M · 0.00 M · 0.00 M | 33 [24–40] | 0.09 | 93% | **89.2** [86–92] | test de stress |
| **S13** KVM 8 hybride gratuit | 10.5 [8.8–13.0] | 15 s | 51 s [25 s–2 min] | 3 min | 9 s | 1% | 12.6 / 22 Go | 1.0% | 2.9 | 5.0 | 0.38 M · 1.26 M · 0.00 M | 33 [24–40] | 0.11 | 97% | **94.5** [93–96] | 93.2 · **94.2** |
| **S14** S13 + F4 payant 30 € | 10.5 [8.8–12.9] | 15 s | 46 s [24 s–80 s] | 3 min | 16 min | 1% | 12.6 / 22 Go | 1.0% | 3.3 | 4.7 | 0.37 M · 1.24 M · 0.03 M | 33 [24–40] | 0.11 | 96% | **94.1** [93–95] | 92.7 · **93.7** |
| **S15** S13 charge ×3 | 21.9 [14.8–26.9] | 15 s | 30 s [24 s–37 s] | 3 min | 4 s | 1% | 12.6 / 22 Go | 1.0% | 6.4 | 9.4 | 0.67 M · 2.27 M · 0.00 M | 33 [24–40] | 0.05 | 96% | **94.4** [94–95] | test de stress |
| **S16** KVM 4 hybride 3B+7B | 10.4 [8.8–12.4] | 15 s | 43 s [23 s–89 s] | 3 min | 7 s | 0% | 8.8 / 10 Go | 1.7% | 2.8 | 3.2 | 0.38 M · 1.30 M · 0.00 M | 16 [12–22] | 0.05 | 96% | **95.3** [94–96] | 92.4 · **94.5** |
| **S17** S13 panne cloud 10 j | 10.2 [8.8–12.2] | 21 s | 5 min [3 min–6 min] | 9 min | 28 s | 2% | 12.6 / 22 Go | 4.0% | 2.8 | 3.4 | 0.85 M · 0.81 M · 0.00 M | 33 [24–40] | 0.11 | 96% | **93.2** [92–95] | test de stress |

## Recommandation : S2 — KVM 2 + optim. V2

S1 + COLLECTOR sans LLM, contrôles par code, cache, gabarits, priorité jour/nuit.

Règle : meilleur score robuste (0,75 × nominal + 0,25 × avec 10 jours de panne du cloud gratuit) parmi les scénarios de conception (S1, S1L, S2, S2L, S3, S4, S5, S6, S7, S13, S14, S16), avec coût p90 ≤ 150 €/mois et RAM sous la limite P1 dans ≥ 95 % des tirages ; à 1 point près, le moins cher l'emporte.

Classement des scénarios éligibles : S3 (95.1) > S2 (94.7) > S16 (94.5) > S13 (94.2) > S14 (93.7) > S7 (93.1) > S1 (92.0) > S5 (91.2) > S6 (90.6) > S4 (90.0) > S2L (84.4) > S1L (76.6)

Le scénario retenu livre 10.4 missions/jour, p90 F2 = 82 s, qualité estimée 95%, pour 10 €/mois.

## Capacité (rampe de charge des missions manuelles)

Soutenable = p90 de l'attente en file (missions de jour) ≤ 1 h et ≥ 85 % des missions livrées.

| Scénario | ×1 | ×3 | ×6 | ×10 | ×15 | ×25 | ×40 | Soutenable |
|---|---|---|---|---|---|---|---|---|
| S1L | 9/j · 22 min ✗ | 17/j · 11 min ✗ | 31/j · 11 min ✗ | 49/j · 22 min ✗ | 71/j · 73 min ✗ | 114/j · 8.9 h ✗ | 148/j · 102.9 h ✗ | **≈ 0/j** (limite atteinte) |
| S2 | 10/j · 74 s | 20/j · 8 s | 36/j · 0 s | 56/j · 0 s | 82/j · 0 s | 132/j · 0 s | 205/j · 33 min | **≈ 205/j** (non saturé) |
| S3 | 10/j · 74 s | 20/j · 10 s | 36/j · 0 s | 56/j · 0 s | 82/j · 0 s | 132/j · 2 s | 206/j · 35 min | **≈ 206/j** (non saturé) |
| S5 | 9/j · 6 min | 19/j · 60 s | 34/j · 0 s | 54/j · 7 s | 78/j · 2 min | 125/j · 7 min | 195/j · 72 min ✗ | **≈ 125/j** (limite atteinte) |
| S13 | 10/j · 18 s | 21/j · 2 s | 37/j · 0 s | 57/j · 0 s | 83/j · 0 s | 134/j · 0 s | 210/j · 3 min | **≈ 210/j** (non saturé) |
| S16 | 10/j · 14 s | 20/j · 5 s | 36/j · 0 s | 56/j · 0 s | 81/j · 0 s | 131/j · 0 s | 204/j · 11 min | **≈ 204/j** (non saturé) |

## Sensibilités (tornade)

Candidats comparés : S2, S3, S16 ; 6 tirages par point. Chaque hypothèse est fixée à son min puis à son max (les autres restent tirées au hasard) ; score = score robuste ; « change la conclusion » = un autre candidat obtient le meilleur score.

| Hypothèse | Plage | Δ score du 1er candidat | Gagnant au min | Gagnant au max | Conclusion changée |
|---|---|---|---|---|---|
| `modele.cloud.q` | 0.65 – 0.88 probabilité | 2.6 | S16 | S3 | oui |
| `modele.3b.q` | 0.3 – 0.6 probabilité | 1.5 | S3 | S2 | oui |
| `v2.gabarit_gain_q` | 0.03 – 0.15 probabilité | 1.4 | S3 | S3 | oui |
| `modele.3b.fp` | 0.08 – 0.25 probabilité | 1.3 | S16 | S3 | oui |
| `qualite.gain_revision` | 0.05 – 0.2 probabilité | 1.0 | S3 | S3 | oui |
| `cloud.pannes_mois` | 0.5 – 6.0 épisodes/mois | 0.9 | S3 | S3 | oui |
| `cloud.duree_panne_h` | 0.5 – 12.0 h | 0.9 | S3 | S3 | oui |
| `offre.KVM2.prix_eur_mois` | 6.99 – 14.99 €/mois | 0.8 | S2 | S3 | oui |
| `v2.detection_code` | 0.2 – 0.5 probabilité | 0.7 | S3 | S3 | oui |
| `modele.cloud.fp` | 0.04 – 0.14 probabilité | 0.7 | S3 | S3 | oui |
| `modele.3b.se` | 0.3 – 0.65 probabilité | 0.6 | S3 | S3 | oui |
| `modele.cloud.se` | 0.6 – 0.85 probabilité | 0.6 | S3 | S16 | oui |
| `tokens.analyst.sortie` | 280 – 520 tokens | 0.5 | S3 | S16 | oui |
| `mix.p_F1` | 0.1 – 0.3 probabilité | 0.5 | S3 | S3 | oui |
| `qualite.auto_biais` | 0.65 – 0.95 facteur | 0.4 | S3 | S3 | oui |

## Score composite

score = 100 × (0,30 × Débit + 0,25 × Délai + 0,30 × Qualité + 0,15 × Coût), × 0,5 si la RAM dépasse la limite P1.
- Débit = missions livrées / missions arrivées (hors tests fantômes).
- Délai = 1 si le p90 F2 ≤ 10 min, 0 si ≥ 4 h, interpolation logarithmique entre les deux.
- Qualité = part estimée de livrables « bons » parmi les livrés (modèle : bon 1er jet, détection du CHECKER, fausses alertes, révisions).
- Coût = 1 − coût mensuel / 150 € (budget maximum).

## Graphiques

![debit.png](debit.png)
![delais.png](delais.png)
![cout_score.png](cout_score.png)
![decideur.png](decideur.png)
![file_7j.png](file_7j.png)
![capacite.png](capacite.png)

## Limites — à mesurer en réel pour confirmer

- Vitesse réelle d'un 7–8B (prefill et génération) sur KVM 4 / KVM 8 : seules deux missions 3B sont mesurées ; l'extrapolation vCPU/taille repose sur des exposants supposés.
- Qualité par modèle (bon 1er jet, sensibilité et fausses alertes du CHECKER) : hypothèses ordonnées par taille ; à mesurer avec le banc d'essai (noter.py) sur 3B, 7B, 8B, cloud gratuit, Haiku, Sonnet.
- Quota, latence et pannes réelles d'Ollama Cloud gratuit (limites non publiées en chiffres).
- Volume réel de missions manuelles et part de N3 (publication/envoi) ; prix Hostinger réels.
- Le jumeau ne modélise ni la mémoire SQLite/PostgreSQL, ni n8n, ni la passerelle MCP (charge supposée faible, incluse dans la RAM de base).

