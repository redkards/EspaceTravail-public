# Jumeau numérique de SYFER V2

Un **simulateur** de la structure SYFER. Il sert à tester des choix de V2 (serveur, modèles, optimisations, IA payante)
**avant d'acheter quoi que ce soit**. Il rejoue un mois de missions des centaines de fois et mesure le débit, les délais,
la file d'attente, la charge du Décideur, la RAM, les tokens et le coût.

Ce dossier est autonome. Il **lit** seulement le reste du dépôt (rien n'est modifié ailleurs).

## Lancer

```bash
cd jumeau-numerique
python3 lancer.py            # tout : 19 scénarios × 200 tirages × 30 jours + robustesse + capacité + sensibilités
python3 lancer.py --rapide   # essai en 2 minutes (20 tirages)
python3 -m pytest -q tests   # 25 tests
```

Il faut Python 3 (bibliothèque standard). **matplotlib** est utilisé s'il est installé (graphiques PNG). Sinon, un graphique
SVG est écrit à la main. PyYAML est facultatif : un lecteur YAML minimal est intégré.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `hypotheses.json` | **Toutes les hypothèses** (92). Chacune a un min, une valeur probable, un max, une unité et une source. « MESURE » = mesuré sur le VPS. Tout le reste est une hypothèse. |
| `scenarios.yaml` | Les scénarios de conception et de stress (S1 à S17). |
| `jumeau.py` | Le moteur (simulation à événements discrets et Monte Carlo). |
| `lancer.py` | Exécute tout et écrit `resultats/`. |
| `resultats/rapport.md` | Le rapport lisible (tableaux, recommandation, sensibilités, limites). |
| `resultats/resultats.json` | Tous les chiffres (moyenne, p10, p90 de chaque indicateur). |
| `resultats/*.png` | Les graphiques : débit, délais, coût et score, Décideur, file sur 7 jours, capacité. |
| `tests/` | Les tests : graine fixe, unités, conservation des missions, sensibilités, plafonds. |

## Ce que le moteur reproduit (d'après le code réel de nexus-core)

- **Arrivées** : missions manuelles (profil horaire, semaine et week-end), pilote du lundi 07:30 (5 projets actifs, plan N3
  unique, missions cochées), banc d'essai du dimanche 04:17 (8 missions), veille de 03:17, audit SYFER (10 missions),
  tests fantômes de nuit (5 missions rejouées avant et après).
- **Pipeline** (`pipeline.py`) : PRIME (LLM seulement en cas d'égalité), COLLECTOR, ANALYST, CHECKER, double contrôle
  local en F3/F4, révisions (F1 0, F2 1, F3 2, F4 3), escalade au directeur (relance possible), GATE, relèvement F1 → F2
  si le livrable est N2/N3, puis décision N3 ou EXECUTOR.
- **Plafonds** (`fonctionnement.yaml`) : budget de tokens, chrono maximal, coût maximal F4 (0,50 €).
- **File** : `NEXUS_MAX_MISSIONS` missions à la fois, ordre FIFO. Option V2 : missions de nuit seulement de 01:00 à 06:00.
- **Modèle local** : vitesse de lecture et d'écriture selon la taille du modèle et les vCPU. Un appel par modèle à la fois.
  Le CPU est partagé entre deux modèles. Chargement depuis le disque, keep-alive de 10 min, RAM limitée par P1.
- **Cloud gratuit** : latence, quota journalier, pannes, puis repli sur le modèle local.
- **IA payante F4** : Sonnet (analyste, contrôleur) et Haiku (le reste). Plafond mensuel, avec repli F3 si le plafond est atteint.
- **Décideur** : sessions de 12:30 et 19:00, plafond de 15 fiches par jour, expiration en 24 h, demandes de révision.
- **Pannes** : redémarrages du serveur (missions relancées, modèles déchargés).

## Calage

Avec les valeurs probables, le jumeau rejoue les deux missions mesurées sur le VPS (KVM 2, qwen2.5:3b, 1,1 vCPU) :
checklist 124 s (mesure : 131 s) et post Poker Feeling 486 s (mesure : environ 480 s), à 1 % près en tokens.

## Les indicateurs

Pour chaque scénario : moyenne, p10 et p90 sur les tirages.

- Missions livrées par jour ; délais p50 et p90 par niveau F (missions de jour) ; attente en file.
- Utilisation du CPU, pic de RAM comparé à la limite P1, taux de plafond atteint (tokens, chrono, coût).
- Fiches N3 par jour, part au-dessus du plafond de 15, décisions expirées.
- Tokens par mois (local, cloud gratuit, payant), coût total en €/mois, coût par mission, qualité estimée.
- **Score composite** = 100 × (0,30 × débit + 0,25 × délai + 0,30 × qualité + 0,15 × coût).
  - Débit = part des missions livrées.
  - Délai = 1 si le p90 F2 est ≤ 10 min, 0 s'il est ≥ 4 h.
  - Qualité = part estimée de bons livrables.
  - Coût = 1 − coût / 150 €.
  - Le score est divisé par 2 si la RAM dépasse la limite P1.
- **Score robuste** = 0,75 × score normal + 0,25 × score avec 10 jours de panne du cloud gratuit. C'est lui qui
  désigne le scénario recommandé (coût p90 ≤ 150 €, RAM correcte). À 1 point près, le moins cher l'emporte.
- **Capacité** : la charge est augmentée de ×1 à ×40 pour trouver combien de missions par jour restent soutenables.
- **Sensibilités** : chaque hypothèse est mise à son min puis à son max. Le moteur regarde si le gagnant change.

## Modifier une hypothèse ou ajouter un scénario

- **Changer une hypothèse** : éditez sa ligne dans `hypotheses.json`, puis relancez `python3 lancer.py`.
- **Ajouter un scénario** : copiez un bloc de `scenarios.yaml` et changez l'`id` et les champs.
- **Forcer une valeur dans un seul scénario** :

```yaml
    surcharges:
      vitesse.gen_ref_tok_s: 7
```

## Ce qu'il faut mesurer en réel pour confirmer

1. La vitesse d'un 7–8B sur KVM 4 ou KVM 8 (lecture et écriture, en tokens par seconde).
2. La qualité par modèle avec le banc d'essai (`banc-essai/noter.py`) : bon premier jet, refus justes et refus à tort du CHECKER.
3. Le quota, la latence et les pannes réelles d'Ollama Cloud gratuit.
4. Le volume réel de missions et la part de N3.
5. Les prix Hostinger réels.
