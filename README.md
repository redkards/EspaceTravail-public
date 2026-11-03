# Mini NEXUS MOTHERSHIP — guide d'installation (VPS Hostinger KVM 2)

## Démarrage MVP en 3 commandes

Dans **hPanel > VPS > Terminal** (déjà root), copiez-collez :

```bash
git clone -b nexus-mothership-kit --depth 1 https://github.com/redkards/espacetravail-public /srv/p1/nexus-mothership
cd /srv/p1/nexus-mothership
bash partitions.sh && cd /srv/p1/nexus-mothership && bash install.sh
```

- `partitions.sh` crée les 4 partitions de 20 Go et replace automatiquement le kit cloné **dans** la partition P1 (d'où le second `cd`).
- `install.sh` vous demande votre e-mail, puis votre **clé Ollama Cloud** (gratuite, saisie masquée). Sans clé, il continue avec l'IA locale.
- À la fin, un encadré affiche l'adresse du cockpit et **la commande pour voir le mot de passe** (`grep COCKPIT_PASSWORD .env`) : aucun secret n'est affiché ni écrit dans `install.log`.

> Pour un **test rapide sans partition** : clonez dans `/opt/nexus-mothership`, puis lancez `bash install.sh --sans-partition`.

Le **MVP** démarre le cockpit (`caddy`), les agents (`nexus-core`, base SQLite), la passerelle des IA (`nexus-bridge`) et l'IA locale de secours (`ollama`). Seuls les ports 80 et 443 sont utilisés. Les alertes N3 arrivent sur le téléphone dès le MVP (appli gratuite ntfy, [section 6](#6-recevoir-les-alertes-n3-sur-le-téléphone)).
La **version complète** (n8n, surveillance, notifications Android) s'ajoute plus tard avec `bash install.sh --complet`.

**Tout est gratuit** : Ollama Cloud en offre gratuite, l'IA locale, et des logiciels open source. Aucune option payante n'est proposée, et le budget de dépense est fixé à 0 €.

---

Ce kit installe votre « Mini Mothership » : **93 rôles d'agents** — 5 du noyau (PRIME, GATE, SENTINEL, LEDGER, BUDGET), 8 directeurs (9 directions en comptant le noyau) et 20 services × 4 agents (COLLECTOR, ANALYST, CHECKER, EXECUTOR), dont le département de cybersécurité défensive **CYBER-FORTRESS** (4 services). COLLECTOR, ANALYST et CHECKER appellent l'IA ; EXECUTOR, SENTINEL, LEDGER et BUDGET sont **déterministes** (aucune IA). Le tout avec un **cockpit** pour valider les décisions importantes depuis votre téléphone. En version complète, il ajoute **n8n** pour les automatisations, des **notifications** sur Android et une **surveillance** des services.
L'IA utilise **Ollama Cloud** (offre gratuite), avec l'IA locale du VPS en secours. Aucune action externe (envoi, publication, paiement) n'est faite sans votre validation.

> Vous avez seulement besoin du **terminal web de hPanel** (déjà connecté en root) et de votre **téléphone Android**.

---

## Sommaire
0. [Ollama Cloud](#ollama-cloud) · [Niveaux de fonctionnement](#niveaux-de-fonctionnement)
1. [Ce qui sera installé](#1-ce-qui-sera-installé)
2. [Partitions](#2-partitions)
3. [Installation pas à pas](#3-installation-pas-à-pas)
4. [Ouvrir les ports dans le pare-feu Hostinger](#4-ouvrir-les-ports-dans-le-pare-feu-hostinger)
5. [Première utilisation](#5-première-utilisation)
6. [Recevoir les alertes N3 sur le téléphone](#6-recevoir-les-alertes-n3-sur-le-téléphone)
7. [Les workflows n8n](#7-les-workflows-n8n)
8. [Sauvegardes](#8-sauvegardes)
9. [Commandes utiles](#9-commandes-utiles)
10. [Problèmes fréquents](#10-problèmes-fréquents)
11. [Désinstaller](#11-désinstaller)
12. [Passerelle Claude · ChatGPT · Gemini](#12-passerelle-claude--chatgpt--gemini)
13. [Entretien au téléphone](#13-entretien-au-téléphone) : mettre à jour, restaurer, changer un mot de passe ou une clé, décideur mobile, mémoire par projet, exercice de restauration, veille cyber

---

## Ollama Cloud

Ollama Cloud fait tourner de gros modèles (par défaut `gemma4:31b`) sur les serveurs d'Ollama : c'est plus rapide et plus intelligent que l'IA locale du VPS.

1. Connectez-vous sur **https://ollama.com** avec votre compte.
2. Créez une clé sur **https://ollama.com/settings/keys** (bouton *Add API key*), puis copiez-la.
3. Lancez `bash install.sh`. À la question « Utiliser Ollama Cloud ? », répondez **O**, puis collez la clé. **Rien ne s'affiche pendant la saisie, c'est normal.**
   Le script teste la clé, affiche les modèles disponibles et propose `gemma4:31b` (ou le premier de la liste).
4. Suivez votre consommation sur **https://ollama.com/settings/usage**.

### Ajouter la clé Ollama au téléphone
La clé n'est enregistrée qu'après un **vrai appel authentifié** à Ollama : une clé refusée (ou un texte de moins de 20 caractères) ne change rien et le Mothership reste sur l'IA locale. Espaces, retours à la ligne et guillemets collés par erreur sont retirés.
- **Méthode 1, collage** : `bash install.sh --cloud`, puis appui long > Coller à « Clé Ollama Cloud » et Entrée (rien ne s'affiche, c'est normal).
- **Méthode 2, fichier (plus fiable dans la console web)** :
  ```bash
  nano /root/cle-ollama.txt          # collez la clé, puis Ctrl+O, Entrée, Ctrl+X
  bash install.sh --cloud --cle-fichier /root/cle-ollama.txt
  ```
  Le script propose ensuite d'effacer le fichier (répondez **o**).
- Si la clé déjà enregistrée est refusée, `bash install.sh --cloud` propose de la remplacer.

À savoir :
- **Offre gratuite** : Ollama ne publie pas les limites exactes de l'offre gratuite. Si elles sont atteintes, les appels sont refusés et le Mothership bascule automatiquement sur l'**IA locale** (`qwen2.5:3b`).
- **Aucune dépense** n'est possible tant que vous ne passez pas vous-même à une offre payante sur ollama.com. Le kit ne le propose jamais.
- La clé est saisie **par vous**. Elle n'est jamais affichée ni écrite dans `install.log`. Elle est stockée uniquement dans `.env`, lisible par root seulement.
- Pour changer de clé : `bash install.sh --cloud --cle-fichier /root/cle-ollama.txt` (voir ci-dessus).

| Option d'install.sh | Effet |
|---|---|
| *(aucune)* | Ollama Cloud si vous fournissez une clé, **+ IA locale de secours** ; sans clé : IA locale seule |
| `--cloud` | ne pose pas la question « Utiliser Ollama Cloud ? » ; propose de remplacer une clé refusée |
| `--cle-fichier CHEMIN` | lit la clé dans un fichier (au lieu du collage), puis propose de l'effacer |
| `--sans-repli` | Ollama Cloud **sans** IA locale : le MVP n'utilise plus qu'environ 0,5 Go de RAM |
| `--local` | IA locale seule, sans Ollama Cloud |
| `--model NOM` | choisit le modèle (doit figurer dans la liste affichée) |

---

## Niveaux de fonctionnement

Chaque mission tourne à un **niveau de fonctionnement** qui règle l'effort, les tokens, le coût et le délai. Ne pas confondre avec les niveaux de **décision** N0–N3 (qui disent si votre accord est nécessaire).

| Niveau | IA utilisée | Tokens max | Corrections | Double contrôle | Délai max | Coût |
|---|---|---|---|---|---|---|
| **F1 Éclair** | IA locale (`qwen2.5:3b`) | 6 000 | 0 | non | 3 min | 0 € |
| **F2 Standard** *(défaut)* | Ollama Cloud si configuré, sinon locale | 20 000 | 1 | non | 10 min | 0 € |
| **F3 Renforcé** | comme F2 + 2ᵉ contrôle par l'IA locale | 40 000 | 2 | oui | 20 min | 0 € |
| **F4 Expert** | Claude (Anthropic), modèle par rôle | 80 000 | 3 | oui | 30 min | ≤ 0,50 € |

- **Choisir** : menu « Niveau de fonctionnement » du formulaire *Nouvelle mission* (cockpit), variable `FONCTIONNEMENT=F3` de `projets/lancer-mission.sh` et `tests-poker/run_tests.sh`, ou paramètre `fonctionnement` de l'outil `mothership_mission` des IA. Défaut : `NEXUS_FONCTIONNEMENT_DEFAUT=F2` dans `.env`.
- **Relèvements automatiques** (jamais de baisse ; la raison est affichée sur la mission) : F1 → F2 si le GATE classe la mission N2 ou N3, ou si l'IA locale est absente ; missions juridiques (`LEX-GUARD/droit-*`), de pilotage (`PILOT-CORE/*`) et de cybersécurité (`CYBER-FORTRESS/*`) → F3 minimum.
- **F4 est payant et toujours soumis à votre accord** : le coût est estimé, une décision « Lancer en F4 — coût estimé X € » apparaît dans le cockpit et rien ne démarre avant votre validation (les IA connectées par la passerelle ne peuvent pas valider). Avec `BUDGET_MONTHLY_EUR=0` (installation gratuite), F4 est indisponible : la mission part en **F3** (case « repli F3 », cochée par défaut) ou est refusée.
- **Plafonds** : si le délai, les tokens ou le coût max sont atteints, la mission s'arrête proprement (statut « plafond atteint »), le livrable partiel est gardé et le cockpit propose de relancer au niveau supérieur.
- **Suivi** : onglet *Fonctionnement* du cockpit (grille et consommation du mois par niveau) ou `GET /api/fonctionnement`. Réglages : `nexus-core/fonctionnement.yaml`.

---

## 1. Ce qui sera installé

```
Internet ──► Caddy (HTTPS automatique, ports 80/443)
               ├─ :443   Cockpit + API ─► nexus-core (SQLite) ─► Ollama Cloud (https://ollama.com)
               │                                    │          └─► Ollama local (secours)
               │                                    └─► ntfy.sh (alerte « Décision N3 en attente #id »)
               └─ :443   /mcp et /bridge ─► nexus-bridge (passerelle des IA, SQLite)
   Version complète (--complet) en plus :
               ├─ :8443  n8n (automatisations)      ─► PostgreSQL, Redis
               ├─ :8444  Uptime Kuma (surveillance)
               └─ :8445  ntfy (notifications Android)
```

**MVP (par défaut)**

| Service | Rôle | RAM max | CPU max |
|---|---|---|---|
| caddy | HTTPS + mot de passe du cockpit | 64 Mo | 0,10 |
| nexus-core | les 93 agents + cockpit (SQLite) | 384 Mo | 0,20 |
| nexus-bridge | passerelle Claude · ChatGPT · Gemini (mémoire commune) | 128 Mo | 0,10 |
| ollama | IA locale de secours (`qwen2.5:3b`) ; absente avec `--sans-repli` | 3,5 Go | 1,10 |
| **Total** | | **≈ 4,1 Go** (0,6 Go sans repli) | **1,5 vCPU** |

**Version complète (`--complet`)**

| Service | Rôle | RAM max | CPU max |
|---|---|---|---|
| ollama | IA locale (si repli) | 2,9 Go | 0,80 |
| postgres | base de données (missions, décisions, journal, n8n) | 640 Mo | 0,20 |
| n8n | automatisations | 640 Mo | 0,15 |
| nexus-core | les 93 agents + cockpit | 384 Mo | 0,10 |
| nexus-bridge | passerelle Claude · ChatGPT · Gemini | 128 Mo | 0,10 |
| redis | file de tâches | 128 Mo | 0,05 |
| uptime-kuma | surveillance | 128 Mo | 0,03 |
| caddy | HTTPS + mots de passe | 64 Mo | 0,05 |
| ntfy | notifications | 48 Mo | 0,02 |
| **Total** | | **≈ 5 Go** | **1,5 vCPU** |

PostgreSQL (extension pgvector) et Redis sont **réservés, non utilisés par le MVP** : nexus-core y bascule seulement en version complète ; pgvector n'est pas encore exploité.

Seul Caddy est accessible depuis Internet. Les autres services n'exposent aucun port (réseau Docker `p1-nexus-net`). nexus-core peut sortir vers Internet pour joindre ollama.com.

---

## 2. Partitions

Le VPS (2 vCPU, 8 Go RAM, 100 Go disque) est découpé en **4 partitions isolées** de 20 Go chacune. Elles sont créées par `partitions.sh` sous forme de fichiers image (`/srv/images/p1.img` … `p4.img`) montés sur `/srv/p1` … `/srv/p4`. **Le disque système n'est pas modifié.** Chaque partition a une taille fixe : un projet qui la remplit ne peut pas saturer le reste du VPS.

| Partition | Usage | RAM réservée | vCPU | Disque |
|---|---|---|---|---|
| **P1** `/srv/p1` | **Mini Mothership** (ce kit) | 5 Go | 1,5 | 20 Go |
| P2 `/srv/p2` | libre (futur projet) | 0,75 Go | ~0,15 | 20 Go |
| P3 `/srv/p3` | libre (futur projet) | 0,75 Go | ~0,15 | 20 Go |
| P4 `/srv/p4` | libre (futur projet) | 0,75 Go | ~0,15 | 20 Go |

Il reste environ 0,75 Go de RAM et ~0,05 vCPU pour Ubuntu, Docker et le terminal.
Au redémarrage, Docker attend que les partitions soient montées (option fstab `x-systemd.before=docker.service` et règle systemd `RequiresMountsFor`) : si une partition manque, Docker reste arrêté au lieu de démarrer sur un dossier vide. En MVP avec Ollama Cloud sans repli (`--sans-repli`), P1 n'utilise qu'environ 0,5 Go.
`partitions.sh` refuse de continuer si l'espace libre sur `/` est inférieur à (4 × taille) + 10 Go, soit **90 Go** pour 4 × 20 Go.

### Installer un futur projet dans P2, P3 ou P4
1. Placez le projet dans sa partition : `mkdir -p /srv/p2/mon-projet && cd /srv/p2/mon-projet`
2. Donnez-lui un nom de projet Docker Compose qui commence par le numéro de partition, par exemple dans son `.env` : `COMPOSE_PROJECT_NAME=p2-monprojet`
3. Mettez **toutes** ses données dans des dossiers de la partition (bind mounts `./data/...`), pas dans des volumes Docker nommés.
4. Respectez les limites de la partition dans son `docker-compose.yml`, avec `mem_limit` et `cpus` sur chaque service. **Total : 0,75 Go et 0,15 vCPU maximum.** Exemple :
   ```yaml
   services:
     app:
       mem_limit: 768m
       cpus: 0.1
       volumes: ["./data/app:/data"]
   ```
5. Utilisez un réseau dédié (par exemple `p2-monprojet-net`) et **n'exposez pas** les ports 80, 443 ou 8443 à 8445 (déjà pris par P1). Pour publier un site, ajoutez plutôt un bloc dans `Caddyfile.mvp` (ou `Caddyfile.complet`) de P1 (sur un port libre, par exemple 8450).

---

## 3. Installation pas à pas

Durée : 20 à 30 minutes, surtout du téléchargement. Ouvrez **hPanel > VPS > Terminal** et copiez-collez les blocs un par un.

### Étape A — Créer les 4 partitions (une seule fois)
```bash
cd /root
git clone -b nexus-mothership-kit --depth 1 https://github.com/redkards/espacetravail-public nexus-mothership-kit
cd nexus-mothership-kit
bash partitions.sh --dry-run     # montre ce qui va être fait, sans rien modifier
bash partitions.sh               # crée les 4 partitions de 20 Go
```
À la fin, un tableau `df -h` affiche `/srv/p1` à `/srv/p4`.

### Étape B — Placer le kit dans la partition P1
```bash
mv /root/nexus-mothership-kit /srv/p1/nexus-mothership
cd /srv/p1/nexus-mothership
```

### Étape C — Lancer l'installation
```bash
bash install.sh --email votre@email.fr
```
C'est le **MVP** (cockpit + agents). Ajoutez `--complet` pour avoir aussi n8n, Uptime Kuma et ntfy. Le nom d'hôte est détecté automatiquement (`hostname -f`). Sinon, le script vous le demande (hPanel > VPS > Vue d'ensemble, du type `srvXXXX.hstgr.cloud`) ; vous pouvez aussi le donner avec `--host`.

Options utiles :
| Option | Effet |
|---|---|
| `--host srvXXXX.hstgr.cloud` | force le nom d'hôte public |
| `--email vous@exemple.fr` | e-mail pour les certificats HTTPS |
| `--model NOM` | change le modèle principal |
| `--complet` | version complète (n8n, Uptime Kuma, ntfy, PostgreSQL) |
| `--cloud` / `--local` / `--sans-repli` | choix de l'IA (voir [Ollama Cloud](#ollama-cloud)) |
| `--sans-partition` | test rapide dans `/opt/nexus-mothership`, sans partition P1 |
| `--yes` | ne pose aucune question (pas de saisie de clé : IA locale seule, sauf si la clé est déjà dans `.env`) |

Le script affiche des étapes numérotées (1/13 … 13/13 ; 14 en mode complet). Il propose aussi (réponse **o**) une **sauvegarde automatique chaque nuit**. À la fin, un **encadré** donne vos adresses et, pour chaque secret, la commande qui l'affiche, par exemple `grep COCKPIT_PASSWORD .env`. Aucun secret n'est écrit dans `install.log` (un ancien journal qui en contenait est nettoyé, après accord).
Notez hors du VPS (gestionnaire de mots de passe) le mot de passe du cockpit et `BACKUP_PASSPHRASE` : `grep -E 'COCKPIT_PASSWORD=|BACKUP_PASSPHRASE' .env`.

Le script peut être **relancé sans risque** : il ne régénère pas les mots de passe si `.env` existe déjà.
Il **ne touche jamais au pare-feu**. Si `ufw` est actif et que des ports manquent, il affiche les commandes `ufw allow …` à lancer vous-même.
Si les ports 80 ou 443 sont déjà utilisés (par Apache, Nginx, etc.), il s'arrête, sans rien modifier, et vous explique quoi faire.

---

## 4. Ouvrir les ports dans le pare-feu Hostinger

Dans **hPanel > VPS > Sécurité > Pare-feu**, autorisez en entrée (TCP) :

| Port | Pour | Mode |
|---|---|---|
| 22 | SSH (souvent déjà ouvert) | tous |
| 80 | obtention du certificat HTTPS | MVP et complet |
| 443 | cockpit | MVP et complet |
| 8443 | n8n | complet |
| 8444 | Uptime Kuma | complet |
| 8445 | ntfy (notifications) | complet |

---

## 5. Première utilisation

Remplacez `srvXXXX.hstgr.cloud` par votre nom d'hôte s'il est différent.

- **Cockpit** : `https://srvXXXX.hstgr.cloud/cockpit`
  Identifiant `decideur` et le mot de passe affiché. C'est ici que vous **validez, refusez ou faites réviser** les décisions N3. Vous y créez aussi des missions et y trouvez le bouton d'**arrêt d'urgence**.
Version complète uniquement :
- **n8n** : `https://srvXXXX.hstgr.cloud:8443`
  Une première fenêtre demande l'identifiant `admin` et son mot de passe (barrière Caddy). Ensuite, n8n vous fait créer votre compte propriétaire.
- **Uptime Kuma** : `https://srvXXXX.hstgr.cloud:8444`. Mêmes identifiants que le cockpit, puis création du compte admin Kuma. Ajoutez par exemple une sonde HTTP sur `http://nexus-core:8000/api/sante`.

Sur Android, ajoutez le cockpit à l'écran d'accueil : menu Chrome **⋮ > Ajouter à l'écran d'accueil**.

> Le tout premier certificat HTTPS peut prendre 1 à 2 minutes. Si le navigateur affiche une erreur de sécurité juste après l'installation, patientez puis rechargez la page.

---

## 6. Recevoir les alertes N3 sur le téléphone

Gratuit, dès le MVP. `install.sh` crée un **sujet secret** aléatoire (`nexus-` + 16 caractères).

1. Installez l'application **ntfy** (Play Store ou F-Droid).
2. Dans le terminal hPanel : `cd /srv/p1/nexus-mothership && grep NTFY_TOPIC .env`
3. Dans ntfy : **+** > nom du sujet = la valeur affichée.
   - **MVP** : laissez le serveur par défaut `ntfy.sh`.
   - **Version complète** : cochez **Utiliser un autre serveur** > `https://srvXXXX.hstgr.cloud:8445`, puis, dans les paramètres de l'appli, ajoutez l'utilisateur `NTFY_USER` / `NTFY_PASSWORD` (`grep NTFY_ .env`). Ce serveur refuse tout par défaut : seul votre compte peut lire le sujet.

> **À savoir** : en MVP, **ntfy.sh est un service tiers** (gratuit, public). Quiconque connaît le sujet peut lire les alertes : il est secret, ne le partagez pas. C'est pourquoi le texte reste **générique** (« Décision N3 en attente #id ») : aucun contenu de mission n'est envoyé. Les détails se lisent dans le cockpit. Pour ne plus rien envoyer à ntfy.sh : mettez `NTFY_TOPIC=` vide dans `.env` puis `docker compose up -d`.

Le rapport du soir (19 h) existe seulement en version complète, si vous l'activez dans n8n.

---

## 7. Les workflows n8n

*(version complète uniquement)*

Trois workflows sont importés automatiquement. Ils sont **désactivés** par défaut : activez-les dans n8n avec l'interrupteur *Active*.

> **Avant d'activer un workflow** (n8n 2.45.6, `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` : les workflows ne lisent jamais les variables du serveur) :
> 1. n8n > **Credentials** > *Add credential* > **Header Auth**, nom exact **`NEXUS API`**, *Name* `X-Nexus-Key`, *Value* : la clé de `grep NEXUS_API_KEY .env`. Les 3 workflows utilisent cet identifiant (s'il n'est pas relié tout seul, choisissez-le dans chaque nœud *HTTP Request*).
> 2. Dans le nœud **Paramètres** (2ᵉ nœud de chaque workflow), remplacez `srvXXXX.hstgr.cloud` et `nexus-XXXX` par vos valeurs (`grep -E 'NEXUS_HOST|NTFY_TOPIC' .env`). Ces valeurs ne sont pas des secrets ; la clé, elle, reste dans l'identifiant chiffré par n8n.
> Faites `bash backup.sh` avant de passer d'une ancienne version (1.64) de n8n à celle-ci.

| Workflow | Fonction |
|---|---|
| **NEXUS — Mission par webhook** | reçoit un POST et crée une mission |
| **NEXUS — Veille quotidienne** | à 8 h, crée une mission de veille (à compléter avec vos textes ; laissez-le désactivé tant que ce n'est pas fait) |
| **NEXUS — Rapport du soir** | à 19 h, envoie sur ntfy un résumé des décisions en attente et des missions |

Exemple d'appel du webhook (une fois le workflow activé). Le mot de passe Caddy de n8n est obligatoire :
```bash
curl -u admin:MOT_DE_PASSE_N8N -X POST https://srvXXXX.hstgr.cloud:8443/webhook/nexus-mission \
  -H 'Content-Type: application/json' \
  -d '{"titre":"Plan de lancement","consigne":"Rédige un plan de projet en 5 étapes","service":"OPS-CORE/projets"}'
```

---

## 8. Sauvegardes

```bash
cd /srv/p1/nexus-mothership
bash backup.sh
```
Cela crée `backups/<date>/` : copie **cohérente** des bases SQLite (`nexus.db`, `bridge.db`, sans fichiers `-wal`/`-shm`) et des livrables, plus les bases PostgreSQL et les workflows n8n (version complète), et le `.env` **chiffré** avec gpg (`env.sauvegarde.gpg`, phrase = `BACKUP_PASSPHRASE`). Les **7** dernières sont gardées. La sauvegarde de chaque nuit à 3 h 30 est proposée par `install.sh` (fichier `/etc/cron.d/nexus-mothership-sauvegarde`).

**Copie hors du VPS (gratuit, Google Drive)** — une seule fois, depuis le terminal :
1. `apt-get install -y rclone` puis `rclone config` : `n` (nouveau), nom `gdrive`, type `drive`, laissez client_id/secret vides, accès `1` (complet), puis à « Use web browser » répondez **n** et suivez l'indication (une commande `rclone authorize` à lancer sur un ordinateur, ou ouvrez le lien sur votre téléphone si proposé).
2. Ensuite : `bash backup.sh --hors-serveur` (copie dans le dossier Drive `nexus-sauvegardes`, 7 gardées). Pour le faire chaque nuit, éditez `/etc/cron.d/nexus-mothership-sauvegarde` et ajoutez `--hors-serveur` après `backup.sh`.

> Sur Drive, seul le `.env` est chiffré ; les bases (missions, mémoire des IA) sont en clair dans votre Drive. Restauration : [section 13](#restaurer-une-sauvegarde).

---

## 9. Commandes utiles

Toujours depuis `/srv/p1/nexus-mothership` :

| Besoin | Commande |
|---|---|
| état des services | `docker compose ps` |
| journaux en direct | `docker compose logs -f --tail=50` |
| journaux d'un service | `docker compose logs -f nexus-core` |
| consommation RAM/CPU | `docker stats --no-stream` |
| redémarrer tout | `docker compose restart` |
| arrêter / relancer | `docker compose down` puis `docker compose up -d` |
| changer de modèle | `bash install.sh --model NOM` (cloud) ; en local : `docker compose exec ollama ollama pull NOM`, puis `NEXUS_MODEL_LOCAL=NOM` dans `.env` et `docker compose up -d` |
| passer en version complète | `bash install.sh --complet` |
| revoir un secret | `grep COCKPIT_PASSWORD .env` (ou `NEXUS_API_KEY`, `NTFY_`, `BACKUP_PASSPHRASE`…) |
| URL des connecteurs IA (passerelle) | `bash bridge-connecteurs.sh` |
| voir les jetons de la passerelle | `grep BRIDGE_TOKEN /srv/p1/nexus-mothership/.env` |
| espace des partitions | `df -h /srv/p*` |

---

## 10. Problèmes fréquents

| Symptôme | Solution |
|---|---|
| `/srv/p1 n'est pas une partition montée` | lancez `bash partitions.sh`, puis déplacez le kit dans `/srv/p1/nexus-mothership` |
| `Ports déjà utilisés : 80 443` | `systemctl disable --now apache2 nginx`, puis relancez `install.sh` |
| la page ne s'ouvre pas | vérifiez le pare-feu Hostinger (section 4) |
| erreur de certificat HTTPS | attendez 2 minutes ; vérifiez que le port 80 est ouvert ; `docker compose logs caddy` |
| réponses de l'IA lentes | avec l'IA locale, c'est normal sur 2 vCPU (de 10 à 60 s par étape) : utilisez Ollama Cloud, ou un modèle local plus petit (`qwen2.5:1.5b`) |
| `Clé Ollama Cloud refusée` | vérifiez la clé sur ollama.com/settings/keys, supprimez la ligne `OLLAMA_API_KEY` de `.env`, puis relancez `install.sh` |
| un service « unhealthy » | `docker compose logs NOM_DU_SERVICE`, puis `docker compose up -d` |
| une IA ne voit pas la passerelle | `docker compose logs nexus-bridge` ; vérifiez l'adresse avec `bash bridge-connecteurs.sh` (section 12) |
| après un redémarrage du VPS | les partitions se remontent seules (fstab), puis Docker et les services redémarrent |
| Docker ne démarre plus après un redémarrage | une partition n'est pas montée : `df -h /srv/p*`, puis `mount -a && systemctl start docker` |
| `COCKPIT_INTERNAL manquant` (ou `LEDGER_HMAC_KEY`) | relancez `bash install.sh` : il ajoute les nouveaux secrets sans toucher aux anciens |

---

## 11. Désinstaller

```bash
cd /srv/p1/nexus-mothership
bash uninstall.sh            # supprime les conteneurs, GARDE les données (./data) et le .env
bash uninstall.sh --purge    # supprime AUSSI données, .env et install.log (taper SUPPRIMER),
                             # puis les sauvegardes si vous tapez SUPPRIMER-SAUVEGARDES
```
Les partitions `/srv/p1` à `/srv/p4` ne sont jamais supprimées par ce script.

---

## 12. Passerelle Claude · ChatGPT · Gemini

**À quoi ça sert ?** Claude, ChatGPT et Gemini partagent un même carnet, rangé sur votre VPS :
- une **mémoire commune** (faits, décisions, vos préférences) ;
- des **tâches** (« Gemini : écris le script de la vidéo 3 ») ;
- des **messages** entre IA ;
- des **passations** : la dernière IA qui a travaillé sur un projet laisse un résumé, la suivante reprend sans tout réexpliquer ;
- un lien avec le Mothership : une IA peut lui **confier une mission** et suivre son statut, mais **ne peut jamais valider** une décision N3 : ça reste dans le cockpit, pour vous seul.

C'est gratuit et open source (service `nexus-bridge`, installé avec le MVP). Chaque IA a sa **propre adresse secrète** : on sait toujours qui a écrit quoi.

### Étape 1 — Récupérer les adresses (terminal web hPanel)

```bash
cd /srv/p1/nexus-mothership
bash bridge-connecteurs.sh
```
Le script affiche une adresse par IA, du type `https://srvXXXX.hstgr.cloud/mcp/<jeton>`, et les étapes à suivre. **Cette adresse est un mot de passe** : ne la collez que dans l'IA concernée. Astuce téléphone : appui long sur l'adresse dans le terminal > Copier, puis collez-la dans l'autre application.

### Étape 2 — Brancher chaque IA

| IA | Où | Comment |
|---|---|---|
| **Claude** | claude.ai dans le **navigateur** (Chrome en mode « Version pour ordinateur » sur Android), ou l'appli de bureau | Paramètres > Connecteurs > **Ajouter un connecteur personnalisé** > nom « NEXUS Passerelle » + adresse Claude. Ensuite il fonctionne aussi dans l'appli Android : « + » > Connecteurs > activer. |
| **ChatGPT** | chatgpt.com dans le **navigateur** | Paramètres > Applications (ex-Connecteurs) > Paramètres avancés > **Mode développeur** activé > Créer une application / ajouter un serveur MCP > adresse ChatGPT, authentification « Aucune ». |
| **Gemini** | **Gemini CLI** (ordinateur, ou Termux sur Android) | Dans `~/.gemini/settings.json`, clé `mcpServers` : `"nexus": { "httpUrl": "<adresse Gemini>" }`, puis `/mcp` dans Gemini pour vérifier. |
| **Gemini (appli)** | appli Gemini / gemini.google.com | Pas de serveur MCP personnel possible : gardez la **méthode miroir Google Doc** déjà en place (Claude ou ChatGPT recopient passations et tâches dans le Google Doc que Gemini lit, et reportent ce que Gemini y note). |

> **À savoir :** ces menus changent souvent de nom ou de place ; si vous ne les trouvez pas, cherchez « Connecteurs », « Applications » ou « MCP » dans les paramètres. **Certaines offres limitent les connecteurs personnalisés** : chez Claude, l'offre gratuite n'en autorise qu'**un seul** et, en Team/Enterprise, seul un administrateur peut l'ajouter ; chez ChatGPT, le mode développeur est réservé aux **offres payantes** (Plus, Pro, Business, Enterprise, Edu) et ne s'active que sur le web. L'ajout se fait depuis un navigateur ; l'usage marche ensuite sur téléphone selon l'application.

### Étape 3 — Premier essai

Dans chaque IA : *« Utilise la passerelle NEXUS : lis tes messages, puis écris en mémoire que la passerelle fonctionne pour toi. »*
Puis ouvrez **https://srvXXXX.hstgr.cloud/bridge** (identifiants du cockpit) : page en lecture seule, lisible sur téléphone, avec les dernières mémoires, tâches, messages, passations et le journal.

### Bonnes habitudes à donner aux IA
- **Début de session** : « lis tes messages, la dernière passation du projet `poker-winners` et les tâches ouvertes ».
- **Fin de session** : « écris une passation pour `poker-winners` ».
- Codes projets : `paradoxx`, `nexus`, `poker-winners`, `poker-feeling`, `redkards`, `top-solver`, `youtube-poker-winner`, `freelance-ia`, `esct-boxe`, `turf`, `divers` (outil `projets_lister`).

### Outils disponibles (18)
`projet_connaissances` (lit la mémoire du projet tenue par le Mothership) · `memoire_ecrire`, `memoire_chercher`, `memoire_lire`, `memoire_oublier` · `tache_creer`, `tache_lister`, `tache_prendre`, `tache_mettre_a_jour` · `message_envoyer`, `messages_lire` · `passation_ecrire`, `passation_derniere` · `projets_lister`, `mothership_mission`, `mothership_statut`, `mothership_decisions_en_attente` · `journal_lister`.

### Sécurité
- **Aucun secret dans la mémoire** : un texte qui ressemble à une clé API, un mot de passe ou un numéro de carte est **refusé** avec une explication. Notez plutôt *où* est rangé le secret.
- 8 Ko maximum par texte, 60 appels par minute et par IA.
- Rien n'est jamais effacé : une correction crée une nouvelle version ; « oublier » archive (seuls l'IA autrice ou vous, avec votre jeton propriétaire, peuvent le faire).
- Les jetons ne sont jamais écrits dans les journaux. **Voir les jetons :** `grep BRIDGE_TOKEN /srv/p1/nexus-mothership/.env`.
- **Changer un jeton** (adresse divulguée) : supprimez sa ligne `BRIDGE_TOKEN_...` dans `.env`, relancez `bash install.sh`, puis recollez la nouvelle adresse dans l'IA.
- Les données sont dans `./data/nexus-bridge/bridge.db`, incluses dans `bash backup.sh`.
- Caddy n'écrit jamais l'adresse `/mcp/<jeton>` dans ses journaux (remplacée par `/mcp/***`).

---

## 13. Entretien au téléphone

Tout se fait dans **hPanel > VPS > Terminal** (console web, déjà root), en commençant par `cd /srv/p1/nexus-mothership`.

### Mettre à jour
```bash
bash backup.sh
git pull
docker compose up -d --build
```
Si un message indique `... manquant dans .env`, lancez `bash install.sh` (il ajoute les nouveaux réglages sans changer vos mots de passe).

### Restaurer une sauvegarde
```bash
bash restore.sh                      # liste les sauvegardes
bash restore.sh 2026-11-03_033000    # restaure celle-ci : tapez RESTAURER
```
Le script vérifie la sauvegarde **avant** de couper quoi que ce soit, arrête nexus-core et nexus-bridge, met les données actuelles de côté (`data/.avant-restauration-<date>/`), restaure, remet les droits, redémarre et contrôle `/api/sante`. Ajoutez `--avec-env` pour remplacer aussi `.env` (sur un VPS neuf, la phrase `BACKUP_PASSPHRASE` notée vous sera demandée).

### Changer le mot de passe du cockpit
```bash
sed -i '/^COCKPIT_PASSWORD/d' .env     # supprime COCKPIT_PASSWORD et COCKPIT_PASSWORD_HASH
bash install.sh
grep COCKPIT_PASSWORD= .env            # nouveau mot de passe
```

### Changer une clé / un jeton de passerelle
- Jeton d'une IA (adresse divulguée) : `sed -i '/^BRIDGE_TOKEN_CHATGPT=/d' .env` (ou `_CLAUDE`, `_GEMINI`, `_PROPRIETAIRE`), `bash install.sh`, puis `bash bridge-connecteurs.sh chatgpt` et recollez l'adresse dans l'IA.
- Clé API (`NEXUS_API_KEY`), secret interne (`COCKPIT_INTERNAL`) ou sujet ntfy (`NTFY_TOPIC`, à ressaisir dans l'appli) : même méthode, supprimez la ligne puis `bash install.sh`.
- Clé Ollama Cloud : `bash install.sh --cloud --cle-fichier /root/cle-ollama.txt` ([détails](#ajouter-la-clé-ollama-au-téléphone)).
- Ne supprimez **pas** `LEDGER_HMAC_KEY` : le journal existant ne serait plus vérifiable.

### Recevoir les alertes N3 sur le téléphone
`grep NTFY_TOPIC .env`, puis abonnez-vous à ce sujet dans l'appli **ntfy** ([section 6](#6-recevoir-les-alertes-n3-sur-le-téléphone)).

### Vérifier que tout va bien
- `docker compose ps` : tous les services « running » / « healthy ».
- `https://srvXXXX.hstgr.cloud/api/sante` : `ledger_hmac` doit valoir `true` ; la liste `avertissements` doit être vide (sinon, elle dit quoi corriger).
- Intégrité du journal LEDGER : `grep '^NEXUS_API_KEY=' .env | sed 's/^NEXUS_API_KEY=/X-Nexus-Key: /' | curl -s -H @- https://srvXXXX.hstgr.cloud/api/ledger/verifier` (la clé passe par l'entrée standard, jamais dans la ligne de commande).
- `ls backups/` : une sauvegarde de moins de 24 h.

### Décideur mobile (/cockpit/decideur, code à 6 chiffres)
- Ouvrez `https://srvXXXX.hstgr.cloud/cockpit/decideur` (identifiants du cockpit) et ajoutez-la à l'écran d'accueil : une décision N3 par écran, risque expliqué, résumé court.
- Les décisions sont regroupées en **sessions** (12 h 30 et 19 h, `NEXUS_SESSIONS_N3`) avec une seule alerte ntfy par session, et un rappel 2 h avant le refus automatique.
- Valider une décision à **risque élevé** demande le **code Décideur** à 6 chiffres, affiché une seule fois à la fin de l'installation, puis : `grep COCKPIT_CODE_DECIDEUR .env`. 5 erreurs = verrou de 15 minutes. Pour en changer : `sed -i '/^COCKPIT_CODE_DECIDEUR=/d' .env && bash install.sh`.

### Mémoire par projet
- Les fiches `projets/*.md` et `tests-poker/contexte/` sont lues (lecture seule) au démarrage ; les livrables validés sont résumés automatiquement (`NEXUS_MEMOIRE_AUTO=1`, mettez `0` pour arrêter).
- Les agents reçoivent les 3 passages les plus utiles du projet ; les IA y accèdent par l'outil `projet_connaissances`. Aucun secret n'y est conservé (filtre automatique).
- Pour ajouter une connaissance durable : complétez la fiche `projets/<projet>.md`, puis `docker compose restart nexus-core`.

### Exercice de restauration mensuel
- Une sauvegarde n'a de valeur que si elle se restaure : `bash exercice-restauration.sh` restaure la **dernière** sauvegarde dans une copie jetable sur la partition **P2** (`/srv/p2/exercice-restauration`), sans toucher P1 : aucun port ouvert, pas de Caddy ni d'IA (IA factice), 512 Mo maximum.
- Il vérifie : l'API répond, mêmes nombres de missions et d'entrées LEDGER que la sauvegarde, chaîne LEDGER (HMAC) valide, `.env` sauvegardé déchiffrable avec `BACKUP_PASSPHRASE`, passerelle qui démarre. Puis il efface tout, écrit un rapport dans `backups/exercices/` et envoie l'alerte « Restauration testée : OK » (ou « ÉCHEC exercice de restauration »).
- `install.sh` propose de le planifier le 1er dimanche du mois à 4 h 47 (`/etc/cron.d/nexus-exercice-restauration`). Si P2 n'est pas montée, l'exercice s'arrête proprement (code 3) et vous prévient.

### Veille cyber hebdo
- `install.sh` propose de la planifier (dimanche 3 h 17, `/etc/cron.d/nexus-veille-cyber`) : elle collecte la configuration du kit **sans aucun secret**, lance deux missions CYBER-FORTRESS (veille des failles de la pile, audit de configuration) en F3, puis envoie l'alerte ntfy « Rapport cyber hebdo prêt ».
- Lancer à la main : `bash automatisations/veille-cyber.sh` ; voir ce qui est collecté : `bash automatisations/veille-cyber.sh --collecte`. Les agents proposent, vous décidez : rien n'est modifié sur le serveur.

### Statuts d'une mission
| Statut | Sens |
|---|---|
| `en_attente_place` | file d'attente : trop de missions en cours (`NEXUS_MAX_MISSIONS`), elle partira seule |
| `en_cours` | traitement par les agents |
| `en_attente_n3` | votre décision est attendue dans le cockpit (alerte ntfy) |
| `a_reformuler` | consigne refusée ou trop floue : reformulez-la et relancez |
| `plafond_atteint` | délai, tokens ou coût max atteint : livrable partiel gardé, relance possible au niveau supérieur |
| `echouee` | échec (le motif est affiché, par ex. « interrompue par un redémarrage ») |
| `terminee` / `validee` / `refusee` / `revision` / `suspendue` | fin normale, décision prise, ou arrêt d'urgence actif |
