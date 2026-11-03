# Tous les projets — accès au Mini NEXUS MOTHERSHIP

Chaque mission porte un champ `projet` (code ci-dessous), choisi dans le sélecteur de projet du cockpit (https://srvXXXX.hstgr.cloud/cockpit) ou passé en 1er argument de `lancer-mission.sh`.
Les 3 projets poker ont des modèles prêts (`missions-modeles.json`) ; les autres utilisent le mode `libre` :
`./lancer-mission.sh <code> libre titre="..." consigne="..." service=<SERVICE>`.

Niveaux : N0 lecture/synthèse · N1 livrable interne · N2 publication sur charte ou code · N3 engageant (montant, envoi, publication, signature…) → décision obligatoire dans le cockpit.

| Code | Projet (registre du QG) | Services conseillés | Exemples de missions (niveau attendu) |
|---|---|---|---|
| `paradoxx` | PARADOXX SYSTÈME (ex STUDIO MASTER) et PARADOXX SYSTÈME DESIGN | OPS-CORE/projets, AGENT-FACTORY/evaluation, LEX-GUARD/conformite | Résumé de l'état des chantiers (N0) · checklist d'un cycle de missions (N1) · évaluation d'un livrable d'agent (N1) · contrôle AI Act / RGPD d'une procédure (N1) |
| `nexus` | vaisseauAmiral — Nexus × Paradox System ; kit Mini NEXUS MOTHERSHIP | CODE-CORE/revue, OPS-CORE/projets, R&D-PARADOX/veille | Revue d'un script d'installation (N2) · plan de passage MVP → complet (N1) · note de veille sur des textes fournis (N1) · synthèse du journal LEDGER (N0) |
| `poker-winners` | Poker Winners — Site (redkards/poker-vitrine) | CODE-CORE/revue, LEX-GUARD/conformite, OPS-CORE/projets, CONTENT-ARENA/redaction, REVENUE-CORE/propositions | Modèles PW-1 à PW-6 : revue de code (N2), conformité RGPD/ANJ (N1), checklist de bêta (N1), leçon + quiz (N2), partenariat (N3), veille (N1) |
| `poker-feeling` | Livre « Poker Feeling » | CONTENT-ARENA/redaction, AGENT-FACTORY/evaluation, OPS-CORE/projets, LEX-GUARD/conformite, REVENUE-CORE/propositions | Modèles PF-1 à PF-6 : chapitre (N2), quatrième de couverture (N2), plan de lancement (N1), conformité ANJ (N1), proposition (N3), évaluation (N1) |
| `redkards` | REDKARDS — Série BD poker | CONTENT-ARENA/redaction, AGENT-FACTORY/evaluation, OPS-CORE/projets, R&D-PARADOX/veille, LEX-GUARD/conformite | Modèles RK-1 à RK-6 : synopsis (N2), cohérence bible (N1), post promo (N3), plan de production (N1), crédibilité d'une main (N1), conformité (N2) |
| `top-solver` | Top Solver — solver GTO pédagogique | CODE-CORE/revue, CONTENT-ARENA/redaction, AGENT-FACTORY/evaluation | Revue d'un module du moteur (N2) · explication pédagogique d'un spot (N2) · évaluation de l'exactitude d'une explication (N1) · spécification d'un écran (N1) |
| `youtube-poker-winner` | Chaîne YouTube Poker Winners | CONTENT-ARENA/redaction, LEX-GUARD/conformite, OPS-CORE/projets | Script d'une vidéo (N2) · conformité ANJ d'une description (N1) · calendrier éditorial du mois (N1) · publication d'une vidéo (action `publier`, N3) |
| `freelance-ia` | Activité freelance IA (statut : idée) | REVENUE-CORE/propositions, LEX-GUARD/conformite, OPS-CORE/projets | Brouillon de devis (N3 : mot « devis ») · relecture de CGV (N1) · plan de lancement de l'activité (N1) |
| `esct-boxe` | ESCT Boxe — Site du club | CODE-CORE/revue, CONTENT-ARENA/redaction, LEX-GUARD/conformite | Revue de code d'une page (N2) · actualité du club (N2) · conformité RGPD du formulaire d'inscription (N1) · mise en ligne (action `mise_en_production`, N3) |
| `turf` | TURF — Pronostics PMU · site, YouTube, application | R&D-PARADOX/veille, CODE-CORE/revue, LEX-GUARD/conformite, CONTENT-ARENA/redaction | Note de veille sur textes fournis (N1) · revue du code du modèle (N2) · conformité ANJ d'un message de pronostic (N1) · post (N2/N3) |
| `divers` | Tout le reste (missions ponctuelles) | selon la demande (PRIME choisit si `service` absent) | Résumé interne (N0) · checklist (N1) |

## Fiches du registre sans code dédié (à décider par le propriétaire)
- « Carnet de mains — analyseur de mains personnel » (bêta) : pas de code dans la liste ; `top-solver` ou `divers` en attendant.
- « EspaceTravail — config agents IA » (en cours) : pas de code dans la liste ; `nexus` ou `divers` en attendant.
- Archivées, non concernées : « Formation CDA (archives) », « PW Solver — étude et lots L0/L1 » (fusionné dans Top Solver).
