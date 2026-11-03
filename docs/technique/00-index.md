# Documentation technique SYFER V2 — Index

| Élément | Valeur |
|---|---|
| Projet | **SYFER** (projet total) |
| Périmètre de ce dossier | **SYFER ATLAS** (version réelle sur VPS : kit « mini-mothership ») et **SYFER ÉCHO** (version virtuelle : jumeau numérique) |
| Dépôt / branche | `espacetravail-public`, branche `v2` |
| Date de rédaction | 4 novembre 2026 |
| État décrit | code tel qu'il est lu dans la branche `v2` à cette date (plusieurs chantiers sont en cours : voir les mentions **[EN COURS]**) |
| Public | développeurs, intégrateurs, auditeurs sécurité, futur repreneur du code |
| Documents associés | `docs/cahier-des-charges/CDC-SYFER-V2.md` (exigences), `docs/operationnel/`, `docs/structurel/`, `docs/business/` (rédigés par d'autres équipes) |

## 1. Sommaire

| N° | Fichier | Contenu |
|---|---|---|
| 00 | `00-index.md` | ce sommaire, conventions, nomenclature, versions |
| 01 | [`01-architecture.md`](01-architecture.md) | vue d'ensemble, composants, déploiement, réseau et ports, zones de sécurité, flux d'une mission, décisions d'architecture (ADR) |
| 02 | [`02-agents-et-pipeline.md`](02-agents-et-pipeline.md) | 93 rôles, quadrants, PRIME, GATE N0–N3, F1–F4, charte, bouclier, double contrôle, révisions, directeur, EXECUTOR, LEDGER |
| 03 | [`03-donnees.md`](03-donnees.md) | modèle SQLite, migrations, archive, compaction, mémoires, leçons, exemples, veille, rétention, RGPD |
| 04 | [`04-api.md`](04-api.md) | routes `/api`, `/cockpit/api`, pages, passerelle MCP (20 outils) |
| 05 | [`05-protocole-nexus-v1.md`](05-protocole-nexus-v1.md) | objets, schémas JSON, versionnement, compatibilité |
| 06 | [`06-securite.md`](06-securite.md) | modèle de menace, mesures par couche, secrets, anti-CSRF, code Décideur, HMAC, durcissement, bouclier, tests |
| 07 | [`07-configuration.md`](07-configuration.md) | toutes les variables d'environnement (sans valeur secrète) |
| 08 | [`08-tests-et-qualite.md`](08-tests-et-qualite.md) | pyramide de tests, suites, simulations, itérations, charge, banc, jumeau, test system, porte de qualité, CI, résultats chiffrés |
| 09 | [`09-performance-et-capacite.md`](09-performance-et-capacite.md) | mesures connues, charge, jumeau, compaction, limites, réglages |

## 2. Nomenclature

| Nom | Définition | Où dans le dépôt |
|---|---|---|
| **SYFER** | Le projet total : organisation d'agents IA pilotée par un seul humain (le Décideur). | tout le dépôt |
| **SYFER ATLAS** | Version réelle, installée sur le VPS Hostinger (KVM 2, partition P1). Correspond au kit « Mini NEXUS MOTHERSHIP ». | `install.sh`, `docker-compose*.yml`, `Caddyfile.*`, `nexus-core/`, `nexus-bridge/` |
| **SYFER ÉCHO** | Version virtuelle « maxi performance » : jumeau numérique (simulation à événements discrets et Monte Carlo) servant à tester des choix avant achat. | `jumeau-numerique/` |
| **NEXUS MOTHERSHIP** | Architecture cible complète (246 agents annoncés). Elle n'existe pas dans le code de la branche `v2` : seule la version réduite à 93 rôles est implémentée. **[PRÉVU]** | `outils-depots/separer.sh` (dépôt documentaire `nexus-mothership`) |
| **Mini Mothership** | Le kit installable (93 rôles d'agents). | `README.md`, `SPEC.md` |
| **Décideur** | L'unique humain qui valide les décisions N3 (identifiant cockpit `decideur`). | `nexus-core/app/decideur.py` |
| **Protocole NEXUS v1** | Contrat d'échange JSON Schema commun aux quatre produits. | `protocole/` |

Les quatre produits futurs issus du monodépôt (script `outils-depots/separer.sh`, **[EN COURS]** : script prêt, dépôts non créés) :

| Produit | Contenu | Version déclarée |
|---|---|---|
| `nexus-bridge` | passerelle MCP + `protocole/` | 1.0.0 |
| `nexus-agents` | 93 fiches YAML, `fonctionnement.yaml`, chartes | 1.0.0 |
| `mini-mothership` | tout le kit (noyau, cockpit, scripts, banc, automatisations) | 1.0.0 |
| `nexus-mothership` | architecture et documentation (`SPEC.md`, guide) | 1.0.0 |

## 3. Conventions de ce dossier

- **Statut d'avancement** (utilisé partout) :
  - **[FAIT]** : présent dans le code de `v2` et couvert par au moins un test automatique ;
  - **[EN COURS]** : code présent mais non intégré, non mesuré, ou modifié pendant la rédaction ;
  - **[PRÉVU]** : décrit dans une spécification ou une recommandation, absent du code.
- **Preuves** : chaque affirmation importante cite un fichier (`chemin/fichier.py`) ou un test (`tests/test_x.py::test_y`).
- **Langue** : français ; identifiants de code conservés tels quels (ils sont eux-mêmes en français).
- **Aucun secret, aucune adresse IP publique** : le nom d'hôte est toujours écrit `srvXXXX.hstgr.cloud`.
- **Schémas** : Mermaid (`flowchart`, `sequenceDiagram`, `erDiagram`, `stateDiagram-v2`), lisibles sur GitHub.
- **Unités** : Mo/Go (base 1 024 pour la RAM Docker), euros TTC sauf mention, durées en s/min/h.
- **Niveaux** : ne pas confondre les niveaux de **décision** N0–N3 (faut-il l'accord du Décideur ?) et les niveaux de **fonctionnement** F1–F4 (quel effort, quel modèle, quel coût ?).

## 4. Versions des composants (état lu le 4 novembre 2026)

| Composant | Version | Source |
|---|---|---|
| Python (images) | 3.12 (`python:3.12-slim`) | `nexus-core/Dockerfile`, `nexus-bridge/Dockerfile` |
| FastAPI / Starlette / Uvicorn | 0.162.0 / 1.7.0 / 0.54.0 | `nexus-core/requirements.txt` |
| SQLAlchemy / psycopg / Pydantic / httpx / PyYAML | 2.0.56 / 3.3.7 / 2.13.5 / 0.28.1 / 6.0.3 | `nexus-core/requirements.txt` |
| pytest | 9.1.1 | `nexus-core/requirements.txt` |
| nexus-core (application) | 1.0.0 (titre FastAPI) | `nexus-core/app/main.py` |
| nexus-bridge | 1.0.0 | `nexus-bridge/app/main.py` (`VERSION`) |
| Protocole NEXUS | **1.0.0** | `protocole/VERSION` |
| MCP (versions acceptées) | 2025-06-18, 2025-03-26, 2024-11-05 | `nexus-bridge/app/main.py` |
| Caddy | 2.8 | `docker-compose.yml` |
| Ollama | 0.40.12 (modèle local `qwen2.5:3b`) | `docker-compose.yml` |
| Ollama Cloud | modèle par défaut `gemma4:31b` | `nexus-core/app/config.py` |
| n8n (mode complet) | 2.45.6 | `docker-compose.yml` |
| PostgreSQL + pgvector (mode complet) | `pgvector/pgvector:pg16` | `docker-compose.yml` |
| Redis (mode complet) | 7-alpine | `docker-compose.yml` |
| ntfy (mode complet) | v2.11.0 | `SPEC.md` |
| Uptime Kuma (mode complet) | 1 | `SPEC.md` |
| Modèles F4 (payants) | `claude-sonnet-5-5` (ANALYST, CHECKER), `claude-haiku-5-5` (autres rôles) | `nexus-core/fonctionnement.yaml` |

## 5. Arborescence utile

```
espacetravail-public/
├── nexus-core/            noyau FastAPI (app/*.py), 93 fiches agents (agents/), chartes/, projets.yaml, fonctionnement.yaml, tests/
├── nexus-bridge/          passerelle MCP (app/*.py), tests/
├── protocole/             Protocole NEXUS v1 : schemas/, exemples/, valider.py, tests/
├── veille/                « méga-base » de veille : catalogue (322 sources), collecteur, recherche, tests/
├── compaction/            banc de mesure de la compaction (module : nexus-core/app/compaction.py)
├── banc-essai/            banc qualité (30 missions de référence, notation)
├── simulations/           103 scénarios de spécification
├── iterations-100/        méthode des 100 itérations (18 oracles)
├── charge-200/            campagne « SYFER à 200 % » (25 scénarios)
├── securite-ia/           attaque simulée du bouclier (corpus mensuel)
├── jumeau-numerique/      SYFER ÉCHO (19 scénarios, 92 hypothèses)
├── syfer-test-system/     système de test unifié, score et porte de qualité
├── automatisations/       veille cyber hebdomadaire
├── outils-depots/         séparation en 4 dépôts
├── n8n/workflows/         3 workflows (mode complet)
├── .github/workflows/     intégration continue
├── install.sh, partitions.sh, backup.sh, restore.sh, exercice-restauration.sh, uninstall.sh, bridge-connecteurs.sh
├── docker-compose.yml, docker-compose.complet.yml, Caddyfile.mvp, Caddyfile.complet, .env.example
└── README.md, SPEC.md
```

## 6. Historique du document

| Version | Date | Objet |
|---|---|---|
| 2.0 | 2026-11-04 | Première rédaction complète pour SYFER V2 (état de la branche `v2`). |
