# Matrice de résilience — connexion PC / S23 → VPS PARADOXX

Version 1 — 04/11/2026. Statut : **SIMULÉ** (maquette virtuelle). La colonne « Test réel » sert à Claude PC.

Chemins d'accès, du plus rapide au secours ultime :

1. **A — Tailscale SSH direct** (PC : `ssh paradoxx`, S23 : Termius) — principal.
2. **B — Tailscale par relais DERP** (automatique si le direct échoue) — plus lent, même commande.
3. **C — Session Claude « PARADOXX VPS »** (appli Claude, Remote Control) — pas de terminal requis.
4. **D — Canal Notion** (MISSIONS VPS / Canal Claude Cloud ↔ Claude PC) — asynchrone, toutes les heures.
5. **E — Console navigateur hPanel** — ne dépend ni de Tailscale ni de SSH. Secours ultime.

| # | Situation | Effet attendu | Chemin qui reste | Parade / amélioration | Test réel | Niveau |
|---|---|---|---|---|---|---|
| S1 | DNS du PC cassé (ERR_NAME_NOT_RESOLVED) | Claude desktop, GitHub, Notion KO ; Tailscale par IP OK | A (par IP Tailscale du VPS) | `ipconfig /flushdns` ; exit node off ; repli `accept-dns=false` | `Resolve-DnsName claude.ai` + `ssh paradoxx` | Sûr |
| S2 | MagicDNS ne résout plus `paradoxx-vps` | `ssh paradoxx-vps` KO | A par IP | Alias SSH avec **IP en HostName** (pas le nom) | `ssh -G paradoxx \| findstr hostname` | Sûr |
| S3 | Box / fibre en panne | Plus d'Internet sur le PC | A depuis le S23 en 4G | Partage de connexion S23 → PC | Termius en 4G (Wi-Fi coupé) | Sûr |
| S4 | Connexion directe bloquée (NAT, Wi-Fi public) | Ping Tailscale « via DERP » plus lent | B | Rien à faire ; surveiller la latence | `tailscale ping paradoxx-vps` + `tailscale netcheck` | Sûr |
| S5 | Coupure brève (Wi-Fi qui saute, veille) | Session SSH figée | A + reprise | `ServerAliveInterval 30` ; **Mosh** pour le S23 ; tmux côté VPS | Couper le Wi-Fi 20 s pendant `ssh paradoxx` | Sûr |
| S6 | Redémarrage du VPS (MAJ, changement d'offre) | 1–3 min KO puis retour | E pendant le reboot | tailscaled, ssh, fail2ban, paradoxx-claude **enabled** au démarrage | `systemctl is-enabled …` | Lecture : sûr / reboot : ADMIN |
| S7 | Clé de machine Tailscale expirée (180 j) | VPS disparaît du réseau d'un coup | E | **Désactiver l'expiration de clé** pour paradoxx-vps dans la console Tailscale | `tailscale status --json` → `KeyExpiry` | Lecture sûr / correction ADMIN |
| S8 | tailscaled arrêté sur le VPS | A, B KO | C, D, E | `Restart=always` (déjà par défaut) ; relance via E | `systemctl show tailscaled -p Restart` | Sûr |
| S9 | Clé SSH du PC perdue / PC réinstallé | `Permission denied (publickey)` | A depuis le S23 (Tailscale SSH), E | 2e clé de secours rangée hors PC ; Tailscale SSH actif | `tailscale status --json` → `SSH_HostKeys` / test S23 | Sûr |
| S10 | sshd réautorise le mot de passe (cloud-init 50-cloud-init.conf) | Surface d'attaque accrue | Tous | Corriger 50-cloud-init.conf → `PasswordAuthentication no` | `sudo sshd -T \| grep -i passwordauth` | Lecture sûr / correction ADMIN |
| S11 | fail2ban bannit l'IP du PC | SSH refusé depuis Internet | A (Tailscale exempté) | `ignoreip = 100.64.0.0/10` dans jail.local | `sudo fail2ban-client get sshd ignoreip` | Lecture sûr / correction ADMIN |
| S12 | Session Claude du VPS déconnectée (login expiré, quota) | C KO, missions à l'arrêt | A, D, E | Service paradoxx-claude + alerte ntfy si « Not logged in » | `tmux capture-pane -p -t paradoxx \| tail` | Sûr |
| S13 | Disque ou RAM pleins | Services qui tombent, SSH lent | E | Seuils d'alerte 85 % (Uptime Kuma / ntfy) | `df -h /` ; `free -h` | Sûr |
| S14 | Abonnement VPS expiré (30/11) | Tout KO, données menacées | Aucun | **Renouveler avant le 25/11** + sauvegarde hors VPS | hPanel → Facturation | ADMIN |
| S15 | Compte Tailscale (Google) inaccessible | Plus d'ajout d'appareil | Appareils déjà liés OK | 2FA + codes de secours Google rangés | — | ADMIN |

## Priorités (avis d'expert)

1. **S14** renouvellement, **S7** expiration de clé : ce sont les deux seules pannes qui coupent tout d'un coup et sans prévenir.
2. **S10** et **S11** : sécurité et faux blocages, corrections en 1 ligne.
3. **S2** et **S5** : confort, appliqués côté PC sans risque (`~/.ssh/config`).
4. Le reste est déjà couvert.

## Bloc `~/.ssh/config` recommandé (PC Windows : `%USERPROFILE%\.ssh\config`)

```
Host paradoxx
    HostName <IP_TAILSCALE_DU_VPS>   # tailscale ip -4 paradoxx-vps
    User paradoxx
    ServerAliveInterval 30
    ServerAliveCountMax 4
    ConnectTimeout 10
    TCPKeepAlive yes
```

Garder l'IP en HostName : ça marche même quand MagicDNS est désactivé (S1, S2).

## Simulation NEXUS virtuelle — 04/11/2026 23 h 25 (SIMULÉ, à confirmer en réel)

Données d'entrée : compte rendu Claude PC MSG-9 (04/11 23 h 15), procédure Notion du 03/11, page VPS Nexus du 04/11.

| Agent virtuel | Scénarios | Verdict simulé | Correction proposée | Qui |
|---|---|---|---|---|
| NET-CORE (réseau) | S1, S2, S3, S4, S5 | S1 réglé ; S2 **à risque** si l'alias pointe sur le nom ; S5 **à risque** (pas de keepalive, Mosh absent) | Bloc `~/.ssh/config` ci-dessus ; Mosh via passerelle S23 (MSG-7) | Claude PC (config PC) / Jérémy (sudo) |
| TS-GUARD (Tailscale) | S7, S8 | S8 OK (tailscaled actif) ; S7 **inconnu, risque majeur** | Désactiver l'expiration de clé de paradoxx-vps | Jérémy (console Tailscale) |
| SSH-SENTINEL (accès) | S9, S10, S11 | S9 couvert par Tailscale SSH ; S10 **probable ÉCHEC** (cloud-init relevé le 03/11) ; S11 inconnu | Corriger 50-cloud-init.conf + ignoreip Tailscale | Jérémy (sudo) |
| OPS-CORE (services) | S6, S12, S13 | S6, S12, S13 OK au 04/11 23 h 15 | Alerte ntfy si Claude « Not logged in » (après MSG-7) | Claude PC |
| PILOT-CORE (contrat) | S14, S15 | S14 **critique** : expiration 30/11, renouvellement auto off | Renouveler avant le 25/11 | Jérémy |

Bilan simulé : **4 risques réels** (S7, S10, S14, S5), tous corrigeables gratuitement sauf S14 (renouvellement payant, déjà prévu). Fusion des solutions : un seul passage `sudo` de Jérémy règle S5 (Mosh), S10 et S11 en même temps (voir ordre Notion).
