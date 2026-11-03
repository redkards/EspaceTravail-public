# Méthode des 100 itérations de mini-scénarios

Tests internes pour durcir SYFER (nexus-core), sans réseau et sans toucher au code testé.

## La méthode en 5 lignes

1. On tire au hasard (graine reproductible) des **mini-scénarios** de 1 à 5 actions en combinant des briques réalistes (`briques.yaml` : service, projet, consigne, montant, verbe, niveau F, contenu, réponse de l'IA, geste du Décideur, événement).
2. Chaque mini-scénario tourne dans le bac à sable de `simulations/simuler.py` (base temporaire, IA factice) et des **oracles** vérifient 18 invariants qui doivent toujours tenir (`oracles.md`).
3. Chaque violation est **réduite** automatiquement au plus petit cas qui échoue encore, puis **dédoublonnée** par cause et enregistrée dans `defauts/<id>.json`.
4. Les itérations suivantes tirent plus souvent les briques des défauts trouvés (**exploration guidée**).
5. On arrête quand **100 itérations consécutives** ne trouvent plus rien de nouveau ; les défauts sont des résultats à corriger dans nexus-core.

## Lancer

```bash
cd iterations-100
python3 iterer.py --iterations 100 --taille 20 --graine 2026      # environ 15 min
python3 iterer.py --jusqu-a-stabilite --max-iterations 400        # critère de sortie complet
python3 -m pytest -q tests                                        # tests de la méthode
```

Résultats : `resultats/AAAA-MM-JJ_HHMM.json` (tout le détail), `rapport.md` (courbes, défauts du plus grave au moins grave, couverture).

## Rejouer un défaut

```bash
python3 iterer.py --rejouer O02-e6d9268e       # l'identifiant est le nom du fichier dans defauts/
```

- « REPRODUIT » (code de sortie 1) : le défaut existe toujours ; la fiche donne le cas minimal, l'observé, l'attendu et le fichier:ligne probable.
- « NON REPRODUIT » (code 0) : l'oracle tient, le défaut est corrigé.

## Fichiers

| Fichier | Rôle |
|---|---|
| `briques.yaml` | Briques et vérité attendue (verbe sensible ou nié, montant réel…) |
| `generateur.py` | Tirage reproductible des mini-scénarios et de leurs textes |
| `executer.py` | Exécution dans le bac à sable `simuler.Bac` (réutilisé, non réécrit) |
| `oracles.py` / `oracles.md` | Les invariants et leur justification |
| `iterer.py` | Itérations, réduction, dédoublonnage, exploration guidée, rapport |
| `defauts/` | Un fichier JSON par défaut unique |
| `tests/` | Reproductibilité, réduction, oracles sur cas connus |
