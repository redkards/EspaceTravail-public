# SYFER Test System v1

Le système de test **unifié** de SYFER : il lance toutes les épreuves existantes, calcule une fiche de
score sur 100, décide **VERT / ROUGE** (la porte de qualité qui autorise un déploiement) et produit un
rapport PDF en français.

## Les 3 commandes

```bash
cd syfer-test-system
python3 syfer_test.py tout            # toutes les épreuves (≈ 30 min, charge en mode court) + PDF
python3 syfer_test.py porte           # VERT ou ROUGE, avec les raisons (code 0 = déploiement autorisé)
python3 syfer_test.py version tous    # compare les 5 versions A à E avec la même graine + PDF
```

Le rapport est dans `resultats/<horodatage>/rapport.pdf`, les données dans `resultats/<horodatage>/syfer_test.json`.

## Autres commandes

| Commande | Rôle |
|---|---|
| `rapide` | sélection rapide (≤ 5 min) : mêmes épreuves, tailles réduites |
| `suite <nom>` | une seule épreuve : `tests`, `protocole`, `simulations`, `iterations`, `attaque`, `banc`, `charge`, `jumeau`, `compaction`, `statiques` (`--rapide` possible) |
| `version <A\|B\|C\|D\|E>` | les épreuves choisies par le profil (`--complet` pour le mode normal) |
| `rapport [dossier]` | refait le PDF du dernier passage (et de la dernière comparaison des versions) |
| `liste` | épreuves, profils, dossiers présents ou absents |

Options générales (avant la commande) : `--graine N` (défaut 2026), `--sans-pdf`. `tout`/`rapide` acceptent
`--version A..E` (profil appliqué, défaut A). Itérations paramétrables : `SYFER_ITER_N` et `SYFER_ITER_TAILLE`
(défaut : 100 × 5 en `tout`, 10 × 5 en `rapide`).

**Codes de sortie** : 0 tout vert / porte VERTE · 1 échec ou porte ROUGE · 2 usage invalide · 3 aucun résultat · 130 interruption.

## Ce qui est garanti

- **Le dépôt n'est jamais modifié** : chaque passage travaille dans une copie jetable (sans `.git`), avec des
  bases temporaires, un LLM factice et aucune variable sensible héritée (`NEXUS_*`, `ANTHROPIC_*`…).
- **Délai maximum par épreuve** : au-delà, le groupe de processus est tué et l'épreuve est notée « délai dépassé ».
- **Journal sans secret** (`journal.log`) : toute sortie passe par le filtre anti-secret de nexus-core.
- **Épreuves en construction** : un dossier ou un script absent est **sauté** avec la raison ; il est intégré
  automatiquement dès qu'il apparaît (détection à chaque passage, options détectées par `--help`).

## Les épreuves

| Épreuve | Commande lancée | Mesures clés |
|---|---|---|
| tests | `pytest -q` dans les 12 dossiers | verts / rouges par dossier |
| protocole | `protocole/valider.py --verifier-schemas`, `--agents`, exemples | conformité |
| simulations | `simulations/simuler.py --json --sans-fichier` (103 scénarios) | taux par méthode |
| iterations | `iterations-100/iterer.py --iterations N --taille T --graine G` | défauts ouverts par gravité |
| attaque | `securite-ia/attaque_simulee.py --mode hors-ligne` | taux de blocage, faux positifs |
| banc | `banc-essai/lancer.sh` contre un nexus-core **local** (LLM factice) | note système, pièges |
| charge | `charge-200/charge.py --rapide` (mode court) | critères, pertes de données |
| jumeau | `jumeau-numerique/lancer.py` + Monte Carlo du profil | score, coût, débit, N3/jour |
| compaction | `compaction/mesure.py` (corpus réduit) | gains, vérifications |
| statiques | `bash -n`, shellcheck, YAML/JSON, secrets, `docker compose config` | erreurs |

## Versions (`versions/*.json`)

Chaque profil = variables d'environnement nexus-core (`env`) + paramètres du jumeau numérique (`jumeau`) +
épreuves à lancer (`suites`). `version tous` rejoue pour chacune ce qui dépend de la configuration
(simulations, itérations, jumeau, charge) avec **la même graine**.

| | Profil | Résumé |
|---|---|---|
| A | Éco | KVM 2, 3B local, 30 rôles essentiels, sécurité standard, autonomie faible, ≈ 10 €/mois |
| B | Local Pro | KVM 8, 7–8B local, double modèle, 93 rôles |
| C | Hybride | B + IA payante F4 plafonnée à 30 €/mois |
| D | Forteresse | 3 zones, admin Tailscale, double contrôle partout (F3 minimum), autonomie faible |
| E | Autonome Max | KVM 8 + vitrine, IA payante ≤ 80 €, pilote hebdo, veille complète, mémoire collective active |

## Score (`config/ponderation.json`, modifiable sans toucher au code)

Chaque axe est la moyenne pondérée de ses composantes (0–100) ; une composante absente est retirée et les
poids renormalisés (champ `couverture`). **Global = Σ(axe × poids) / Σ(poids des axes disponibles).**

| Axe (poids) | Composantes (poids) |
|---|---|
| Fiabilité (0,20) | tests 0,40 · simulations 0,30 · itérations 0,25 · protocole 0,05 |
| Sécurité (0,25) | attaque 0,35 (−10 par faux positif bloquant) · secrets 0,25 (−50 par suspect) · oracles sécurité 0,25 · porte N3 0,15 |
| Performance (0,10) | score du jumeau 0,5 · critères de charge 0,5 |
| Qualité (0,15) | note système du banc 0,5 · pièges 0,2 · charte (simulations) 0,3 · note livrable 0 (0,3 avec un vrai LLM) |
| Résilience (0,15) | continuité 0,3 · pannes en charge 0,25 · robustesse du jumeau (panne cloud, Décideur absent) 0,25 · restauration/intégrité 0,2 |
| Coût (0,075) | 100 × (1 − coût mensuel / 150 €) |
| Charge Décideur (0,075) | N3/jour 0,5 (2 → 100, 12 → 0) · expirations 0,25 · délai de décision 0,25 (6 h → 100, 24 h → 0) |

## Porte de qualité (`config/porte.json`)

Bloquants par défaut : tous les tests verts · simulations ≥ 99 % · 0 défaut critique ouvert (iterations-100) ·
attaque ≥ 95 % et 0 faux positif bloquant · 0 secret · banc sans baisse > 5 points vs le dernier passage ·
charge 200 % sans perte de données. Chaque critère : `actif`, `bloquant`, `si_absent` (`bloquant` = pas de
preuve, pas de déploiement ; ou `ignore`). Les valeurs factices volontaires (tests, corpus) sont listées dans
`config/secrets_autorises.json`.

## Schéma de `syfer_test.json` (`syfer-test/1`)

```
schema, systeme, version_systeme, horodatage, mode (tout|rapide|suite|version), graine, duree_s
profil {code, nom}                     depot {chemin, presence {dossier: bool}}
suites {nom: {nom, titre, statut (reussi|echoue|saute|erreur|delai), motif, duree_s, commandes[], mesures{}, defauts[]}}
score {axes {axe: {libelle, score, couverture, composantes{}}}, global, couverture_globale, formule}
indice_banc                            porte {verdict (VERT|ROUGE), criteres[{critere, libelle, etat, bloque, mesure, raison}], raisons[], deploiement_autorise}
defauts [{id, suite, gravite (critique|majeure|mineure|info), titre, preuve, correction, responsable}]
tendance [{horodatage, mode, global, verdict, axes{}}]
mode version : versions {code: {profil, suites, score, defauts}}, classement [codes], suites_comparees
```

## Tests de l'orchestrateur

```bash
python3 -m pytest -q        # formule de score, porte, agrégation, saut propre, secrets, PDF
```

## Limites

Banc local avec LLM factice (la note livrable ne mesure pas la qualité réelle : banc réel sur le VPS) ·
jumeau fondé sur des hypothèses · zones/Tailscale/nombre de rôles non simulables hors VPS · charge en mode
court (temps compressé).
