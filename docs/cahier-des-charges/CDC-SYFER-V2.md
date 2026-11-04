# Cahier des charges — SYFER V2

| Rubrique | Valeur |
|---|---|
| Projet | SYFER — version 2 |
| Périmètre | SYFER ATLAS (version réelle sur VPS) et SYFER ÉCHO (jumeau numérique) ; architecture cible NEXUS MOTHERSHIP en perspective |
| Référence | CDC-SYFER-V2, révision 1.0 |
| Date | 4 novembre 2026 |
| Base de rédaction | code de la branche `v2` du dépôt `espacetravail-public` ; documentation technique `docs/technique/` |
| Maîtrise d'ouvrage | le Décideur (propriétaire unique du projet) |
| Maîtrise d'œuvre | agents de développement (IA) sous validation du Décideur |
| Licence | propriétaire (dépôts privés) |
| Statut du document | à valider par le Décideur |

---

## 1. Contexte et objectifs

### 1.1 Contexte

Le Décideur pilote seul plusieurs projets (Poker Winners, Poker Feeling, REDKARDS, Top Solver, NEXUS, activité freelance IA…). SYFER fournit une **organisation d'agents IA spécialisés** (directions, services, quadrants COLLECTOR / ANALYST / CHECKER / EXECUTOR) qui produisent des livrables, avec **un seul humain** pour valider les décisions importantes.

La version 1 (« Mini NEXUS MOTHERSHIP ») est installée sur un VPS Hostinger KVM 2 partitionné. La V2 ajoute la mémoire collective auto-apprenante, le Décideur mobile, le bouclier anti-injection, la veille sourcée, les niveaux de fonctionnement F1–F4, le Protocole NEXUS v1, la séparation en quatre produits, et un dispositif complet de tests (simulations, itérations, charge, jumeau numérique, porte de qualité).

### 1.2 Nomenclature

| Nom | Définition |
|---|---|
| SYFER | le projet total |
| SYFER ATLAS | la version réelle sur le VPS (kit mini-mothership : nexus-core, nexus-bridge, Caddy, Ollama, scripts) |
| SYFER ÉCHO | la version virtuelle « maxi performance » : jumeau numérique servant à décider avant d'acheter |
| NEXUS MOTHERSHIP | l'architecture cible (246 agents), hors périmètre de réalisation V2 |

### 1.3 Objectifs

| N° | Objectif | Indicateur |
|---|---|---|
| O1 | Produire des livrables utiles pour les projets du Décideur, sans action externe automatique | ≥ 10 missions livrées par jour en nominal (jumeau S2) ; 0 action externe exécutée par le système |
| O2 | Garantir que **seul le Décideur** engage le projet (argent, publication, envoi, signature, production) | 0 décision N3 prise hors cockpit ; 0 livrable N3 exécuté sans validation (oracles O03, O06) |
| O3 | Fonctionner à coût maîtrisé, **IA gratuite par défaut** | coût total ≤ budget (≈ 90 € TTC/mois) ; dépense IA payante = 0 € sans accord explicite |
| O4 | S'améliorer sans dériver (mémoire collective) | leçons appliquées seulement après acceptation ; suspension automatique en cas de régression |
| O5 | Résister aux injections et aux erreurs des modèles | attaque simulée ≥ 95 % ; 0 faux positif bloquant |
| O6 | Être exploitable depuis un téléphone Android | toutes les opérations courantes faisables via le cockpit PWA et le terminal web hPanel |
| O7 | Préparer la séparation en quatre produits commercialisables | Protocole NEXUS v1 publié ; script de séparation opérationnel |

## 2. Périmètre

### 2.1 Inclus

- Noyau multi-agents nexus-core : 93 rôles, pipeline, GATE N0–N3, niveaux F1–F4, charte, bouclier, LEDGER, Décideur, cockpit et PWA, mémoire projet et collective, archive, test fantôme, pilote hebdomadaire, export QG, résumé quotidien.
- Passerelle MCP nexus-bridge (Claude, ChatGPT, Gemini) : 20 outils.
- Veille sourcée (322 sources publiques) et son intégration au COLLECTOR.
- Infrastructure : partitions, Docker Compose (MVP et complet), Caddy, Ollama, sauvegarde, restauration, exercice mensuel, désinstallation, veille cyber hebdomadaire.
- Protocole NEXUS v1 (schémas, validateur, exemples).
- Dispositif qualité : tests unitaires, simulations, itérations, charge, banc d'essai, attaque simulée, jumeau numérique, SYFER Test System, CI.
- Compaction de l'archive (intégration).
- Outillage de séparation en 4 dépôts.

### 2.2 Exclus

- Toute **action externe automatique** (envoi d'e-mail, publication, paiement, signature, mise en production) : le système prépare, l'humain ou un workflow explicitement activé exécute.
- La réalisation de l'architecture complète NEXUS MOTHERSHIP (246 agents).
- L'utilisation de pgvector (recherche vectorielle) et de Redis (réservés, non exploités).
- Le multi-utilisateur (un seul Décideur ; pas de gestion de rôles humains).
- Les applications mobiles natives (le cockpit est une PWA).
- L'exploitation offensive en cybersécurité (posture strictement défensive).
- La commercialisation (modèle commercial décidé ultérieurement).

## 3. Acteurs et rôles

| Acteur | Type | Droits | Interface |
|---|---|---|---|
| **Décideur** | humain unique | crée des missions ; **seul** à valider/refuser/réviser les N3, accepter/rejeter les leçons, effacer (RGPD), lancer F4 ; arrêt d'urgence ; administration du VPS | cockpit `/cockpit`, Décideur mobile `/cockpit/decideur`, terminal hPanel, appli ntfy |
| **Agents SYFER** (93 rôles) | logiciels (70 LLM, 23 déterministes) | produisent, contrôlent, classent, enregistrent ; aucune action externe | internes à nexus-core |
| **IA externes** (Claude, ChatGPT, Gemini) | clients MCP | lisent et écrivent la mémoire commune, tâches, messages, passations ; créent des missions ; lisent les décisions ; **ne décident jamais** | `/mcp/<jeton>` |
| **Automatisations** (n8n, scripts cron, banc) | logiciels | appellent l'API par clé ; lecture des décisions ; création de missions | `/api/*` avec `X-Nexus-Key` |
| **Fournisseurs IA** | tiers | Ollama Cloud (gratuit), Ollama local, Anthropic (F4 payant, désactivé par défaut) | HTTPS sortant |
| **Hébergeur** | tiers | VPS Hostinger KVM 2, pare-feu hPanel | hPanel |
| **Sources de veille** | tiers | publient des flux et API publics lus par le collecteur | HTTP(S) sortant, `robots.txt` respecté |

## 4. Exigences fonctionnelles

Convention : **Priorité** M = indispensable (Must), S = souhaitable (Should), C = confort (Could). **Statut** FAIT = implémenté et vérifié par au moins un test vert ; EN COURS = implémenté partiellement, non intégré ou test rouge ; PRÉVU = à réaliser. Les chemins de tests sont relatifs au dossier indiqué (`nc/` = `nexus-core/tests/`, `nb/` = `nexus-bridge/tests/`, `sim/` = `simulations/` méthode N, `it/` = oracle de `iterations-100/`).

### 4.1 Missions et pipeline (MIS)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-01 | Le système accepte une mission (titre, consigne, projet, service, niveau F) et répond immédiatement avec un identifiant. | M | `POST /api/missions` → 202 avec `id` et `statut` en < 1 s ; traitement en tâche de fond | `nc/test_api.py::test_mission_complete_n1` | FAIT |
| EF-02 | Une mission soumise deux fois n'est exécutée qu'une fois. | M | deux appels concurrents à `traiter(mid)` → une seule exécution, LEDGER `mission_deja_prise` | `nc/test_concurrence.py::test_mission_traitee_une_seule_fois` ; `it/O11` | FAIT (O11 : violations ouvertes) |
| EF-03 | Le nombre de missions simultanées est borné ; les suivantes attendent dans l'ordre d'arrivée. | M | jamais plus que `NEXUS_MAX_MISSIONS` en cours ; statut `en_attente_place` visible | `nc/test_file_reprise.py::test_jamais_plus_que_la_capacite`, `::test_file_fifo_et_statut_en_attente_de_place` | FAIT |
| EF-04 | Après un redémarrage, aucune mission n'est perdue : les missions en cours sont marquées échouées avec motif, celles en file sont relancées dans l'ordre. | M | statut `echouee` « interrompue par un redémarrage » ; relance FIFO | `nc/test_file_reprise.py::test_reprise_au_demarrage` ; charge-200 S18 | FAIT (S18 à exécuter) |
| EF-05 | PRIME choisit le service : paramètre explicite, sinon mots-clés en mots entiers, sinon départage par le LLM, sinon priorité de prudence. | M | 10 scénarios de routage conformes | `sim/1` (10/10) ; `nc/test_prime_audit.py` | FAIT |
| EF-06 | Chaque étape (agent, rôle, entrée, sortie, verdict, tokens) est enregistrée et consultable. | M | `GET /api/missions/{id}` renvoie `etapes[]` | `nc/test_api.py::test_mission_complete_n1` | FAIT |
| EF-07 | Les messages envoyés au modèle respectent la limite du niveau, en tronquant d'abord les sections les moins prioritaires. | M | livrable entier pour le CHECKER malgré une consigne longue | `nc/test_fiche_technique.py::test_checker_recoit_livrable_complet_malgre_longue_consigne` | FAIT |
| EF-08 | L'arrêt d'urgence (grille, direction, agent) suspend immédiatement les missions concernées. | M | statut `suspendue` ; LEDGER `killswitch_on` | `nc/test_pipeline.py::test_kill_switch_grille_suspend`, `::test_kill_switch_direction_suspend` | FAIT |
| EF-09 | Les livrables sont rangés par projet et listables par projet. | S | fichier `livrables/<projet>/<id>.md` ; filtre `?projet=` | `nc/test_projets.py::test_livrable_range_par_projet`, `::test_filtres_missions_et_decisions` | FAIT |
| EF-10 | Le registre des projets se recharge sans redémarrage ; un fichier invalide ne casse pas le registre en place. | S | `GET /api/projets?recharger=1` ; 500 explicite et ancien registre conservé | `nc/test_projets.py::test_rechargement_sans_redemarrage` | FAIT |
| EF-11 | Un projet inconnu est refusé avec un message clair. | M | 422 | `nc/test_projets.py::test_projet_inconnu_422` | FAIT |

### 4.2 Agents (AGT)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-12 | Le système comporte 93 rôles : 5 noyau, 8 directeurs, 20 services × 4 quadrants. | M | chargement de 93 fiches valides, 20 services complets | `nc/test_agents_gate.py::test_chargement_93_agents`, `::test_vingt_services_complets` | FAIT |
| EF-13 | EXECUTOR, SENTINEL, LEDGER et BUDGET sont déterministes et n'appellent jamais de modèle. | M | appel LLM au nom d'un agent déterministe → erreur | `nc/test_agents_gate.py::test_agent_deterministe_jamais_appele` | FAIT |
| EF-14 | Toute fiche agent est conforme au schéma `agent` du Protocole NEXUS v1. | M | `valider.py --agents` sans erreur | CI `configuration` ; `protocole/tests/test_protocole.py::test_fiches_agents_yaml` | FAIT |
| EF-15 | Le département CYBER-FORTRESS (4 services, 16 agents) est strictement défensif. | M | consignes défensives ; secret ou action offensive → refus déterministe | `nc/test_cyber.py::test_consignes_defensives`, `::test_detection_offensive` ; `sim/7` | FAIT |
| EF-16 | L'organigramme expose pour chaque agent son statut actif/suspendu et s'il appelle un modèle. | S | `GET /api/agents` : `statut`, `appelle_llm` | `nc/test_agents_gate.py::test_api_agents_expose_appelle_llm` | FAIT |

### 4.3 Classement GATE N0–N3 (GATE)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-17 | Le GATE classe chaque livrable N0–N3 par règles déterministes portant sur la consigne **et** le livrable. | M | 10 scénarios conformes | `sim/2` (10/10) ; `nc/test_fiche_technique.py::test_gate_livrable_dans_le_pipeline` | FAIT |
| EF-18 | L'avis du modèle ne peut que monter le niveau, jamais le descendre. | M | 0 violation O01 | `nc/test_agents_gate.py::test_llm_ne_peut_pas_descendre` ; `it/O01` (0) | FAIT |
| EF-19 | Tout montant engagé ou cité, et toute action engageante (envoyer, publier, signer, payer, supprimer, déployer, données sensibles), classe en N3, y compris conjugués, à l'impératif, en anglais, en lettres ou en M€. | M | 0 violation O02 sur 2 000 mini-scénarios | `nc/test_gate_audit.py` ; `it/O02` | **EN COURS** (298 violations, 8 défauts ; correctif en cours) |
| EF-20 | Une négation proche (« aucun paiement », « ne pas publier ») n'entraîne pas de N3, sans ouvrir de contournement. | S | cas niés non N3 ; « ne pas oublier de payer » reste N3 | `nc/test_gate_audit.py::test_negation_ignoree`, `::test_negation_ne_permet_pas_de_contourner` | FAIT |
| EF-21 | Les faux positifs techniques (« ligne de commande », « envoyez-moi », « pays ») ne déclenchent pas de N3. | S | cas listés non N3 | `nc/test_gate_audit.py::test_ligne_de_commande_ne_declenche_pas`, `::test_pays_n_est_pas_pay` ; `nc/test_fiche_technique.py::test_gate_envoi_au_proprietaire_pas_n3` | FAIT |
| EF-22 | Règles par service : droit N2 minimum (N3 si tiers), cyber N2 minimum (N3 si action production/notification), pilotage N3 si engagement, RSE N3 si communication externe. | M | classements attendus | `nc/test_nouveaux_services.py::test_gate_droit_minimum_n2_et_n3_pour_tiers`, `::test_gate_pilotage_engagement_n3`, `::test_gate_rse_publication_externe_n3` ; `nc/test_cyber.py::test_gate_cyber_n3_action_production_ou_notification` | FAIT |
| EF-23 | Un livrable ou une source suspecte d'injection ne peut pas être classé en dessous de N2. | M | 0 violation O08 | `nc/test_bouclier_integration.py::test_gate_classer_plancher_si_suspect` ; `it/O08` | **EN COURS** (22 violations) |
| EF-24 | Un livrable N3 n'est jamais exécuté sans validation humaine ; un refus ou une expiration n'entraîne aucune exécution. | M | 0 violation O03, O17 | `nc/test_pipeline.py::test_devis_n3_cree_decision` ; `it/O03`, `it/O17` (0) | EN COURS (O03 dérive d'O02) |

### 4.4 Niveaux de fonctionnement F1–F4 (FCT)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-25 | Quatre niveaux F1–F4 fixent fournisseur, budget de tokens, corrections, double contrôle, délai et coût maximal, depuis un fichier unique. | M | grille chargée ; `GET /api/fonctionnement` | `nc/test_fonctionnement.py::test_chargement_grille`, `::test_mesures_et_route_fonctionnement` | FAIT |
| EF-26 | Le niveau appliqué ne descend jamais ; chaque relèvement est motivé et journalisé. | M | `fonctionnement_raison` renseigné ; LEDGER `fonctionnement_releve` | `nc/test_fonctionnement.py::test_jamais_de_descente` ; `sim/3` | FAIT |
| EF-27 | Les services droit, pilotage et cybersécurité tournent au minimum en F3 ; un pré-classement N2/N3 relève F1 en F2. | M | 0 violation O14 | `nc/test_fonctionnement.py::test_plancher_f3_droit_et_pilotage`, `::test_releve_f1_vers_f2_par_gate_n2` ; `it/O14` (0) | FAIT |
| EF-28 | F4 (payant) ne démarre qu'après une décision N3 « Lancer en F4 — coût estimé X € » validée par le Décideur. | M | aucune dépense F4 sans validation (O15 = 0) | `nc/test_fonctionnement.py::test_f4_decision_n3_avant_lancement`, `::test_f4_refuse_par_le_proprietaire` ; `it/O15` (0) | FAIT |
| EF-29 | Si F4 est indisponible (budget 0, clé absente, budget restant insuffisant), la mission part en F3 (repli par défaut) ou est refusée. | M | message « F4 indisponible… » ; 422 sans repli | `nc/test_fonctionnement.py::test_f4_refuse_budget_zero_avec_repli_f3`, `::test_f4_refuse_sans_repli`, `::test_f4_budget_restant_insuffisant` | FAIT |
| EF-30 | Les plafonds de tokens, de délai et de coût arrêtent proprement la mission en conservant le livrable partiel et en proposant une relance. | M | statut `plafond_atteint`, livrable partiel présent | `nc/test_fonctionnement.py::test_delai_depasse_arret_propre`, `::test_budget_tokens_depasse_arret_propre`, `::test_f4_plafond_de_cout` | FAIT |
| EF-31 | Le coût d'un appel F4 est contrôlé **avant** l'appel (sortie maximale incluse) : jamais de dépassement. | M | coût cumulé ≤ 0,50 € | `nc/test_fonctionnement.py::test_f4_plafond_de_cout` | FAIT |
| EF-32 | Sans IA locale joignable, F1 est relevé en F2. | S | relèvement journalisé | `nc/test_fonctionnement.py::test_f1_sans_ia_locale_releve_en_f2` | FAIT |
| EF-33 | La consommation du mois (missions, tokens, coût, durée moyenne) est affichée par niveau. | S | `consommation[]` de `/api/fonctionnement` | `nc/test_fonctionnement.py::test_mesures_et_route_fonctionnement` | FAIT |

### 4.5 Qualité des livrables (QUA)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-34 | Le CHECKER rend un verdict JSON ; un refus renvoie à l'ANALYST dans la limite du niveau (F1 0, F2 1, F3 2, F4 3). | M | boucle respectée | `nc/test_pipeline.py::test_checker_refus_puis_acceptation` ; `nc/test_fonctionnement.py::test_f1_aucune_correction` | FAIT |
| EF-35 | En F3/F4, un second contrôle par le modèle local est exigé ; son indisponibilité est tracée, jamais silencieuse. | M | les deux doivent valider ; LEDGER `double_controle_indisponible` | `nc/test_fonctionnement.py::test_double_controle_f3_refus_puis_revision` ; `nc/test_modeles_roles.py::test_double_controle_trace_separement` | FAIT |
| EF-36 | La charte de chaque projet est contrôlée par du code avant le CHECKER (marques, termes interdits, mentions obligatoires, ton, inachevé). | M | violation bloquante → retour ANALYST ; jamais publié si non corrigé | `nc/test_charte.py::test_pipeline_bloque_puis_corrige`, `::test_pipeline_cas_reel_jamais_publie_si_non_corrige` ; `sim/4` | FAIT |
| EF-37 | Un livrable contenant « À COMPLÉTER » ou mélangeant les marques n'est jamais livré comme terminé s'il est destiné à publication. | M | 0 violation O10 | `nc/test_charte.py::test_inacheve_avertissement_hors_publication` ; `it/O10` | **EN COURS** (48 violations) |
| EF-38 | Tout livrable juridique se termine par « Information générale, ne remplace pas l'avis d'un avocat ». | M | mention présente une seule fois | `nc/test_nouveaux_services.py::test_mention_avocat_dans_sortie_juridique`, `::test_mention_non_dupliquee_et_absente_hors_droit` | FAIT |
| EF-39 | Au-delà des corrections permises, le directeur décide : une seule relance automatique (jamais en F4), reformulation ou échec. | M | `relance_auto` ≤ 1 ; `a_reformuler` avec suggestion | `nc/test_directeur.py` (5 tests) | FAIT |
| EF-40 | Le CHECKER peut recevoir un modèle différent de l'ANALYST (diversité) en cloud. | S | modèles distincts enregistrés par rôle | `nc/test_modeles_roles.py::test_diversite_par_defaut_en_cloud` | FAIT |
| EF-41 | Les modèles effectivement utilisés par rôle sont enregistrés sur la mission. | S | `modeles` non vide | `nc/test_modeles_roles.py::test_modeles_utilises_enregistres` | FAIT |

### 4.6 Décideur et cockpit (DEC)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-42 | Les décisions N3 se prennent **uniquement** dans le cockpit ; la clé API, la passerelle et n8n ne peuvent ni valider, ni refuser, ni réviser. | M | 403 via `/api` ; 0 violation O06 | `nc/test_bouclier_integration.py::test_api_ne_decide_plus_par_defaut` ; `nc/test_securite_cockpit.py::test_cle_api_inchangee_et_passerelle_sans_validation` ; `it/O06` (0) | FAIT |
| EF-43 | Chaque fiche N3 présente un résumé de 3 lignes, une recommandation, le coût estimé, un risque faible/moyen/élevé avec ses raisons, les sources et l'avis du CHECKER. | M | champs présents et explicables | `nc/test_decideur.py::test_carte_resume_et_infos`, `::test_risque_explicable` | FAIT |
| EF-44 | Une décision à risque élevé (montant ≥ 1 000 €, irréversible, production, données sensibles) exige le code Décideur à 6 chiffres. | M | 0 violation O04, O05 | `nc/test_decideur.py::test_code_exige_pour_risque_eleve`, `::test_risque_montant_et_action` ; `it/O04`, `it/O05` | **EN COURS** (369 et 135 violations : montants mal évalués) |
| EF-45 | 5 codes erronés verrouillent la validation 15 minutes ; un code non configuré interdit la validation à risque élevé. | M | HTTP 423 ; 403 | `nc/test_decideur.py::test_verrou_apres_cinq_erreurs`, `::test_code_non_configure_bloque_validation_risque_eleve` | FAIT |
| EF-46 | Toute action du Décideur mobile passe par une confirmation en deux temps (jeton à usage unique de 120 s). | M | sans jeton valide → 409 | `nc/test_decideur.py::test_confirmation_obligatoire` | FAIT |
| EF-47 | Un double clic n'applique la décision qu'une fois ; décision et expiration concurrentes sont exclusives. | M | 0 violation O18 | `nc/test_concurrence.py::test_une_seule_decision_gagne`, `::test_decision_et_expiration_concurrentes` ; `it/O18` (0) | FAIT |
| EF-48 | Une révision exige un motif (3–200 caractères) et est limitée à 2 par mission ; impossible pour un lancement F4 ou un plan de semaine. | M | 422 / 409 | `nc/test_decideur.py::test_revision_motif_obligatoire` ; `nc/test_fiche_technique.py::test_revision_relance_la_mission_et_limite` ; `nc/test_pilote.py::test_revision_impossible` | FAIT |
| EF-49 | Les décisions sont présentées par sessions (12 h 30 et 19 h par défaut) avec une seule notification par session, une notification immédiate si l'expiration est proche, un rappel 2 h avant le refus automatique. | S | 1 notification par session ; rappel | `nc/test_decideur.py::test_regroupement_par_session_et_notification_unique`, `::test_urgence_notification_immediate`, `::test_rappel_deux_heures_avant` | FAIT |
| EF-50 | Les notifications sont génériques : aucun contenu métier ni secret. | M | texte « Décision N3 en attente #id » + lien | `nc/test_decideur.py::test_contenu_ntfy_generique_et_lien` | FAIT |
| EF-51 | Une décision sans réponse après 24 h expire en refus par défaut ; au plus 15 fiches N3 sont créées par jour, le reste est mis en file. | M | statut `expiree` ; `n3_mise_en_file` | `nc/test_pipeline.py::test_expiration_n3_refus`, `::test_plafond_n3_mise_en_file` ; charge-200 S08 | FAIT (S08 à exécuter) |
| EF-52 | Le cockpit est installable sur Android (PWA), fonctionne hors ligne en mode dégradé et ne met jamais en cache décisions ni missions. | S | manifeste, service worker limité au statique, page hors ligne | `nc/test_pwa_resume.py::test_manifest`, `::test_service_worker_ne_cache_que_le_statique`, `::test_page_hors_ligne_et_pages_installables` | FAIT |
| EF-53 | Le cockpit permet : nouvelle mission, file des N3, missions et statuts, organigramme, journal, arrêt d'urgence, fonctionnement, note en un geste. | M | fonctions présentes et appelant `/cockpit/api` | `nc/test_api.py::test_cockpit_sans_cle` ; `sim/9` (13/13) | FAIT |
| EF-54 | Le Décideur peut noter un échantillon (20 %) des livrables en un geste (positif/négatif + motif). | C | avis enregistré ; négatif → signal de leçon ; positif → candidat exemple | `nc/test_avis.py` (6 tests) | FAIT |
| EF-55 | Un plan de la semaine par projet actif est proposé chaque lundi ; seules les missions cochées sont lancées (tout décoché par défaut). | S | 1 décision consolidée ; missions cochées uniquement | `nc/test_pilote.py::test_consolidation_une_seule_decision`, `::test_validation_lance_seulement_les_missions_cochees`, `::test_tout_decoche_par_defaut` ; `sim/10` | FAIT |
| EF-56 | Un résumé quotidien générique est envoyé à l'heure configurée, une fois par jour, désactivable. | C | 1 envoi/jour | `nc/test_pwa_resume.py::test_resume_quotidien_une_fois_par_jour`, `::test_resume_hors_fenetre_et_desactivable` | FAIT |

### 4.7 Journal LEDGER (LED)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-57 | Chaque événement significatif est journalisé dans un journal append-only chaîné. | M | aucune route de modification ; chaîne recalculable | `nc/test_pipeline.py::test_ledger_chaine_et_alteration` ; `it/O12` (0) | FAIT |
| EF-58 | Le journal est scellé par HMAC-SHA256 avec une clé hors base ; toute réécriture, mauvaise clé ou déclassement est détecté. | M | `GET /api/ledger/verifier` → `valide=false` sur altération | `nc/test_ledger_hmac.py` (6 tests) | FAIT |
| EF-59 | L'état du scellement est visible dans la santé du service. | M | `/api/sante` : `ledger_hmac`, `avertissements` | `nc/test_ledger_hmac.py::test_sans_cle_avertissement_et_sha256` | FAIT |
| EF-60 | L'EXECUTOR journalise chaque livrable avec `action_externe=false`. | M | LEDGER `livrable_enregistre` | `nc/test_pipeline.py::test_executor_aucune_action_externe` | FAIT |

### 4.8 Mémoire projet et mémoire collective (MEM)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-61 | Chaque projet a une mémoire consultable en plein texte (accents ignorés), alimentée par import, ajout manuel et résumé automatique des livrables. | M | recherche FTS ; import idempotent | `nc/test_memoire.py::test_ajout_et_recherche_api`, `::test_import_idempotent`, `::test_memorisation_automatique` | FAIT |
| EF-62 | COLLECTOR et CHECKER reçoivent les 3 extraits les plus pertinents dans un budget dépendant du niveau F. | M | extraits présents et bornés | `nc/test_memoire.py::test_collector_et_checker_recoivent_les_extraits`, `::test_budget_adapte_au_niveau` | FAIT |
| EF-63 | Chaque mission terminée ou décidée est archivée dans une archive immuable chaînée et vérifiable. | M | altération détectée | `nc/test_memoire_collective.py::test_archive_complete_chainee_et_verifiable`, `::test_archive_alteration_detectee` | FAIT |
| EF-64 | Les erreurs répétées deviennent des leçons proposées (≥ 3 missions distinctes) ; seules les leçons acceptées par le Décideur sont appliquées, dans une limite de 5 leçons / 800 caractères. | M | injection bornée et conditionnelle | `nc/test_memoire_collective.py::test_extraction_deterministe_et_seuil`, `::test_injection_seulement_si_acceptee_et_bornee` ; `sim/5` | FAIT |
| EF-65 | Une leçon qui fait baisser la qualité de plus de 10 points est suspendue automatiquement. | M | statut `suspendue` | `nc/test_memoire_collective.py::test_suspension_sur_regression`, `::test_pas_de_suspension_si_stable` | FAIT |
| EF-66 | Les livrables validés ou bien notés deviennent des exemples (≤ 3 par service), filtrés (secret, charte, injection), retirables. | S | exemple injecté ≤ 1 500 car. | `nc/test_exemples.py` (7 tests) | FAIT |
| EF-67 | Avant activation d'une leçon, d'un exemple, d'une charte ou de modèles, un test fantôme rejoue K missions la nuit, sans effet de bord, et compare. | S | rejeux exclus des listes ; gain < 0 → déconseillé | `nc/test_fantome.py` (8 tests) | FAIT |
| EF-68 | Accepter/rejeter une leçon et effacer une archive ne se font que dans le cockpit. | M | absent de `/api` | `nc/test_memoire_collective.py::test_decisions_reservees_au_cockpit`, `::test_effacement_cockpit_seulement` | FAIT |
| EF-69 | La compaction par paliers (chaud/tiède/froid) de l'archive est intégrée aux tâches de nuit, à la recherche, à l'effacement RGPD et à la sauvegarde. | S | 5 points d'intégration branchés ; vérification Merkle verte | `nc/test_compaction.py` (22 tests, module seul) | **EN COURS** (module non branché) |

### 4.9 Passerelle MCP (BRG)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-70 | La passerelle expose 20 outils MCP (mémoire, tâches, messages, passations, projets, mémoire collective, leçons, missions, décisions en lecture, journal) en « Streamable HTTP ». | M | `tools/list` = 20 outils conformes au protocole | `nb/test_bridge.py::test_tools_list_schemas` ; `protocole/tests/test_protocole.py::test_entrees_mcp_synchronisees_avec_la_passerelle` | FAIT |
| EF-71 | Chaque IA a son propre jeton qui identifie l'auteur de chaque écriture. | M | auteur = identité du jeton | `nb/test_bridge.py::test_jeton_chemin_et_entete_auteur`, `::test_jeton_absent_ou_faux` | FAIT |
| EF-72 | La mémoire commune est versionnée ; « oublier » archive sans effacer et n'est permis qu'à l'auteur ou au propriétaire. | M | versions conservées ; refus pour un tiers | `nb/test_bridge.py::test_fts_et_versions`, `::test_memoire_oublier_droits` | FAIT |
| EF-73 | Une tâche ne peut être prise que par une IA à la fois. | S | second `tache_prendre` refusé | `nb/test_bridge.py::test_verrou_de_tache` | FAIT |
| EF-74 | Une IA peut confier une mission au noyau et suivre son statut, mais jamais valider une décision. | M | `mothership_mission` → id ; aucun outil de décision | `nb/test_bridge.py::test_mothership_mission`, `::test_mothership_mission_fonctionnement` | FAIT |
| EF-75 | Le journal de la passerelle est en ajout seul et ne contient aucun contenu. | M | UPDATE/DELETE refusés par la base | `nb/test_bridge.py::test_journal_append_only` | FAIT |
| EF-76 | Une page `/bridge` en lecture seule, lisible sur téléphone, montre l'activité commune. | C | page servie derrière le mot de passe du cockpit | `nb/test_bridge.py::test_page_bridge` | FAIT |

### 4.10 Veille (VEI)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-77 | La veille lit uniquement les flux et API publics d'un catalogue de sources (322), en respectant `robots.txt`, un délai ≥ 2 s par site et des quotas. | M | tests de politesse verts | `veille/tests/test_politesse_robots.py`, `test_catalogue.py` | FAIT |
| EF-78 | Le stockage dépend de la licence (intégral, extrait, métadonnées, agrégé) et chaque fiche porte un niveau de confiance A–D. | M | règles appliquées | `veille/tests/test_v2_documents_licences.py`, `test_fiches.py` | FAIT |
| EF-79 | Les fiches pertinentes sont fournies au COLLECTOR, citées avec source, confiance et date, encapsulées et filtrées par le bouclier ; une veille absente ne bloque jamais une mission. | M | fiches dans le message du COLLECTOR | `nc/test_veille.py::test_collector_recoit_les_fiches_citees_et_encapsulees`, `::test_veille_absente_ou_desactivee_ne_bloque_rien` | **EN COURS** (test rouge) |
| EF-80 | Une information issue seulement d'une source de confiance D n'est jamais présentée comme un fait. | M | refus déterministe puis correction ; 0 violation O09 | `nc/test_veille.py::test_fiche_d_presentee_comme_fait_refusee_puis_corrigee`, `::test_affirmations_d` ; `it/O09` | **EN COURS** (test rouge ; 21 violations) |

### 4.11 Sécurité IA (SIA)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-81 | Tout contenu externe (veille, documents, connaissances, mémoire) est nettoyé, scoré et encapsulé ; score ≥ 60 → rejeté ; ≥ 30 → alerte au CHECKER et au Décideur. | M | politique à trois issues | `nc/test_bouclier.py::test_politique_trois_issues_et_journal` ; `nc/test_bouclier_integration.py::test_extraits_encapsules_alerte_checker_et_plancher_n2` ; `sim/6` | FAIT |
| EF-82 | Aucun secret ni canari n'est stocké en clair (consigne, étapes, livrables, archive, mémoire, exemples, export). | M | 0 violation O07 | `nc/test_bouclier_integration.py::test_secret_masque_pour_tous_les_services` ; `nc/test_cyber.py::test_secret_persistant_jamais_stocke` ; `it/O07` | **EN COURS** (secret de la consigne stocké en clair : défaut O07-956bdf2b) |
| EF-83 | L'attaque simulée mensuelle atteint ≥ 95 % de blocage au niveau attendu avec 0 faux positif bloquant. | M | rapport mensuel | `securite-ia/resultats/2026-11.md` (40/40, 0/10 FP) | FAIT |

### 4.12 Exploitation (EXP)

| ID | Exigence | Prio | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| EF-84 | L'installation se fait en 3 commandes depuis le terminal web, est relançable sans régénérer les secrets et n'affiche ni ne journalise aucun secret. | M | `install.sh` idempotent ; `install.log` sans secret | revue de `install.sh` ; CI `scripts` (shellcheck) | FAIT (pas de test automatique d'installation) |
| EF-85 | La sauvegarde quotidienne produit des copies cohérentes des bases, chiffre le `.env`, garde les 7 dernières, avec option de copie hors serveur. | M | dossier daté complet | revue `backup.sh` ; exercice de restauration | FAIT |
| EF-86 | La restauration vérifie la sauvegarde avant toute coupure, met de côté les données actuelles et contrôle la santé après redémarrage. | M | `/api/sante` OK après restauration | revue `restore.sh` ; `exercice-restauration.sh` | FAIT |
| EF-87 | Un exercice de restauration mensuel restaure la dernière sauvegarde sur P2 sans toucher P1 et vérifie missions, LEDGER, HMAC, `.env` et passerelle. | M | code de sortie 0, rapport daté | `exercice-restauration.sh` (codes 0–4) ; `sim/8` | FAIT |
| EF-88 | La veille cyber hebdomadaire collecte la configuration sans secret et lance deux missions CYBER-FORTRESS en F3. | S | collecte filtrée ; idempotente dans la semaine | `automatisations/tests/test_veille_cyber.py` (7 tests) | FAIT |
| EF-89 | Les livrables terminés sont exportés vers le QG par un webhook signé HMAC, avec reprise et abandon après 10 tentatives ; rien n'est envoyé sans secret. | C | signature vérifiable ; statut `echec` visible | `nc/test_export_qg.py` (7 tests) | FAIT |
| EF-90 | Le monodépôt se sépare en 4 dépôts privés (nexus-bridge, nexus-agents, mini-mothership, nexus-mothership) en conservant l'historique, avec licence propriétaire, CHANGELOG et étiquette v1.0.0. | S | 4 dépôts générés localement, rien n'est poussé | `outils-depots/separer.sh` (CI shellcheck) | EN COURS (script prêt, non exécuté) |
| EF-91 | Le Protocole NEXUS v1 décrit tous les objets échangés, est versionné en SemVer et validé sur des réponses réelles. | M | `valider.py --verifier-schemas` et tests verts | `protocole/tests/test_protocole.py` | **EN COURS** (3 erreurs : générateur bloqué par EF-42) |

## 5. Exigences non fonctionnelles

| ID | Catégorie | Exigence | Critère d'acceptation | Vérification | Statut |
|---|---|---|---|---|---|
| ENF-01 | Performance | Une mission F2 standard est livrée rapidement avec le fournisseur cloud gratuit. | p90 F2 ≤ 10 min (cible jumeau S2 : 82 s) | jumeau (S2) ; banc d'essai F2 | EN COURS (simulé ; mesure réelle à faire) |
| ENF-02 | Performance / capacité | La plateforme absorbe 200 % du pic nominal (30 missions/h) sans perte, doublon ni blocage. | critères de base de charge-200 tenus sur S01–S25 | `charge-200/charge.py` | PRÉVU (aucun résultat) |
| ENF-03 | Performance | L'API répond vite hors inférence. | p95 des routes de lecture ≤ 500 ms sous 200 % | charge-200 S16 | PRÉVU |
| ENF-04 | Disponibilité | Les services redémarrent seuls et reprennent les missions après un arrêt brutal. | `restart: unless-stopped` ; 0 perte après `kill -9` ×2 | `nc/test_file_reprise.py` ; charge-200 S18 | EN COURS |
| ENF-05 | Disponibilité | Une panne du cloud gratuit ne bloque pas le service. | bascule locale journalisée ; score robuste jumeau ≥ 90 | `nc/test_llm_cloud.py::test_bascule_locale_sur_429` ; jumeau S9/S17 | FAIT |
| ENF-06 | Disponibilité | Les données sont restaurables (RPO ≤ 24 h). | sauvegarde < 24 h ; exercice mensuel OK | `exercice-restauration.sh` | FAIT |
| ENF-07 | Sécurité | Seul Caddy est exposé ; ports 80/443 (+ 8443–8445 en complet). | `docker compose config` ; aucun autre `ports:` | CI `configuration` | FAIT |
| ENF-08 | Sécurité | Conteneurs applicatifs durcis : non root (UID 10001), `cap_drop ALL`, `read_only`, `no-new-privileges`, limites mémoire/CPU. | présent dans `docker-compose.yml` | CI `configuration` ; revue | FAIT |
| ENF-09 | Sécurité | Le cockpit résiste au CSRF et au contournement du proxy. | requêtes sans `X-Cockpit-Auth`, sans `X-Cockpit`, d'une autre origine ou non JSON → 403 | `nc/test_securite_cockpit.py` (8 tests) | FAIT |
| ENF-10 | Sécurité | Aucun secret dans le dépôt, les journaux, les sorties d'API ou la mémoire commune. | contrôle `secrets` du test system = 0 ; jetons masqués | `nb/test_bridge.py::test_jeton_jamais_dans_les_logs`, `::test_refus_secrets` ; `nc/test_llm_cloud.py::test_cle_absente_des_sorties_api` | EN COURS (contrôle du dépôt non exécuté) |
| ENF-11 | Sécurité | La passerelle limite le débit (60/min/identité), la taille (8 Ko/champ, 64 Ko/requête) et les lots (≤ 10). | 429, 413, 400 | `nb/test_bridge.py::test_limite_de_debit`, `::test_taille_max`, `::test_lot_trop_grand_refuse` | FAIT |
| ENF-12 | RGPD | Le droit à l'effacement supprime le contenu d'une mission partout (archive, mémoire, exemples, leçons, avis, étapes, mission, décisions, fichier) en ne gardant qu'une trace sans contenu au LEDGER. | 0 violation O13 | `nc/test_bouclier_integration.py::test_effacement_rgpd_en_cascade` ; `it/O13` | **EN COURS** (191 violations) |
| ENF-13 | RGPD | Minimisation et rétention : veille 180 j (sociale 30 j, anonymisée), sauvegardes 7 j, notifications sans contenu. | paramètres appliqués | `veille/tests/test_v2_social_web_tendances.py` ; revue | FAIT |
| ENF-14 | Coût | Le coût total mensuel (VPS, sécurité, IA) reste dans le budget, IA gratuite par défaut. | ≤ 90 € TTC/mois ; dépense IA = 0 € si `BUDGET_MONTHLY_EUR=0` | `nc/test_llm_cloud.py::test_garde_fou_anthropic_budget_zero`, `::test_cout_nul_par_defaut` ; jumeau (coût) | FAIT (garde-fous) |
| ENF-15 | Coût | La dépense IA payante est plafonnée par mission (0,50 €) et par mois (`BUDGET_MONTHLY_EUR`), contrôlée avant chaque appel. | jamais de dépassement | `nc/test_pipeline.py::test_budget_mensuel_payant_refuse` ; `nc/test_fonctionnement.py::test_f4_plafond_de_cout` | FAIT |
| ENF-16 | Maintenabilité | Le code est testé automatiquement en CI à chaque modification ; tous les tests sont verts avant fusion. | CI verte | `.github/workflows/ci.yml` | EN COURS (5 tests rouges/erreurs) |
| ENF-17 | Maintenabilité | Les règles métier sont paramétrables sans code : `fonctionnement.yaml`, `projets.yaml`, chartes, fiches agents, variables d'environnement documentées. | `docs/technique/07-configuration.md` exhaustif | revue | FAIT |
| ENF-18 | Maintenabilité | Les évolutions de schéma de base sont additives (migrations douces) ; le protocole suit SemVer. | aucune colonne retirée en 1.x | `nc/test_fonctionnement.py::test_migration_colonnes_fonctionnement` ; `protocole/tests/test_protocole.py::test_version_semver` | FAIT |
| ENF-19 | Portabilité | Le kit s'installe sur Ubuntu 22.04/24.04 avec Docker, sur tout VPS 2 vCPU / 8 Go ; le noyau fonctionne sous SQLite et PostgreSQL. | `docker compose config` MVP et complet | CI `configuration` ; `nc/test_mvp.py::test_sqlite_fichier_en_wal` | FAIT (PostgreSQL non testé en CI) |
| ENF-20 | Accessibilité | Le cockpit et le Décideur mobile sont utilisables au doigt et en contraste suffisant (cibles ≥ 44 px, thème sombre, une décision par écran). | audit WCAG 2.1 AA sans défaut bloquant | audit manuel | PRÉVU (aucun audit formel) |
| ENF-21 | Mobile | Toutes les opérations courantes (décider, créer une mission, sauvegarder, restaurer, changer un secret) se font depuis un téléphone Android. | procédures du README réalisables au terminal web et au cockpit PWA | `README.md` § 13 ; `sim/9` | FAIT |
| ENF-22 | Qualité | La porte de qualité du SYFER Test System est VERTE avant toute mise en production. | `syfer_test.py porte` → code 0 | `syfer-test-system/` | **EN COURS** (porte estimée ROUGE) |
| ENF-23 | Langue | Toute l'interface, les messages, la documentation et les livrables sont en français. | revue | revue | FAIT |

## 6. Contraintes

| N° | Contrainte | Conséquence technique |
|---|---|---|
| C1 | **Budget ≈ 90 € TTC/mois** tout compris ; borne de calcul 150 €/mois dans le jumeau et le score | choix d'infrastructure validé par le jumeau (coût p90) ; `cout_nul_eur=150` dans `syfer-test-system/config/ponderation.json` |
| C2 | **IA gratuite par défaut** (Ollama Cloud offre gratuite, IA locale) ; `install.sh` ne propose jamais d'option payante | `BUDGET_MONTHLY_EUR=0`, `LLM_EUR_PAR_1K_TOKENS=0` ; Anthropic refusé au démarrage sans budget |
| C3 | **F4 payante plafonnée et validée** : ≤ 0,50 €/mission, budget mensuel explicite, décision N3 préalable, jamais par relance automatique | `fonctionnement.yaml`, `fonctionnement.disponibilite_f4` |
| C4 | **VPS Hostinger** (KVM 2 actuel : 2 vCPU, 8 Go, 100 Go), administration par le terminal web hPanel, pare-feu hPanel | partitions de 20 Go ; P1 ≤ 5 Go RAM / 1,5 vCPU ; aucun outil local requis |
| C5 | **Un seul humain** décide | pas de multi-utilisateur ; décisions réservées au cockpit |
| C6 | **Aucune action externe automatique** | EXECUTOR déterministe sans effet externe |
| C7 | **Licence propriétaire**, dépôts privés | `separer.sh` ajoute une LICENSE propriétaire à chaque dépôt |
| C8 | Logiciels libres et gratuits uniquement pour l'infrastructure | Caddy, Docker, Ollama, SQLite, n8n, ntfy, Uptime Kuma |
| C9 | Conformité RGPD, droit d'auteur (veille), AI Act (transparence des contenus générés) | effacement en cascade, stockage selon licence, mention de l'origine IA dans les livrables publiés (à charge du Décideur) |
| C10 | Exploitable depuis Android | PWA, notifications ntfy, procédures en copier-coller |

## 7. Livrables

| N° | Livrable | Emplacement | Statut |
|---|---|---|---|
| L1 | Code source nexus-core, nexus-bridge, veille, scripts | dépôt `v2` | FAIT |
| L2 | 93 fiches agents, 7 chartes, registre de projets, grille F1–F4 | `nexus-core/` | FAIT |
| L3 | Protocole NEXUS v1 (schémas, validateur, exemples) | `protocole/` | EN COURS (exemples à régénérer) |
| L4 | Kit d'installation (compose MVP et complet, Caddyfile, `.env.example`, scripts) | racine | FAIT |
| L5 | Dispositif de test (suites, simulations, itérations, charge, banc, attaque, jumeau, test system, CI) | dossiers dédiés | FAIT (outillage) ; résultats charge et banc à produire |
| L6 | Documentation technique (10 documents) | `docs/technique/` | FAIT (cette révision) |
| L7 | Cahier des charges (ce document) | `docs/cahier-des-charges/` | à valider |
| L8 | Documentation opérationnelle, structurelle et business | `docs/operationnel/`, `docs/structurel/`, `docs/business/` | autres équipes |
| L9 | 4 dépôts privés séparés, étiquetés v1.0.0 | sortie de `separer.sh` | PRÉVU |
| L10 | Rapport de porte de qualité VERTE et rapport PDF du test system | `syfer-test-system` | PRÉVU |

## 8. Critères de recette

La recette de SYFER V2 est prononcée par le Décideur lorsque **la porte de qualité est VERTE** (`python3 syfer-test-system/syfer_test.py tout` puis `porte` → code 0), soit l'ensemble des critères bloquants de `syfer-test-system/config/porte.json` :

| Critère | Seuil | Exigences couvertes |
|---|---|---|
| Tests unitaires | 100 % verts | toutes les EF vérifiées par pytest, ENF-16 |
| Simulations | ≥ 99 % | EF-05, EF-17, EF-25 à EF-27, EF-36, EF-64, EF-81, EF-15, EF-87, EF-53, EF-55 |
| Itérations | 0 défaut critique ouvert | EF-02, EF-19, EF-23, EF-24, EF-37, EF-44, EF-80, EF-82, ENF-12 |
| Attaque simulée | ≥ 95 % et 0 faux positif bloquant | EF-83, EF-81 |
| Secrets | 0 dans le dépôt | ENF-10 |
| Banc d'essai | pas de baisse > 5 points vs passage précédent | EF-65, ENF-01 |
| Charge 200 % | sans perte de données | ENF-02, ENF-03, ENF-04, EF-04, EF-51 |

Compléments exigés hors porte : exercice de restauration réussi sur le VPS (EF-87), CI verte (ENF-16), vérification manuelle de l'installation sur un VPS neuf (EF-84), revue d'accessibilité du cockpit (ENF-20).

État au 4 novembre 2026 : **non recevable** (porte estimée ROUGE : tests rouges, défauts critiques ouverts, charge et banc non mesurés).

## 9. Matrice de traçabilité exigences ↔ tests

### 9.1 Par épreuve

| Épreuve | Fichiers / méthode | Exigences vérifiées |
|---|---|---|
| `nexus-core/tests/test_api.py` | API, cockpit, devis N3 | EF-01, EF-06, EF-53 |
| `test_concurrence.py` | atomicité | EF-02, EF-47 |
| `test_file_reprise.py` | file et reprise | EF-03, EF-04, ENF-04 |
| `test_prime_audit.py` | routage | EF-05 |
| `test_fiche_technique.py` | assemblage, GATE, révision | EF-07, EF-17, EF-21, EF-48 |
| `test_pipeline.py` | pipeline, kill switch, N3, LEDGER, EXECUTOR | EF-08, EF-24, EF-34, EF-51, EF-57, EF-60, ENF-15 |
| `test_projets.py` | registre et filtres | EF-09, EF-10, EF-11 |
| `test_agents_gate.py` | 93 agents, GATE | EF-12, EF-13, EF-16, EF-18 |
| `test_cyber.py` | CYBER-FORTRESS | EF-15, EF-22, EF-82 |
| `test_gate_audit.py`, `test_gate_commande.py` | déclencheurs N3 | EF-19, EF-20, EF-21 |
| `test_nouveaux_services.py` | droit, pilotage, RSE | EF-22, EF-38 |
| `test_fonctionnement.py` | F1–F4 | EF-25 à EF-35, ENF-15, ENF-18 |
| `test_charte.py` | charte | EF-36, EF-37 |
| `test_directeur.py` | escalade | EF-39 |
| `test_modeles_roles.py` | modèles par rôle | EF-35, EF-40, EF-41 |
| `test_decideur.py` | Décideur | EF-43 à EF-46, EF-48 à EF-50 |
| `test_pwa_resume.py` | PWA, résumé | EF-52, EF-56 |
| `test_avis.py` | note en un geste | EF-54 |
| `test_pilote.py` | plan de la semaine | EF-48, EF-55 |
| `test_ledger_hmac.py` | scellement | EF-58, EF-59 |
| `test_memoire.py` | mémoire projet | EF-61, EF-62 |
| `test_memoire_collective.py` | archive, leçons | EF-63, EF-64, EF-65, EF-68 |
| `test_exemples.py` | exemples | EF-66 |
| `test_fantome.py` | test fantôme | EF-67 |
| `test_compaction.py` | compaction (module) | EF-69 |
| `test_veille.py` | intégration veille | EF-79, EF-80 |
| `test_bouclier.py`, `test_bouclier_integration.py` | bouclier | EF-23, EF-42, EF-81, EF-82, ENF-12 |
| `test_securite_cockpit.py` | anti-CSRF | EF-42, ENF-09 |
| `test_llm_cloud.py` | fournisseurs, coûts | ENF-05, ENF-10, ENF-14 |
| `test_export_qg.py` | export QG | EF-89 |
| `test_mvp.py` | SQLite, ntfy | ENF-19 |
| `nexus-bridge/tests/test_bridge.py` | passerelle | EF-70 à EF-76, ENF-10, ENF-11 |
| `protocole/tests/test_protocole.py` | protocole | EF-14, EF-70, EF-91, ENF-18 |
| `veille/tests/*` (206) | veille | EF-77, EF-78, ENF-13 |
| `automatisations/tests/test_veille_cyber.py` | veille cyber | EF-88 |
| `simulations/` (103 scénarios) | méthodes 1–10 | EF-05, EF-15, EF-17, EF-25–27, EF-36, EF-53, EF-55, EF-64, EF-81, EF-87 |
| `iterations-100/` (18 oracles) | propriétés | EF-02, EF-18, EF-19, EF-23, EF-24, EF-27, EF-28, EF-37, EF-42, EF-44, EF-47, EF-57, EF-80, EF-82, ENF-12 |
| `securite-ia/` | attaque simulée | EF-83 |
| `charge-200/` (25 scénarios) | capacité, pannes | EF-04, EF-51, ENF-02, ENF-03, ENF-04 |
| `jumeau-numerique/` | capacité, coût | ENF-01, ENF-05, ENF-14 |
| `banc-essai/` | qualité réelle | ENF-01, EF-65 |
| `exercice-restauration.sh` | restauration | EF-85, EF-86, EF-87, ENF-06 |
| CI `configuration`, `scripts` | compose, Caddy, YAML, shellcheck | EF-14, EF-84, ENF-07, ENF-08, ENF-16, ENF-19 |
| `syfer-test-system/` | porte | ENF-22 |

### 9.2 Synthèse

| Indicateur | Valeur |
|---|---|
| Exigences fonctionnelles | 91 (EF-01 à EF-91) |
| Exigences non fonctionnelles | 23 (ENF-01 à ENF-23) |
| **Total** | **114** |
| Statut FAIT (dont 6 avec réserve : EF-02, EF-04, EF-51, EF-84, ENF-14, ENF-19) | 94 |
| Statut EN COURS | 17 |
| Statut PRÉVU | 3 |
| Exigences sans test automatique (vérification par revue ou exercice) | EF-84, EF-85, EF-86, ENF-17, ENF-20, ENF-21, ENF-23 |

## 10. Risques

| N° | Risque | Probabilité | Impact | Mesures | Propriétaire |
|---|---|---|---|---|---|
| R1 | Contournement du GATE (formulation imprévue) → livrable engageant classé N0–N2 | moyenne | élevé | règles déterministes, plancher par service, iterations-100, EXECUTOR sans action externe | développement |
| R2 | Injection indirecte via veille ou mémoire | moyenne | élevé | bouclier, encapsulation, plancher N2, CHECKER, décision humaine | développement |
| R3 | Dépense IA involontaire | faible | moyen | budget 0 par défaut, F4 soumis à N3, contrôle avant appel | Décideur |
| R4 | Quotas ou panne d'Ollama Cloud gratuit (limites non publiées) | moyenne | moyen | repli local, score robuste du jumeau, F1 local | exploitation |
| R5 | Qualité insuffisante du modèle local 3B | élevée (S1L : 55 %) | moyen | cloud gratuit, F3 double contrôle, banc d'essai, option 7B (KVM 4) | Décideur |
| R6 | Surcharge du Décideur (trop de N3, expirations) | moyenne | moyen | sessions groupées, plafond 15/jour, risque explicable, réglage des faux positifs | Décideur |
| R7 | Perte de `LEDGER_HMAC_KEY` ou de `BACKUP_PASSPHRASE` | faible | élevé | `.env` chiffré en sauvegarde, consigne de noter la phrase hors du VPS | Décideur |
| R8 | Fuite d'un jeton de passerelle (URL copiée) | moyenne | moyen | un jeton par IA, masquage, rotation par `install.sh`, aucun pouvoir de décision | Décideur |
| R9 | Données en clair dans la copie Google Drive | moyenne | moyen | documenté ; chiffrement des bases à ajouter | exploitation |
| R10 | Évolutions concurrentes par plusieurs agents de développement → régressions | élevée | moyen | CI, porte de qualité, protocole SemVer | développement |
| R11 | Saturation disque P1 (20 Go) | faible | élevé | rotation 7 sauvegardes, journaux bornés, compaction | exploitation |
| R12 | Écart entre simulation (jumeau) et réalité | moyenne | moyen | mesures réelles banc + recalage | développement |
| R13 | Dépendance à un seul VPS (pas de redondance) | certaine | moyen | sauvegardes hors serveur, exercice mensuel, restauration documentée | exploitation |
| R14 | Non-conformité RGPD (trace résiduelle après effacement) | moyenne | moyen | cascade d'effacement, minimisation du LEDGER à arbitrer | Décideur |

## 11. Glossaire

| Terme | Définition |
|---|---|
| ADR | décision d'architecture documentée |
| ANALYST | agent qui rédige le livrable brouillon |
| Bouclier | module déterministe de défense contre l'injection de consignes |
| Canari | marqueur fictif servant à détecter une exfiltration |
| Charte | règles éditoriales et de marque d'un projet, contrôlées par du code |
| CHECKER | agent contrôleur qui rend un verdict JSON |
| COLLECTOR | agent qui structure les éléments fournis |
| Cockpit | interface web du Décideur |
| Compaction | réduction de l'archive ancienne en blocs compressés par paliers |
| Décideur | l'unique humain qui valide les décisions importantes |
| Double contrôle | second CHECKER exécuté avec le modèle local (F3/F4) |
| EXECUTOR | agent déterministe qui enregistre le livrable sans action externe |
| F1–F4 | niveaux de fonctionnement (effort, modèle, coût) |
| GATE | agent de classement N0–N3 |
| HMAC | code d'authentification de message à clé secrète (SHA-256) |
| Jumeau numérique | simulation de SYFER (SYFER ÉCHO) |
| LEDGER | journal append-only chaîné |
| Leçon | règle apprise d'erreurs répétées, appliquée après acceptation |
| MCP | Model Context Protocol, protocole d'outils pour les IA |
| N0–N3 | niveaux de décision (N3 = accord du Décideur obligatoire) |
| Oracle | propriété vérifiée automatiquement sur chaque mini-scénario |
| Porte de qualité | ensemble de critères bloquants avant mise en production |
| PRIME | agent de routage vers un service |
| PWA | application web installable |
| SENTINEL | agent d'arrêt d'urgence |
| Test fantôme | rejeu sans effet de missions passées pour évaluer une variante |
| VPS | serveur privé virtuel |
