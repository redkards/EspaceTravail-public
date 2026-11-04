# SERENITY P4 — maquette virtuelle (V3.1)

BROUILLON — généré par IA, à valider · 04/11/2026 · NIVEAU ADMIN JÉRÉMY (installation serveur) · 0 €

## Architecture
```
IA (Claude, ChatGPT, Gemini) ──jeton──► nexus-bridge ─┐
                                                      ├─ p1-nexus-net (aucun port public)
SERENITY P4 (1 cœur · 4 Go · /srv/p4) ◄──jeton IA─────┘
   ├─ 4 rôles : COLLECTOR → ANALYST → CHECKER (3 refus = ÉCHEC) → EXECUTOR
   ├─ 9 profils : principale + 8 mini-structures (modules 12, 15-21)
   ├─ MNEMOS : SQLite signé HMAC, secrets masqués
   └─ Leçons : CANDIDATE → PROPOSÉE (3 vues, 2 sources) → ACCEPTÉE (jeton Décideur, 5 max)
        └─ IA locale : ollama qwen2.5:3b (partagée, 0 €)
```

## Garde-fous
- Classement déterministe avant l'IA ; jamais de baisse ; REFUS (faux Décideur, promesse de gains…) sans appel IA.
- SERENITY n'exécute rien : brouillons et cartes seulement.
- Conteneur : lecture seule, aucun droit système, utilisateur sans privilège, 128 processus max.

## Tests (FAIT)
| Banc | Résultat |
|---|---|
| Classement (12 cas), 4 rôles, 3 refus = ÉCHEC | ✅ |
| MNEMOS : signature, altération détectée, secrets masqués | ✅ |
| Leçons : 3 vues + 2 sources, quarantaine, 5 max | ✅ |
| HTTP : jeton obligatoire, acceptation réservée au Décideur | ✅ |
| **Total** | **16/16** |
| docker compose config (25 %, aucun port) | ✅ |

## Limites (SIMULÉ / NON TROUVÉ)
- Modules 12, 15-21 résumés depuis l'index V3.1 : contenu exact à importer du zip SYFER.
- Code MNEMOS v2 et 8 mini-structures du projet « Écosystème Poker » non accessibles : remplacés par cette version.
- Qualité des réponses limitée par qwen2.5:3b (modèle 7B = carte séparée).

## Installation réelle (après carte)
`bash installer-serenity.sh` → secrets générés sur le serveur, jamais affichés · retour : `--retour` (données conservées).
