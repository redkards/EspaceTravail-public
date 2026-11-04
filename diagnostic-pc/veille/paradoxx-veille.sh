#!/usr/bin/env bash
# PARADOXX - Veille connexion VPS (lancée toutes les 5 min par systemd, en root, lecture seule)
# Alerte le téléphone (ntfy) au CHANGEMENT d'état ; envoie un battement horaire à n8n (-> Notion).
# Aucun secret ici : le sujet ntfy et l'URL n8n sont lus dans /etc/paradoxx/veille.conf (root, 600).
set -u
CONF=/etc/paradoxx/veille.conf; [[ -r $CONF ]] && . "$CONF"
NTFY_URL=${NTFY_URL:-}            # ex. https://ntfy.sh/<sujet-secret>
N8N_WEBHOOK=${N8N_WEBHOOK:-http://127.0.0.1:5678/webhook/paradoxx-battement}
ETAT=/var/lib/paradoxx/veille.etat; mkdir -p /var/lib/paradoxx

ko=()
systemctl is-active -q tailscaled || ko+=("tailscaled arrêté")
tailscale status >/dev/null 2>&1   || ko+=("Tailscale déconnecté")
systemctl is-active -q ssh         || ko+=("sshd arrêté")
systemctl is-active -q fail2ban    || ko+=("fail2ban arrêté")
systemctl is-active -q paradoxx-claude 2>/dev/null || ko+=("service paradoxx-claude arrêté")
pane=$(su - paradoxx -c "tmux capture-pane -p -t paradoxx 2>/dev/null" | grep -v '^\s*$' | tail -5)
grep -qi 'not logged in\|/login' <<<"$pane" && ko+=("Claude VPS à reconnecter (/login)")
d=$(df --output=pcent / | tail -1 | tr -dc 0-9); (( d >= 85 )) && ko+=("disque ${d} %")
m=$(free | awk '/Mem:/{printf "%d", $7*100/$2}'); (( m <= 10 )) && ko+=("RAM dispo ${m} %")
exp=$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json,datetime as D
d=json.load(sys.stdin)["Self"].get("KeyExpiry")
print("" if not d or d.startswith("0001") else (D.datetime.fromisoformat(d.replace("Z","+00:00"))-D.datetime.now(D.timezone.utc)).days)' 2>/dev/null)
[[ -n $exp ]] && (( exp < 14 )) && ko+=("clé Tailscale expire dans ${exp} j")

etat=$([[ ${#ko[@]} -eq 0 ]] && echo OK || echo KO)
detail=$(IFS='; '; echo "${ko[*]:-tout est vert}")
avant=$(cat "$ETAT" 2>/dev/null || echo INCONNU)
echo "$etat" > "$ETAT"

notif(){ [[ -n $NTFY_URL ]] && curl -fsS -m 10 -H "Title: PARADOXX VPS $1" -H "Priority: $2" -H "Tags: $3" -d "$4" "$NTFY_URL" >/dev/null; }
if [[ $etat != "$avant" ]]; then
  [[ $etat == KO ]] && notif "en panne" high warning "$detail" || notif "rétabli" default white_check_mark "$detail"
fi
# Battement : chaque heure (minute < 5) ou à chaque changement d'état
if [[ $etat != "$avant" ]] || (( 10#$(date +%M) < 5 )); then
  curl -fsS -m 10 -H 'Content-Type: application/json' \
    -d "{\"etat\":\"$etat\",\"detail\":\"$detail\",\"heure\":\"$(TZ=Europe/Paris date '+%d/%m %H:%M')\"}" \
    "$N8N_WEBHOOK" >/dev/null || logger -t paradoxx-veille "n8n injoignable"
fi
logger -t paradoxx-veille "$etat - $detail"
