#!/usr/bin/env bash
# PARADOXX - Bilan de santé connexion VPS (LECTURE SEULE, aucune modification)
# Usage (sur le VPS, utilisateur paradoxx) :  bash ~/vps-sante.sh
# Les contrôles qui demandent root utilisent sudo -n : sans droit, ils sont notés NON MESURÉ.
set -u
ok(){ printf '[OK]     %s\n' "$*"; }
ko(){ printf '[ECHEC]  %s\n' "$*"; }
nm(){ printf '[NON MESURÉ] %s\n' "$*"; }
h(){ printf '\n== %s ==\n' "$*"; }
S(){ sudo -n "$@" 2>/dev/null; }

echo "=== Santé VPS $(hostname) — $(date '+%d/%m/%Y %H:%M:%S %Z') ==="
uptime -p; last -x reboot 2>/dev/null | head -2

h "S6 — Services au démarrage"
for s in tailscaled ssh fail2ban ufw paradoxx-claude docker; do
  a=$(systemctl is-active "$s" 2>/dev/null); e=$(systemctl is-enabled "$s" 2>/dev/null)
  [[ $a == active && $e == enabled ]] && ok "$s actif + lancé au démarrage" || ko "$s : actif=$a démarrage=$e"
done

h "S7/S8 — Tailscale"
if command -v tailscale >/dev/null; then
  tailscale version | head -1
  j=$(tailscale status --json 2>/dev/null)
  exp=$(printf '%s' "$j" | python3 -c 'import sys,json;d=json.load(sys.stdin)["Self"];print(d.get("KeyExpiry","aucune"))' 2>/dev/null)
  [[ -z $exp || $exp == aucune || $exp == 0001-* ]] && ok "Expiration de clé désactivée" || ko "Clé Tailscale expire le $exp → désactiver l'expiration (console Tailscale)"
  r=$(systemctl show tailscaled -p Restart --value); [[ $r == on-failure || $r == always ]] && ok "tailscaled se relance seul ($r)" || ko "tailscaled Restart=$r"
  tailscale status | head -6
else ko "tailscale absent"; fi

h "S10 — SSH"
if out=$(S sshd -T); then
  grep -qi '^passwordauthentication no' <<<"$out" && ok "Mot de passe SSH interdit" || ko "PasswordAuthentication actif (corriger /etc/ssh/sshd_config.d/50-cloud-init.conf)"
  grep -qi '^permitrootlogin no' <<<"$out" && ok "Root SSH interdit" || ko "PermitRootLogin pas à no"
  grep -iE '^(clientaliveinterval|maxauthtries) ' <<<"$out"
else nm "sshd -T (sudo requis)"; fi

h "S11 — fail2ban / ufw"
if f=$(S fail2ban-client get sshd ignoreip); then
  grep -q '100.64.0.0/10' <<<"$f" && ok "Tailscale exempté du bannissement" || ko "Ajouter ignoreip = 100.64.0.0/10 (jail.local)"
  S fail2ban-client status sshd | grep -E 'Currently banned|Total banned'
else nm "fail2ban (sudo requis)"; fi
S ufw status | head -12 || nm "ufw (sudo requis)"

h "S12 — Claude sur le VPS"
if tmux has-session -t paradoxx 2>/dev/null; then
  ok "Session tmux « paradoxx » présente"
  pane=$(tmux capture-pane -p -t paradoxx | grep -v '^\s*$' | tail -5)
  grep -qi 'not logged in\|/login' <<<"$pane" && ko "Claude demande une reconnexion (/login)" || ok "Session Claude sans alerte de connexion"
else ko "Session tmux « paradoxx » absente"; fi
pgrep -x claude >/dev/null || pgrep -f 'bin/claude( |$)' >/dev/null && ok "Processus claude présent" || ko "Processus claude absent"

h "S13 — Ressources"
d=$(df --output=pcent / | tail -1 | tr -dc 0-9); [[ $d -lt 85 ]] && ok "Disque $d %" || ko "Disque $d % (≥ 85)"
free -h | sed -n 2p
m=$(free | awk '/Mem:/{printf "%d", $7*100/$2}'); [[ $m -gt 15 ]] && ok "RAM disponible $m %" || ko "RAM disponible $m %"

h "Sortie Internet du VPS"
getent hosts api.anthropic.com >/dev/null && ok "DNS VPS OK" || ko "DNS VPS KO"
curl -s -o /dev/null -m 8 -w '%{http_code}' https://api.anthropic.com >/dev/null && ok "HTTPS sortant OK" || ko "HTTPS sortant KO"

echo; echo "Fin du bilan. Copier tout ce texte dans le compte rendu (aucun secret affiché)."
