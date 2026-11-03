# Veille SYFER — la « méga base de données virtuelle »

> En une phrase : SYFER ne copie pas Internet. Il garde une **liste de sources sérieuses** (le catalogue). Il va lire
> **uniquement ce que ces sources publient pour les machines** : flux RSS/Atom, API officielles, documents sous
> licence ouverte. Il range ensuite des **fiches courtes** (ou, quand la licence le permet, des **sections citables**
> de normes et de guides) dans une petite base que les agents peuvent consulter.

---

## 1. Comment ça marche

```
 catalogue.yaml (322 sources) ─► collecteur.py ─────────────┐
 documents/documents.yaml ─────► documents/ingestion.py ────┤   robots.txt, délai ≥ 2 s / site, quotas,
                                                            ├─► bouclier anti-injection, anonymisation,
 recherche-web/ (à la demande, désactivée par défaut) ──────┘   licence → stockage, dédoublonnage
                                                            ▼
                     veille.db (SQLite + index plein texte FTS5, publiée de façon atomique)
                                                            ▼
     recherche.py (classement calibré) ─► COLLECTOR de nexus-core │ tendances.py ─► Croissance / Création, cockpit
```

| Fichier / dossier | Rôle |
|---|---|
| `catalogue.yaml` | Les sources, une par bloc. C'est **le seul fichier à modifier** pour ajouter une source. |
| `CATALOGUE.md` | Le même catalogue en tableaux lisibles, par domaine, avec la licence et le stockage (`python collecteur.py tableau`). |
| `collecteur.py` | Va chercher les nouveautés (flux, API) et fabrique les fiches. |
| `documents/` | `documents.yaml` (normes, RFC, guides, documentation, lois) et `ingestion.py` (découpage en sections citables). |
| `recherche.py` | Retrouve les fiches utiles avec un **classement calibré**. Contient le bloc **INTÉGRATION**. |
| `tendances.py` | Agrégats « tendances » des réseaux sociaux et des médias (volume, évolution, tonalité). |
| `recherche-web/` | Recherche Web à la demande : SearXNG auto-hébergé et Wikipédia. **Désactivée par défaut.** |
| `calibration/` | Jeu d'évaluation (60 requêtes), calibrage des poids, `poids.json` versionné, rapport. |
| `RGPD_social.md` | Règles RGPD du mode social, modèle de fiche de registre et de mention d'information. |
| `tests/` | 206 tests automatiques, sans Internet (faux flux locaux). |
| `veille.db`, `journal/` | La base et les journaux (jamais versionnés ; jamais de clé dans les journaux). |

Chaque fiche porte un **niveau de confiance** :

| Niveau | Signification | Exemples |
|---|---|---|
| **A** | Source officielle | CNIL, CERT-FR, NIST, IETF, W3C, EUR-Lex, BOAMP, INSEE |
| **B** | Expert reconnu | OWASP, SANS ISC, GTO Wizard, Nielsen Norman |
| **C** | Communauté, presse et médias (plafond pour toute fiche média) | Hacker News, Stack Overflow, Le Monde, franceinfo, GDELT |
| **D** | Réseau social, résultat Web non recoupé | Mastodon, Bluesky, YouTube |

Les agents reçoivent d'abord les fiches A à C. Une fiche D n'arrive qu'en dernier recours et doit être **recoupée**.
Les fiches sociales et médias sont toujours marquées **« SIGNAL (opinion/tendance, pas un fait) »**.

---

## 2. Règles légales

### Droit d'auteur : ce qu'on stocke dépend de la LICENCE
| Stockage | Pour quelles licences | Ce qui est gardé |
|---|---|---|
| `integral` | Licence Ouverte Etalab, domaine public (NIST, SQLite), CC0, CC BY / BY-SA (OWASP, WHATWG, Wikipédia), licence IETF des RFC, licence W3C, MIT, Apache 2.0, réutilisation UE (EUR-Lex) | Texte des **sections** (6 000 caractères au plus par partie), avec la référence précise et le lien |
| `extrait` | Droits réservés (presse, blogs), licence inconnue, documentation Python | Titre, résumé ≤ 500 caractères (**≤ 300 pour la presse**, droit voisin des éditeurs) et lien |
| `metadonnees` | Normes payantes (ISO/IEC), ETSI (téléchargement gratuit mais reproduction restreinte) | Titre, numéro et lien uniquement |
| `agrege` | Réseaux sociaux | Extrait anonymisé ≤ 200 caractères, 30 jours, agrégats |

Le stockage effectif est **toujours le plus restrictif** entre ce que demande la source et ce que permet sa licence.
Le code applique cette règle à chaque enregistrement. Le validateur refuse par exemple `integral` pour une licence
`droits-reserves`. On ne télécharge jamais la page d'un article de presse : seul le flux publié par l'éditeur est lu.

### RGPD
- **Pas de profils** et **pas de champ « auteur »**. Les e-mails, téléphones, @pseudos, u/pseudos et liens vers des
  profils sont retirés automatiquement.
- **Réseaux sociaux** (recommandations CNIL sur le moissonnage, juin 2025) :
  - finalité « veille de tendances et de sujets » ;
  - aucun identifiant de personne physique, sauf compte institutionnel déclaré ;
  - le lien d'un post de particulier est remplacé par la page du sujet, suivie d'une empreinte du contenu ;
  - extraits ≤ 200 caractères, **rétention 30 jours** (`VEILLE_RETENTION_SOCIAL_JOURS`) ;
  - contenus sensibles ou non publics ignorés, agrégats seulement.

  Voir **`RGPD_social.md`** : modèle de fiche de registre et de mention d'information.
- **Rétention** : 180 jours pour les fiches (`VEILLE_RETENTION_JOURS`), 30 jours pour le social.
  **Effacement ciblé** : `python collecteur.py supprimer --texte "Nom Prénom"`.
- Limite : le **nom en clair** d'une personne citée dans une actualité n'est pas retiré. La base ne sert jamais à
  rechercher des personnes.

### CGU, robots.txt, aucun contournement
- robots.txt est respecté pour tous les flux, pages et documents. Les API officielles suivent leurs conditions
  et leurs quotas.
- Au moins 2 secondes entre deux requêtes vers un même site. Le collecteur envoie les en-têtes ETag et
  If-Modified-Since.
- Pas de connexion à un compte, pas de faux navigateur, pas de rotation d'adresses. Les sources **payantes ne sont
  jamais activées** sans votre accord sur le coût.

### Réseaux sociaux et médias : statut de chaque plateforme (vérifié le 2026-11-04)
| Plateforme | Accès | Coût | Statut |
|---|---|---|---|
| Mastodon | API publique (fils de hashtags) et RSS de comptes | Gratuit | **Collecte auto** (règles RGPD sociales) |
| Bluesky | API publique AT Protocol (fils de comptes) | Gratuit | **Collecte auto** pour les comptes. La recherche exige un mot de passe d'application que vous créez vous-même : **désactivée** |
| YouTube | Flux RSS par chaîne et YouTube Data API v3 | Gratuit (10 000 unités/jour ; 1 recherche = 100 unités) | **Désactivé** tant que la clé Google Cloud n'est pas créée |
| Reddit | Data API | Usage commercial sous contrat payant ; nouvelles demandes fermées depuis le 31/10/2026 ; RSS arrêtés le 13/11/2026 | **Réservé / indisponible** |
| Threads | API Meta `keyword_search` (2 200 requêtes / 24 h) | Gratuit, mais revue d'application Meta | **Désactivé, à décider** |
| Telegram | API client MTProto (compte personnel requis) | Gratuit | **Non collecté** (consultation manuelle) |
| X (Twitter) | API à la lecture (≈ 0,005 $ par post lu, offre gratuite fermée le 06/02/2026) | ≈ 150 $/mois pour 1 000 posts par jour | **Payant, désactivé, validation requise** |
| LinkedIn | Pas d'API publique de recherche | — | **Réservé** (vos pages : via Metricool) |
| Facebook / Instagram | Meta Content Library (chercheurs à but non lucratif) | Gratuit pour eux | **Réservé** |
| TikTok | Research API (chercheurs) | — | **Réservé** |
| Presse, radio, podcasts | Flux RSS officiels (Le Monde, franceinfo, Ouest-France, Radio France…) | Gratuit | **Collecte auto** (titre + 300 caractères + lien) |
| GDELT DOC 2.0 | API mondiale d'actualité | Gratuit | **Collecte auto** (confiance C) |
| Europe Media Monitor (JRC) | NewsBrief, flux à confirmer | Gratuit | Collecte auto après `verifier` |
| Media Cloud, AFP | Compte hébergé / abonnement | — / payant | Manuel / non utilisé |

**Vos propres comptes** (statistiques, publications) passent par vos connecteurs **Metricool** (réseaux sociaux) et
**vidIQ** (YouTube) côté Claude. Ils ne sont pas intégrés à ce code.

---

## 3. Mise en route sur le VPS (Hostinger KVM 2)

Pré-requis : Python 3.11 ou plus récent, avec **PyYAML** (déjà dans l'image `nexus-core`). Le paquet `pypdf` est
facultatif : sans lui, les PDF sont enregistrés en métadonnées et lien, et le journal le dit.

```bash
cd /opt/syfer/espacetravail-public/veille
export VEILLE_CONTACT="https://votre-site.fr/contact"   # page de contact, pas d'e-mail personnel
python3 collecteur.py valider              # → « 322 source(s), 0 erreur(s). »
python3 collecteur.py verifier             # teste chaque flux UNE fois, ne stocke rien
python3 documents/ingestion.py --lister    # documents prévus et politique de licence appliquée
python3 collecteur.py collecter            # premier passage
python3 documents/ingestion.py             # normes, RFC, guides → sections citables
python3 collecteur.py stats
```

### Tâches automatiques (cron)
```
17 */6 * * * cd /opt/syfer/espacetravail-public/veille && VEILLE_CONTACT="https://votre-site.fr/contact" /usr/bin/python3 collecteur.py collecter >> journal/cron.log 2>&1
43 3 * * 1   cd /opt/syfer/espacetravail-public/veille && VEILLE_CONTACT="https://votre-site.fr/contact" /usr/bin/python3 documents/ingestion.py >> journal/cron.log 2>&1
```
La collecte tourne toutes les 6 h, et chaque source n'est interrogée que lorsqu'elle est « due ». Les documents sont
rafraîchis chaque lundi.

Publication sans risque pour les lecteurs : le collecteur travaille sur `veille.db.tmp` (journal DELETE, jamais WAL),
puis le remplace d'un coup par `veille.db` (fsync, puis `os.replace`). Le verrou `veille.db.lock` empêche deux
collectes en même temps. Côté nexus-core, la base se lit depuis un montage en lecture seule (`VEILLE_LECTURE_SEULE=1`).

### Taille et trafic estimés
- Environ **1 000 nouvelles fiches par jour** (médias inclus), plus quelques milliers de sections de documents.
- Avec 180 jours de rétention (30 jours pour le social), **200 à 350 Mo** sur le disque.
- Environ 900 requêtes par jour, soit **80 à 150 Mo** téléchargés : négligeable pour le VPS.

### Variables utiles
| Variable | Défaut | Rôle |
|---|---|---|
| `VEILLE_CONTACT` | « contact du propriétaire à configurer » | Ajouté au User-Agent `SYFER-veille/1.0 (+…)` |
| `VEILLE_DB` | `veille/veille.db` | Emplacement de la base |
| `VEILLE_RETENTION_JOURS` / `VEILLE_RETENTION_SOCIAL_JOURS` | 180 / 30 | Durées de conservation |
| `VEILLE_DELAI_DOMAINE` | 2 | Délai entre deux requêtes vers un même site (jamais moins de 2) |
| `VEILLE_NEXUS_CORE` | `../nexus-core` | Emplacement du bouclier anti-injection |
| `VEILLE_LECTURE_SEULE` | — | `1` côté nexus-core : lecture `mode=ro&immutable=1`, sans aucun fichier annexe |
| `VEILLE_POIDS` | `calibration/poids.json` | Poids du classement |
| `VEILLE_WEB` | — | `1` (et `actif: true` dans `recherche-web/config.yaml`) pour autoriser la recherche Web |
| `NVD_API_KEY`, `STACKEXCHANGE_KEY`, `GITHUB_TOKEN_LECTURE`, `YOUTUBE_API_KEY`, `OPENALEX_API_KEY` | — | Clés facultatives. À mettre dans l'environnement, **jamais dans le catalogue** |

---

## 4. Ajouter une source ou un document

**Une source (flux ou API)** : copier un bloc existant de `catalogue.yaml` et l'adapter. Champs principaux :
- `id`, `nom`, `domaines`, `services_syfer`, `projets` ;
- `type` (officielle, expert, media, communaute, reseau_social) et `confiance` ;
- `acces` (rss, atom, api, document, manuel), `url`, `url_flux` ;
- `licence` et `stockage` (voir §2) ;
- `type_doc` (actualite, norme, guide, loi, jurisprudence, documentation, cahier_des_charges, appel_offres, donnees,
  recherche, release, discussion, social, podcast) ;
- `conditions`, `donnees_personnelles` (« non » ou « risque: règle »), `verifie`, `flux_verifie`, `collecte`
  (+ `raison` si « non »).

Ensuite : `python3 collecteur.py valider`, puis `verifier --source mon-id`, puis `tableau`.

**Un document long** (norme, guide, RFC, cahier des charges type) : ajouter un bloc dans `documents/documents.yaml`
avec `id`, `source`, `titre`, `ref_court` (préfixe des citations), `url`, `format` (auto, html, txt, md, pdf) et
`stockage`. Les références produites sont précises, par exemple « NIST SP 800-63B-4 §3.1.1 », « RFC 9110 §8.8.3 »,
« RGPD art. 28 » ou « RGAA 4.1 critère 11.1 ».

Cas particuliers :
- **YouTube** : `url_flux: https://www.youtube.com/feeds/videos.xml?channel_id=UC…`.
- **Mastodon institutionnel** : `https://<instance>/@<compte>.rss` avec `compte_institutionnel: true`.
- **Légifrance / Judilibre** : compte gratuit sur piste.gouv.fr. L'adaptateur OAuth reste à écrire.
- **Profils d'acheteurs (DCE)** : toujours `manuel`, car les DCE se téléchargent après inscription.

---

## 5. Rechercher, tendances, Web

```bash
python3 recherche.py "exigences mots de passe" --confiance-min B
python3 recherche.py mission "Rédiger le cahier des charges d'un site vitrine" --service REVENUE-CORE/propositions
python3 tendances.py --projet poker-winners --jours 7          # volume, évolution, tonalité, mots-clés, sources
python3 recherche.py serveur      # 127.0.0.1:8765 : /sante, /recherche, /mission, /tendances
VEILLE_WEB=1 python3 recherche-web/connecteurs_web.py "cahier des charges accessibilité"   # si activée
```

**Classement calibré** (`calibration/poids.json`) :
- pertinence plein texte (BM25), avec **expansion FR ↔ EN** (« mot de passe » → *password*, etc.) ;
- confiance A–D (hiérarchie jamais inversée) ;
- **type de document adapté au service** (LEX-GUARD préfère les lois, DESIGN-SYSTEM les normes, REVENUE-CORE les
  cahiers des charges…) ;
- fraîcheur et poids propre à chaque canal (document, flux, média, social, Web).

Les missions des agents excluent le social par défaut (`inclure_social=True` pour une mission « tendances »).

**Recherche Web à la demande** (double verrou : `actif: true` et `VEILLE_WEB=1`) :
- **SearXNG auto-hébergé** : service optionnel `recherche-web/docker-compose.searxng.yml`, accessible seulement en
  local (127.0.0.1), limité à 0,5 CPU et 384 Mo, à intégrer par l'agent INFRA ;
- **API Wikipédia** : gratuite.
- Requêtes contenant une donnée personnelle : refusées.
- Journal sans le texte des requêtes (empreinte seulement), quotas par jour.
- Résultats en confiance **D** (Wikipédia : C), relevés à A/B seulement si l'URL appartient à une source A/B du
  catalogue (recoupement).
- Brave Search (plus de gratuit, ≈ 4 à 5 $ / 1 000 requêtes) et Mojeek (≈ 2 £ / 1 000) : **non activés**, à votre
  décision.

## 6. Branchement sur les agents (COLLECTOR)

Le bloc **INTÉGRATION**, en tête de `recherche.py`, décrit le branchement : `fiches_pour_mission(consigne, service,
projet, max=5)` est appelée dans `pipeline._charger_connaissances`, puis le bloc passe par
`bouclier.filtrer_contenu`. Les citations ont la forme `[veille:<source> · <référence> · confiance X · date]`. Ce
dossier **ne modifie pas** nexus-core.

## 7. Calibration

```bash
python3 calibration/calibrer.py            # recalcule poids.json + RAPPORT_CALIBRATION.md
python3 calibration/calibrer.py --evaluer  # mesure les poids actuels
python3 calibration/calibrer.py --evaluer --db veille.db   # mesure sur la base réelle
```
Le jeu d'évaluation compte 60 requêtes des 20 services, dont 10 « tendances / médias ». Mesures : precision@5 et
nDCG@10. L'optimisation se fait par coordonnées sur une grille, sous contraintes (A ≥ B ≥ C ≥ D, social ≤ média ≤
flux), avec **validation croisée à 5 plis** contre le surapprentissage. Résultats : `calibration/RAPPORT_CALIBRATION.md`.

## 8. Limites (à connaître)

- **Vérification** : 227 sources sur 322 ont été vues en ligne le 2026-11-04. Beaucoup d'adresses de flux et de
  documents restent à confirmer sur le VPS (`verifier`, `ingestion.py`), car ce bac à sable ne pouvait pas joindre
  les sites depuis Python.
- **Calibration** sur un corpus d'évaluation rédigé pour l'occasion (165 fiches), avec des jugements posés à la
  main. À refaire sur la base réelle après quelques semaines (`--db`). Les écarts de quelques centièmes ne sont pas
  significatifs.
- **Tonalité** par lexique simple : indicative. L'ironie et le sarcasme lui échappent.
- **Anti-injection** et **anonymisation** par motifs : contournables. Les fiches restent des données non fiables,
  encapsulées pour les agents.
- **PDF** : sans `pypdf`, ils sont enregistrés en métadonnées et lien. Les gros PDF (RGESN, guides ANSSI) gagnent à
  avoir `pypdf` installé.
- **87 sources manuelles** (ANJ, INPI, CNL, DCE des acheteurs…) : à consulter de temps en temps.

## 9. Tests

```bash
cd veille && python3 -m pytest -q        # 206 tests, aucun accès réseau
```
Ce que couvrent les tests :
- lecture des flux et des API (RSS/RDF/Atom/JSON, HAL, BOAMP, TED en POST, data.gouv, GDELT, YouTube, Bluesky,
  Mastodon) et refus des DTD XML ;
- robots.txt, délais, ETag, limites de débit, quotas ;
- politique de licence, découpage HTML/RFC/Markdown, références précises, PDF sans lecteur, normes payantes en
  métadonnées ;
- règles RGPD du social (aucun pseudo, lien remplacé, rétention 30 jours, comptes institutionnels), plafond C des
  médias, tonalité et tendances ;
- recherche (expansion FR/EN, références citées, social exclu des missions), recherche Web (désactivée par défaut,
  requêtes personnelles refusées, recoupement, bouclier, journal, quotas) ;
- cohérence de la calibration, migration d'une base v1, publication atomique et lecture seule.
