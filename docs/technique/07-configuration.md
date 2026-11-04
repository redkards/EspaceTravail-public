# 07 — Configuration

Toute la configuration passe par des **variables d'environnement** (fichier `.env` généré par `install.sh`, modèle sans secret `.env.example`) et par quelques **fichiers YAML** versionnés. Ce document ne contient **aucune valeur secrète** : la colonne « Défaut » indique « généré » pour un secret créé par `install.sh`.

Légende : **Oblig.** = obligatoire pour démarrer (oui / non / complet = obligatoire en mode complet) ; **Sens.** = sensible (secret : ne jamais afficher, journaliser, versionner ni coller dans une IA).

`cfg()` relit l'environnement à chaque appel (`nexus-core/app/config.py`) ; une modification de `.env` est prise en compte par `docker compose up -d` (recréation du conteneur). Les variables marquées `:?` dans `docker-compose.yml` font échouer le démarrage si elles manquent.

## 1. Accès public, Docker et partitions

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `COMPOSE_PROJECT_NAME` | nom du projet compose (préfixe partition) | `p1-nexus` | oui | non |
| `COMPOSE_PROFILES` | profils actifs : vide (cloud seul), `local`, `complet`, `complet,local` | `local` | non | non |
| `COMPOSE_FILE` | `docker-compose.yml:docker-compose.complet.yml` en mode complet | — | complet | non |
| `NEXUS_HOST` | nom d'hôte public (`srvXXXX.hstgr.cloud`) : TLS, origine anti-CSRF, liens ntfy | `hostname -f` | **oui** | non |
| `ACME_EMAIL` | e-mail Let's Encrypt | demandé | **oui** | non (donnée personnelle) |
| `NEXUS_BIND_IP` | adresse IPv4 de publication des ports Caddy | détectée (`0.0.0.0` à défaut) | non | non |
| `NEXUS_PART_BASE`, `NEXUS_FSTAB`, `NEXUS_SYSTEMD_DIR` | chemins de test de `partitions.sh` | `/srv`, `/etc/fstab`, `/etc/systemd/system` | non | non |
| `NEXUS_RESOLVE` | résolution forcée `hote:443:<adresse>` pour les scripts lancés sur le VPS | posé par les crons | non | non |

## 2. Cockpit, API et Décideur

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `NEXUS_API_KEY` | clé de l'API `/api/*` (`X-Nexus-Key`) ; aussi utilisée par nexus-bridge | généré | **oui** | **oui** |
| `COCKPIT_USER` | identifiant basic auth | `decideur` | non | non |
| `COCKPIT_PASSWORD` | mot de passe du cockpit (en clair dans `.env`, pour le Décideur) | généré | oui | **oui** |
| `COCKPIT_PASSWORD_HASH` | hash bcrypt pour Caddy (entre apostrophes) | généré | **oui** | **oui** |
| `COCKPIT_INTERNAL` | secret interne Caddy → nexus-core (`X-Cockpit-Auth`, 64 hex) ; vide = cockpit verrouillé | généré | **oui** | **oui** |
| `COCKPIT_CODE_DECIDEUR` | code à 6 chiffres exigé pour valider un risque élevé ; vide = validation à risque élevé impossible | généré une fois | non (fortement recommandé) | **oui** |
| `NEXUS_API_PEUT_DECIDER` | `1` autorise l'API à décider : **tests uniquement** | `0` | non | non |
| `NEXUS_SEUIL_RISQUE_ELEVE_EUR` | montant (engagé ou cité) à partir duquel le risque est élevé | `1000` | non | non |
| `NEXUS_SESSIONS_N3` | heures des sessions de décision (Europe/Paris) | `12:30,19:00` | non | non |
| `N3_TIMEOUT_HOURS` | expiration d'une décision N3 = refus par défaut | `24` | non | non |
| `N3_DAILY_CAP` | nombre maximal de fiches N3 créées par jour | `15` | non | non |
| `NEXUS_RESUME_QUOTIDIEN` | heure du résumé ntfy (`off` pour désactiver) | `19:00` | non | non |

## 3. Noyau nexus-core

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `DATABASE_URL` | base : SQLite (MVP) ou `postgresql+psycopg://…` (complet) | `sqlite:////data/nexus.db` | non | **oui** si PostgreSQL (contient le mot de passe) |
| `NEXUS_DATA_DIR` | dossier des données (livrables, base) | `/data` | non | non |
| `NEXUS_AGENTS_DIR` | dossier des fiches agents | `<image>/agents` | non | non |
| `NEXUS_PROJETS_FILE` | registre des projets | `/config/projets.yaml` (monté) | non | non |
| `NEXUS_FONCTIONNEMENT_FILE` | grille F1–F4 | `<image>/fonctionnement.yaml` | non | non |
| `NEXUS_CHARTES_DIR` | dossier de chartes supplémentaire (prioritaire) | vide (`/config/chartes` monté) | non | non |
| `NEXUS_CONNAISSANCES_DIR` | fiches de connaissances importées au démarrage | `/connaissances` | non | non |
| `NEXUS_MEMOIRE_AUTO` | `1` = résumé automatique des livrables dans la mémoire projet | `1` | non | non |
| `NEXUS_MAX_MISSIONS` | missions simultanées (file FIFO) | vide = 1 en local, 2 sinon | non | non |
| `NEXUS_TACHES_FOND` | `0` désactive les boucles de fond (tests) | `1` | non | non |
| `REDIS_URL` | file Redis (réservée, non utilisée) | vide (MVP) | non | non |
| `TZ` | fuseau des conteneurs | `Europe/Paris` | non | non |

## 4. Modèles de langage et niveaux de fonctionnement

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `LLM_PROVIDER` | `ollama` (local) · `ollama_cloud` · `anthropic` (refusé si budget 0) · `fake` (tests) | `ollama` | non | non |
| `LLM_FALLBACK` | repli si le fournisseur échoue : `ollama` ou `aucun` | `ollama` | non | non |
| `NEXUS_MODEL` | modèle principal | `qwen2.5:3b` (local) / `gemma4:31b` (cloud) | non | non |
| `NEXUS_MODEL_CHECKER` | modèle dédié au CHECKER | = `NEXUS_MODEL` | non | non |
| `NEXUS_MODEL_LOCAL` | modèle local (F1, repli, double contrôle) | `qwen2.5:3b` | non | non |
| `NEXUS_MODELES_ROLES` | modèle par rôle : `role=modele` ou `role@fournisseur=modele` | vide | non | non |
| `NEXUS_MODELES_CLOUD` | modèles cloud autorisés (diversité ANALYST/CHECKER) | `gemma4:31b,gpt-oss:120b` | non | non |
| `OLLAMA_URL` | Ollama local | `http://ollama:11434` | non | non |
| `OLLAMA_CLOUD_URL` | Ollama Cloud | `https://ollama.com` | non | non |
| `OLLAMA_API_KEY` | clé Ollama Cloud (validée par appel authentifié) | vide | non | **oui** |
| `OLLAMA_NUM_CTX` | contexte Ollama (base F2) | `8192` | non | non |
| `LLM_MAX_CHARS` | taille max d'un message (base F2, min 1 000) | `12000` | non | non |
| `LLM_TIMEOUT_S` | délai max d'un appel | `180` | non | non |
| `ANTHROPIC_API_KEY` | clé Anthropic (F4 payant ; jamais proposée) | vide | non | **oui** |
| `ANTHROPIC_MODEL` | modèle Anthropic hors F4 | `claude-3-5-haiku-latest` | non | non |
| `NEXUS_FONCTIONNEMENT_DEFAUT` | niveau F par défaut | `F2` | non | non |
| `BUDGET_TASK_TOKENS` | budget de tokens d'une mission (base F2) | `20000` | non | non |
| `BUDGET_MONTHLY_EUR` | budget IA mensuel ; `0` = aucune dépense, F4 indisponible | `0` | non | non |
| `LLM_EUR_PAR_1K_TOKENS` | tarif appliqué à Ollama Cloud (0 = gratuit) | `0` | non | non |
| `EUR_PAR_USD` | conversion des tarifs F4 | `0.92` | non | non |

## 5. Mémoire collective, test fantôme, pilote, banc

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `NEXUS_ARCHIVE_DIR` | archive immuable | `/data/archive` | non | non |
| `NEXUS_EXEMPLES_SEUIL` | note à partir de laquelle un livrable devient exemple | `4` | non | non |
| `NEXUS_LECONS_SEUIL` | occurrences (missions distinctes) pour proposer une leçon | `3` | non | non |
| `NEXUS_LECONS_MESURES_MIN` | mesures du banc avant contrôle de régression | `3` | non | non |
| `NEXUS_LECONS_BAISSE` | baisse (points) qui suspend une leçon | `10` | non | non |
| `NEXUS_LECONS_REFORMULER` | `1` = reformulation des leçons par LLM (marquée) | `0` | non | non |
| `NEXUS_ECHANTILLON_NOTE` | part des missions proposées à la note en un geste | `0.2` | non | non |
| `NEXUS_FANTOME_K` | missions rejouées par test fantôme | `5` | non | non |
| `NEXUS_FENETRE_NUIT` | fenêtre des tâches lourdes (Paris) | `01:00-06:00` | non | non |
| `NEXUS_PILOTE_HEBDO` | heure du pilote du lundi (`off` pour désactiver) | `07:30` | non | non |
| `NEXUS_BANC_RESULTATS` | tableau des notes du banc (régression des leçons) | `/banc/tableau.json` | non | non |
| `NEXUS_BANC_DIR` | dossier du banc (notation des rejeux) | `/banc-essai` | non | non |

## 6. Veille (lecture par nexus-core et collecteur)

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `NEXUS_VEILLE` | `0` désactive la veille dans les missions | `1` | non | non |
| `NEXUS_VEILLE_DIR` | code de veille (`recherche.py`) | `/veille` | non | non |
| `NEXUS_VEILLE_MAX` | fiches maximum par mission (1–10) | `5` | non | non |
| `VEILLE_DB` | base de veille | `/veille-donnees/veille.db` (conteneur) ; `data/veille/veille.db` (cron) | non | non |
| `VEILLE_LECTURE_SEULE` | ouverture en lecture seule | `1` (nexus-core) | non | non |
| `VEILLE_CONTACT` | contact ajouté au User-Agent (page de contact, pas d'e-mail personnel) | « contact du propriétaire à configurer » | recommandé | non |
| `VEILLE_CATALOGUE` | catalogue des sources | `veille/catalogue.yaml` | non | non |
| `VEILLE_DELAI_DOMAINE` | délai minimal entre deux requêtes d'un même site (s, ≥ 2) | `2` | non | non |
| `VEILLE_RETENTION_JOURS` | rétention des fiches | `180` | non | non |
| `VEILLE_RETENTION_SOCIAL_JOURS` | rétention des fiches sociales | `30` | non | non |
| `VEILLE_JOURNAL` | journal du collecteur | `veille/journal/veille.log` | non | non |
| `VEILLE_POIDS` | poids calibrés du classement | `veille/calibration/poids.json` | non | non |
| `VEILLE_NEXUS_CORE` | chemin de nexus-core (projets, bouclier) | `../nexus-core` | non | non |
| `VEILLE_SANS_BOUCLIER` | désactive le bouclier à l'ingestion (**tests uniquement**) | vide | non | non |
| `VEILLE_WEB` | `1` active la recherche Web à la demande (avec `config.yaml actif: true`) | vide (désactivée) | non | non |
| `VEILLE_WEB_ETAT` | état des quotas Web | `journal/web_quotas.json` | non | non |
| `VEILLE_JETON` | jeton facultatif du micro-service de recherche | vide | non | **oui** |

## 7. Compaction **[EN COURS]** (module non branché)

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `NEXUS_COMPACTION_DIR` | dossier compact | `<NEXUS_ARCHIVE_DIR>/compact` | non | non |
| `COMPACTION_TIEDE_JOURS` / `COMPACTION_FROID_JOURS` | seuils des paliers | `30` / `180` | non | non |
| `COMPACTION_BLOC_N` / `COMPACTION_BLOC_N_FROID` | enregistrements max par bloc | `256` / `1024` | non | non |
| `COMPACTION_BLOC_OCTETS` | taille non compressée max d'un bloc | `1000000` | non | non |
| `COMPACTION_PLAFOND_CONNAISSANCES` | plafond de connaissances « auto » par projet (0 = aucun) | `0` | non | non |
| `COMPACTION_RETIRER_SOURCES` | `1` supprime les `AAAA-MM.jsonl.gz` compactés | `0` | non | non |
| `COMPACTION_VACUUM_JOUR` | jour du VACUUM complet (6 = dimanche) | `6` | non | non |
| `COMPACTION_ALGO_TIEDE` | `lzma` au lieu de zlib pour le tiède | `zlib` | non | non |
| `COMPACTION_FTS_DETAIL` | `full` pour le classement bm25 | `none` | non | non |
| `COMPACTION_AGREGATS_JOURS` | granularité journalière des agrégats | `90` | non | non |

## 8. Passerelle nexus-bridge

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `BRIDGE_TOKEN_CLAUDE` | jeton de Claude (≥ 32 car.) | généré | non (identité absente sinon) | **oui** |
| `BRIDGE_TOKEN_CHATGPT` | jeton de ChatGPT | généré | non | **oui** |
| `BRIDGE_TOKEN_GEMINI` | jeton de Gemini | généré | non | **oui** |
| `BRIDGE_TOKEN_PROPRIETAIRE` | jeton du propriétaire (archive toute mémoire) | généré | non | **oui** |
| `BRIDGE_LIMITE_PAR_MINUTE` | appels par minute et par identité | `60` | non | non |
| `BRIDGE_DB` | base de la passerelle | `/data/bridge.db` | non | non |
| `BRIDGE_PROJETS` | liste de codes projets de repli | 11 codes intégrés | non | non |
| `BRIDGE_ORIGINES` | origines HTTP autorisées (vide = toutes) | vide | non | non |
| `NEXUS_CORE_URL` | URL interne de nexus-core | `http://nexus-core:8000` | non | non |

## 9. Notifications, export, sauvegardes

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `NTFY_URL` | serveur ntfy | `https://ntfy.sh` (MVP) ; `http://ntfy` forcé en complet | non | non |
| `NTFY_TOPIC` | sujet secret `nexus-<16 hex>` (vide = aucune notification) | généré | complet | **oui** (quiconque le connaît lit les alertes) |
| `NTFY_USER` / `NTFY_PASSWORD` | compte de lecture ntfy (mode complet) | `proprietaire` / généré | complet | mot de passe **oui** |
| `NEXUS_WEBHOOK_QG` | URL du webhook QG (vide = export désactivé) | vide | non | non (URL non secrète) |
| `NEXUS_WEBHOOK_SECRET` | secret HMAC de l'export (sans lui, rien n'est envoyé) | généré | non | **oui** |
| `BACKUP_PASSPHRASE` | phrase gpg qui chiffre `env.sauvegarde` | généré | oui | **oui** (à noter hors du VPS) |
| `BACKUP_AGE_RECIPIENT` | clé publique age (remplace gpg si présente) | vide | non | non (clé publique) |
| `NEXUS_RCLONE_REMOTE` | remote rclone pour `--hors-serveur` | `gdrive` | non | non |

## 10. Mode complet (PostgreSQL, n8n)

| Variable | Rôle | Défaut | Oblig. | Sens. |
|---|---|---|---|---|
| `POSTGRES_USER` / `POSTGRES_DB` | compte et base | `nexus` / `nexus` | complet | non |
| `POSTGRES_PASSWORD` | mot de passe PostgreSQL | généré | complet | **oui** |
| `N8N_ENCRYPTION_KEY` | chiffrement des identifiants n8n | généré | complet | **oui** |
| `N8N_BASIC_USER` | barrière Caddy de n8n | `admin` | complet | non |
| `N8N_BASIC_PASSWORD` / `N8N_BASIC_PASSWORD_HASH` | mot de passe et hash bcrypt | généré | complet | **oui** |

Variables fixées dans `docker-compose.yml` pour n8n (non modifiables par `.env`) : `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, `N8N_DIAGNOSTICS_ENABLED=false`, `EXECUTIONS_DATA_MAX_AGE=336`, `NODE_OPTIONS=--max-old-space-size=512`, `WEBHOOK_URL=https://${NEXUS_HOST}:8443/`.

## 11. Fichiers de configuration

| Fichier | Contenu | Rechargement | Monté |
|---|---|---|---|
| `nexus-core/projets.yaml` | 11 projets : code, `actif` (pilote), nom, description, services conseillés | `GET /api/projets?recharger=1` | `/config/projets.yaml:ro` |
| `nexus-core/fonctionnement.yaml` | grille F1–F4, tarifs $/MTok, `eur_par_usd`, `part_entree_estimation` | redémarrage | dans l'image |
| `nexus-core/chartes/*.yaml` | `_commun` + 6 chartes de projet | redémarrage | `/config/chartes:ro` |
| `nexus-core/agents/*.yaml` | 93 fiches | redémarrage (image) | dans l'image |
| `veille/catalogue.yaml` | 322 sources | prochain passage du collecteur | `/veille:ro` |
| `Caddyfile.mvp` / `Caddyfile.complet` | routage, en-têtes, journaux | `docker compose restart caddy` | `/etc/caddy/Caddyfile:ro` |
| `syfer-test-system/config/porte.json`, `ponderation.json` | critères de la porte de qualité, poids du score | à chaque passage | — |

Projets actifs pour le pilote hebdomadaire : `nexus`, `poker-winners`, `poker-feeling`, `redkards`, `top-solver` ; inactifs : `paradoxx`, `youtube-poker-winner`, `freelance-ia`, `esct-boxe`, `turf`, `divers`.
