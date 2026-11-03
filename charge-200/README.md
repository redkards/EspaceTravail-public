# charge-200 — « SYFER à 200 % »

Faire travailler nexus-core (et nexus-bridge) à **2 fois sa charge normale, puis au-delà jusqu'à la
rupture**, pour trouver les goulots et les défauts **avant** la production. Rien n'est corrigé ici :
les défauts trouvés sont des résultats (voir `resultats/rapport.md`).

## Ce qu'il y a dans le dossier

| Fichier | Rôle |
|---|---|
| `scenarios.yaml` | La charge nominale et les **25 scénarios** (charge visée, durée, mix de missions, fautes, critères chiffrés). |
| `charge.py` | Le moteur : lance nexus-core en local, envoie la charge, injecte les fautes, mesure, vérifie l'intégrité. |
| `serveur.py` | Lance nexus-core ou nexus-bridge dans un processus à part, avec un **LLM factice réglable** (lenteur, pannes, tokens). |
| `rapport.py` | Fabrique `resultats/rapport.md` et les graphiques à partir du JSON de résultats. |
| `analyse.md` | L'analyse experte (goulots, corrections, capacité KVM 2 / KVM 8, réglages), insérée en tête du rapport. |
| `tests/` | Tests rapides du générateur (`pytest`). |
| `resultats/` | `AAAA-MM-JJ_HHMM.json` (toutes les mesures), `rapport.md`, graphiques `.png`. |

## Lancer

```bash
cd charge-200
python3 -m pytest -q tests          # 1 s : vérifie le générateur
python3 charge.py --lister          # liste des 25 scénarios
python3 charge.py --ids S01,S05     # quelques scénarios
python3 charge.py --rapide          # toute la campagne, durées ÷ 3 (≈ 10 min)
python3 charge.py                   # campagne complète (≈ 25-30 min sur 2 vCPU)
python3 rapport.py                  # refait le rapport depuis le dernier JSON
```

Prérequis : Python 3.11+, les dépendances de nexus-core (`nexus-core/requirements.txt`) et de
nexus-bridge, `pyyaml`, `httpx`. Facultatif : `psutil` (sinon lecture de `/proc`), `matplotlib`
(sinon graphiques SVG simples). Le scénario « disque presque plein » monte un petit `tmpfs` : il
faut être root, sinon il est **sauté** avec la raison.

Aucun réseau n'est utilisé, aucune donnée réelle, aucun crédit dépensé : bases SQLite temporaires,
LLM factice, faux secrets et faux canaris.

## Comment ça marche (simplement)

1. **Charge nominale** (définie dans `scenarios.yaml`) : 40 missions/jour, pic du lundi 15 missions/h,
   2 sessions de décision N3/jour (plafond 15), veille 4 collectes/jour, 3 IA sur la passerelle.
   « 200 % » = deux fois le **pic** (30 missions/h), sauf mention contraire.
2. **Temps accéléré** : nexus-core n'a pas d'horloge réglable. On comprime donc le temps d'un facteur
   C : les missions arrivent C fois plus vite et chaque appel au LLM factice dure C fois moins
   (hypothèse : 15 s par appel réel). Les tâches de fond (expirations N3, rappels) tournent aussi C
   fois plus vite. Le travail propre de nexus-core (base, LEDGER, archive) n'est pas accéléré : il pèse
   donc *plus* lourd qu'en vrai — les résultats sont prudents.
3. **Pendant la charge**, des fils simulent le cockpit, les 3 IA (MCP), la mémoire collective, les
   effacements RGPD, le Décideur en double clic, la sauvegarde, la veille… et des **fautes** sont
   injectées : arrêt brutal (`kill -9`), LLM lent ou en panne, disque plein.
4. **Après la charge**, on attend que la file se vide puis on vérifie, en lisant directement la base
   et les fichiers : chaîne du LEDGER recalculée (indépendamment du code de nexus-core), archive
   chaînée, aucune mission perdue, dupliquée ou bloquée, compteurs de tokens exacts, plafond N3 tenu,
   aucun secret ni canari stocké.

## Lire les résultats

- `resultats/rapport.md` : synthèse, analyse experte, tableau des 25 scénarios, détails.
- Un scénario est **réussi** si tous ses critères chiffrés sont tenus ; sinon le rapport dit lesquels.
- « Débit tenu » = part des missions offertes réellement traitées ; « p95 » = 95 % des requêtes sont
  plus rapides que cette valeur.

## Limites à garder en tête

- **Le LLM est factice** : les durées de bout en bout dépendent surtout du vrai modèle (Ollama local
  ou cloud). Le temps LLM réel est à prendre dans le **jumeau numérique** ; ici on mesure la
  plateforme autour du LLM et ses comportements sous pression.
- Machine de test ≈ KVM 2 (2 vCPU, 8 Go) ; SQLite (pas PostgreSQL) ; pas de Caddy ni de Docker.
- L'endurance « 24 h » est simulée en ≈ 2 minutes réelles (volume réel, cadence comprimée).
