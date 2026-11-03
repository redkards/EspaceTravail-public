# REDKARDS (BD / webtoon) — plan d'emploi des agents NEXUS

Code projet : `redkards` · cockpit : https://srvXXXX.hstgr.cloud/cockpit · modèles : `RK-1` à `RK-6` dans `missions-modeles.json`.
Contexte de référence : `../tests-poker/contexte/redkards.md`.

## Principe
Les agents préparent : synopsis, contrôles et plans. Le propriétaire garde la main sur la direction artistique, le style et toute diffusion. Aucun agent ne publie : les EXECUTOR enregistrent seulement le livrable.

## Tâches récurrentes

| Tâche | Service NEXUS | Modèle | Fréquence | Niveau | Ce que le propriétaire valide dans le cockpit |
|---|---|---|---|---|---|
| Synopsis d'un épisode (250–350 mots) | CONTENT-ARENA/redaction | RK-1 | 1 par épisode à scénariser (S1 : E02–E20, puis S2) | N2 | Relit le livrable ; pas de décision bloquante, mais rien ne part sans sa relecture |
| Cohérence avec la bible narrative | AGENT-FACTORY/evaluation | RK-2 | à chaque synopsis ou storyboard modifié | N1 | Arbitre les incohérences signalées |
| Post de promotion d'un épisode | CONTENT-ARENA/redaction (+ action `publier`) | RK-3 | 1 à 2 par semaine une fois la diffusion lancée | **N3** | Fiche de décision : Valider / Refuser / Demander une révision. La publication reste manuelle |
| Plan de production (dessin E02–E20) | OPS-CORE/projets | RK-4 | 1 par mois, ou à chaque changement de capacité | N1 | Valide le calendrier et les priorités |
| Crédibilité poker d'une main | R&D-PARADOX/veille | RK-5 | pour chaque épisode contenant une main clé | N1 | Choisit entre la version d'origine et la version corrigée |
| Conformité d'un épisode (marques, mineurs, jeu responsable) | LEX-GUARD/conformite | RK-6 | avant toute diffusion d'un épisode | N2 | Tranche les points de gravité élevée |

## Circuit type d'un épisode
1. RK-1 synopsis → 2. RK-5 main clé → 3. RK-2 cohérence → 4. storyboard / dessin (humain) → 5. RK-6 conformité → 6. RK-3 post de promotion (N3, décision dans le cockpit).

## Garde-fous
- Compétitions, marques et joueurs fictifs ; pas de glorification du jeu d'argent.
- Toute mission contenant « publier », « envoyer », un montant ou une action engageante passe en N3 (règles du GATE, non contournables par le LLM).
- Le texte d'un épisode transmis dans `{{texte}}` doit être un extrait court ; pas de données personnelles.
