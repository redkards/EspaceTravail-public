# Compaction SYFER — résultats du banc de mesure

_Généré par `compaction/mesure.py` le 2026-11-04 00:47 — Python 3.13.18, SQLite 3.53.1. Corpus synthétique : 10000 missions sur 250 jours, 5000 fiches de veille, 2000 connaissances (20 % de quasi-doublons)._

## 1. Missions : comparaison des méthodes (corpus complet, enregistrements intégraux)

Taille brute (JSON canonique des lignes d'archive) : **91.63 Mo**, soit 9.2 Ko par mission.

| Méthode | Taille | Ratio | Compaction | Lecture d'un enregistrement | Remarque |
|---|---:|---:|---:|---:|---|
| **Format actuel** (gzip par ligne, AAAA-MM.jsonl.gz) | 26.52 Mo | 3.45 | 4.1 s | 111.5 ms | lecture = décompresser et parcourir le mois |
| + index actuel archive_index/FTS (texte ≤ 4000) | 34.38 Mo | — | — | — | recherche 29.49 ms |
| zlib ligne | 26.32 Mo | 3.48 | 3.0 s | 0.15 ms | accès direct si l'offset est indexé |
| zlib ligne + dict | 21.32 Mo | 4.30 | 4.0 s | 0.16 ms | accès direct si l'offset est indexé |
| zlib bloc | 9.91 Mo | 9.25 | 3.1 s | 2.50 ms | 93 blocs |
| zlib bloc + dict | 9.83 Mo | 9.32 | 3.2 s | 2.97 ms | 93 blocs |
| lzma bloc | 6.69 Mo | 13.69 | 38.1 s | 7.30 ms | 93 blocs |
| zlib bloc + dict + dédup | 10.75 Mo | 8.52 | 8.9 s | 2.31 ms | 83 blocs, 9053 fragments dédupliqués |
| lzma bloc + dédup | 8.10 Mo | 11.31 | 36.6 s | 6.77 ms | 83 blocs, 9053 fragments dédupliqués |

## 2. Pipeline complet à paliers (module `app/compaction.py`)

Chaud ≤ 30 j laissé au format actuel ; tiède 31–180 j ; froid > 180 j. Enregistrements compactés : 6000 tièdes, 2800 froids.

| Palier | Avant (brut) | Fichiers de blocs | Ratio fichiers |
|---|---:|---:|---:|
| froid | 25.63 Mo | 1.11 Mo | 23.15 |
| tiede | 55.00 Mo | 4.26 Mo | 12.91 |

- Fragments dédupliqués : 186 (0.01 Mo stockés, 1.00 Mo de texte non répété).
- Index SQLite (blocs, enregistrements, feuilles de Merkle, FTS5, agrégats) : 3.17 Mo dont FTS5 1.10 Mo ; après entretien (VACUUM) : 3.05 Mo.
- Total dossier compact/ : **8.42 Mo** pour 80.63 Mo brut → ratio global **9.6** (index compris) ; 15.0 hors index.
- Temps : compaction tiède 12.04 s, migration froid 0.0 s, vérification complète 1.2 s (valide : True), vérification d'un enregistrement 2.87 ms.
- Lecture d'un enregistrement (cache vide) : tiède 2.049 ms (p95 5.317 ms), froid 9.139 ms (p95 17.838 ms).
- Recherche FTS5 : 13.22 ms par requête (15.73 ms avec extraits) ; format actuel : 29.49 ms.
- Effacement RGPD d'un enregistrement dans un bloc : 520.3 ms (bloc réécrit, racine recalculée).

Variantes (même corpus) :

| Variante | Dossier compact/ | Fichiers de blocs | Index après VACUUM | Compaction tiède | Lecture tiède | Recherche |
|---|---:|---:|---:|---:|---:|---:|
| **défaut** (tiède zlib + dict, FTS5 detail=none) | 8.42 Mo | 5.37 Mo | 3.05 Mo | 12.04 s | 2.049 ms | 13.22 ms |
| tiède en lzma (COMPACTION_ALGO_TIEDE=lzma) | 7.17 Mo | 4.12 Mo | 3.05 Mo | 20.7 s | 6.746 ms | 8.04 ms |
| FTS5 detail=full, classement bm25 (COMPACTION_FTS_DETAIL=full) | 10.99 Mo | 5.37 Mo | 5.62 Mo | 9.69 s | 1.907 ms | 6.41 ms |

## 3. Veille et mémoire de travail

- Veille : 5000 fiches sur 360 j ; base 5.97 Mo → 3.02 Mo après archivage des 2500 fiches expirées (> 180 j) en palier froid : 1.29 Mo au lieu de la suppression actuelle (ratio fichiers 7.71).
- Connaissances : 2000 dont 400 quasi-doublons injectés ; 293 fusionnées, 207 évincées (plafond 250/projet) vers l'archive ; base 2.97 Mo → 2.18 Mo en 5.35 s (archive 0.34 Mo, vérification True).

## 4. Projection d'espace disque (archive des missions + index)

Coût par mission mesuré : chaud 6.1 Ko (format actuel + index), tiède 1.06 Ko, froid 0.74 Ko (index compris).

| Rythme | Horizon | Missions | Sans compaction | Avec compaction | Gain | Veille actuelle (purge) | Veille archivée (sans perte) |
|---|---|---:|---:|---:|---:|---:|---:|
| nominal (40/j) | 1 an | 14600 | 88.9 Mo | 19.1 Mo | ×4.6 | 6.0 Mo | 8.7 Mo |
| nominal (40/j) | 3 an | 43800 | 266.8 Mo | 40.8 Mo | ×6.5 | 6.0 Mo | 19.2 Mo |
| 200 % (80/j) | 1 an | 29200 | 177.8 Mo | 38.3 Mo | ×4.6 | 12.0 Mo | 17.4 Mo |
| 200 % (80/j) | 3 an | 87600 | 533.5 Mo | 81.6 Mo | ×6.5 | 12.0 Mo | 38.5 Mo |

## 5. Choix retenus et justification (d'après ces mesures)

- **Blocs plutôt que lignes** : le format actuel (un membre gzip par ligne) plafonne à un ratio de 3.5 ; la concaténation en blocs atteint 9.25 en zlib et 13.69 en lzma, et l'index (bloc, offset) ramène la lecture d'un enregistrement de 111 ms (parcours du mois) à quelques ms.
- **Dictionnaire zlib** : ×1.24 sur des objets isolés (fragments), mais seulement ×1.01 sur des blocs de 1 Mo (la fenêtre zlib de 32 Ko limite sa portée). Conservé car gratuit à la lecture ; versionné.
- **lzma pour le froid** (×1.47 par rapport à zlib) : lecture plus lente mais rare. **zlib pour le tiède** : lecture et recherche avec extraits ~4× plus rapides ; passer le tiède en lzma (COMPACTION_ALGO_TIEDE=lzma) gagnerait encore 15 % pour une lecture à 6.746 ms.
- **Déduplication : gain faible, à ne pas surestimer.** Sur les enregistrements intégraux elle DÉGRADE le ratio (zlib bloc 9.32 → 8.52, lzma 13.69 → 11.31) : un fragment compressé seul perd le contexte du bloc. Dans le pipeline à paliers, avec le critère `rentable` (segments longs et fréquents seulement), elle reste légèrement positive : 186 fragments, 1.00 Mo de texte non répété, ≈ 0,3 % sur le total (8,42 Mo contre 8,44 Mo sans dédup, mesuré à part). Gardée pour les consignes types et gabarits réels (plus longs que dans ce corpus).
- **Paliers** : le plus gros gain vient de la réduction du contenu (tiède ×12.91, froid ×23.15 en fichiers), en gardant ce qui alimente la mémoire collective (problèmes du CHECKER, décisions, métriques, extrait d'exemple) et la chaîne d'empreintes de l'archive.
- **Index FTS5 detail=none** : 5.62 Mo → 3.05 Mo d'index (−23 % au total) ; le classement bm25 est remplacé par « nombre de termes trouvés, puis le plus récent » (COMPACTION_FTS_DETAIL=full pour bm25).
- **Limites** : le chaud (≤ 30 j) et les tables `missions`/`etapes` de nexus.db ne sont pas compactés (hors périmètre) ; le tiède/froid est une réduction volontaire (les sorties intermédiaires des agents disparaissent après 30 j, leur empreinte reste) ; l'effacement RGPD coûte un 'optimize' FTS (~0,5 s).

![Résultats](resultats.png)
