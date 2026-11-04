#!/usr/bin/env bash
# PARADOXX - Correctifs ADMIN JÉRÉMY (S10 + S11). À lancer PAR JÉRÉMY : sudo bash ~/correctifs-admin.sh
# Sauvegarde avant modification, test sshd -t avant redémarrage, retour arrière automatique en cas d'erreur.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Lancer avec sudo"; exit 1; }
b=/root/sauvegarde-correctifs-$(date +%Y%m%d-%H%M%S); mkdir -p "$b"
cp -a /etc/ssh/sshd_config.d "$b/"; [[ -f /etc/fail2ban/jail.local ]] && cp -a /etc/fail2ban/jail.local "$b/"
echo "Sauvegarde : $b"

# S10 - mot de passe SSH interdit. sshd garde la PREMIÈRE valeur lue : 50-cloud-init.conf passait
# avant 99-paradoxx.conf. On renomme notre fichier en 00- pour qu'il soit lu en premier, et on neutralise cloud-init.
d=/etc/ssh/sshd_config.d
[[ -f $d/99-paradoxx.conf ]] && mv "$d/99-paradoxx.conf" "$d/00-paradoxx.conf"
[[ -f $d/50-cloud-init.conf ]] && sed -i 's/^\s*PasswordAuthentication\s\+yes/PasswordAuthentication no/I' "$d/50-cloud-init.conf"
if sshd -t; then systemctl reload ssh; echo "[OK] sshd rechargé"
else cp -a "$b/sshd_config.d/." /etc/ssh/sshd_config.d/; echo "[ECHEC] config sshd invalide : restaurée"; exit 1; fi
sshd -T | grep -iE '^(passwordauthentication|permitrootlogin) '

# S11 - ne jamais bannir le réseau Tailscale ni la console hPanel
j=/etc/fail2ban/jail.local
if ! grep -q '100.64.0.0/10' "$j" 2>/dev/null; then
  grep -q '^\[DEFAULT\]' "$j" 2>/dev/null || printf '[DEFAULT]\n' >> "$j"
  sed -i '/^\[DEFAULT\]/a ignoreip = 127.0.0.1/8 ::1 100.64.0.0/10 169.254.0.0/16' "$j"
fi
systemctl restart fail2ban && fail2ban-client get sshd ignoreip
echo "Terminé. Garder ce terminal ouvert et tester 'ssh paradoxx' depuis le PC avant de fermer."
