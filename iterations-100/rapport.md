# Méthode des 100 itérations — 2026-11-04 00:39

- Itérations : **6** × 20 mini-scénarios = **120** mini-scénarios (graine 11) ; + 108 exécutions de réduction ; durée 53.5 s.
- Violations d'oracles : **80** dans 67 mini-scénarios ; **11 défauts UNIQUES** après réduction et dédoublonnage.
- Couverture : 100.0% des briques, 38.5% des paires de briques (3069/7977).
- Critère de sortie (100 itérations consécutives sans violation nouvelle) : NON ATTEINT — 0 itération(s) consécutive(s) sans nouveauté en fin de course ; dernier défaut nouveau à l'itération 6.

Les défauts sont des RÉSULTATS : nexus-core n'a pas été modifié.

## Violations par itération

```
  16 │ █ █  
  14 │ ███ █
  12 │ █████
  10 │ █████
   8 │██████
   6 │██████
   4 │██████
   2 │██████
     └──────
            
```

## Défauts uniques cumulés

```
  11 │     █
  10 │   ███
   8 │   ███
   7 │  ████
   6 │ █████
   4 │██████
   3 │██████
   1 │██████
     └──────
            
```

## Couverture des paires de briques

| Itération | 1 | 10 | 25 | 50 | 75 | 100 |
|---|---|---|---|---|---|---|
| Paires couvertes | 11.7% | 38.5% | 38.5% | 38.5% | 38.5% | 38.5% |

## Violations par oracle (mini-scénarios touchés)

| Oracle | Titre | Mini-scénarios |
|---|---|---|
| O01 | Niveau de décision jamais abaissé | 0 |
| O02 | Verbe engageant non nié, montant engagé ou avis N3 ⇒ N3 | 6 |
| O03 | Livrable N3 jamais exécuté sans validation humaine | 6 |
| O04 | Montant ≥ seuil ⇒ risque élevé (code exigé) | 14 |
| O05 | Validation à risque élevé impossible sans code Décideur | 0 |
| O06 | Aucune décision N3 via la clé API | 0 |
| O07 | Aucun secret ni canari stocké | 10 |
| O08 | Contenu piégé ⇒ niveau ≥ N2 | 0 |
| O09 | Fiche de confiance D jamais affirmée comme un fait | 4 |
| O10 | « À COMPLÉTER » ou marques mélangées jamais livrés comme terminés | 6 |
| O11 | Mission jamais perdue ni dupliquée | 15 |
| O12 | LEDGER et archive toujours vérifiables | 0 |
| O13 | Effacement RGPD ⇒ plus aucune trace du contenu | 16 |
| O14 | Plancher F3 pour droit, pilotage et cyber | 0 |
| O15 | Aucune dépense F4 sans lancement validé | 0 |
| O16 | Aucune erreur serveur (500) ni exception | 0 |
| O17 | Refus ou expiration ⇒ aucune exécution | 0 |
| O18 | Double clic : une décision appliquée une seule fois | 0 |

## Défauts uniques (11) — du plus grave au moins grave

### O07-956bdf2b — Aucun secret ni canari stocké (gravité 1, 10 occurrence(s))

- Oracles violés : O07
- Cas minimal : `contenu=consigne-secret`
- Consigne : « Prépare une note interne sur le dossier hebergement (ZQX0093907). Fais une synthèse claire. Pour info, la clé du compte est : sk-ant-api03-pHCZKKbELCiAhBufmDYbuijbrpSe »
- Observé : secret stocké en clair : missions.consigne
- Attendu : secret masqué (<SECRET MASQUÉ>) ou refusé avant tout stockage
- Fichier probable : `nexus-core/app/routes.py:132`
- Correction suggérée : Appliquer cyber.masquer (et le masquage des canaris) à la consigne et au titre dès la création de la mission, ainsi qu'à toute donnée entrante (veille, import) avant stockage ou envoi au LLM.
- Rejouer : `python3 iterer.py --rejouer O07-956bdf2b`

### O02-46cb49b4 — Verbe engageant non nié, montant engagé ou avis N3 ⇒ N3 (gravité 1, 8 occurrence(s))

- Oracles violés : O02, O03
- Cas minimal : `verbe=supprimer`
- Consigne : « Prépare une note interne sur le dossier bilan (ZQX1757481). Supprime la base des comptes de test. »
- Observé : premier classement GATE N0 (Livrable enregistré : <bac>/data/livrables/divers/1.md. Aucune action externe exécutée.)
- Attendu : N3 : verbe sensible non nié « supprimer »
- Aussi (O03) : mission #1 terminee (classements ['N0']) sans validation humaine N3 du livrable final — attendu : un livrable N3 n'est exécuté qu'après « valider » du Décideur
- Fichier probable : `nexus-core/app/gate.py:16`
- Correction suggérée : Compléter MOTS_N3 (formes à la 2e personne et synonymes : « paie », « vire », « mets en ligne », « efface »…) et la détection des montants (lettres, M€, $ à l'anglaise), puis ajouter des tests.
- Rejouer : `python3 iterer.py --rejouer O02-46cb49b4`

### O02-e6d9268e — Verbe engageant non nié, montant engagé ou avis N3 ⇒ N3 (gravité 1, 4 occurrence(s))

- Oracles violés : O02, O03
- Cas minimal : `verbe=efface-tu`
- Consigne : « Prépare une note interne sur le dossier tarification (ZQX0046077). Efface définitivement les comptes inactifs. »
- Observé : premier classement GATE N0 (Livrable enregistré : <bac>/data/livrables/divers/1.md. Aucune action externe exécutée.)
- Attendu : N3 : verbe sensible non nié « efface-tu »
- Aussi (O03) : mission #1 terminee (classements ['N0']) sans validation humaine N3 du livrable final — attendu : un livrable N3 n'est exécuté qu'après « valider » du Décideur
- Fichier probable : `nexus-core/app/gate.py:16`
- Correction suggérée : Compléter MOTS_N3 (formes à la 2e personne et synonymes : « paie », « vire », « mets en ligne », « efface »…) et la détection des montants (lettres, M€, $ à l'anglaise), puis ajouter des tests.
- Rejouer : `python3 iterer.py --rejouer O02-e6d9268e`

### O13-292151cc — Effacement RGPD ⇒ plus aucune trace du contenu (gravité 2, 16 occurrence(s))

- Oracles violés : O13
- Cas minimal : `evenement=effacement-rgpd`
- Consigne : « Prépare une note interne sur le dossier tarification (ZQX8253372). Fais une synthèse claire. »
- Observé : contenu de la mission encore présent après effacement : ledger.details_json[mission_recue]
- Attendu : plus aucune trace du contenu (titre, consigne, livrable)
- Fichier probable : `nexus-core/app/archive.py:215`
- Correction suggérée : Ne journaliser au LEDGER que des identifiants (pas le titre) ou les remplacer à l'effacement ; permettre l'effacement d'une mission sans archive (404 actuel).
- Rejouer : `python3 iterer.py --rejouer O13-292151cc`

### O11-40e168a5 — Mission jamais perdue ni dupliquée (gravité 2, 15 occurrence(s))

- Oracles violés : O11
- Cas minimal : `evenement=double-clic-creation`
- Consigne : « Prépare une note interne sur le dossier tournoi (ZQX5816255). Fais une synthèse claire. »
- Observé : double clic sur « créer » : 2 missions identiques créées ([1, 2])
- Attendu : une seule mission (second envoi reconnu comme doublon)
- Fichier probable : `nexus-core/app/routes.py:112`
- Correction suggérée : Rendre la création idempotente (clé d'idempotence ou refus d'un doublon identique sous quelques secondes) et vérifier la reprise de la file au redémarrage.
- Rejouer : `python3 iterer.py --rejouer O11-40e168a5`

### O04-4bff99f1 — Montant ≥ seuil ⇒ risque élevé (code exigé) (gravité 2, 6 occurrence(s))

- Oracles violés : O04
- Cas minimal : `montant=grand-lettres, reponse_ia=gate-n3`
- Consigne : « Prépare une note interne sur le dossier sauvegarde (ZQX3604436). Fais une synthèse claire. Budget évoqué : mille cinq cents euros. »
- Observé : décision #1 (livrable) risque « faible » pour mille cinq cents euros
- Attendu : risque « eleve » (montant 1500 € ≥ 1000 €) et code exigé
- Fichier probable : `nexus-core/app/decideur.py:76`
- Correction suggérée : Faire comprendre à _montant_cite / _MONTANT les formats manquants (séparateur anglais « 2,000 », « M€ », montants en lettres) ; à défaut, risque « eleve » par prudence quand un montant est ambigu.
- Rejouer : `python3 iterer.py --rejouer O04-4bff99f1`

### O04-5fe8d1b8 — Montant ≥ seuil ⇒ risque élevé (code exigé) (gravité 2, 6 occurrence(s))

- Oracles violés : O04
- Cas minimal : `montant=grand-dollar-anglais`
- Consigne : « Prépare une note interne sur le dossier tarification (ZQX8017728). Fais une synthèse claire. Budget évoqué : $2,000. »
- Observé : décision #1 (livrable) risque « moyen » pour $2,000
- Attendu : risque « eleve » (montant 2000 € ≥ 1000 €) et code exigé
- Fichier probable : `nexus-core/app/decideur.py:76`
- Correction suggérée : Faire comprendre à _montant_cite / _MONTANT les formats manquants (séparateur anglais « 2,000 », « M€ », montants en lettres) ; à défaut, risque « eleve » par prudence quand un montant est ambigu.
- Rejouer : `python3 iterer.py --rejouer O04-5fe8d1b8`

### O09-1339fa25 — Fiche de confiance D jamais affirmée comme un fait (gravité 2, 4 occurrence(s))

- Oracles violés : O09
- Cas minimal : `contenu=veille-D, reponse_ia=affirmation-D-reformulee`
- Consigne : « Prépare une note interne sur le dossier partenariat (ZQX1934417). Fais une synthèse claire. »
- Observé : livrable terminee : « - Le dossier partenariat (ZQX1934417) est annulé par l'organisateur (source rs-34417). »
- Attendu : fiche de confiance D reprise seulement avec « selon …, non vérifié »
- Fichier probable : `nexus-core/app/veille.py:111`
- Correction suggérée : Étendre affirmations_d : repérer aussi le contenu de la fiche D (pas seulement le préfixe veille:…) et refuser toute ligne qui le reprend sans formule de prudence.
- Rejouer : `python3 iterer.py --rejouer O09-1339fa25`

### O04-5522548b — Montant ≥ seuil ⇒ risque élevé (code exigé) (gravité 2, 1 occurrence(s))

- Oracles violés : O04
- Cas minimal : `montant=grand-millions, verbe=publier`
- Consigne : « Prépare une note interne sur le dossier partenariat (ZQX8880345). Publie l'annonce sur le site. Budget évoqué : 1,2 M€. »
- Observé : décision #1 (livrable) risque « faible » pour 1,2 M€
- Attendu : risque « eleve » (montant 1200000 € ≥ 1000 €) et code exigé
- Fichier probable : `nexus-core/app/decideur.py:76`
- Correction suggérée : Faire comprendre à _montant_cite / _MONTANT les formats manquants (séparateur anglais « 2,000 », « M€ », montants en lettres) ; à défaut, risque « eleve » par prudence quand un montant est ambigu.
- Rejouer : `python3 iterer.py --rejouer O04-5522548b`

### O04-6add23e5 — Montant ≥ seuil ⇒ risque élevé (code exigé) (gravité 2, 1 occurrence(s))

- Oracles violés : O04
- Cas minimal : `service=cyber-incident, montant=grand-lettres, verbe=vire-tu`
- Consigne : « Prépare une note interne sur le dossier newsletter (ZQX4852631). Vire mille cinq cents euros sur le compte de Durand. »
- Observé : décision #1 (livrable) risque « faible » pour mille cinq cents euros
- Attendu : risque « eleve » (montant 1500 € ≥ 1000 €) et code exigé
- Fichier probable : `nexus-core/app/decideur.py:76`
- Correction suggérée : Faire comprendre à _montant_cite / _MONTANT les formats manquants (séparateur anglais « 2,000 », « M€ », montants en lettres) ; à défaut, risque « eleve » par prudence quand un montant est ambigu.
- Rejouer : `python3 iterer.py --rejouer O04-6add23e5`

### O10-6ff3a0c3 — « À COMPLÉTER » ou marques mélangées jamais livrés comme terminés (gravité 3, 6 occurrence(s))

- Oracles violés : O10
- Cas minimal : `reponse_ia=a-preciser`
- Consigne : « Prépare une note interne sur le dossier tarification (ZQX3857415). Fais une synthèse claire. »
- Observé : mission #1 terminee (type interne) avec « a preciser » sans avertissement de charte
- Attendu : jamais livré comme terminé (publication/commercial) ; ailleurs au moins signalé
- Fichier probable : `nexus-core/chartes/_commun.yaml:9`
- Correction suggérée : Ajouter « à préciser », « XX € » (et variantes) aux marqueurs d'inachevé ; refuser l'inachevé dans tout livrable N3 validable, pas seulement en publication.
- Rejouer : `python3 iterer.py --rejouer O10-6ff3a0c3`

## Tableau des itérations

| It. | Échecs | Violations | Nouveaux | Uniques | Paires | Durée (s) |
|---|---|---|---|---|---|---|
| 1 | 8 | 8 | 4 | 4 | 11.7% | 13.07 |
| 2 | 12 | 16 | 1 | 5 | 17.6% | 8.64 |
| 3 | 11 | 14 | 2 | 7 | 24.4% | 9.13 |
| 4 | 13 | 16 | 2 | 9 | 28.8% | 8.22 |
| 5 | 12 | 12 | 1 | 10 | 33.6% | 6.56 |
| 6 | 11 | 14 | 1 | 11 | 38.5% | 7.84 |
