# 01 — Routines d'exploitation

> Objectif : **5 minutes par jour**, 20 minutes le lundi, 1 heure par mois.
> Tout se fait au téléphone : appli **ntfy**, cockpit **/cockpit/decideur** (installé sur l'écran
> d'accueil) et, si besoin, la **console web hPanel**.

## Vue d'ensemble

```mermaid
gantt
    title Une semaine type de SYFER ATLAS (heure de Paris)
    dateFormat  HH:mm
    axisFormat  %H:%M
    section Chaque jour
    Sauvegarde (cron)            :03:30, 15m
    Veille sources (00:17, 06:17, 12:17, 18:17) :06:17, 10m
    Session N3 de midi           :12:30, 30m
    Session N3 du soir + bilan   :19:00, 30m
    section Lundi
    Pilote hebdo (plan semaine)  :07:30, 30m
    Revue des leçons (notif)     :08:00, 10m
    section Dimanche
    Veille cyber (F3)            :03:17, 45m
    Banc d'essai (8 missions)    :04:17, 60m
    Exercice restauration (1er dim.) :04:47, 20m
    Attaque simulée (2e dim.)    :05:17, 15m
```

## 1. Routine quotidienne (5 minutes)

| Quand | Où | Quoi faire | Résultat attendu |
|---|---|---|---|
| Le matin, 1 min | appli ntfy | Lire les alertes de la nuit. Repérer « ÉCHEC », « Restauration testée », « Rapport cyber ». | Aucune alerte d'échec. |
| **12 h 30**, 2 min | `/cockpit/decideur` | Session N3 de midi : traiter chaque carte (Valider / Refuser / Réviser). | File N3 vide ou décisions reportées en connaissance de cause. |
| **19 h 00**, 2 min | `/cockpit/decideur` + ntfy | Session N3 du soir. Lire le **bilan du jour** (alerte « résumé quotidien »). | File N3 vide. Bilan cohérent (missions terminées, aucune « echouee » inexpliquée). |
| Si alerte « rappel » | `/cockpit/decideur` | Une décision sera **refusée automatiquement dans 2 h** (24 h sans réponse). | Décider, ou laisser expirer volontairement. |

**Lire une carte N3 en 30 secondes**
1. Le **résumé en 3 lignes** : que veut faire l'agent ?
2. Le **risque** (faible / moyen / élevé) et **ses raisons** (montant, irréversible, tiers, production, données sensibles).
3. Le **coût estimé** (0 € sauf F4).
4. L'**avis du CHECKER** et les **avertissements de charte**.
5. Décision. Risque **élevé** : le **code Décideur** à 6 chiffres est demandé (`grep COCKPIT_CODE_DECIDEUR .env` si oublié).

> **Avis d'expert** (certitude élevée) — En cas de doute, **refusez** ou demandez une **révision** avec
> un commentaire précis (« retirer la mention de prix », « vouvoyer »). Un refus ne coûte rien ; une
> validation hâtive peut engager. Ne validez jamais une décision « pour voir ».

**Bonus 30 secondes (facultatif)** : la **note en un geste** (👍 / 👎 + motif) proposée sur une mission
terminée sur cinq. C'est elle qui nourrit les leçons et les exemples.

## 2. Routine hebdomadaire

### Lundi (20 minutes)

| Heure | Événement automatique | Votre action |
|---|---|---|
| **07 h 30** | **Pilote hebdo** : une décision N3 « Plan de la semaine » (3 priorités et 1 à 5 missions par projet actif). **Tout est décoché par défaut.** | Cocher **seulement** les missions utiles. Valider. Les autres ne partent pas. |
| **dès 08 h 00** | **Revue des leçons** : alerte « Leçons de la semaine : N à examiner ». | Carte « Leçons de la semaine » : accepter ou rejeter chaque leçon. Regarder le **test fantôme** (« +12 points sur 5 missions ») quand il existe. |
| Quand vous voulez | — | Lire les rapports du dimanche (voir ci-dessous) s'ils n'ont pas été lus. |

Règle simple pour les leçons :
- gain fantôme **positif** et texte clair → **accepter** ;
- gain **négatif** ou texte vague → **rejeter** (une leçon n'est jamais supprimée, elle reste tracée) ;
- pas encore de test fantôme → attendre la semaine suivante si rien ne presse.

### Dimanche (10 minutes, à lire dimanche soir ou lundi)

| Heure | Rapport | Où le lire | Ce qu'il faut vérifier |
|---|---|---|---|
| 03 h 17 | **Veille cyber** (2 missions CYBER-FORTRESS en F3) → alerte « Rapport cyber hebdo prêt » | Cockpit, missions du projet `nexus` | Failles « critique » ou « élevée » sur la pile (Ubuntu, Docker, Caddy, Ollama, Python). Toute action proposée sur la production arrive en **N3**. |
| 04 h 17 | **Banc d'essai** (8 missions de référence, F2 si cloud sinon F1) | `banc-essai/tableau.html` ou `banc-essai/resultats/hebdo/` | Note livrable et note système stables ; **pièges** tous réussis ; pas de baisse de plus de 5 points. |

```bash
cd /srv/p1/nexus-mothership
ls -t banc-essai/resultats/hebdo/ | head -3        # derniers rapports du banc
tail -n 5 banc-essai/resultats/hebdo.log           # fin du dernier passage
```

> **Avis d'expert** (certitude moyenne) — Le banc et la veille cyber tournent sur la même IA que vos
> missions. Sur le KVM 2 avec l'IA locale, un banc peut durer plus d'une heure : ne lancez pas de
> mission lourde le dimanche avant 6 h. Sur le KVM 8, la marge est suffisante.

## 3. Routine mensuelle (1 heure)

| Quand | Tâche | Comment | Résultat attendu |
|---|---|---|---|
| **1er dimanche, 04 h 47** (auto) | **Exercice de restauration** sur P2 | Automatique. Lire l'alerte ntfy. Rapport : `ls backups/exercices/` | Alerte « Restauration testée : OK ». |
| **2e dimanche, 05 h 17** (auto) | **Attaque simulée** du bouclier | Automatique. Rapport : `ls securite-ia/resultats/` | Taux de blocage ≥ 95 %, 0 faux positif bloquant, canari jamais ressorti. |
| Dernier jour du mois | **Revue des coûts** | Hostinger (hPanel > Facturation), Ollama (ollama.com/settings/usage), onglet *Fonctionnement* du cockpit (consommation par niveau F) | Total conforme au budget (≈ 90 € TTC/mois cible). F4 ≤ plafond fixé. |
| Fin de mois | **Checklist fin de mois** | [05-calendrier-et-checklists.md](05-calendrier-et-checklists.md) | Tout coché. |
| Une fois par mois | **Nouveaux cas d'attaque** | Ajouter 2 ou 3 cas inédits dans `securite-ia/corpus.json` (via Claude, relu par vous) | Le corpus vieillit moins vite que les attaques. |

```bash
cd /srv/p1/nexus-mothership
ls -t backups/exercices/ | head -1                  # dernier rapport d'exercice
ls -t securite-ia/resultats/ | head -2              # dernier rapport d'attaque simulée
tail -n 20 /var/log/nexus-securite-ia.log           # journal de l'attaque simulée
```

## 4. Routine trimestrielle (janvier, avril, juillet, octobre)

| Tâche | Comment | Pourquoi |
|---|---|---|
| **Rotation des clés et jetons** | Procédure 6 de [02-procedures.md](02-procedures.md) : mot de passe du cockpit, code Décideur, jetons de passerelle, clé API. **Jamais** `LEDGER_HMAC_KEY`. | Un secret qui a fuité sans que vous le sachiez cesse de servir. |
| Mise à jour du **gestionnaire de mots de passe** (Bitwarden, prévu) | Recopier chaque nouveau secret (lu par `grep NOM .env`). | Sans cela, une restauration sur un VPS neuf est impossible. |
| Revue des **sources de veille** | `python3 collecteur.py stats` (voir procédure 12) | Retirer les sources mortes, ajouter les utiles. |
| Revue des **projets actifs** | `nexus-core/projets.yaml`, champ `actif` | Le pilote du lundi ne travaille que sur les projets actifs. |

> **Avis d'expert** (certitude élevée) — La rotation trimestrielle est une **bonne pratique**, pas une
> obligation légale. Le vrai déclencheur reste l'**événement** : téléphone perdu, capture d'écran
> partagée, IA qui a vu un secret → rotation **immédiate** (fiche « Suspicion de compromission »).

## 5. Ce que vous ne faites jamais en routine

- Supprimer des fichiers dans `data/` ou `backups/` à la main.
- Lancer `bash uninstall.sh --purge`.
- Modifier le pare-feu ou SSH sans snapshot et sans la procédure 7.
- Passer `NEXUS_API_PEUT_DECIDER` à `1` (réservé aux tests).
- Monter `BUDGET_MONTHLY_EUR` au-dessus de 0 avant l'achat de la configuration complète et votre accord écrit.
