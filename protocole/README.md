# Protocole NEXUS v1

Contrat d'échange commun aux quatre produits NEXUS. Il décrit, en **JSON Schema draft 2020-12**, les objets
qui circulent entre le noyau (nexus-core), la passerelle MCP (nexus-bridge), la bibliothèque d'agents et les
outils (banc d'essai, automatisations, cockpit). Les schémas ont été **déduits du code existant** (routes
FastAPI, modèles SQLAlchemy, outils MCP), puis vérifiés sur des réponses réelles.

Version actuelle : voir `VERSION` (**1.0.0**).

## Contenu

| Fichier `schemas/` | Objet | Source dans le code |
|---|---|---|
| `commun` | types partagés (horodatage, code projet, service, N0–N3, F1–F4, statut…) | — |
| `mission-creation` / `mission-creation-reponse` | création de mission (POST /api/missions) | `routes.py` NouvelleMission, `creer_mission` |
| `mission` (+ `#liste`) | état d'une mission (GET /api/missions[/{id}]) | `routes._mission`, `models.Mission` |
| `etape` | étape du pipeline | `models.Etape` |
| `decision` (+ `#liste`, `#action`, `#actionReponse`, `#refusApi`) | décision N3, action du Décideur (cockpit) et refus 403 à la clé API | `routes._decision`, `pipeline.decider` |
| `livrable` | vue normalisée du livrable (porté par la mission en v1) | `Mission.livrable_texte`, outil `mothership_statut` |
| `connaissance` (+ `#liste`, `#ajout`, `#ajoutReponse`) | mémoire projet | `memoire.py`, `models.Connaissance` |
| `agent` (+ `#publique`, `#liste`) | fiche YAML d'agent et sa vue GET /api/agents | `agents.py`, `nexus-core/agents/*.yaml` |
| `evenement-ledger` (+ `#liste`, `#verification`) | journal chaîné SHA-256 / HMAC | `ledger.py` |
| `sante` | GET /api/sante | `main.sante_publique` (le cockpit ajoute `agents`, `arret_urgence`) |
| `fonctionnement` | GET /api/fonctionnement | `routes.lire_fonctionnement`, `fonctionnement.py` |
| `mcp-outils` | outils de la passerelle (20 en 1.0.0, liste dans `x-outils`) : `<outil>.entree` et `<outil>.sortie`, plus `erreur` | `nexus-bridge/app/outils.py`, `main._appeler` |

`exemples/` : instantané d'exemples **réels** (régénérable, voir plus bas), nommés `<cible>__<cas>.json`
(`#` remplacé par `@`). Les fichiers `_brut__*` servent seulement à rejouer nexus-core pour la passerelle.

## Principes

1. **Versionnement SemVer du protocole** (`VERSION`), indépendant des versions des produits :
   - **correctif** (1.0.x) : description, exemple, motif corrigé sans changer ce qui est accepté en pratique ;
   - **mineure** (1.x.0) : ajout d'un champ facultatif, d'un objet, d'un outil MCP, d'une valeur de statut ;
   - **majeure** (2.0.0) : champ retiré ou renommé, type changé, champ facultatif devenu obligatoire,
     sémantique modifiée. Une majeure impose une période où le serveur sert les deux formes.
2. **Compatibilité ascendante** : tout producteur 1.y doit rester lisible par un consommateur 1.x (x ≤ y).
   On n'ajoute que des champs facultatifs ; on ne retire rien dans une même majeure.
3. **Champs inconnus ignorés** (lecture tolérante) : les schémas de réponse ne ferment pas les objets
   (`additionalProperties` absent). Un client 1.0 qui reçoit un champ ajouté en 1.3 l'ignore.
   Les statuts de mission et objets de décision sont des chaînes **ouvertes** (motif + `x-valeurs-connues`) :
   une valeur inconnue se traite comme « en cours ». Les énumérations fermées sont réservées aux valeurs
   stables (N0–N3, F1–F4, risque, rôles d'agent).
4. **Écriture stricte** : les **entrées** des outils MCP gardent `additionalProperties: false` (la passerelle
   refuse un paramètre inconnu, avec un message en français) — c'est le contrat réellement appliqué.
5. **Aucun secret** dans un objet du protocole : ni clé, ni jeton, ni mot de passe. `sante` ne divulgue
   que le fournisseur et le nom du modèle.
6. **Validation humaine** : aucun objet du protocole ne permet à une IA de valider une décision N3 ; les
   outils MCP sont en lecture ou en création de mission uniquement.
7. Les horodatages sont en ISO 8601 UTC : nexus-core les écrit sans fuseau, nexus-bridge avec `+00:00`.
   Le motif commun accepte les deux.

Extensions non standard (ignorées par les validateurs) : `x-valeurs-connues`, `x-valeurs-dynamiques`,
`x-ecriture` (l'outil écrit dans le journal de la passerelle), `x-outils`.

## Compatibilité produits ↔ protocole

| Produit (dépôt) | Version produit | Protocole | Rôle vis-à-vis du protocole |
|---|---|---|---|
| **mini-mothership** (nexus-core, cockpit, banc-essai, automatisations) | 1.0.0 | **1.0** | **produit** mission, étape, décision, livrable, connaissance, ledger, santé, fonctionnement ; **consomme** les fiches agent |
| **nexus-bridge** (passerelle MCP) | 1.0.0 | **1.0** | **produit** `mcp-outils` ; **consomme** mission, décision, connaissance, projets via l'API de nexus-core |
| **nexus-agents** (93 fiches YAML) | 1.0.0 | **1.0** | **produit** les fiches `agent` |
| **nexus-mothership** (architecture, docs) | 1.0.0 | **1.0** | référence documentaire ; aucun code |

Règle : un produit déclare la plage de protocole qu'il accepte (ici `>=1.0 <2.0`). Tant que la majeure est 1,
les quatre dépôts peuvent évoluer séparément.

## Valider

Sans dépendance (moteur interne, sous-ensemble 2020-12 suffisant pour ces schémas), ou avec `jsonschema`
(≥ 4.18) s'il est installé — `--moteur auto` choisit tout seul :

```bash
python3 valider.py --liste                              # cibles disponibles
python3 valider.py mission reponse.json                 # code 0 si conforme, 1 sinon
python3 valider.py "mcp-outils#mothership_mission.entree" args.json
python3 valider.py --agents ../nexus-core/agents        # 93 fiches YAML (PyYAML requis)
python3 valider.py --verifier-schemas                   # $ref résolus, mots-clés pris en charge, méta-schéma
```

En Python : `from valider import valider, livrable_depuis_mission` → `valider(objet, "decision")` renvoie la
liste des erreurs (vide si conforme).

## Tests et exemples réels

```bash
python3 -m pytest -q          # depuis protocole/
```

Les tests lancent **nexus-core en local avec le LLM factice** (SQLite temporaire, aucun réseau) dans un
processus séparé, créent des missions (N1, devis N3 refusé à la clé API (403) puis validé via le cockpit avec le code Décideur, lancement F4 en attente — rien de payant n'est
appelé), une connaissance, lisent agents, ledger, santé, fonctionnement ; puis **nexus-bridge** est appelé en
MCP, ses requêtes vers nexus-core étant servies avec ces réponses réelles. Tout est validé avec les deux
moteurs. Un test vérifie aussi que les entrées MCP du protocole sont identiques aux schémas servis par la
passerelle. Si nexus-core n'est pas présent (dépôt nexus-bridge séparé), l'instantané `exemples/` est rejoué.

Régénérer l'instantané après une évolution volontaire :

```bash
rm -rf exemples && python3 produire_exemples.py core exemples && python3 produire_exemples.py bridge exemples
```

## Faire évoluer le protocole

1. Modifier le code **et** le schéma dans la même PR ; régénérer `exemples/`.
2. Ajuster `VERSION` selon les règles SemVer ci-dessus et noter le changement dans le CHANGELOG du dépôt.
3. `python3 valider.py --verifier-schemas && python3 -m pytest -q` doivent passer (la CI le fait).
