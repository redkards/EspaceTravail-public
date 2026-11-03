# Fiche contexte — Site « Poker Winners »

Sources : pages Notion « Poker Winners — Projet » et « PILOTE POKER WINNERS — Cadrage », dépôt public GitHub redkards/poker-vitrine (commit 3fb0452 du 31/10/2026, lecture seule). Résumé reformulé.

## Pitch
- Site communautaire et pédagogique de poker en français : « La communauté poker francophone ».
- Site **éducatif** : aucun jeu d'argent réel, aucun lien vers un opérateur.

## Pages (routes Angular)
- Accueil `/`, connexion, inscription, vérification e-mail, mon espace, suppression de compte (RGPD).
- Actualités `/actualites` (4 portées : France, International, tournois live, tournois en ligne).
- Vidéos `/videos` (vidéos sous licence libre CC BY, favoris ; vidéos Premium verrouillées).
- Leçons `/lecons` (3 niveaux, quiz de 5 questions) et tableaux de ranges `/lecons/ranges`.
- Calendrier des tournois `/calendrier` (France, Belgique, international).
- Forum `/forum` (modéré, signalement), recherche `/recherche`, profils publics `/membres/:pseudo`.
- Premium `/premium` (paiement en ligne pas encore ouvert).
- Pages légales : `/mentions-legales`, `/confidentialite`, `/cgu` ; `/cgv` et `/boutique` masquées tant que la boutique (v2) est désactivée.
- Pied de page : liens légaux + mention « Le jeu comporte des risques : endettement, dépendance… Appelez le 09 74 75 13 13 (appel non surtaxé). Interdit aux moins de 18 ans. »

## Stack technique
- Back : Symfony 7.4 (PHP 8.2), Doctrine, JWT + refresh, EasyAdmin, rate limiting, CSP/HSTS/CORS strict.
- Front : Angular 22 (Node 22), composants autonomes, SEO via titres et descriptions par route.
- Base : MariaDB 10.6 (Docker en local). Hébergement prévu : mutualisé o2switch.
- Dépôt : `backPoker/` (API), `frontPoker/` (Angular), `solver/` (moteur Rust expérimental), `docs/`, `deploy/`.
- Versions : SemVer ; code en 0.8.1 ; la mise en ligne publique sera la 1.0.0.

## RGPD et juridique (état constaté)
- Consentements, export des données, suppression confirmée par e-mail + anonymisation (pseudo remplacé par un libellé anonyme).
- Un seul fichier de configuration légale alimente mentions, confidentialité et CGU ; les champs Premium (prix, renouvellement, résiliation, rétractation) sont encore « À COMPLÉTER ».
- Éditeur : particulier non professionnel (adresse non publiée, art. 6 III-2 LCEN) ; hébergeur o2switch.
- À faire : section Premium des CGU, note de vigilance « jeux d'argent », crons RGPD et sauvegardes confirmés sur le serveur.

## État d'avancement (début novembre 2026)
- Bêta privée (sous-domaine protégé, non indexé), testée par le propriétaire seul.
- Pilote PARADOXX en cours : checklist de test solo → anomalies triées → thème « casino bleu azur » sur branche séparée → contrôle juridique → recette → v1.0.
- Hors pilote : paiement Stripe, boutique, solver.

## Règles du projet
- Rien n'est mis en ligne sans confirmation explicite du propriétaire.
- Aucun secret ni mot de passe dans le chat ou sur GitHub.
- Vidéos uniquement sous licence libre avec attribution.
