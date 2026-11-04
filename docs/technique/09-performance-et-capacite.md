# 09 — Performance et capacité

## 1. Principe

Le temps de bout en bout d'une mission est dominé par **l'inférence LLM** ; la plateforme (FastAPI, SQLite, LEDGER, archive) pèse peu. Les chiffres viennent donc de trois sources distinctes, à ne pas confondre :

| Source | Nature | Fiabilité |
|---|---|---|
| Mesures réelles sur le VPS (KVM 2, `qwen2.5:3b`) | deux missions chronométrées, reprises comme points de calage du jumeau | **mesuré** |
| Jumeau numérique SYFER ÉCHO | simulation Monte Carlo sur 92 hypothèses | **simulé** (hypothèses explicites) |
| Banc de compaction | corpus synthétique de 10 000 missions | **mesuré sur corpus synthétique** |
| Campagne charge-200 | plateforme avec LLM factice | **à exécuter** (aucun résultat versionné) |

## 2. Mesures réelles connues

| Mesure | Valeur | Contexte | Source |
|---|---|---|---|
| Mission « checklist » N1 | **131 s**, 1 611 tokens | KVM 2, `qwen2.5:3b`, 1,1 vCPU | `jumeau-numerique/resultats/rapport.md` (calage) |
| Mission « post Poker Feeling » | **480 s**, 6 396 tokens | idem | idem |
| Durée d'une étape en IA locale | 10 à 60 s | 2 vCPU | `README.md` § 10 |
| Empreinte MVP sans repli local | ≈ 0,5–0,6 Go (plafond 576 Mo) | Ollama Cloud seul | `README.md`, `docker-compose.yml` |
| Empreinte MVP avec repli local | plafond ≈ 4,1 Go | + Ollama 3,5 Go | idem |
| Durée des suites de tests | nexus-core 75 s (483 tests), toutes suites ≈ 2 min 40 | poste de développement, LLM factice | exécution du 4 novembre (voir 08) |
| Simulations | 103 scénarios en 7,7 s | LLM factice | `simulations/resultats/2026-11-04_0023.md` |

Estimations **non mesurées** du banc d'essai (modèle local, 2 vCPU) : F1 30 min–1 h (8 missions) / 2–4 h (30) ; F2 1–2 h / 4–7 h ; F3 1 h 30–3 h / 6–10 h (`banc-essai/README.md`).

## 3. Résultats du jumeau numérique

Exécution versionnée : 19 scénarios × **20 tirages** × 30 jours, graine 2026 (mode rapide ; la campagne complète prévoit 200 tirages). Valeurs moyennes [p10–p90].

| Scénario | Livrées/j | p90 F2 | p90 F3 | RAM pic / P1 | Coût €/mois | Qualité | Score | Score robuste |
|---|---|---|---|---|---|---|---|---|
| S1 V1 actuelle (cloud gratuit + repli) | 10,1 | 73 s | 6 min | 3,1 / 5 Go | 10 | 90 % | 93,7 | 92,0 |
| S1L V1 locale (mesurée) | 8,7 | 15 min | 33 min | 3,1 / 5 Go | 10 | 55 % | 76,6 | 76,6 |
| **S2 KVM 2 + optimisations V2** | 10,4 | 82 s | 4 min | 3,1 / 5 Go | **10** | 95 % | **95,7** | **94,7** |
| S2L KVM 2 V2 locale | 9,3 | 10 min | 21 min | 3,1 / 5 Go | 10 | 71 % | 84,4 | 84,4 |
| S3 KVM 4 + 7B | 10,5 | 71 s | 5 min | 6,4 / 10 Go | 16 | 96 % | 95,6 | **95,1** |
| S4 KVM 8 + 7B local seul | 9,9 | 7 min | 14 min | 6,4 / 22 Go | 33 | 89 % | 90,0 | 90,0 |
| S5 KVM 8 double modèle | 9,8 | 6 min | 15 min | 12,6 / 22 Go | 33 | 94 % | 91,2 | 91,2 |
| S6 S5 + F4 payant 30 € | 9,7 | 7 min | 14 min | 12,6 / 22 Go | 33 | 94 % | 90,6 | 90,6 |
| S7 performance max ≤ 150 € | 10,5 | 49 s | 3 min | 12,6 / 22 Go | 43 | 97 % | 93,2 | 93,1 |
| S13 KVM 8 hybride gratuit | 10,5 | 51 s | 3 min | 12,6 / 22 Go | 33 | 97 % | 94,5 | 94,2 |
| S14 S13 + F4 30 € | 10,5 | 46 s | 3 min | 12,6 / 22 Go | 33 | 96 % | 94,1 | 93,7 |
| S16 KVM 4 hybride 3B + 7B | 10,4 | 43 s | 3 min | 8,8 / 10 Go | 16 | 96 % | 95,3 | 94,5 |

Tests de stress (score) : S8 charge ×3 sur S5 91,3 ; S9 panne cloud 10 j sur S3 93,5 ; S10 Décideur absent 3 j 90,7 (10,1 expirations/mois) ; S11 pic du lundi 91,2 ; S12 nuit chargée 89,2 ; S15 charge ×3 sur S13 94,4 ; S17 panne cloud 10 j sur S13 93,2.

Formule : score = 100 × (0,30 Débit + 0,25 Délai + 0,30 Qualité + 0,15 Coût), divisé par 2 si la RAM dépasse la limite ; score robuste = 0,75 × nominal + 0,25 × avec 10 jours de panne du cloud gratuit ; coût de référence 150 €/mois.

**Recommandation du jumeau** : S2 (KVM 2 + optimisations V2 : COLLECTOR sans LLM, contrôles par code, cache, gabarits, priorité jour/nuit) — 10,4 missions/jour, p90 F2 = 82 s, qualité estimée 95 %, 10 €/mois ; S3 (KVM 4 + 7B) obtient le meilleur score robuste (95,1) pour 16 €/mois. La sensibilité montre que la conclusion dépend surtout de la qualité réelle du cloud gratuit et du 3B (`modele.cloud.q`, `modele.3b.q`) : **à mesurer avec le banc** avant achat.

Les optimisations V2 de S2 ne sont **pas encore implémentées** dans nexus-core **[PRÉVU]** (le COLLECTOR appelle toujours le LLM : `pipeline._executer`).

### 3.1 Capacité soutenable

Soutenable = p90 de l'attente en file ≤ 1 h et ≥ 85 % des missions livrées (rampe de charge des missions manuelles) :

| Scénario | ×1 | ×10 | ×25 | ×40 | Capacité soutenable |
|---|---|---|---|---|---|
| S1L (local seul, V1) | 9/j · 22 min | 49/j · 22 min | 114/j · 8,9 h | 148/j · 103 h | **≈ 0/j au-delà du nominal** (limite atteinte) |
| S2 | 10/j · 74 s | 56/j · 0 s | 132/j · 0 s | 205/j · 33 min | ≈ 205/j (non saturé) |
| S3 | 10/j · 74 s | 56/j · 0 s | 132/j · 2 s | 206/j · 35 min | ≈ 206/j |
| S5 | 9/j · 6 min | 54/j · 7 s | 125/j · 7 min | 195/j · 72 min | ≈ 125/j |
| S13 | 10/j · 18 s | 57/j · 0 s | 134/j · 0 s | 210/j · 3 min | ≈ 210/j |
| S16 | 10/j · 14 s | 56/j · 0 s | 131/j · 0 s | 204/j · 11 min | ≈ 204/j |

Lecture : avec un fournisseur cloud gratuit disponible, la plateforme absorbe environ **5 fois la charge nominale** de 40 missions/jour ; en IA locale seule sur KVM 2, la file sature dès la charge nominale (délais de dizaines de minutes).

### 3.2 Limites du jumeau

Seules deux missions 3B sont mesurées ; vitesse réelle d'un 7–8B sur KVM 4/8, qualité par modèle, quotas et pannes d'Ollama Cloud gratuit, volume réel de N3 et prix Hostinger restent des hypothèses ; le jumeau ne modélise ni SQLite/PostgreSQL, ni n8n, ni la passerelle MCP.

## 4. Compaction de l'archive

Banc `compaction/mesure.py` (4 novembre 00 h 47 ; corpus synthétique : 10 000 missions sur 250 jours, 5 000 fiches de veille, 2 000 connaissances dont 20 % de quasi-doublons). Brut : 91,63 Mo (9,2 Ko/mission).

| Méthode | Taille | Ratio | Lecture d'un enregistrement |
|---|---|---|---|
| Format actuel (gzip par ligne, mensuel) | 26,52 Mo | 3,45 | 111,5 ms (parcours du mois) |
| zlib bloc + dictionnaire | 9,83 Mo | 9,32 | 2,97 ms |
| lzma bloc | 6,69 Mo | 13,69 | 7,30 ms |

Pipeline à paliers (module `app/compaction.py`, réglages par défaut) :

| Indicateur | Valeur |
|---|---|
| Dossier `compact/` total | **8,42 Mo** pour 80,63 Mo brut → ratio global 9,6 (15,0 hors index) |
| Ratio fichiers tiède / froid | 12,91 / 23,15 |
| Lecture tiède / froid (cache vide) | 2,0 ms (p95 5,3) / 9,1 ms (p95 17,8) |
| Recherche FTS5 | 13,2 ms (format actuel : 29,5 ms) |
| Compaction tiède | 12,0 s pour 6 000 enregistrements |
| Vérification complète | 1,2 s (valide) ; d'un enregistrement 2,9 ms |
| Effacement RGPD dans un bloc | 520 ms |
| Veille : archivage froid des fiches expirées | base 5,97 → 3,02 Mo, archive 1,29 Mo au lieu d'une suppression |
| Connaissances : fusion de quasi-doublons et plafond 250/projet | 2,97 → 2,18 Mo en 5,35 s |

Projection disque (archive + index) :

| Rythme | Horizon | Sans compaction | Avec compaction | Gain |
|---|---|---|---|---|
| nominal 40/j | 1 an | 88,9 Mo | 19,1 Mo | ×4,6 |
| nominal 40/j | 3 ans | 266,8 Mo | 40,8 Mo | ×6,5 |
| 200 % (80/j) | 1 an | 177,8 Mo | 38,3 Mo | ×4,6 |
| 200 % (80/j) | 3 ans | 533,5 Mo | 81,6 Mo | ×6,5 |

Conclusion : même sans compaction, l'archive reste très en dessous des 20 Go de P1 sur 3 ans ; la compaction sert surtout la **vitesse de lecture et de recherche** et l'effacement RGPD dans l'archive ancienne. Statut : **[EN COURS]** (non branché ; voir 03).

## 5. Limites de capacité de la plateforme

| Ressource | Limite | Réglage | Comportement au-delà |
|---|---|---|---|
| Missions simultanées | 1 (IA locale) ou 2 (cloud) | `NEXUS_MAX_MISSIONS` | file FIFO, statut `en_attente_place` |
| Worker HTTP | 1 Uvicorn | Dockerfile | requêtes concurrentes servies par le pool de fils |
| RAM nexus-core / nexus-bridge | 384 Mo / 128 Mo | `mem_limit` | arrêt OOM du conteneur, redémarrage `unless-stopped`, reprise |
| Fiches N3 par jour | 15 | `N3_DAILY_CAP` | mise en file, création dès que possible |
| Tokens par mission | 6 000 à 80 000 selon F | `fonctionnement.yaml`, `BUDGET_TASK_TOKENS` | `plafond_atteint`, livrable partiel |
| Délai par mission | 180 à 1 800 s selon F | `fonctionnement.yaml` | `plafond_atteint` |
| Taille d'un message LLM | 4 000 à 24 000 caractères | `LLM_MAX_CHARS` (F2) | troncature contrôlée par priorité |
| Consigne | 20 000 caractères | Pydantic | 422 |
| Appels MCP | 60/min par identité ; lots ≤ 10 ; 8 Ko par champ ; corps 64 Ko | `BRIDGE_LIMITE_PAR_MINUTE` | 429 + `Retry-After`, 400, 413 |
| Écriture SQLite | sérialisée (WAL, `busy_timeout` 30 s) | `db.py` | attente |
| Disque P1 | 20 Go | `partitions.sh --size` | voir scénario S19 de charge-200 |
| Ollama local | 1 requête parallèle, 1 modèle chargé, `keep_alive` 10 min | `docker-compose.yml` | file côté Ollama |

## 6. Réglages recommandés

| Objectif | Réglage |
|---|---|
| Délais courts sur KVM 2 | Ollama Cloud (`LLM_PROVIDER=ollama_cloud`) avec repli local ; `NEXUS_MAX_MISSIONS=2` |
| Économiser la RAM | `install.sh --sans-repli` (≈ 0,5 Go) — au prix de l'absence de F1 et de double contrôle local |
| Réduire la charge Décideur | ajuster `NEXUS_SESSIONS_N3` ; surveiller les faux positifs N3 du GATE |
| Qualité du contrôle | `NEXUS_MODELES_CLOUD` avec au moins deux modèles (diversité ANALYST/CHECKER) ; F3 pour les sujets sensibles |
| Missions longues en local | F1 pour les tâches simples ; `OLLAMA_NUM_CTX=8192` pour lire 12 000 caractères |
| Tâches lourdes | `NEXUS_FENETRE_NUIT` pour le test fantôme et la future compaction |
| Mesure avant achat | banc d'essai F1/F2/F3 puis comparaison avec le jumeau (hypothèses `modele.*.q`) |

## 7. Travaux de mesure restants

| N° | Mesure | Outil | Statut |
|---|---|---|---|
| P1 | Campagne complète charge-200 (25 scénarios, ≈ 25–30 min sur 2 vCPU) | `charge-200/charge.py` | [PRÉVU] |
| P2 | Banc qualité F1, F2, F3 sur le VPS, avec Ollama Cloud | `banc-essai/lancer.sh` | [PRÉVU] (résultats non versionnés) |
| P3 | Jumeau en mode complet (200 tirages) recalé sur P2 | `jumeau-numerique/lancer.py` | [PRÉVU] |
| P4 | Mesure d'un 7B sur KVM 4 avant toute montée en gamme | banc + jumeau | [PRÉVU] |
| P5 | Intégration et mesure de la compaction en production | `compaction.tache_nocturne` | [EN COURS] |
