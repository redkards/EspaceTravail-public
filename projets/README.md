# projets/ — lancer une mission NEXUS pour un projet

| Fichier | Contenu |
|---|---|
| `redkards.md`, `poker-feeling.md`, `poker-winners.md` | Plan d'emploi des agents par projet (services, fréquence, niveau N0–N3, ce que vous validez) |
| `tous-les-projets.md` | Codes projet de tous les projets et services conseillés |
| `missions-modeles.json` | 18 modèles (6 par projet poker) avec `{{placeholders}}` |
| `lancer-mission.sh` | Remplit un modèle et envoie la mission à l'API |

## Depuis le téléphone (console hPanel)

1. hPanel → VPS → **Terminal du navigateur** (connexion root).
2. Se placer dans le kit et charger la clé (elle n'est jamais affichée) :
   ```bash
   cd /srv/p1/nexus-mothership/projets
   export NEXUS_API_KEY=$(grep '^NEXUS_API_KEY=' ../.env | cut -d= -f2-)
   export NEXUS_RESOLVE="srv2113898.hstgr.cloud:443:2.24.51.112"   # sur le VPS, force l'IP publique
   ```
3. Voir les modèles et les clés à remplir :
   ```bash
   ./lancer-mission.sh --liste redkards
   ```
4. Tester sans envoyer, puis envoyer :
   ```bash
   SIMULATION=1 ./lancer-mission.sh redkards 1 saison=1 episode=4 titre_episode="La Table" situation="premier tournoi sérieux"
   ./lancer-mission.sh redkards 1 saison=1 episode=4 titre_episode="La Table" situation="premier tournoi sérieux"
   ```
   Mission hors modèle, pour n'importe quel projet :
   ```bash
   ./lancer-mission.sh turf libre titre="Plan de la semaine" consigne="Établis une checklist ..." service=OPS-CORE/projets
   ```
5. Suivre et décider dans le cockpit : https://srv2113898.hstgr.cloud/cockpit (sélecteur de projet). Les missions N3 attendent vos boutons Valider / Refuser / Demander une révision ; rien n'est publié ni envoyé automatiquement.

Astuce téléphone : mettez les valeurs longues entre guillemets ; pour un `{{texte}}` long, préférez le formulaire « Nouvelle mission » du cockpit.
Code projet inconnu ou valeur manquante → le script s'arrête avec un message clair, sans rien envoyer.
