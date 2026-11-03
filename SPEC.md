# SPEC — Kit « Mini NEXUS MOTHERSHIP » pour VPS Hostinger KVM 2

Cible : Ubuntu 22.04/24.04, 2 vCPU, 8 Go RAM, ~100 Go disque. Accès via le terminal web hPanel (root). Langue de toute l'interface et des messages : français.
Contraintes : gratuit / open source uniquement ; aucune clé API payante requise ; aucune action externe engageante exécutée automatiquement.

## Arborescence du dépôt (racine = nexus-mothership-kit/)

```
partitions.sh           # crée les 4 partitions P1..P4 (agent INFRA)
install.sh              # installation en une commande (agent INFRA)
uninstall.sh            # arrêt + suppression des conteneurs (garde les volumes sauf --purge)
backup.sh               # dump PostgreSQL + export n8n vers ./backups/
docker-compose.yml      # agent INFRA (MVP par défaut ; profils local / complet)
docker-compose.complet.yml # agent INFRA (surcouche du mode complet)
Caddyfile.mvp           # agent INFRA (cockpit seul, 80/443)
Caddyfile.complet       # agent INFRA (+ 8443/8444/8445)
.env.example            # agent INFRA (toutes les variables, sans secrets)
n8n/workflows/*.json    # agent INFRA
nexus-core/             # agent CORE (service Python)
README.md               # agent INFRA (guide FR)
```

## Services Docker (réseau interne `nexus`)

| Service | Image | Exposé |
|---|---|---|
| caddy | caddy:2.8 | 80, 443 (cockpit), 8443 (n8n), 8444 (Uptime Kuma), 8445 (ntfy) — HTTPS Let's Encrypt sur `${NEXUS_HOST}` (nom d'hôte du VPS, ex. srvXXXX.hstgr.cloud) |
| postgres | pgvector/pgvector:pg16 | interne |
| redis | redis:7-alpine | interne |
| n8n | n8nio/n8n:1.64.3 | interne (via caddy :8443) ; base PostgreSQL (schéma `n8n`) |
| ollama | ollama/ollama:0.3.14 | interne ; modèle par défaut `qwen2.5:3b` (variable `NEXUS_MODEL`) |
| nexus-core | build ./nexus-core | interne :8000 (via caddy :443) |
| uptime-kuma | louislam/uptime-kuma:1 | interne (via caddy :8444) |
| ntfy | binwiederhier/ntfy:v2.11.0 | interne (via caddy :8445) ; topic `${NTFY_TOPIC}` |

Limites (mem_limit / cpus, partition P1 ≤ 5 Go et ≤ 1,5 vCPU) : ollama 2944m/0.8, postgres 640m/0.2, n8n 640m/0.15, nexus-core 384m/0.1, nexus-bridge 128m/0.1, redis 128m/0.05, uptime-kuma 128m/0.03, caddy 64m/0.05, ntfy 48m/0.02 (total 5104 Mo, 1,5 vCPU). Projet compose `p1-nexus`, réseau `p1-nexus-net`. Données persistantes en bind mounts `./data/<service>` (aucun volume nommé).
Cockpit (:443) protégé par basic auth Caddy (`COCKPIT_USER` / hash de `COCKPIT_PASSWORD`). nexus-core exige aussi l'en-tête `X-Nexus-Key: ${NEXUS_API_KEY}` pour l'API (le cockpit servi par nexus-core l'injecte côté serveur : les routes `/cockpit/*` sont protégées par Caddy, l'API `/api/*` par la clé).

## Variables d'environnement (.env)

NEXUS_HOST, ACME_EMAIL, POSTGRES_USER=nexus, POSTGRES_PASSWORD, POSTGRES_DB=nexus, REDIS_URL=redis://redis:6379/0,
NEXUS_API_KEY, COCKPIT_USER=decideur, COCKPIT_PASSWORD, COCKPIT_PASSWORD_HASH (bcrypt pour Caddy),
N8N_ENCRYPTION_KEY, N8N_BASIC_USER, N8N_BASIC_PASSWORD,
NEXUS_MODEL=qwen2.5:3b, OLLAMA_URL=http://ollama:11434,
LLM_PROVIDER=ollama (valeurs possibles : ollama | anthropic — anthropic désactivé tant que ANTHROPIC_API_KEY vide),
ANTHROPIC_API_KEY=, ANTHROPIC_MODEL=,
BUDGET_MONTHLY_EUR=0, BUDGET_TASK_TOKENS=6000,
N3_TIMEOUT_HOURS=24, N3_DAILY_CAP=15,
NTFY_URL=http://ntfy, NTFY_TOPIC=nexus-<aléatoire>,
DATABASE_URL=postgresql+psycopg://nexus:${POSTGRES_PASSWORD}@postgres:5432/nexus

## nexus-core (agent CORE)

Python 3.12, FastAPI, SQLAlchemy 2, psycopg 3, httpx, PyYAML, uvicorn. Dockerfile slim, utilisateur non root. Tests pytest avec SQLite et LLM factice (aucun réseau).

### Agents (fichiers YAML dans nexus-core/agents/) — Mini Mothership = 93 rôles
93 = noyau (5) + 8 directeurs + 20 services × quadrant COLLECTOR / ANALYST / CHECKER / EXECUTOR (80 agents).
- Noyau (5) : NEXUS-PRIME, NEXUS-GATE, NEXUS-SENTINEL, NEXUS-LEDGER, NEXUS-BUDGET.
- 8 directeurs : DIR-STRATEGIE, DIR-CROISSANCE, DIR-CREATION, DIR-TECH, DIR-OPERATIONS, DIR-SAVOIR, DIR-AGENTOPS, DIR-IMPACT.
- 7 services pilotes d'origine (1 par direction) :
  - LEX-GUARD/conformite (Stratégie : conformité RGPD/AI Act, relecture CGV)
  - REVENUE-CORE/propositions (Croissance : brouillons de devis et propositions commerciales)
  - CONTENT-ARENA/redaction (Création : articles, posts, newsletters)
  - CODE-CORE/revue (Tech : revue de code et specs)
  - OPS-CORE/projets (Opérations : plans de projet, checklists)
  - R&D-PARADOX/veille (Savoir : synthèse de veille à partir de textes fournis)
  - AGENT-FACTORY/evaluation (Agent-Ops : évalue les sorties d'autres agents)
- 9 services spécialisés : CODE-CORE/conception, DESIGN-SYSTEM/ui, LEX-GUARD/droit-france | droit-europe | droit-international, PILOT-CORE/etudes | pilotage (Opérations), GREEN-CORE/environnement | rse (direction DIR-IMPACT).
- Département CYBER-FORTRESS (direction Tech, DIR-TECH) — 4 services, 16 agents :
  - CYBER-FORTRESS/audit (revue de sécurité du code, des configurations Docker/Caddy/SSH/pare-feu et des dépendances ; OWASP Top 10 / ASVS, hygiène ANSSI, CIS ; constat = gravité, preuve, correction)
  - CYBER-FORTRESS/veille (CVE, avis CERT-FR sur la pile du kit ; priorisation, mises à jour à planifier)
  - CYBER-FORTRESS/conformite (NIS2 si applicable, RGPD art. 32, notification CNIL 72 h, politique de mots de passe et de clés, sauvegardes 3-2-1, PCA/PRA)
  - CYBER-FORTRESS/incident (qualification, confinement, éradication, reprise, retour d'expérience, rotation des jetons et clés)
  - Règles : posture strictement défensive (jamais d'exploitation, de malware, de contournement d'authentification ni d'attaque d'un tiers) ; les agents proposent, n'exécutent rien ; aucun secret dans les livrables ; références citées seulement si certaines (« référence à vérifier » sinon). Garde-fou déterministe (`app/cyber.py`) avant le CHECKER : secret ou action offensive → refus et secret masqué avant tout stockage. GATE : N2 minimum, N3 si action sur la production (pare-feu, comptes, clés, redémarrage, suppression, ports) ou notification à une autorité. Fonctionnement : F3 minimum.
- Format YAML d'un agent : `id, nom, role (prime|gate|sentinel|ledger|budget|directeur|collector|analyst|checker|executor), direction, departement, service, mission, consignes (prompt système FR), outils_autorises (liste), modele (optionnel)`.

### Modèle de données (tables)
missions(id, titre, consigne, service, statut[recue|en_cours|en_attente_n3|validee|refusee|revision|terminee|echouee|suspendue|plafond_atteint], niveau[N0..N3], cree_le, maj_le, livrable_texte, tokens, cout_eur, projet, fonctionnement_demande, fonctionnement, fonctionnement_raison, repli_f3, tokens_entree, tokens_sortie, duree_s, revisions, attente)
etapes(id, mission_id, agent_id, role, entree, sortie, verdict, tokens, cree_le)
decisions(id, mission_id, niveau, objet[livrable|lancement_f4], resume, recommandation, cout_estime_eur, risque[faible|moyen|eleve], sources, avis_checker, statut[en_attente|validee|refusee|revision|expiree], cree_le, decide_le, commentaire)
ledger(id, horodatage, acteur, action, mission_id, details_json, hash_prec, hash) — chaîne de hachage SHA-256, append-only (aucune route de suppression/modification).
etat(cle, valeur) — kill switch (`kill:grille`, `kill:dir:<x>`, `kill:agent:<id>`), compteurs budget.

### Pipeline d'une mission (POST /api/missions {titre, consigne, service?, montant_eur?, action?})
1. SENTINEL vérifie le kill switch → si actif, statut `suspendue`, journal.
2. PRIME choisit le service (paramètre `service` sinon classement par mots-clés puis LLM) et le directeur concerné.
3. COLLECTOR structure les éléments fournis (pas d'accès web dans la mini-version ; il liste ce qui manque).
4. ANALYST produit le livrable brouillon.
5. CHECKER (prompt différent, température basse) rend un verdict JSON {ok: bool, problemes: [...]}. Si refus → retour ANALYST, 2 boucles max, puis `echouee` + escalade N2.
6. GATE classe la mission N0–N3 par **règles déterministes** (le LLM ne peut que monter le niveau, jamais le descendre) : N3 si montant_eur > 0, action ∈ {envoyer_client, publier, signer, mise_en_production, depense, supprimer, donnees_sensibles}, ou mots-clés (contrat, devis, paiement, facture, mot de passe, données personnelles, publier, envoyer) ; N2 si publication sur charte / production de code ; N1 sinon pour un livrable ; N0 pour une simple lecture/synthèse interne.
7. N3 → crée une `decision` (fiche : résumé 3 lignes, recommandation, coût, risque, sources, avis CHECKER), statut mission `en_attente_n3`, notification ntfy, plafond N3_DAILY_CAP par jour (au-delà : mise en file, message clair). N0–N2 → EXECUTOR « exécute ».
8. EXECUTOR mini-version : n'effectue AUCUNE action externe ; il enregistre le livrable final (table + fichier /data/livrables/<id>.md) et prépare l'action pour qu'un humain ou un workflow n8n la réalise.
9. LEDGER journalise chaque étape (acteur, action, coût). BUDGET compte les tokens ; dépassement BUDGET_TASK_TOKENS → arrêt de la mission ; si LLM_PROVIDER payant et dépense du mois ≥ BUDGET_MONTHLY_EUR → refus.
10. Tâche de fond toutes les 10 min : décisions en attente depuis > N3_TIMEOUT_HOURS → `expiree` = refus par défaut + journal.

### Niveaux de fonctionnement F1..F4 (`nexus-core/fonctionnement.yaml`, source unique)
Distincts des niveaux de décision N0–N3. Chaque niveau fixe : fournisseur, budget_tokens, revisions_max (boucles de correction ANALYST après refus CHECKER), double_controle (2ᵉ CHECKER avec le modèle local, les deux doivent valider), llm_max_chars, num_ctx, delai_max_s, cout_max_eur.
F1 Éclair (ollama local, 6 000, 0, non, 4 000, 4096, 180 s, 0 €) · F2 Standard (LLM_PROVIDER courant, 20 000, 1, non, 12 000, 8192, 600 s, 0 € ; BUDGET_TASK_TOKENS / LLM_MAX_CHARS / OLLAMA_NUM_CTX restent la base de F2) · F3 Renforcé (courant, 40 000, 2, oui, 16 000, 8192, 1 200 s, 0 €) · F4 Expert (anthropic, ANALYST/CHECKER claude-sonnet-5-5, COLLECTOR/EXECUTOR/autres claude-haiku-5-5, 80 000, 3, oui, 24 000, 1 800 s, ≤ 0,50 € ; tarifs $/MTok en config, EUR_PAR_USD défaut 0.92).
- Choix : champ `fonctionnement` (F1..F4) de POST /api/missions, défaut NEXUS_FONCTIONNEMENT_DEFAUT (F2) ; champ `repli_f3` (bool, défaut true).
- Planchers (ne fait que monter, raison tracée dans `fonctionnement_raison` et LEDGER) : GATE N2+ (pré-classement par règles, puis GATE final) → F1 relevé en F2 ; IA locale injoignable → F1 relevé en F2 ; LEX-GUARD/droit-*, PILOT-CORE/* et CYBER-FORTRESS/* → F3 minimum.
- F4 : indisponible si BUDGET_MONTHLY_EUR=0, ANTHROPIC_API_KEY absente ou budget mensuel restant < estimation → repli F3 (« F4 indisponible : budget IA à 0 € — mission lancée en F3 ») si `repli_f3`, sinon 422. Disponible → décision N3 `objet=lancement_f4` « Lancer en F4 — coût estimé X € » ; aucune exécution avant validation (révision impossible ; refus → `refusee`). Disponibilité revérifiée au démarrage.
- Exécution : plafonds tokens / délai (chrono global) / coût (contrôlé avant et après chaque appel) → statut `plafond_atteint`, livrable partiel conservé, proposition de relance au niveau supérieur. Jamais de dépassement silencieux.
- Mesures par mission : fonctionnement_demande / fonctionnement, fonctionnement_raison, tokens_entree, tokens_sortie, cout_eur, duree_s, revisions ; LEDGER : fonctionnement_applique, fonctionnement_releve, plafond_atteint, mission_bilan.

### API (préfixe /api, clé X-Nexus-Key)
GET /api/sante (+ fonctionnement_defaut) · GET /api/fonctionnement (grille + consommation du mois par niveau : missions, tokens, €, durée moyenne) · POST /api/missions · GET /api/missions · GET /api/missions/{id} (avec étapes) · GET /api/decisions?statut=en_attente · POST /api/decisions/{id}/valider|refuser|reviser {commentaire} · POST /api/killswitch {portee: grille|direction|agent, cible?, actif: bool} · GET /api/ledger?limit= · GET /api/ledger/verifier (vérifie la chaîne) · GET /api/agents · GET /api/budget.
Traitement des missions : en tâche de fond (BackgroundTasks ou file Redis simple) pour ne pas bloquer l'appel ; la réponse renvoie l'id et le statut.

### Cockpit (/cockpit, HTML servi par nexus-core, sans dépendance externe)
Français, utilisable sur téléphone Android : file des décisions N3 avec boutons Valider / Refuser / Demander une révision, liste des missions et statuts, formulaire « Nouvelle mission », organigramme des 93 agents (actif/suspendu), journal LEDGER, bouton d'arrêt d'urgence avec confirmation intégrée à la page. Les appels du cockpit passent par des routes /cockpit/api/* qui réutilisent la logique sans exiger la clé (Caddy protège /cockpit par basic auth). `/` redirige vers `/cockpit`.

## n8n (agent INFRA)
Workflows importés automatiquement par install.sh (`n8n import:workflow --separate --input=/workflows`) :
1. « NEXUS — Mission par webhook » : Webhook POST → HTTP Request vers http://nexus-core:8000/api/missions (en-tête X-Nexus-Key depuis variable d'env `$env.NEXUS_API_KEY`) → réponse.
2. « NEXUS — Veille quotidienne » : Cron 08:00 Europe/Paris → mission R&D-PARADOX/veille (désactivé par défaut).
3. « NEXUS — Rapport du soir » : Cron 19:00 → GET /api/decisions?statut=en_attente + /api/missions → message ntfy récapitulatif.
n8n : N8N_ENCRYPTION_KEY, DB_TYPE=postgresdb, GENERIC_TIMEZONE=Europe/Paris, N8N_HOST=${NEXUS_HOST}, N8N_PORT=5678, N8N_PROTOCOL=https, WEBHOOK_URL=https://${NEXUS_HOST}:8443/, N8N_BLOCK_ENV_ACCESS_IN_NODE=false, NEXUS_API_KEY transmis.

## install.sh (agent INFRA)
Idempotent, en français, `set -euo pipefail`. Étapes : vérifie root + Ubuntu ; affiche RAM/disque ; installe Docker + plugin compose s'ils manquent (dépôt officiel) ; détecte `NEXUS_HOST` (hostname -f, confirmation possible via argument `--host`) ; demande ACME_EMAIL (argument `--email` ou invite) ; génère .env avec secrets aléatoires (openssl rand) et le hash bcrypt via `docker run --rm caddy:2.8 caddy hash-password` ; vérifie ufw sans le modifier (voir ci-dessous) ; `docker compose up -d --build` ; `docker compose exec ollama ollama pull $NEXUS_MODEL` ; importe les workflows n8n ; mission de test « Rédige une checklist de démarrage du Mothership » (service OPS-CORE/projets) ; affiche les URL, identifiants et la commande pour revoir les identifiants (`cat /srv/p1/nexus-mothership/.env`). Répertoire d'installation : /srv/p1/nexus-mothership. Journal d'installation : /srv/p1/nexus-mothership/install.log.
**Pare-feu : install.sh ne modifie JAMAIS ufw ni le pare-feu Hostinger** ; il détecte l'état d'ufw, affiche les commandes `ufw allow` manquantes et rappelle d'ouvrir 80, 443, 8443, 8444, 8445 dans hPanel > Sécurité > Pare-feu. `--host` par défaut : `hostname -f`, ou `srv2113898.hstgr.cloud` si ce n'est pas un FQDN. install.sh vérifie que /srv/p1 est un point de montage (sinon propose partitions.sh).

## Partitions (agent INFRA)
VPS réel : Ubuntu 24.04, `srv2113898.hstgr.cloud`, 2 vCPU / 8 Go / 100 Go (~95 Go libres).
`partitions.sh` (root, idempotent, `--size 20G`, `--dry-run`) : 4 fichiers image ext4 `/srv/images/p1.img … p4.img` (fallocate, `mkfs.ext4 -F -L nexus-pN`), montés en loop sur `/srv/p1 … /srv/p4`, ajoutés à /etc/fstab avec `loop,nofail,defaults` (sauvegarde `/etc/fstab.bak-<date>`, pas de doublon). Refus si espace libre sur / < (4 × taille) + 10 Go (90 Go pour 20G). Le disque système n'est pas modifié.

| Partition | Usage | RAM | vCPU | Disque |
|---|---|---|---|---|
| P1 | Mini Mothership (/srv/p1/nexus-mothership) | 5 Go | 1,5 | 20 Go |
| P2, P3, P4 | libres, réservées à de futurs projets (compose `pN-xxx`, réseau `pN-xxx-net`, bind mounts sous /srv/pN) | 1 Go chacune | ~0,15 chacune | 20 Go chacune |

nexus-core : les livrables sont écrits dans /data/livrables (bind mount ./data/nexus-core). Le conteneur tourne en non-root : install.sh donne le dossier à l'uid/gid de l'image.

## Modes MVP / complet et IA gratuite (agent INFRA)
- **MVP (défaut)** : caddy + nexus-core (SQLite `sqlite:////data/nexus.db`), ports 80/443, Caddyfile.mvp. Profil `local` = ollama (repli). Limites : ollama 3584m/1.1, nexus-core 384m/0.2, nexus-bridge 128m/0.1, caddy 64m/0.1 (4160 Mo, 1,5 vCPU ; 576 Mo sans repli).
- **Complet** (`install.sh --complet`) : `COMPOSE_PROFILES=complet[,local]` + `COMPOSE_FILE=docker-compose.yml:docker-compose.complet.yml` (PostgreSQL, Redis, n8n, Uptime Kuma, ntfy, Caddyfile.complet, ports 8443–8445 ; 5104 Mo / 1,5 vCPU).
- **IA, tout gratuit** : par défaut Ollama Cloud (`LLM_PROVIDER=ollama_cloud`, `NEXUS_MODEL=gemma4:31b`, `OLLAMA_CLOUD_URL=https://ollama.com`, clé `OLLAMA_API_KEY` saisie par `read -rs`, testée sur /api/tags) + repli local `LLM_FALLBACK=ollama`, `NEXUS_MODEL_LOCAL=qwen2.5:3b` (profil `local`). `--sans-repli` → `LLM_FALLBACK=aucun`, pas d'ollama. Sans clé ou clé refusée → `LLM_PROVIDER=ollama`, `NEXUS_MODEL=qwen2.5:3b`. `--local` force le local. `BUDGET_MONTHLY_EUR=0`, `LLM_EUR_PAR_1K_TOKENS=0`. Anthropic : payant, jamais proposé (variables vides).
- `--sans-partition` : installation de test dans /opt/nexus-mothership. Réseau `p1-nexus-net` non interne (sortie HTTPS vers ollama.com). `/api/sante` public (healthcheck sans clé). Données nexus-core : chown 10001:10001.
- Démarrage : `git clone -b nexus-mothership-kit --depth 1 https://github.com/redkards/espacetravail-public /srv/p1/nexus-mothership` (kit à la racine de la branche), puis `bash partitions.sh` (qui replace le contenu existant de /srv/p1 dans la partition) et `bash install.sh`.

## nexus-bridge — passerelle Claude · ChatGPT · Gemini (agent BRIDGE)
Serveur MCP « Streamable HTTP » (spécification 2025-06-18, réponses JSON, sans session ni SSE ; GET/DELETE → 405), Python 3.12 + FastAPI, JSON-RPC implémenté à la main (initialize, notifications/*, ping, tools/list, tools/call ; lots acceptés). Image python:3.12-slim, UID 10001, 1 worker, 128m/0.1, données `./data/nexus-bridge/bridge.db` (SQLite WAL + FTS5).
- Authentification : un jeton par identité `BRIDGE_TOKEN_CLAUDE|CHATGPT|GEMINI|PROPRIETAIRE` (≥ 32 caractères, générés par install.sh) via `Authorization: Bearer` ou chemin `/mcp/<jeton>` ; comparaison à temps constant ; le jeton fixe l'auteur de chaque écriture ; jamais journalisé (`/mcp/***`, journal d'accès uvicorn désactivé).
- Outils : memoire_ecrire/chercher/lire/oublier (versionnée, archivage par l'auteur ou le propriétaire), tache_creer/lister/prendre (verrou)/mettre_a_jour, message_envoyer/messages_lire (lus par destinataire), passation_ecrire/derniere, projets_lister (GET /api/projets, repli liste fixe), mothership_mission (POST /api/missions avec `projet`) / mothership_statut / mothership_decisions_en_attente (lecture seule, aucune validation N3), journal_lister (append-only, sans contenu).
- Codes projets : paradoxx, nexus, poker-winners, poker-feeling, redkards, top-solver, youtube-poker-winner, freelance-ia, esct-boxe, turf, divers.
- Garde-fous : 8 Ko par champ, 60 appels/min par jeton (429 + Retry-After), refus des contenus ressemblant à des secrets (clés API, mots de passe, cartes — Luhn —, jetons du Mothership).
- Caddy : `/mcp*` → nexus-bridge sans basic auth ; `/bridge*` → page HTML lecture seule avec le basic auth du cockpit. `bridge-connecteurs.sh` affiche les URL à coller dans chaque IA.

