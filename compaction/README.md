# Compaction de la mémoire et des archives SYFER

Ce dossier contient le **banc de mesure** et la **documentation** du module
`nexus-core/app/compaction.py`. Le module range les vieilles archives de façon beaucoup plus
compacte, **sans perdre** :

- **l'intégrité** : on peut toujours prouver que rien n'a été modifié ;
- **la recherche** : on retrouve une mission par mots-clés ;
- **le droit à l'effacement (RGPD)** : on peut effacer une personne ou une mission, pour de vrai.

Résultats chiffrés : voir [`resultats.md`](resultats.md) (et `resultats.json`, `resultats.png`).

---

## L'idée en 4 points

### 1. Trois « paliers » selon l'âge

| Palier | Âge | Ce qu'on garde | Rangement |
|---|---|---|---|
| **CHAUD** | ≤ 30 jours | tout (rien ne change) | système actuel : base SQLite + `archive/AAAA-MM.jsonl.gz` |
| **TIÈDE** | 31 à 180 jours | livrable complet, consigne, verdicts, décisions, métriques ; pour chaque étape : agent, rôle, verdict, tokens, avis du CHECKER (300 caractères) | blocs compressés **zlib + dictionnaire** |
| **FROID** | plus de 180 jours | résumé (≤ 600 caractères), métriques, empreintes, et tout ce qui nourrit la mémoire collective (problèmes relevés, décisions, extrait d'exemple si la mission était bien notée) | blocs compressés **lzma** (plus fort, plus lent) |

Les seuils se règlent : `COMPACTION_TIEDE_JOURS` (30) et `COMPACTION_FROID_JOURS` (180).

### 2. Ranger par paquets (« blocs »)

Aujourd'hui chaque mission est compressée **seule**. Or les missions se ressemblent beaucoup
(mêmes clés JSON, mêmes formulations des agents). En les compressant **par paquets de 256**
(ou ~1 Mo), le compresseur exploite ces ressemblances : le fichier devient 3 à 4 fois plus petit
qu'aujourd'hui, avant même de réduire le contenu.

Un petit **index SQLite** dit dans quel bloc et à quelle position se trouve chaque mission :
pour en relire une, on ne décompresse **qu'un seul bloc** (quelques millisecondes).

### 3. Ne stocker qu'une fois ce qui se répète

Les textes longs et fréquents (consignes types, gabarits) sont stockés **une seule fois**
(repérés par leur empreinte SHA-256), et les missions y font référence. Un critère de
rentabilité évite de le faire pour les petits textes (le banc montre que ce serait contre-productif).
Honnêtement : le gain mesuré est faible (≈ 0,3 %) ; l'essentiel vient des blocs et des paliers.

### 4. Prouver l'intégrité

- Chaque bloc a une **racine de Merkle** : une empreinte unique calculée à partir de toutes
  ses missions. Si une seule lettre change, la racine change.
- Chaque création, migration ou effacement de bloc est écrit dans un **journal chaîné et signé
  HMAC** avec la **même clé que le LEDGER** (`LEDGER_HMAC_KEY`). Sans la clé, impossible de
  réécrire l'histoire sans que ça se voie.
- La chaîne d'empreintes de l'archive d'origine (`seq`, `prec`, `hash`) est conservée dans chaque
  mission compactée : elle reste vérifiable avec la fonction d'`archive.py`.

---

## Effacement RGPD

`effacer(id, motif)` :

1. réécrit le bloc concerné en remplaçant la mission par une **pierre tombale** (« effacé le …
   à la demande de … ») — l'ancien fichier est remplacé, pas conservé ;
2. retire ses mots de l'index de recherche, supprime les textes partagés qui ne servent plus
   (avec `secure_delete` : les octets sont écrasés dans SQLite) ;
3. recalcule la racine de Merkle et écrit dans le journal chaîné : ancienne racine, nouvelle
   racine, empreinte de l'enregistrement effacé, motif, demandeur ;
4. la vérification reste **valide** : elle contrôle que seule la pierre tombale a changé.

`effacer_mission(mid)` efface tous les enregistrements d'une mission (y compris les
connaissances « livrable #mid » archivées lors d'une consolidation).

⚠️ Les **sauvegardes** (`backup.sh`, 7 jours par défaut) gardent l'ancien bloc jusqu'à leur
rotation : c'est le délai d'effacement complet à annoncer.

---

## Mémoire de travail (connaissances)

`consolider_connaissances(conn, plafond)` :

- repère les **quasi-doublons** (même texte à quelques phrases près : MinHash + Jaccard ≥ 0,85) ;
- garde le meilleur représentant (manuel > import > auto, puis le plus récent) ;
- applique un **plafond par projet** selon un score d'utilité (récence, accès, note, citations) ;
- **n'efface jamais** une connaissance « manuel » ou « import » ; les « auto » retirées sont
  d'abord **archivées** (rien n'est perdu).

Des **résumés agrégés** (jour → semaine → mois : nombre de missions, tokens, coût, durée, note
moyenne) sont tenus pour le tableau de bord : `agregats("j" | "s" | "m")`.

---

## Entretien la nuit

`tache_nocturne()` ne fait rien hors de la fenêtre de nuit (`NEXUS_FENETRE_NUIT`, défaut
01:00-06:00 heure de Paris), ni plus d'une fois par jour, et prend un verrou (deux processus ne
peuvent pas compacter en même temps). Elle enchaîne :

1. compaction tiède puis froid ;
2. (option) consolidation des connaissances (`COMPACTION_PLAFOND_CONNAISSANCES`) ;
3. archivage de la veille expirée (au lieu de la supprimer) ;
4. entretien SQLite de `nexus.db`, `veille.db` et de l'index : `auto_vacuum` incrémental,
   `optimize` des index plein texte, `ANALYZE`, `VACUUM` complet le dimanche
   (`COMPACTION_VACUUM_JOUR`) ou si plus de 25 % de la base est vide.

---

## API

```python
from app import compaction
c = compaction.defaut(journal=ledger.journaliser)

c.compacter("tiede")                     # ou "froid" ; avant_date=… pour forcer une date
c.lire("m:1234")                         # un enregistrement (seq d'archive 1234)
c.lire_mission(42)                       # tous les enregistrements de la mission 42
c.rechercher("sauvegarde serveur", projet="studio-master")
c.verifier()                             # vérification complète
c.verifier_enregistrement("m:1234")      # preuve de Merkle d'un seul enregistrement
c.effacer("m:1234", "droit à l'effacement", demandeur="Kevin")
c.statistiques()                         # tailles avant/après, ratio, blocs, dédup
c.reprendre()                            # après un arrêt brutal (fait aussi automatiquement)
```

Après un arrêt brutal, rien n'est à moitié écrit : soit l'opération est entièrement prise en
compte, soit elle est annulée ; `reprendre()` range les fichiers restés en suspens.

---

## Fichiers

```
<archive>/compact/
  compaction.db          index : blocs, positions, feuilles de Merkle, fragments, journal, agrégats, FTS5
  blocs/tiede/*.blk      un fichier par bloc (zlib + dictionnaire)
  blocs/froid/*.blk      un fichier par bloc (lzma)
  dictionnaires/v1.zdict dictionnaires zlib versionnés (jamais supprimés)
```

**À sauvegarder ensemble** (le dossier entier). L'intégration (`archive.py`, `memoire.py`,
veille, boucle de nuit, `backup.sh`) est décrite dans le bloc « INTÉGRATION » en tête de
`nexus-core/app/compaction.py`.

---

## Refaire les mesures

```bash
python3 compaction/mesure.py                    # 10 000 missions (~5 min)
python3 compaction/mesure.py --missions 2000    # rapide
cd nexus-core && python3 -m pytest tests/test_compaction.py -q
```
