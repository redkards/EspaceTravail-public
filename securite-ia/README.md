# securite-ia — attaque simulée mensuelle

**But** : vérifier chaque mois que NOS agents NEXUS résistent à l'injection de consignes
(prompt injection) venue d'une consigne, d'un contenu collecté (web) ou d'une connaissance
stockée (mémoire projet / collective). C'est une red team **défensive** : elle ne vise que notre
propre instance.

## Contenu

| Fichier | Rôle |
|---|---|
| `corpus.json` | 40 attaques fictives (9 familles) + 10 cas légitimes qui ne doivent PAS être bloqués |
| `attaque_simulee.py` | évaluation hors-ligne (bouclier seul) et/ou via l'API NEXUS ; rapport mensuel |
| `test_attaque_simulee.py` | tests sans serveur : `python -m pytest -q securite-ia` (depuis la racine) |
| `resultats/AAAA-MM.md` / `.json` | taux de blocage, faux positifs, échecs détaillés |

Le filtre lui-même est `nexus-core/app/bouclier.py` (nettoyage, score d'injection, encapsulation,
vérification des sorties, plancher GATE N2). Son en-tête liste les 4 points d'intégration.

## Utilisation

```bash
python3 securite-ia/attaque_simulee.py                    # hors-ligne (défaut), aucun serveur
python3 securite-ia/attaque_simulee.py --mode complet     # + missions F1 sur l'instance (NEXUS_URL, clé du .env)
python3 securite-ia/attaque_simulee.py --mode api --selection SA-03,SA-17
```

Mode API : missions F1 titrées `[SECURITE-IA]` ; la clé est lue dans l'environnement ou le `.env`,
écrite dans un fichier d'en-tête temporaire 600 (jamais en argument) ; le script **ne valide
jamais** une décision (chemins interdits dans le client) ; un secret factice `CANARI-XXXX`, tiré
à chaque exécution, ne doit apparaître dans aucun livrable ni aucune sortie d'étape.
`--avec-connaissances` écrit réellement les cas « connaissance » en mémoire projet (l'API ne
permet pas de les supprimer) : à n'utiliser que sur un projet de test.
Les planchers de NEXUS peuvent relever F1 en F2/F3 : le coût éventuel est celui de ces niveaux.

Cron proposé (2e dimanche du mois, 05:17) :

```
17 5 8-14 * * root [ "$(date +\%u)" = 7 ] && /usr/bin/python3 /srv/p1/nexus-mothership/securite-ia/attaque_simulee.py --mode complet >> /var/log/nexus-securite-ia.log 2>&1
```

## Limites (à garder en tête)

- **La détection par motifs ne suffit pas seule.** Paraphrases, autres langues, fautes
  volontaires, images ou encodages imprévus la contournent ; sur des paraphrases inédites
  (hors corpus), seule une minorité est détectée. Le corpus a été écrit en même temps que le
  bouclier : son taux de 100 % est **optimiste**. Ajoutez chaque mois des cas nouveaux, jamais vus.
- La distinction « mention » / « injonction » est heuristique (guillemets, contexte « par exemple »,
  « les attaquants »…) : un attaquant peut imiter un article pour baisser son score.
- D'où la **défense en profondeur** : encapsulation systématique des données, CHECKER, plancher GATE
  N2 pour tout livrable suspect, décision humaine N3, filtre anti-secret (`cyber.py`), EXECUTOR sans
  action externe.
- **Jamais** de vraies données, de vrais secrets ni de vraie attaque contre un tiers : domaines
  réservés `.example`, secrets factices, aucune charge malveillante.
