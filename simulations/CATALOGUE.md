# Catalogue des 103 simulations SYFER

Ce dossier fait « vivre » la structure SYFER (nexus-core) dans des **simulations virtuelles** : de fausses missions, une fausse IA dont on écrit les réponses à l'avance (bonne, mauvaise, piégée, en panne), une fausse horloge. Rien ne sort de l'ordinateur, rien n'est payé, aucune donnée personnelle ni vrai secret n'est utilisé.

## Mode d'emploi (3 commandes)

Depuis la racine du dépôt (Python 3.11 ou plus, dépendances de `nexus-core/requirements.txt` installées) :

```bash
cd simulations
python3 simuler.py
cat resultats/*.md | less
```

1. `cd simulations` : se placer dans ce dossier.
2. `python3 simuler.py` : lance les 103 scénarios (moins de 30 secondes). Chaque ligne affiche OK, ÉCHEC ou SAUTÉ.
3. Lire le rapport `resultats/AAAA-MM-JJ_HHMM.md` : bilan par méthode et, pour chaque échec, ce qui était **attendu** et ce qui a été **obtenu**.

Variantes utiles :

- une seule méthode : `python3 simuler.py --methode decideur` (ou `--methode 9`) ;
- quelques scénarios : `python3 simuler.py --id SIM-012,SIM-085` ;
- seulement les critiques : `python3 simuler.py --criticite critique` ;
- résultat brut pour un autre outil : `python3 simuler.py --json` ;
- vérifier le fichier de scénarios : `python3 simuler.py --valider` ; tests du dossier : `python3 -m pytest -q tests`.

**Un échec n'est pas une panne du simulateur** : c'est un écart entre le comportement attendu de SYFER et le code actuel. Le code de nexus-core n'est jamais modifié pour faire passer un scénario.

**Décisions N3 : uniquement via le cockpit.** Valider, refuser ou réviser passe par `/cockpit/api/decisions/…` (en-têtes `X-Cockpit-Auth` et `X-Cockpit: 1`, corps JSON, code Décideur pour un risque élevé). La clé API (passerelle IA, n8n) est refusée (403, tracé au LEDGER) : c'est ce que vérifient SIM-101 à SIM-103.

## Vocabulaire

- **Mode** : *hors ligne* = les fonctions de nexus-core sont appelées directement ; *API factice* = l'application nexus-core est démarrée sur l'ordinateur (base temporaire, IA factice) et interrogée comme le ferait le cockpit ; *VPS* = réservé à un essai réel sur le serveur, jamais lancé ici.
- **Prérequis** : module de nexus-core nécessaire (charte, leçons, bouclier, archive, pilote, passerelle). S'il manque, le scénario est *sauté* proprement, avec la raison.
- **Criticité** : critique (argent, sécurité, validation humaine), haute, moyenne, basse.

Répartition : 10 scénarios par méthode, 13 pour le Décideur (3 de non-régression) · modes : 80 hors ligne, 23 API factice, 0 VPS · criticité : 41 critiques, 46 hautes, 14 moyennes, 2 basses.

## 1. Routage PRIME

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-001 | Article de blog Poker Winners → rédaction | haute | hors ligne | — |
| SIM-002 | « Code du travail » → droit français, pas revue de code | haute | hors ligne | — |
| SIM-003 | Égalité RGPD / faille : départage par priorité | haute | hors ligne | — |
| SIM-004 | Égalité : l'avis PRIME choisit parmi les candidats | moyenne | hors ligne | — |
| SIM-005 | Égalité : avis PRIME hors candidats ignoré | haute | hors ligne | — |
| SIM-006 | Égalité avec IA PRIME en panne | haute | hors ligne | — |
| SIM-007 | Multi-domaines : score pondéré par la longueur des expressions | moyenne | hors ligne | — |
| SIM-008 | Aucun mot-clé : décision du LLM PRIME | moyenne | hors ligne | — |
| SIM-009 | Aucun mot-clé et réponse PRIME illisible → service par défaut | basse | hors ligne | — |
| SIM-010 | Service imposé valide respecté, service inconnu refusé (API) | haute | API factice | — |

## 2. Niveaux de décision GATE N0–N3

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-011 | Montant écrit dans la consigne → N3 | critique | hors ligne | — |
| SIM-012 | Virement de 300 € : mission complète jusqu'à la fiche N3 | critique | hors ligne | — |
| SIM-013 | Négations : « sans aucun paiement ni publication » | haute | hors ligne | — |
| SIM-014 | « Ne pas oublier de payer » reste N3 | critique | hors ligne | — |
| SIM-015 | Post LinkedIn N2, action « publier » N3 | haute | hors ligne | — |
| SIM-016 | « Envoyez-moi la synthèse » = envoi au propriétaire → N0 | moyenne | hors ligne | — |
| SIM-017 | Juridique : plancher N2, tiers → N3 | critique | hors ligne | — |
| SIM-018 | Cyber : N2, recommandation pare-feu dans le livrable → N3 | critique | hors ligne | — |
| SIM-019 | RSE : communication externe N3, note interne non N3 | haute | hors ligne | — |
| SIM-020 | L'avis LLM ne fait que monter ; données sensibles → N3 | critique | hors ligne | — |

## 3. Niveaux de fonctionnement F1–F4

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-021 | F1 relevé en F2 par le pré-classement N2 | haute | hors ligne | — |
| SIM-022 | Droit : plancher F3 et double contrôle | haute | hors ligne | — |
| SIM-023 | Plafond de tokens F1 : arrêt propre, proposition F2 | critique | hors ligne | — |
| SIM-024 | Plafond de délai F1 (horloge simulée) | haute | hors ligne | — |
| SIM-025 | F4 à budget 0 € : repli F3 annoncé | critique | API factice | — |
| SIM-026 | F4 à budget 0 € sans repli : refus 422, rien créé | haute | API factice | — |
| SIM-027 | F4 disponible : décision de lancement avant toute dépense | critique | API factice | — |
| SIM-028 | Double contrôle F3 : le second contrôleur refuse puis valide | haute | hors ligne | — |
| SIM-029 | Double contrôle indisponible : tracé, jamais silencieux | moyenne | hors ligne | — |
| SIM-030 | Refus répétés en F2 → relance automatique unique en F3 | haute | hors ligne | — |

## 4. Charte projet et qualité

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-031 | Poker Winners : « Red Cards » bloquant | haute | hors ligne | charte |
| SIM-032 | Poker Winners : « Poker Feeling » = simple avertissement | moyenne | hors ligne | charte |
| SIM-033 | Poker Feeling : mention ANJ obligatoire en publication | critique | hors ligne | charte |
| SIM-034 | « À COMPLÉTER » : bloquant en publication, avertissement en interne | haute | hors ligne | charte |
| SIM-035 | Mention avocat ajoutée à tout avis juridique | critique | hors ligne | charte |
| SIM-036 | Vouvoiement exigé (Poker Winners), tutoiement permis (REDKARDS) | moyenne | hors ligne | charte |
| SIM-037 | REDKARDS : circuit réel (WSOP) interdit | haute | hors ligne | charte |
| SIM-038 | Pipeline : marque mélangée corrigée avant le CHECKER | critique | hors ligne | charte |
| SIM-039 | Freelance IA : promesses et références clients | haute | hors ligne | charte |
| SIM-040 | Exemple d'un autre projet jamais injecté s'il viole la charte | haute | hors ligne | charte |

## 5. Mémoire collective et leçons

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-041 | Signal répété → leçon proposée au seuil (3) | haute | hors ligne | lecons |
| SIM-042 | Validation par le propriétaire seulement après proposition | haute | hors ligne | lecons |
| SIM-043 | Injection bornée des leçons (≤ 5 et ≤ 800 caractères) | haute | hors ligne | lecons |
| SIM-044 | Suspension automatique d'une leçon en cas de régression | haute | hors ligne | lecons |
| SIM-045 | Sous le seuil : candidate ; une mission compte une seule fois | moyenne | hors ligne | lecons |
| SIM-046 | Effacement RGPD : archive ET mémoire du projet | critique | hors ligne | archive |
| SIM-047 | Connaissance contenant un secret refusée (API) | critique | API factice | — |
| SIM-048 | Extraits de mémoire bornés selon le niveau F | moyenne | hors ligne | — |
| SIM-049 | Exemples : au plus 3 actifs par service | basse | hors ligne | — |
| SIM-050 | Mémorisation automatique du livrable (désactivable) | moyenne | hors ligne | — |

## 6. Sécurité IA / injection

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-051 | Injection directe dans la consigne : GATE ne se laisse pas descendre | critique | hors ligne | — |
| SIM-052 | Injection via le contenu collecté : aucune auto-validation | critique | hors ligne | — |
| SIM-053 | Injection indirecte via une connaissance stockée | critique | hors ligne | bouclier |
| SIM-054 | Exfiltration d'un canari détectée en sortie | critique | hors ligne | bouclier |
| SIM-055 | Injection demandant un changement de niveau F (F4 gratuit) | haute | hors ligne | — |
| SIM-056 | Secret produit par l'IA hors cybersécurité : jamais stocké | critique | hors ligne | — |
| SIM-057 | « Désactiver le GATE » refusé par la charte SYFER | haute | hors ligne | charte |
| SIM-058 | Contenu collecté hostile rejeté et journalisé | critique | hors ligne | bouclier |
| SIM-059 | Sortie suspecte : jamais N0/N1 ni terminée en silence | critique | hors ligne | bouclier |
| SIM-060 | Valider une N3 sans clé ni passage par Caddy : refusé | critique | API factice | — |

## 7. Cybersécurité défensive

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-061 | Mission CYBER-FORTRESS légitime : audit Caddy | haute | hors ligne | — |
| SIM-062 | Demande offensive refusée (reverse shell) | critique | hors ligne | — |
| SIM-063 | Secret dans un livrable cyber : refusé et masqué partout | critique | hors ligne | — |
| SIM-064 | Recommandation pare-feu → N3 à risque élevé | critique | hors ligne | — |
| SIM-065 | Incident : rotation des clés → service incident et N3 | haute | hors ligne | — |
| SIM-066 | Veille CVE : égalité veille/R&D tranchée vers la cybersécurité | moyenne | hors ligne | — |
| SIM-067 | Texte défensif non bloqué | moyenne | hors ligne | — |
| SIM-068 | Masquage : gabarit conservé, vrai mot de passe masqué | haute | hors ligne | — |
| SIM-069 | Notification CNIL 72 h → conformité cyber, N3 | haute | hors ligne | — |
| SIM-070 | Clé privée : refusée en ajout manuel, masquée à l'import | critique | hors ligne | — |

## 8. Continuité

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-071 | Redémarrage pendant une mission | critique | hors ligne | — |
| SIM-072 | File d'attente pleine : places limitées, ordre FIFO | haute | hors ligne | — |
| SIM-073 | IA cloud en panne → repli sur l'IA locale | critique | hors ligne | — |
| SIM-074 | IA cloud en panne sans repli : erreur claire sans fuite de clé | haute | hors ligne | — |
| SIM-075 | IA locale absente : F1 relevé en F2 | haute | hors ligne | — |
| SIM-076 | LEDGER falsifié détecté | critique | hors ligne | — |
| SIM-077 | LEDGER : entrée non signée après des entrées HMAC (déclassement) | critique | hors ligne | — |
| SIM-078 | Double clic simultané Valider / Refuser | critique | hors ligne | — |
| SIM-079 | Sauvegarde puis restauration à blanc | critique | hors ligne | — |
| SIM-080 | Panne LLM en pleine mission : jamais bloquée « en_cours » | haute | hors ligne | — |

## 9. Décideur

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-081 | Sessions N3 groupées : une seule notification par session | haute | hors ligne | — |
| SIM-082 | Urgence : notification immédiate (< 4 h) | haute | hors ligne | — |
| SIM-083 | Expiration 24 h = refus par défaut | critique | hors ligne | — |
| SIM-084 | Plafond de 15 décisions N3 par jour | haute | hors ligne | — |
| SIM-085 | Risque élevé : code Décideur à 6 chiffres exigé | critique | API factice | — |
| SIM-086 | 5 codes faux → verrou de 15 minutes | critique | API factice | — |
| SIM-087 | Anti-CSRF : écritures hors cockpit refusées | critique | API factice | — |
| SIM-088 | La passerelle IA ne peut pas valider une N3 | critique | hors ligne | passerelle |
| SIM-089 | Jeton de confirmation : lié au choix et à usage unique | haute | API factice | — |
| SIM-090 | Lancement F4 : carte claire, révision impossible, refus sans dépense | haute | API factice | — |
| SIM-101 | Non-régression : décider avec la clé API est refusé (403) et tracé | critique | API factice | — |
| SIM-102 | Non-régression : cockpit sans code pour un risque élevé refusé | critique | API factice | — |
| SIM-103 | Non-régression : cockpit avec le bon code accepté | critique | API factice | — |

## 10. Projets réels et pilotage

| Id | Titre | Criticité | Mode | Prérequis |
|---|---|---|---|---|
| SIM-091 | Poker Feeling : plan du chapitre 3 | haute | API factice | charte |
| SIM-092 | Poker Feeling : quatrième de couverture sans fausse disponibilité | haute | API factice | charte |
| SIM-093 | REDKARDS : synopsis d'épisode (tutoiement de BD permis) | moyenne | API factice | charte |
| SIM-094 | REDKARDS : annonce à publier → N3, risque moyen | haute | API factice | — |
| SIM-095 | Poker Winners : page « À propos » et compteur projet | moyenne | API factice | charte |
| SIM-096 | Poker Winners : e-mail aux testeurs de la bêta → N3 | haute | API factice | charte |
| SIM-097 | Top Solver : spécification, usage entraînement uniquement | haute | API factice | charte |
| SIM-098 | SYFER : plan de déploiement V2 (N3, pas d'automatisme) | critique | API factice | charte |
| SIM-099 | Freelance IA : devis de 2 400 € (prospect fictif) | haute | API factice | charte |
| SIM-100 | Pilote hebdomadaire : plan consolidé, rien lancé sans accord | haute | hors ligne | pilote |

## Fichiers

- `scenarios.json` : les 103 scénarios (préparation, étapes, perturbations, attendus, mesures).
- `schema.json` : format attendu de `scenarios.json` (JSON Schema).
- `simuler.py` : le moteur (IA factice scriptable, horloge simulée, base temporaire par scénario).
- `resultats/` : un rapport `.json` et `.md` par lancement.
- `tests/test_simulations.py` : contrôle du format, des identifiants, de la répartition et d'un sous-ensemble.
