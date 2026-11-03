# Veille SYFER — la « méga base de données virtuelle »

> En une phrase : SYFER ne copie pas Internet. Il garde une **liste de sources sérieuses** (le catalogue),
> va lire **uniquement ce que ces sources publient pour être lu par des machines** (flux RSS/Atom, API
> officielles) et range des **fiches courtes** (titre, résumé de 500 caractères au plus, lien, date, source, niveau
> de confiance) dans une petite base consultable par les agents.

---

## 1. Comment ça marche

```
 catalogue.yaml ──► collecteur.py ──────────────────────────────► veille.db ──► recherche.py ──► COLLECTOR (nexus-core)
 (243 sources)      • robots.txt, délai ≥ 2 s / site              (SQLite +     • rechercher()      via import Python
                    • ETag / If-Modified-Since, quotas            index FTS5)   • fiches_pour_      ou mini-serveur HTTP
                    • bouclier anti-injection (nexus-core)                        mission()          local (127.0.0.1)
                    • retrait e-mails / téléphones / pseudos
                    • dédoublonnage, rétention 180 j
```

| Fichier | Rôle |
|---|---|
| `catalogue.yaml` | Les sources, une par bloc. C'est **le seul fichier à modifier** pour ajouter une source. |
| `CATALOGUE.md` | Le même catalogue en tableaux lisibles, par domaine (régénéré par `python collecteur.py tableau`). |
| `collecteur.py` | Va chercher les nouveautés et fabrique les fiches. |
| `recherche.py` | Retrouve les fiches utiles (pour vous, ou pour les agents). Contient le bloc **INTÉGRATION**. |
| `tests/` | 124 tests automatiques, sans Internet (faux flux locaux). |
| `veille.db` | La base (créée au premier passage ; jamais versionnée). |
| `journal/` | Journaux du collecteur et rapports de vérification (jamais de clé dedans). |

Chaque fiche porte un **niveau de confiance** :

| Niveau | Signification | Exemples |
|---|---|---|
| **A** | Source officielle | CNIL, CERT-FR, Conseil d'État, EUR-Lex, NVD, INSEE |
| **B** | Expert reconnu ou presse spécialisée | SANS ISC, GTO Wizard, Nielsen Norman, ActuaBD |
| **C** | Communauté | Hacker News, Stack Overflow, Lobsters |
| **D** | Réseau social | Comptes Mastodon institutionnels |

Les agents reçoivent d'abord les fiches A à C. Une fiche D n'arrive qu'en dernier recours et doit être **recoupée**.

---

## 2. Règles légales : ce qui est collecté, ce qui ne l'est pas, et pourquoi

### Droit d'auteur
- **Jamais d'article intégral.** Le collecteur ne lit que le flux (ce que l'éditeur publie lui-même pour la
  syndication). Il ne télécharge **jamais** la page de l'article.
- Une fiche contient : titre, **résumé de 500 caractères au plus** (**300 pour la presse**, par prudence vis-à-vis du droit
  voisin des éditeurs de presse), lien vers l'original, date et source. C'est l'usage d'un agrégateur de liens
  (courte citation avec mention de la source).
- Les licences sont notées dans le champ `conditions` (Licence Ouverte Etalab, réutilisation UE, CC BY-SA de
  Stack Exchange…). Le **lien** vers l'original, toujours gardé, sert d'attribution.

### RGPD (données personnelles)
- **Pas de profils** et **pas de champ « auteur »** dans la base : on ne garde ni le nom ni le pseudo de qui a écrit.
- Avant enregistrement, le collecteur retire automatiquement **e-mails, numéros de téléphone, @pseudos, u/pseudos**
  et les **liens vers des profils** (`/@nom`, `/user/…`). Seuls les comptes institutionnels listés dans
  `comptes_autorises` d'une source peuvent rester.
- **Minimisation et durée** : fiches courtes, effacées automatiquement après **180 jours** (`VEILLE_RETENTION_JOURS`).
- **Effacement sur demande** : `python collecteur.py supprimer --texte "Nom Prénom"` (ou `--url`, `--source`).
- Limite honnête : le filtre fonctionne par motifs. Le **nom en clair** d'une personne citée dans une actualité
  (un ministre, un dirigeant…) n'est pas retiré. La base ne sert donc jamais à rechercher des personnes.

### Conditions d'utilisation des plateformes (CGU) et robots.txt
- **robots.txt respecté** pour tous les flux et pages des sites. Si robots.txt est inaccessible, la source est
  sautée pour ce passage, par prudence.
- **API officielles** : leurs conditions et quotas s'appliquent (NVD : 1 requête toutes les 6 s sans clé ;
  Stack Exchange : 300 requêtes/jour sans clé, et le champ `backoff` est respecté ; GitHub : 60/h sans jeton).
- **Politesse** : au moins 2 secondes entre deux requêtes vers un même site. Le collecteur envoie aussi les en-têtes
  ETag / If-Modified-Since, pour que le site réponde « rien de neuf » sans renvoyer tout le flux.
- **Aucun contournement** : pas de connexion à un compte, pas de faux navigateur, pas de rotation d'adresses.

### Ce qui n'est PAS collecté
| Plateforme | Statut | Raison |
|---|---|---|
| X (Twitter), LinkedIn, Facebook, Instagram, TikTok | **Consultation manuelle seulement** | Pas de flux public ni d'API publique légitime pour ce besoin. Les CGU interdisent la collecte automatisée. |
| Reddit (r/poker, r/PokerTheory) | **Consultation manuelle** | Reddit a annoncé (r/modnews, 30/09/2026) l'**arrêt des flux RSS le 13/11/2026**. Son API est réservée aux applications enregistrées. |
| Two Plus Two, Club Poker (forums à pseudos) | Manuelle | Aucun flux public confirmé. Le scraping d'un forum à pseudos poserait un risque RGPD. |
| Hashtags Mastodon | **Désactivés par défaut** | Ils contiennent les messages de particuliers. Seuls les **comptes institutionnels** sont suivis. |
| Légifrance, Judilibre | En attente | Accès uniquement par l'**API PISTE**, avec inscription gratuite (voir §4). Le site n'est jamais aspiré. |
| Pages sans flux (ANJ, INPI, ADEME, CNL…) | Manuelle | Pas de flux confirmé. Pour ces sites, on ne lit pas les pages HTML. |

La liste complète des 71 sources non collectées, avec la raison de chacune, se trouve à la fin de `CATALOGUE.md`.

---

## 3. Mise en route sur le VPS (Hostinger KVM 2)

Pré-requis : Python 3.11 ou plus récent, avec **PyYAML** (déjà présent dans l'image `nexus-core`). Aucune autre
dépendance.

```bash
# 1. Se placer dans le dossier (exemple)
cd /opt/syfer/espacetravail-public/veille

# 2. Indiquer un contact pour les sites consultés (page de contact, pas d'e-mail personnel)
export VEILLE_CONTACT="https://votre-site.fr/contact"

# 3. Contrôler le catalogue
python3 collecteur.py valider            # → « 243 source(s), 0 erreur(s). »

# 4. Tester tous les flux UNE fois (ne stocke rien ; rapport dans journal/verification-*.json)
python3 collecteur.py verifier

# 5. Premier passage réel
python3 collecteur.py collecter
python3 collecteur.py stats
```

### Passage automatique toutes les 6 heures (cron)
`crontab -e`, puis ajouter (minute 17 pour éviter l'heure pile) :
```
17 */6 * * * cd /opt/syfer/espacetravail-public/veille && VEILLE_CONTACT="https://votre-site.fr/contact" /usr/bin/python3 collecteur.py collecter >> journal/cron.log 2>&1
```
Chaque source a sa propre `frequence_conseillee` (6h, 24h ou 7j). Un passage toutes les 6 h n'interroge donc que
les sources « dues ».

Variante Docker : monter `./veille:/veille` dans le service `nexus-core`, puis lancer
`docker compose exec nexus-core python /veille/collecteur.py collecter`. Ce changement du `docker-compose` est à
faire par l'agent noyau, voir §6.

### Taille et trafic estimés
- Environ **800 nouvelles fiches par jour**. arXiv est plafonné à 25 fiches par passage, et la NVD à 50.
- Avec 180 jours de rétention : **environ 150 000 fiches**, soit **150 à 250 Mo** sur le disque (fiches et index).
- Environ 700 requêtes par jour au total, soit **50 à 100 Mo** téléchargés : négligeable pour le VPS.

### Variables utiles
| Variable | Défaut | Rôle |
|---|---|---|
| `VEILLE_CONTACT` | « contact du propriétaire à configurer » | Ajouté au User-Agent `SYFER-veille/1.0 (+…)` |
| `VEILLE_DB` | `veille/veille.db` | Emplacement de la base |
| `VEILLE_RETENTION_JOURS` | 180 | Durée de conservation des fiches |
| `VEILLE_DELAI_DOMAINE` | 2 | Délai entre deux requêtes vers un même site (jamais moins de 2) |
| `VEILLE_NEXUS_CORE` | `../nexus-core` | Emplacement du bouclier anti-injection |
| `VEILLE_LECTURE_SEULE` | — | `1` côté nexus-core (montage `:ro`, ex. `/veille-donnees/veille.db`) : lecture `mode=ro&immutable=1`, aucun fichier annexe. Détecté aussi automatiquement si le fichier ou son dossier n'est pas inscriptible. |

Publication sans risque pour les lecteurs : le collecteur travaille sur `veille.db.tmp` (journal DELETE, jamais
WAL). En fin de collecte, il le remplace d'un coup par `veille.db` (fsync puis `os.replace`). Les agents voient
donc toujours une base complète. Le verrou `veille.db.lock` empêche deux collectes simultanées.
| `NVD_API_KEY`, `STACKEXCHANGE_KEY`, `GITHUB_TOKEN_LECTURE` | — | Clés gratuites facultatives (quotas plus larges). Les mettre dans l'environnement, **jamais dans le catalogue**. |

---

## 4. Ajouter une source

1. Vérifier que la source publie un **flux RSS/Atom** (icône RSS, `/feed`, `/rss.xml`…) ou une **API publique
   documentée**. Sinon, ajouter `acces: manuel`.
2. Copier ce modèle à la fin de `catalogue.yaml` :
   ```yaml
   - id: ma-source                      # minuscules, chiffres, tirets ; unique
     nom: Nom lisible
     domaines: [droit]                  # droit, cybersecurite, ia, entreprise, environnement, design_ux,
                                        # marketing_communication, poker, bd_edition, forums_experts,
                                        # reseaux_sociaux, communication_institutionnelle, tech
     services_syfer: [LEX-GUARD/droit-france]
     projets: [poker-winners]           # codes de nexus-core/projets.yaml
     type: officielle                   # officielle (A) | expert (B) | media (B/C) | communaute (C) | reseau_social (D)
     confiance: A
     acces: rss                         # rss | atom | api | manuel
     url: https://site.fr/actualites
     url_flux: https://site.fr/rss.xml  # vide si manuel
     langue: fr
     frequence_conseillee: 24h          # 6h | 24h | 7j
     conditions: Licence Ouverte Etalab 2.0
     donnees_personnelles: non          # ou « risque: <règle appliquée> »
     verifie: '2026-11-04'              # date de votre vérification, sinon non_verifie
     flux_verifie: oui                  # oui | motif | non | sans_objet (manuel)
     collecte: oui                      # non → ajouter « raison: … »
   ```
3. Contrôler, tester la source seule, puis régénérer le tableau :
   ```bash
   python3 collecteur.py valider
   python3 collecteur.py verifier --source ma-source
   python3 collecteur.py tableau
   ```

Cas particuliers :
- **Chaîne YouTube** : `acces: atom`, `url_flux: https://www.youtube.com/feeds/videos.xml?channel_id=UC…`. L'ID
  s'obtient sur la chaîne via « Partager la chaîne », puis « Copier l'ID de la chaîne ». Les modèles GTO Wizard,
  Jonathan Little et Upswing sont prêts dans le catalogue.
- **Compte Mastodon institutionnel** : `url_flux: https://<instance>/@<compte>.rss`.
- **Compte Bluesky institutionnel** : `url_flux: https://bsky.app/profile/<did:plc:…>/rss`.
- **Légifrance / Judilibre** : créer un compte gratuit sur piste.gouv.fr. Dans le catalogue PISTE, s'abonner aux
  API « Légifrance » et « Judilibre », puis récupérer `client_id` et `client_secret` dans la console. Ces API
  utilisent OAuth : un adaptateur dédié reste à écrire. Les sources sont prêtes (`adaptateur: a_configurer`).

---

## 5. Rechercher

```bash
python3 recherche.py "AI Act obligations transparence" --domaine droit --confiance-min B --depuis 30j
python3 recherche.py mission "Mettre à jour les CGU du site poker" --service LEX-GUARD/droit-france --projet poker-winners
python3 recherche.py serveur          # http://127.0.0.1:8765/sante, /recherche?q=…, /mission?consigne=…
```
Le classement multiplie trois facteurs : la **pertinence** (index plein texte, sans tenir compte des accents), la
**confiance** (A ×1, B ×0,85, C ×0,6, D ×0,4) et la **fraîcheur**. Si `VEILLE_JETON` est défini, le mini-serveur
exige l'en-tête `X-Veille-Jeton`. Il écoute uniquement sur la machine (127.0.0.1) et ouvre la base en lecture seule.

## 6. Branchement sur les agents (COLLECTOR)

Le bloc **INTÉGRATION**, en tête de `recherche.py`, décrit le branchement : `fiches_pour_mission(consigne,
service, projet, max=5)` est appelée dans `pipeline._charger_connaissances`, puis le bloc passe par
`bouclier.filtrer_contenu`. Les fiches sont citées sous la forme `[veille:<source>]`. Ce dossier **ne modifie
pas** nexus-core : le branchement revient à l'agent noyau.

## 7. Limites (à connaître)

- **Vérification** : le 2026-11-04, 177 sources sur 243 ont été vues en ligne, et l'adresse exacte du flux a été
  confirmée pour 110 d'entre elles. 30 adresses suivent un motif documenté (GitHub releases, PyPI, arXiv, Mastodon,
  Discourse). 36 adresses restent à confirmer : lancer `python3 collecteur.py verifier` sur le VPS. Ce bac à sable
  ne pouvait pas joindre les sites depuis Python. Une source qui échoue 5 fois de suite est suspendue 48 h, puis
  signalée par `stats`.
- **Anti-injection** : le bouclier détecte des motifs, ce qui se contourne (paraphrase, autre langue). Les fiches
  restent donc des **données non fiables**, encapsulées pour les agents. Elles ne déclenchent jamais d'action.
- **Anonymisation** par motifs : voir §2 (les noms en clair ne sont pas retirés).
- **Pas de traduction** : beaucoup de sources sont en anglais. La recherche en français trouve surtout les fiches
  en français.
- **Flux qui changent** : les sites changent parfois l'adresse de leurs flux. Le journal et `stats` signalent les
  sources en échec.
- **67 sources manuelles** (ANJ, INPI, ADEME, CNL, Livres Hebdo…) : à consulter de temps en temps. Elles servent aussi
  de liste de lecture.

## 8. Tests

```bash
cd veille && python3 -m pytest -q        # 124 tests, aucun accès réseau
```
Couverture des tests : lecture RSS, RDF, Atom et JSON ; refus des DTD et entités XML ; robots.txt (autorisé,
interdit, 404, 403, réseau) ; délai de 2 s ; ETag et réponse 304 ; limites 429 / Retry-After ; quotas, backoff,
suspension. Ils couvrent aussi le retrait des données personnelles, l'anti-injection (avec et sans bouclier), la
troncature, le dédoublonnage, la rétention et l'effacement ciblé. Enfin : la recherche (filtres, requêtes hostiles,
lecture seule), les fiches pour mission, le mini-serveur local et la validation du catalogue réel (schéma, unicité,
au moins 8 sources par domaine, URL, plateformes exclues).
