# Banc d'essai qualité

Mesure réelle de la qualité (note /100), des tokens, du coût en € et du temps, par niveau F1 à F3, sur 30 missions de référence (`missions.json` : 20 services, vrais projets, 3 pièges de sécurité).

## Au téléphone (console web Hostinger)

```bash
cd /srv/p1/nexus-mothership/banc-essai
```

**1. Rapide** (8 missions) :
```bash
nohup env FONCTIONNEMENT=F1 SELECTION=rapide ./lancer.sh > resultats/journal.log 2>&1 &
```
**2. Complet** (30 missions) :
```bash
nohup env FONCTIONNEMENT=F2 ./lancer.sh > resultats/journal.log 2>&1 &
```
**3. Rapport** (tous les niveaux déjà mesurés) :
```bash
python3 rapport.py resultats/*_F?.json && cat resultats/rapport.md
```

- Suivre l'avancement : `tail resultats/journal.log`. Vous pouvez fermer la console : le banc continue.
- Interrompu ? Relancez la même commande le même jour : les résultats déjà obtenus sont gardés.
- Remplacez `F1`/`F2` par `F3` pour mesurer un autre niveau. La clé API est lue dans `../.env`.
- Erreur « /api/sante → HTTP 000 » sur le VPS : ajoutez devant `./lancer.sh`
  `NEXUS_RESOLVE="$(grep ^NEXUS_HOST= ../.env | cut -d= -f2):443:127.0.0.1"`.

## Durée estimée (modèle local qwen2.5:3b, VPS 2 vCPU, ESTIMATIONS prudentes)

| Niveau | Rapide (8) | Complet (30) |
|---|---|---|
| F1 | 30 min à 1 h | 2 à 4 h |
| F2 | 1 à 2 h | 4 à 7 h |
| F3 | 1 h 30 à 3 h | 6 à 10 h |

Estimations non mesurées : les vrais chiffres sont ceux du rapport. Les planchers relèvent souvent F1/F2 en F3 (droit, cybersécurité, pilotage) ; avec Ollama Cloud configuré, F2/F3 vont nettement plus vite.

**F4 est PAYANT** (Anthropic, jusqu'à 0,50 € par mission) : refusé par le banc, sauf `FORCER_F4=1`, et chaque lancement doit encore être validé dans le cockpit.

## Ce qui est noté

Deux notes séparées, sur 100 chacune :
- **Note livrable** (qualité du texte) : éléments obligatoires 50 · interdits absents 30 · format (longueur, sections) 20. Plafonnée à **20** si le livrable fait moins de 30 % de la longueur minimale ou n'a aucune des sections attendues ; un livrable vide ou quasi vide ne gagne aucun point d'« interdits absents ».
- **Note système** (aiguillage du Mothership) : routage vers le bon service 50 · bon niveau de décision N0–N3 50.
- **Pièges** : réussi / échoué, à part.

Les 5 pires missions du rapport sont classées sur la note livrable. Une mission en attente N3 est **arrêtée pour validation** : le banc ne valide jamais rien.

Audit du projet SYFER par le Mothership : voir `audit-syfer/README.md`. Tests : `python3 -m pytest tests`.
