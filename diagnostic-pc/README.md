# Diagnostic connexion PC → VPS (mission Claude Code)

**Lancement en 1 commande (PowerShell, PC Windows) :**

```powershell
irm https://raw.githubusercontent.com/redkards/espacetravail-public/nexus-mothership-kit/diagnostic-pc/test-connexion.ps1 | iex
```

**Variante Python 3.14 :**

```powershell
py -c "import urllib.request as u;exec(u.urlopen('https://raw.githubusercontent.com/redkards/espacetravail-public/nexus-mothership-kit/diagnostic-pc/test_connexion.py').read())"
```

Si GitHub ne répond pas (DNS cassé), lancer d'abord :
`ipconfig /flushdns; tailscale set --exit-node=` puis relancer la commande.

## Ce que fait le test (automatique)

1. Réseau local : passerelle, Internet par IP, serveurs DNS.
2. DNS : claude.ai, api.anthropic.com, github.com, google.com + test direct via 1.1.1.1.
3. Tailscale : état, exit node, DNS Tailscale.
4. Réparations sûres et réversibles **seulement si le DNS est cassé** : vidage DNS → désactivation exit node → `accept-dns=false`.
5. VPS : `tailscale ping`, port 22, SSH par clé (`ssh paradoxx`), services, tmux, Claude, Docker.
6. Rapport : `Bureau\diagnostic-paradoxx.txt` + presse-papiers.

Aucun mot de passe demandé, aucun secret écrit.

## Consigne pour Claude Code (PC)

> Lance `diagnostic-pc/test-connexion.ps1`, lis le rapport, corrige ce qui est en [ECHEC] dans la limite des règles du canal Notion « Canal Claude Cloud ↔ Claude PC » (actions ADMIN JÉRÉMY : montrer la commande et attendre « OUI »), puis écris le compte rendu dans ce canal (Pour = Claude Cloud, Réponse à = l'ordre correspondant).

## Résilience (v1, 04/11/2026)

- `SCENARIOS.md` : 15 situations de panne, chemins de secours, simulation NEXUS.
- `vps-sante.sh` : bilan de santé VPS en **lecture seule** (à lancer par Claude PC sur le VPS).
- `correctifs-admin.sh` : correctifs S10 + S11, **à lancer par Jérémy** avec sudo (sauvegarde + retour arrière).
- `test-multiscenarios.ps1` : test de stabilité PC → VPS (S1, S2, S4, S5, S7, S9, exposition publique), lecture seule.
- `SCHEMA-CONFIG.md` + `schema-config.png` : configuration cible (Tailscale, ufw, sshd, fail2ban, pare-feu Hostinger).

## Adresse du VPS (variables d'environnement)

Les scripts ne contiennent plus l'adresse du serveur. Sur le PC, définir une fois (PowerShell) :

```powershell
[Environment]::SetEnvironmentVariable('PARADOXX_VPS_IP', '<IP Tailscale du VPS>', 'User')        # tailscale ip -4 paradoxx-vps
[Environment]::SetEnvironmentVariable('PARADOXX_VPS_PUBLIC', '<nom public du VPS>', 'User')
```

Sans ces variables, les scripts utilisent le nom MagicDNS `paradoxx-vps` (le test « DNS cassé » S1 demande l'IP).
