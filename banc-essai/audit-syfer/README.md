# Audit SYFER par le Mothership

10 missions d'audit du projet SYFER (NEXUS MOTHERSHIP + Mini Mothership + agents NEXUS + nexus-bridge), en **F3**, projet `nexus`, chacune confiée à son service (cybersécurité, architecture, code, droit français et européen, études, pilotage, environnement). Chaque consigne contient un court dossier factuel tiré du dépôt, sans secret ni adresse.

```bash
cd /srv/p1/nexus-mothership/banc-essai
```

**1. Lancer** :
```bash
nohup env MISSIONS=audit-syfer/missions.json ./lancer.sh > resultats/journal-audit.log 2>&1 &
```
**2. Rapport** :
```bash
MISSIONS=audit-syfer/missions.json python3 rapport.py --nom audit-syfer resultats/*audit-syfer*.json && cat resultats/rapport_audit-syfer.md
```

- **Durée estimée** en F3 avec le modèle local qwen2.5:3b : **2 à 4 heures** (≈ 10 à 20 min par mission ; estimation, pas une mesure). Bien plus rapide avec Ollama Cloud.
- Les livrables complets sont dans `resultats/*audit-syfer*.json` et dans le cockpit.
- 5 missions sur 10 s'arrêtent en **attente de décision N3** (montants, contrat, mot de passe, pare-feu cités dans le dossier) : c'est voulu, leur livrable est lisible dans le cockpit ; le banc ne valide rien.
- Aucun coût : F3 n'utilise que des modèles gratuits.
