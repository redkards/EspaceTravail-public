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
- À la fin, un encadré affiche l'adresse du cockpit et son mot de passe.

> Pour un **test rapide sans partition** : clonez dans `/opt/nexus-mothership`, puis lancez `bash install.sh --sans-partition`.

Le **MVP** démarre seulement le cockpit (`caddy`), les agents (`nexus-core`, base SQLite) et l'IA locale de secours (`ollama`). Seuls les ports 80 et 443 sont utilisés.
La **version complète** (n8n, surveillance, notifications Android) s'ajoute plus tard avec `bash install.sh --complet`.

**Tout est gratuit** : Ollama Cloud en offre gratuite, l'IA locale, et des logiciels open source. Aucune option payante n'est proposée, et le budget de dépense est fixé à 0 €.

---

Ce kit installe votre « Mini Mothership » : 93 agents IA organisés en directions (dont un département de cybersécurité défensive, CYBER-FORTRESS), avec un **cockpit** pour valider les décisions importantes depuis votre téléphone. En version complète, il ajoute **n8n** pour les automatisations, des **notifications** sur Android et une **surveillance** des services.
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
6. [Recevoir les notifications sur Android](#6-recevoir-les-notifications-sur-android)
7. [Les workflows n8n](#7-les-workflows-n8n)
8. [Sauvegardes](#8-sauvegardes)
9. [Commandes utiles](#9-commandes-utiles)
10. [Problèmes fréquents](#10-problèmes-fréquents)
11. [Désinstaller](#11-désinstaller)
12. [Passerelle Claude · ChatGPT · Gemini](#12-passerelle-claude--chatgpt--gemini)

---

## Ollama Cloud

Ollama Cloud fait tourner de gros modèles (par défaut `gemma4:31b`) sur les serveurs d'Ollama : c'est plus rapide et plus intelligent que l'IA locale du VPS.

1. Connectez-vous sur **https://ollama.com** avec votre compte.
2. Créez une clé sur **https://ollama.com/settings/keys** (bouton *Add API key*), puis copiez-la.
3. Lancez `bash install.sh`. À la question « Utiliser Ollama Cloud ? », répondez **O**, puis collez la clé. **Rien ne s'affiche pendant la saisie, c'est normal.**
   Le script teste la clé, affiche les modèles disponibles et propose `gemma4:31b` (ou le premier de la liste).
4. Suivez votre consommation sur **https://ollama.com/settings/usage**.

À savoir :
- **Offre gratuite** : Ollama ne publie pas les limites exactes de l'offre gratuite. Si elles sont atteintes, les appels sont refusés et le Mothership bascule automatiquement sur l'**IA locale** (`qwen2.5:3b`).
- **Aucune dépense** n'est possible tant que vous ne passez pas vous-même à une offre payante sur ollama.com. Le kit ne le propose jamais.
- La clé est saisie **par vous**. Elle n'est jamais affichée ni écrite dans `install.log`. Elle est stockée uniquement dans `.env`, lisible par root seulement.
- Pour changer de clé : supprimez la ligne `OLLAMA_API_KEY=` dans `.env`, puis relancez `bash install.sh`.

| Option d'install.sh | Effet |
|---|---|
| *(aucune)* | Ollama Cloud si vous fournissez une clé, **+ IA locale de secours** ; sans clé : IA locale seule |
| `--cloud` | ne pose pas la question « Utiliser Ollama Cloud ? » |
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
               └─ :443   Cockpit + API ─► nexus-core (SQLite) ─► Ollama Cloud (https://ollama.com)
                                                              └─► Ollama local (secours)
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

Seul Caddy est accessible depuis Internet. Les autres services n'exposent aucun port (réseau Docker `p1-nexus-net`). nexus-core peut sortir vers Internet pour joindre ollama.com.

---

## 2. Partitions

Le VPS (2 vCPU, 8 Go RAM, 100 Go disque) est découpé en **4 partitions isolées** de 20 Go chacune. Elles sont créées par `partitions.sh` sous forme de fichiers image (`/srv/images/p1.img` … `p4.img`) montés sur `/srv/p1` … `/srv/p4`. **Le disque système n'est pas modifié.** Chaque partition a une taille fixe : un projet qui la remplit ne peut pas saturer le reste du VPS.

| Partition | Usage | RAM réservée | vCPU | Disque |
|---|---|---|---|---|
| **P1** `/srv/p1` | **Mini Mothership** (ce kit) | 5 Go | 1,5 | 20 Go |
| P2 `/srv/p2` | libre (futur projet) | 1 Go | ~0,15 | 20 Go |
| P3 `/srv/p3` | libre (futur projet) | 1 Go | ~0,15 | 20 Go |
| P4 `/srv/p4` | libre (futur projet) | 1 Go | ~0,15 | 20 Go |

Il reste environ 0 à 1 Go de RAM et ~0,05 vCPU pour Ubuntu, Docker et le terminal. En MVP avec Ollama Cloud sans repli (`--sans-repli`), P1 n'utilise qu'environ 0,5 Go.
`partitions.sh` refuse de continuer si l'espace libre sur `/` est inférieur à (4 × taille) + 10 Go, soit **90 Go** pour 4 × 20 Go.

### Installer un futur projet dans P2, P3 ou P4
1. Placez le projet dans sa partition : `mkdir -p /srv/p2/mon-projet && cd /srv/p2/mon-projet`
2. Donnez-lui un nom de projet Docker Compose qui commence par le numéro de partition, par exemple dans son `.env` : `COMPOSE_PROJECT_NAME=p2-monprojet`
3. Mettez **toutes** ses données dans des dossiers de la partition (bind mounts `./data/...`), pas dans des volumes Docker nommés.
4. Respectez les limites de la partition dans son `docker-compose.yml`, avec `mem_limit` et `cpus` sur chaque service. **Total : 1 Go et 0,15 vCPU maximum.** Exemple :
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
C'est le **MVP** (cockpit + agents). Ajoutez `--complet` pour avoir aussi n8n, Uptime Kuma et ntfy. Le nom d'hôte est détecté automatiquement. Si `hostname -f` ne renvoie pas un nom complet, le script utilise `srvXXXX.hstgr.cloud`. Vous pouvez aussi le forcer avec `--host`.

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

Le script affiche des étapes numérotées (1/12 … 12/12 ; 13 en mode complet). À la fin, un **encadré** donne vos adresses et mots de passe. **Prenez-le en photo ou copiez-le.**
Pour revoir les identifiants plus tard : `cat /srv/p1/nexus-mothership/.env`

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

## 6. Recevoir les notifications sur Android

*(version complète uniquement : `bash install.sh --complet`)*

1. Installez l'application **ntfy** (Play Store ou F-Droid).
2. Touchez **+**, cochez **Utiliser un autre serveur**, puis saisissez `https://srvXXXX.hstgr.cloud:8445`.
3. Comme nom de topic, saisissez la valeur `NTFY_TOPIC` affichée à la fin de l'installation (`nexus-xxxxxxxxxxxx`).

Vous serez prévenu à chaque décision N3 en attente et chaque soir à 19 h (si le rapport du soir est activé).
Le nom du topic est **secret** : ne le partagez pas.

---

## 7. Les workflows n8n

*(version complète uniquement)*

Trois workflows sont importés automatiquement. Ils sont **désactivés** par défaut : activez-les dans n8n avec l'interrupteur *Active*.

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
Cela crée `backups/<date>/` avec la base SQLite et les livrables (MVP), plus les bases PostgreSQL et les workflows n8n (version complète), ainsi qu'une copie du `.env`. Les 14 dernières sauvegardes sont conservées.
Pour une sauvegarde automatique chaque nuit à 3 h 30, tapez `crontab -e` et ajoutez :
```
30 3 * * * /srv/p1/nexus-mothership/backup.sh >> /srv/p1/nexus-mothership/backups/backup.log 2>&1
```
Pensez aussi à télécharger régulièrement une sauvegarde hors du VPS, par exemple sur votre PC.

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
| revoir les identifiants | `cat .env` |
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
| après un redémarrage du VPS | les partitions se remontent seules (fstab) et les services redémarrent seuls |

---

## 11. Désinstaller

```bash
cd /srv/p1/nexus-mothership
bash uninstall.sh            # supprime les conteneurs, GARDE les données (./data) et le .env
bash uninstall.sh --purge    # supprime AUSSI toutes les données (demande de taper SUPPRIMER)
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

### Outils disponibles (17)
`memoire_ecrire`, `memoire_chercher`, `memoire_lire`, `memoire_oublier` · `tache_creer`, `tache_lister`, `tache_prendre`, `tache_mettre_a_jour` · `message_envoyer`, `messages_lire` · `passation_ecrire`, `passation_derniere` · `projets_lister`, `mothership_mission`, `mothership_statut`, `mothership_decisions_en_attente` · `journal_lister`.

### Sécurité
- **Aucun secret dans la mémoire** : un texte qui ressemble à une clé API, un mot de passe ou un numéro de carte est **refusé** avec une explication. Notez plutôt *où* est rangé le secret.
- 8 Ko maximum par texte, 60 appels par minute et par IA.
- Rien n'est jamais effacé : une correction crée une nouvelle version ; « oublier » archive (seuls l'IA autrice ou vous, avec votre jeton propriétaire, peuvent le faire).
- Les jetons ne sont jamais écrits dans les journaux. **Voir les jetons :** `grep BRIDGE_TOKEN /srv/p1/nexus-mothership/.env`.
- **Changer un jeton** (adresse divulguée) : supprimez sa ligne `BRIDGE_TOKEN_...` dans `.env`, relancez `bash install.sh`, puis recollez la nouvelle adresse dans l'IA.
- Les données sont dans `./data/nexus-bridge/bridge.db` (sauvegarde : copiez ce dossier, ou `docker compose exec nexus-bridge python -c "import sqlite3; s=sqlite3.connect('/data/bridge.db'); d=sqlite3.connect('/data/bridge-sauvegarde.db'); s.backup(d)"`).

