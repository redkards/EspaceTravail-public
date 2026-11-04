# Veille VPS PARADOXX (v1, 04/11/2026)

Poste de pilotage : **le téléphone** (ntfy + e-mail).

```
systemd (toutes les 5 min) ──► paradoxx-veille.sh ──► ntfy (téléphone) au changement d'état
                                    │
                                    └─(chaque heure + à chaque panne)─► n8n webhook local ──► page Notion « Battement VPS »
Tâche planifiée Claude (toutes les heures) ──► lit « Battement VPS » + canal Notion
        └── si battement > 75 min ou état KO ──► e-mail redkardss@gmail.com
```

Pourquoi ce partage :
- n8n 2.x désactive le nœud « Execute Command » : les contrôles serveur sont faits par systemd, n8n ne fait que transmettre à Notion.
- Zapier gratuit (2 étapes, pas de filtre, webhooks payants, 100 tâches/mois) ne sait pas détecter un silence : c'est la tâche Claude qui joue le rôle du surveillant extérieur.

## Installation (Jérémy, sur le VPS)

1. n8n → Credentials → **Header Auth** « Notion PARADOXX » : `Authorization` = `Bearer <jeton intégration Notion>` (saisi par Jérémy, jamais dans le chat). Partager la page « Battement VPS » avec l'intégration.
2. n8n → Import → `n8n-battement-notion.json` → choisir le credential → **Activer**.
3. `sudo bash ~/veille/install-veille.sh` (sujet ntfy saisi en masqué).

Test : `sudo systemctl start paradoxx-veille.service` → le titre de la page Notion change.
