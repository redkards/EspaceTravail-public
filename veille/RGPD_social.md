# Veille SYFER — réseaux sociaux et médias : cadre RGPD

> Modèles à compléter par le propriétaire (responsable du traitement). Rédigés le 2026-11-04 d'après la fiche de la
> CNIL « Focus : l'intérêt légitime et la collecte par moissonnage (web scraping) » du 19 juin 2025
> (https://www.cnil.fr/fr/focus-interet-legitime-collecte-par-moissonnage). Ce document n'est pas un avis juridique.
> En cas de doute, faire relire le texte par LEX-GUARD/conformite puis par un professionnel.

## 1. Ce que fait (et ne fait pas) le mode social

| Fait | Ne fait pas |
|---|---|
| Lit des contenus **publics**, uniquement par des **API officielles** ou des flux publics (Mastodon, Bluesky, YouTube Data API si une clé est fournie). | Pas de scraping de X, LinkedIn, Facebook, Instagram, TikTok ou Telegram, pas de connexion à un compte, pas de contournement. |
| Garde un **extrait court anonymisé** (≤ 200 caractères), la date, la plateforme, le sujet et la tonalité. | Ne garde **aucun identifiant de personne physique** : ni pseudo, ni nom de compte, ni lien vers un profil, ni photo. |
| Remplace le lien d'un post de particulier par la page du sujet, suivie d'une **empreinte du contenu** (pseudonyme par contenu, jamais par personne). | Ne crée **aucun profil**, ne relie pas les posts d'une même personne, ne fait **aucun profilage**. |
| Calcule des **agrégats** : volume, évolution, tonalité globale, mots-clés et sources principales. | Ne présente jamais un post comme un fait : confiance **D**, mention « signal ». |
| Ignore les contenus marqués sensibles, non publics, et les partages. | Ne cherche pas de données sensibles (santé, opinions…). Une donnée sensible captée par hasard est effacée à la rétention. |
| Efface les fiches sociales au bout de **30 jours** (`VEILLE_RETENTION_SOCIAL_JOURS`). | Ne conserve rien de social au-delà de cette durée, à part les agrégats anonymes. |

Les **comptes institutionnels ou d'entreprise** (CNIL, CNRS, compte officiel Mastodon ou Bluesky…) sont déclarés dans le
catalogue (`compte_institutionnel: true` ou `comptes_autorises`). Ils gardent leur lien, car ce ne sont pas des
personnes physiques.

Les comptes du propriétaire passent par **ses** connecteurs Metricool (réseaux sociaux) et vidIQ (YouTube) côté
Claude. Ils ne passent pas par ce collecteur.

## 2. Modèle — fiche du registre des activités de traitement (art. 30 RGPD)

| Rubrique | Contenu proposé |
|---|---|
| Nom du traitement | Veille de tendances et de sujets sur les réseaux sociaux et les médias (SYFER) |
| Responsable du traitement | [Nom, statut (micro-entreprise / SASU), adresse, contact] |
| Finalité | Repérer des **sujets et tendances** (volume, tonalité globale) utiles aux projets (Poker Winners, chaîne YouTube, Top Solver, freelance IA…). Exclusions : prospection, profilage, décision individuelle. |
| Base légale | Intérêt légitime (art. 6.1.f) : veille de marché et de contenus, avec les garanties de la section 1 (mise en balance documentée). |
| Personnes concernées | Auteurs de messages publics sur les sujets suivis (non identifiés dans la base). |
| Catégories de données | Extrait court anonymisé de messages publics, date, plateforme, sujet, tonalité calculée. Aucun identifiant, aucune donnée sensible recherchée. |
| Sources | API publiques officielles (Mastodon, Bluesky, YouTube Data API) et flux RSS officiels des médias, listés dans `veille/CATALOGUE.md`. |
| Destinataires | Usage interne : agents SYFER (services Croissance/Création), cockpit du propriétaire. Aucune transmission à des tiers. |
| Transferts hors UE | Aucun stockage hors du VPS. Les API interrogées peuvent être opérées hors UE (lecture seule de données publiques). |
| Durée de conservation | Fiches sociales : 30 jours. Fiches médias : 180 jours. Agrégats : calculés à la demande, non stockés (un export éventuel est anonyme). |
| Mesures de sécurité | Base sur le VPS (accès SSH par clé), lecture seule pour les agents, anonymisation automatique, journal sans données personnelles, bouclier anti-injection. |
| Droits | Opposition préalable via une liste d'exclusion (mots-clés, comptes, sites), effacement ciblé (`python collecteur.py supprimer --texte …`), contact : [adresse]. |

## 3. Modèle — mention d'information (à publier sur le site ou la page « confidentialité »)

> **Veille sur les sujets publics.** [Nom] réalise une veille automatisée des **sujets** et **tendances** abordés
> publiquement sur certains réseaux sociaux (Mastodon, Bluesky, YouTube) et dans les médias en ligne, sur les thèmes
> suivants : [poker, intelligence artificielle, bande dessinée…]. Seules les API et flux officiels sont utilisés.
> Les messages sont **anonymisés dès la collecte** : aucun nom, pseudonyme ni lien de profil n'est conservé. Seul un
> extrait court est gardé, **30 jours au plus**, pour calculer des statistiques globales (volume, tonalité).
> Ce traitement repose sur notre intérêt légitime à suivre l'actualité de nos domaines. Vous pouvez vous y opposer
> ou demander l'effacement d'un contenu en écrivant à [adresse de contact]. Vous pouvez aussi saisir la CNIL (cnil.fr).
> Liste des sources consultées : [lien vers la liste publique des sources, par exemple un extrait de CATALOGUE.md].

## 4. Vérifications avant d'activer une source sociale

1. API officielle et CGU compatibles avec l'usage prévu, y compris commercial (voir la colonne « raison » du
   catalogue). Une source payante n'est **jamais** activée sans l'accord du propriétaire sur le coût estimé.
2. `stockage: agrege`, `donnees_personnelles: "risque: …"` et le sujet suivi sont renseignés. Les comptes
   institutionnels sont déclarés.
3. Aucun site dont le contenu est principalement intrusif (santé, mineurs) et aucun site qui s'oppose au moissonnage
   (robots.txt, CGU).
4. La liste publique des sources et la mention d'information sont à jour.
