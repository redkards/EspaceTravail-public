# Méthode des 100 itérations — 2026-11-04 01:10

- Itérations : **10** × 20 mini-scénarios = **200** mini-scénarios (graine 2026) ; + 43 exécutions de réduction ; durée 44.5 s.
- Violations d'oracles : **44** dans 44 mini-scénarios ; **5 défauts UNIQUES** après réduction et dédoublonnage.
- Couverture : 100.0% des briques, 53.4% des paires de briques (4257/7977).
- Critère de sortie (100 itérations consécutives sans violation nouvelle) : NON ATTEINT — 1 itération(s) consécutive(s) sans nouveauté en fin de course ; dernier défaut nouveau à l'itération 9.

Les défauts sont des RÉSULTATS : nexus-core n'a pas été modifié.

## Violations par itération

```
   6 │ █  █   █ 
   5 │ █ ██ █ ██
   4 │ █ ██ █ ██
   4 │ █ ██ ████
   3 │ █████████
   2 │ █████████
   2 │ █████████
   1 │██████████
     └──────────
               1
```

## Défauts uniques cumulés

```
   5 │        ██
   4 │        ██
   4 │        ██
   3 │   ███████
   2 │   ███████
   2 │ █████████
   1 │██████████
   1 │██████████
     └──────────
               1
```

## Couverture des paires de briques

| Itération | 1 | 10 | 25 | 50 | 75 | 100 |
|---|---|---|---|---|---|---|
| Paires couvertes | 11.9% | 53.4% | 53.4% | 53.4% | 53.4% | 53.4% |

## Violations par oracle (mini-scénarios touchés)

| Oracle | Titre | Mini-scénarios |
|---|---|---|
| O01 | Niveau de décision jamais abaissé | 0 |
| O02 | Verbe engageant non nié, montant engagé ou avis N3 ⇒ N3 | 0 |
| O03 | Livrable N3 jamais exécuté sans validation humaine | 0 |
| O04 | Montant ≥ seuil ⇒ risque élevé (code exigé) | 0 |
| O05 | Validation à risque élevé impossible sans code Décideur | 0 |
| O06 | Aucune décision N3 via la clé API | 0 |
| O07 | Aucun secret ni canari stocké | 0 |
| O08 | Contenu piégé ⇒ niveau ≥ N2 | 0 |
| O09 | Fiche de confiance D jamais affirmée comme un fait | 0 |
| O10 | « À COMPLÉTER » ou marques mélangées jamais livrés comme terminés | 0 |
| O11 | Mission jamais perdue ni dupliquée | 21 |
| O12 | LEDGER et archive toujours vérifiables | 0 |
| O13 | Effacement RGPD ⇒ plus aucune trace du contenu | 23 |
| O14 | Plancher F3 pour droit, pilotage et cyber | 0 |
| O15 | Aucune dépense F4 sans lancement validé | 0 |
| O16 | Aucune erreur serveur (500) ni exception | 0 |
| O17 | Refus ou expiration ⇒ aucune exécution | 0 |
| O18 | Double clic : une décision appliquée une seule fois | 0 |

## Défauts uniques (5) — du plus grave au moins grave

### O11-31b6819a — Mission jamais perdue ni dupliquée (gravité 2, 21 occurrence(s))

- Oracles violés : O11
- Cas minimal : `service=ui, reponse_ia=a-completer, evenement=double-clic-creation`
- Consigne : « Prépare une note interne sur le dossier hebergement (ZQX1075416). Fais une synthèse claire. »
- Observé : double clic sur « créer » : 2 missions identiques créées ([1, 2])
- Attendu : une seule mission (second envoi reconnu comme doublon)
- Fichier probable : `nexus-core/app/routes.py:120`
- Correction suggérée : Rendre la création idempotente (clé d'idempotence ou refus d'un doublon identique sous quelques secondes) et vérifier la reprise de la file au redémarrage.
- Rejouer : `python3 iterer.py --rejouer O11-31b6819a`

### O13-a8149e86 — Effacement RGPD ⇒ plus aucune trace du contenu (gravité 2, 15 occurrence(s))

- Oracles violés : O13
- Cas minimal : `verbe=supprimer, decideur=valider-mobile-code, evenement=effacement-rgpd`
- Consigne : « Prépare une note interne sur le dossier hebergement (ZQX7178444). Supprime la base des comptes de test. »
- Observé : contenu de la mission encore présent après effacement : etat.valeur
- Attendu : plus aucune trace du contenu (titre, consigne, livrable)
- Fichier probable : `nexus-core/app/archive.py:248`
- Correction suggérée : Ne journaliser au LEDGER que des identifiants (pas le titre) ou les remplacer à l'effacement ; permettre l'effacement d'une mission sans archive (404 actuel).
- Rejouer : `python3 iterer.py --rejouer O13-a8149e86`

### O13-639e751a — Effacement RGPD ⇒ plus aucune trace du contenu (gravité 2, 5 occurrence(s))

- Oracles violés : O13
- Cas minimal : `montant=grand-centimes, decideur=valider-cockpit-code, evenement=effacement-rgpd`
- Consigne : « Prépare une note interne sur le dossier chapitre (ZQX6606936). Fais une synthèse claire. Budget évoqué : 1 250,50 €. »
- Observé : contenu de la mission encore présent après effacement : etat.valeur
- Attendu : plus aucune trace du contenu (titre, consigne, livrable)
- Fichier probable : `nexus-core/app/archive.py:248`
- Correction suggérée : Ne journaliser au LEDGER que des identifiants (pas le titre) ou les remplacer à l'effacement ; permettre l'effacement d'une mission sans archive (404 actuel).
- Rejouer : `python3 iterer.py --rejouer O13-639e751a`

### O13-73e9b6f5 — Effacement RGPD ⇒ plus aucune trace du contenu (gravité 2, 2 occurrence(s))

- Oracles violés : O13
- Cas minimal : `reponse_ia=gate-n3, decideur=valider-mobile-sans-code, evenement=effacement-rgpd`
- Consigne : « Prépare une note interne sur le dossier tarification (ZQX9746556). Fais une synthèse claire. »
- Observé : contenu de la mission encore présent après effacement : etat.valeur
- Attendu : plus aucune trace du contenu (titre, consigne, livrable)
- Fichier probable : `nexus-core/app/archive.py:248`
- Correction suggérée : Ne journaliser au LEDGER que des identifiants (pas le titre) ou les remplacer à l'effacement ; permettre l'effacement d'une mission sans archive (404 actuel).
- Rejouer : `python3 iterer.py --rejouer O13-73e9b6f5`

### O13-dcdf68f0 — Effacement RGPD ⇒ plus aucune trace du contenu (gravité 2, 1 occurrence(s))

- Oracles violés : O13
- Cas minimal : `fonctionnement=F4-disponible, evenement=effacement-rgpd`
- Consigne : « Prépare une note interne sur le dossier maquette (ZQX1833355). Fais une synthèse claire. »
- Observé : effacement refusé (HTTP 404) pour la mission #1 au statut en_attente_n3
- Attendu : droit à l'effacement exerçable pour toute mission existante
- Fichier probable : `nexus-core/app/routes_memoire.py:134`
- Correction suggérée : Ne journaliser au LEDGER que des identifiants (pas le titre) ou les remplacer à l'effacement ; permettre l'effacement d'une mission sans archive (404 actuel).
- Rejouer : `python3 iterer.py --rejouer O13-dcdf68f0`

## Tableau des itérations

| It. | Échecs | Violations | Nouveaux | Uniques | Paires | Durée (s) |
|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 1 | 1 | 11.9% | 6.56 |
| 2 | 6 | 6 | 1 | 2 | 19.1% | 7.33 |
| 3 | 3 | 3 | 0 | 2 | 25.3% | 5.59 |
| 4 | 5 | 5 | 1 | 3 | 31.1% | 3.56 |
| 5 | 6 | 6 | 0 | 3 | 35.4% | 3.35 |
| 6 | 3 | 3 | 0 | 3 | 39.4% | 2.31 |
| 7 | 5 | 5 | 0 | 3 | 43.2% | 3.16 |
| 8 | 4 | 4 | 0 | 3 | 47.2% | 4.39 |
| 9 | 6 | 6 | 2 | 5 | 50.8% | 5.49 |
| 10 | 5 | 5 | 0 | 5 | 53.4% | 2.81 |
