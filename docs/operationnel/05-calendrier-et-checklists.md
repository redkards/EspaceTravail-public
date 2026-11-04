# 05 — Calendrier et checklists imprimables

> Imprimez cette page (Chrome > ⋮ > Partager > Imprimer) ou recopiez les cases dans le QG Notion.
> Une case = une vérification **faite par vous**, pas supposée.

## 1. Calendrier de novembre–décembre 2026 (plan d'action ATLAS)

| Date | Action | Responsable | État |
|---|---|---|---|
| 04/11 | Snapshot neuf | Décideur | **[PRÉVU]** |
| 04/11 | Secrets rangés dans un gestionnaire de mots de passe | Décideur | **[PRÉVU]** |
| 04/11 | Budget retenu ≈ 90 € TTC/mois, configuration complète | Décideur | **[FAIT]** (décidé) |
| 05/11 | Nouvelle clé Ollama Cloud ou 100 % local | Décideur, guidé par Claude | **[PRÉVU]** |
| 06/11 | Déployer la V2 + activer les tâches | Décideur + Claude | **[PRÉVU]** |
| 07/11 | Exercice de restauration + attaque simulée | Décideur lance, Claude analyse | **[PRÉVU]** |
| 08–09/11 | Premiers rapports du dimanche | Claude | **[PRÉVU]** |
| 10/11 | Copie hors serveur chaque nuit (rclone) | Décideur + Claude | **[PRÉVU]** |
| 12/11 | Dépôt GitHub en privé | Décideur | **[PRÉVU]** |
| 14/11 | SSH via Tailscale, mot de passe SSH coupé | Claude prépare, Décideur valide | **[PRÉVU]** |
| 18/11 | Plafonner ou arrêter n8n Hostinger ; nettoyer les images | Claude propose, Décideur valide | **[PRÉVU]** |
| **avant 25/11** | **Achat** KVM 8 + vitrine, coffre externe, 2 clés physiques, Bitwarden | Décideur | **[PRÉVU]** |
| 25–29/11 | Migration vers le KVM 8 (procédure 3) | Claude + Décideur | **[PRÉVU]** |
| **30/11** | Échéance du KVM 2 : paiement ou fin de migration vérifiés | Décideur | **[PRÉVU]** |
| 06/12 | 1er exercice de restauration automatique | Claude vérifie | **[PRÉVU]** |
| décembre | Avant toute vente : SIREN, antériorité « SYFER », e-Soleau, licence et CGV B2B, RC pro | Décideur | **[PRÉVU]** |

## 2. Calendrier récurrent

| Fréquence | Moment | Quoi |
|---|---|---|
| Quotidien | 12 h 30 · 19 h | Sessions N3, bilan du jour |
| Hebdomadaire | Lundi 7 h 30 – 8 h | Plan de la semaine, leçons |
| Hebdomadaire | Dimanche (lecture lundi) | Rapport cyber, banc d'essai |
| Mensuel | 1er dimanche | Exercice de restauration |
| Mensuel | 2e dimanche | Attaque simulée |
| Mensuel | Dernier jour | Revue des coûts, checklist fin de mois |
| Trimestriel | Janvier, avril, juillet, octobre | Rotation des secrets, revue veille et projets |
| Annuel | Date anniversaire du VPS − 30 jours | Décision de renouvellement (dans 2 ans, le KVM 8 repasse à ≈ 60 € TTC/mois : prévoir un retour au KVM 4) |

---

## 3. Checklist — Mise en production (nouvelle version)

**Avant (J-1)**
- [ ] Porte de qualité : `Déploiement AUTORISÉ.` (Claude, hors serveur)
- [ ] Intégration continue GitHub verte sur la branche à déployer
- [ ] Notes de version lues (ce qui change, ce qui se casse, retour arrière)
- [ ] Créneau calme choisi (1 h), téléphone chargé, aucune session N3 en cours
- [ ] Mot de passe hPanel et `BACKUP_PASSPHRASE` accessibles hors du VPS

**Pendant**
- [ ] Snapshot hPanel créé et **terminé**
- [ ] `bash backup.sh` réussi — nom noté : `________________`
- [ ] Branche notée : `________________` · commit noté : `________`
- [ ] `git status --short` vide
- [ ] Code récupéré (`git fetch` + `git checkout`)
- [ ] `bash install.sh` terminé sans erreur

**Vérifications (procédure 2B, étape 5)**
- [ ] 1. `docker compose ps` : tout `healthy`
- [ ] 2. `/cockpit` sans mot de passe → 401
- [ ] 3. `/mcp` sans jeton → 401
- [ ] 4. En-têtes de sécurité : 3
- [ ] 5. `/api/sante` : `ledger_hmac` true, `avertissements` vide
- [ ] 6. 6 tâches `nexus` dans `/etc/cron.d/`
- [ ] 7. Exercice de restauration : OK
- [ ] 8. Attaque simulée hors ligne : ≥ 95 %
- [ ] `/cockpit/decideur` s'ouvre ; LEDGER vérifié

**Après**
- [ ] Nouveau snapshot (nouveau point sûr)
- [ ] Surveillance 48 h : alertes ntfy normales, aucune mission `echouee` inexpliquée
- [ ] Résumé bref dans le QG Notion (version, date, résultat)

## 4. Checklist — Fin de mois

- [ ] Alerte « Restauration testée : OK » reçue (1er dimanche)
- [ ] Rapport d'attaque simulée lu : ≥ 95 %, 0 faux positif bloquant, canari jamais ressorti
- [ ] 4 rapports cyber du mois lus ; actions N3 décidées
- [ ] Banc d'essai : pas de baisse > 5 points sur le mois
- [ ] Leçons : aucune en attente depuis plus de 2 semaines ; suspensions comprises
- [ ] Sauvegarde < 24 h et copie hors serveur < 48 h
- [ ] Snapshot de moins de 30 jours
- [ ] Partitions < 80 % (`df -h /srv/p*`)
- [ ] Coûts : Hostinger conforme · Ollama dans la limite gratuite · dépense IA = budget validé
- [ ] Échéance du VPS > 30 jours (sinon : décision de renouvellement)
- [ ] Demandes RGPD du mois traitées et inscrites au registre
- [ ] Mises à jour Ubuntu appliquées (automatiques : vérifier `apt list --upgradable` vide)
- [ ] Synthèse du mois dans le QG Notion (5 lignes)

## 5. Checklist — Avant tout achat

- [ ] Besoin écrit en une phrase (quel problème l'achat résout)
- [ ] Alternative gratuite étudiée et écartée pour une raison claire
- [ ] Simulation SYFER ÉCHO ou banc d'essai à l'appui (si l'achat touche l'IA ou le serveur)
- [ ] Prix **TTC** relevé sur le site officiel, avec la date du relevé
- [ ] Prix de **renouvellement** relevé (et pas seulement le prix d'appel)
- [ ] Durée d'engagement et montant **payé d'avance** (ex. 24 mois)
- [ ] Conditions de résiliation et de remboursement lues
- [ ] Impact sur le budget mensuel (≈ 90 € TTC/mois retenu) : `______ €`
- [ ] Données : où sont-elles hébergées ? (UE de préférence) Contrat de sous-traitance disponible ?
- [ ] Pour une IA payante : plafond fixé **avant** activation (`BUDGET_MONTHLY_EUR`), F4 validé mission par mission
- [ ] TVA : en micro-entreprise en franchise, raisonner en **TTC** (non récupérable) — à confirmer avec un comptable
- [ ] Décision prise **par vous**, notée dans le QG (date, montant, raison). Claude n'achète rien.

## 6. Checklist — Avant la première vente (SYFER ou un service bâti dessus)

> Information générale, ne remplace pas l'avis d'un avocat ou d'un expert-comptable.

**Entreprise**
- [ ] Statut créé (micro-entreprise prévue), **SIREN** obtenu
- [ ] Assurance **RC professionnelle** souscrite
- [ ] Compte bancaire dédié à l'activité

**Propriété intellectuelle**
- [ ] Recherche d'antériorité du nom « SYFER » (INPI, EUIPO) ; dépôt de marque décidé
- [ ] Preuve de création (e-Soleau ou équivalent)
- [ ] Licence choisie (aujourd'hui : tous droits réservés) ; licences des composants open source respectées
- [ ] Dépôts GitHub en **privé**

**Contrats et conformité**
- [ ] **CGV B2B** rédigées et relues
- [ ] **Registre des traitements** (RGPD art. 30)
- [ ] **Contrat de sous-traitance** (RGPD art. 28) pour les clients
- [ ] Liste des sous-traitants ultérieurs (Hostinger, Ollama Cloud, Anthropic si F4, Google Drive si utilisé)
- [ ] Mention **« généré par IA »** sur les livrables concernés (AI Act art. 50)
- [ ] Procédure d'effacement **définitif** dans la passerelle (aujourd'hui : archivage seulement)
- [ ] Sauvegardes **chiffrées** hors serveur (pas de bases en clair sur Drive)

**Technique**
- [ ] Données de chaque client isolées (une instance ou une partition par client)
- [ ] Administration par Tailscale, SSH par mot de passe coupé
- [ ] Porte de qualité verte sur la version vendue ; numéro de version SemVer figé
- [ ] Procédure d'incident testée (Fiche 7) et contact CNIL connu

> **Avis d'expert** (certitude élevée) — Ne vendez pas tant que les cases « contrat de sous-traitance »,
> « effacement définitif » et « sauvegardes chiffrées » ne sont pas cochées : ce sont les trois points
> qu'un client sérieux vérifiera en premier.
