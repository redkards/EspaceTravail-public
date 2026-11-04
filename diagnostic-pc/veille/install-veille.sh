#!/usr/bin/env bash
# À lancer PAR JÉRÉMY sur le VPS :  sudo bash ~/veille/install-veille.sh
# Demande le sujet ntfy (saisie masquée) ; ne l'affiche jamais.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Lancer avec sudo"; exit 1; }
cd "$(dirname "$0")"
install -m 755 paradoxx-veille.sh /usr/local/bin/paradoxx-veille.sh
install -m 644 paradoxx-veille.service paradoxx-veille.timer /etc/systemd/system/
install -d -m 700 /etc/paradoxx
if [[ ! -f /etc/paradoxx/veille.conf ]]; then
  read -rsp "Sujet ntfy (celui abonné sur le téléphone, Entrée pour plus tard) : " t; echo
  printf 'NTFY_URL=%s\nN8N_WEBHOOK=http://127.0.0.1:5678/webhook/paradoxx-battement\n' \
    "${t:+https://ntfy.sh/$t}" > /etc/paradoxx/veille.conf
  chmod 600 /etc/paradoxx/veille.conf
fi
systemctl daemon-reload && systemctl enable --now paradoxx-veille.timer
systemctl start paradoxx-veille.service
journalctl -t paradoxx-veille -n 3 --no-pager
systemctl list-timers paradoxx-veille.timer --no-pager
echo "[OK] Veille installée. Retour arrière : systemctl disable --now paradoxx-veille.timer"
