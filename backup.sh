#!/usr/bin/env bash
# =============================================================================
#  backup.sh — sauvegarde du Mini NEXUS MOTHERSHIP dans ./backups/<date>/
#
#  Contenu de chaque sauvegarde :
#    - nexus-core.tar.gz     : livrables + copie COHÉRENTE de la base nexus.db
#    - nexus-bridge.tar.gz   : mémoire commune des IA (copie cohérente de bridge.db)
#    Mode complet uniquement :
#    - nexus.sql.gz / n8n.sql.gz : bases PostgreSQL « nexus » et « n8n »
#    - n8n-workflows/        : export JSON des workflows n8n
#    - env.sauvegarde.gpg (ou .age) : copie CHIFFRÉE du .env (secrets)
#      Phrase de déchiffrement : BACKUP_PASSPHRASE dans .env (notez-la hors du VPS).
#      Sans gpg ni age : env.sauvegarde en clair, lisible par root seulement.
#
#  Usage :  bash backup.sh                  (garde les 7 dernières sauvegardes)
#           bash backup.sh --garder 14
#           bash backup.sh --hors-serveur   (copie aussi vers Google Drive avec rclone,
#                                            remote NEXUS_RCLONE_REMOTE, défaut « gdrive »)
#  Restaurer : bash restore.sh   (voir README, « Restaurer une sauvegarde »)
#  Planification quotidienne : proposée par install.sh (/etc/cron.d).
# =============================================================================
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GARDER=7
HORS_SERVEUR=0
# Permet aux tests de remplacer docker par un simulateur
DOCKER="${NEXUS_DOCKER:-docker}"

info()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --garder) [ $# -ge 2 ] || erreur "--garder attend un nombre"; GARDER="$2"; shift 2 ;;
    --hors-serveur) HORS_SERVEUR=1; shift ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) erreur "Option inconnue : $1 (voir --help)" ;;
  esac
done
if ! [[ "$GARDER" =~ ^[0-9]+$ ]] || [ "$GARDER" -lt 1 ]; then erreur "--garder doit être un nombre >= 1"; fi

cd "$KIT_DIR"
[ -f .env ] || erreur ".env introuvable : le Mothership n'est pas installé ici."
lire_env() {
  { grep -E "^${1}=" .env || true; } | tail -n 1 | cut -d= -f2- | sed "s/^'//; s/'\$//"
}
PGUSER="$(lire_env POSTGRES_USER)"; PGUSER="${PGUSER:-nexus}"

umask 077
mkdir -p "$KIT_DIR/backups"
chmod 700 "$KIT_DIR/backups"
DEST="$KIT_DIR/backups/$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$DEST"
info "Sauvegarde vers $DEST"

service_actif() { "$DOCKER" compose ps --status running -q "$1" 2>/dev/null | grep -q .; }

# Copie cohérente d'une base SQLite (API de sauvegarde : inclut le contenu du -wal).
# $1 service, $2 dossier data/, $3 nom de la base, $4 nom de la copie
copie_sqlite() {
  local service="$1" dossier="$2" base="$3" copie="$4"
  rm -f "$dossier/$copie"
  [ -f "$dossier/$base" ] || return 1
  local py="import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"
  if service_actif "$service"; then
    "$DOCKER" compose exec -T "$service" python -c "$py" "/data/$base" "/data/$copie" && return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "$py" "$dossier/$base" "$dossier/$copie" && return 0
  fi
  return 1
}

# Archive un dossier de données : la copie cohérente remplace la base (renommée
# avec son nom d'origine) ; les fichiers -wal / -shm ne sont jamais archivés.
# $1 service, $2 nom de la base (ex. nexus.db)
archiver() {
  local service="$1" base="$2" copie="${2%.db}-sauvegarde.db" exclure=()
  local dossier="data/$service"
  [ -d "$dossier" ] || { info "$dossier absent : ignoré"; return 0; }
  exclure=(--exclude='*.db-wal' --exclude='*.db-shm' --exclude='*-journal')
  if copie_sqlite "$service" "$dossier" "$base" "$copie"; then
    exclure+=(--exclude="$service/$base")
  elif [ -f "$dossier/$base" ]; then
    avert "Copie cohérente de $base impossible : copie brute (arrêtez $service pour plus de sûreté)."
  fi
  tar -C data -czf "$DEST/$service.tar.gz" "${exclure[@]}" \
      --transform "s,^$service/$copie\$,$service/$base," "$service"
  rm -f "$dossier/$copie"
  ok "$service.tar.gz ($(du -h "$DEST/$service.tar.gz" | cut -f1))"
}

info "1/4 — nexus-core (livrables et base SQLite) et nexus-bridge (mémoire commune)"
archiver nexus-core nexus.db
archiver nexus-bridge bridge.db

info "2/4 — Bases PostgreSQL et workflows n8n (mode complet)"
if service_actif postgres; then
  for base in nexus n8n; do
    "$DOCKER" compose exec -T postgres pg_dump -U "$PGUSER" -d "$base" --no-owner | gzip -9 > "$DEST/$base.sql.gz"
    ok "$base.sql.gz ($(du -h "$DEST/$base.sql.gz" | cut -f1))"
  done
else
  info "PostgreSQL non démarré (mode MVP) : rien à faire"
fi
if service_actif n8n; then
  mkdir -p "$DEST/n8n-workflows"
  if "$DOCKER" compose exec -T n8n sh -c 'rm -rf /tmp/export && mkdir -p /tmp/export && n8n export:workflow --all --separate --output=/tmp/export >/dev/null && tar -C /tmp/export -cf - .' \
       | tar -C "$DEST/n8n-workflows" -xf -; then
    ok "Workflows n8n exportés ($(find "$DEST/n8n-workflows" -name '*.json' | wc -l) fichiers)"
  else
    avert "Export JSON des workflows impossible (la base n8n.sql.gz suffit pour restaurer)."
  fi
fi

info "3/4 — Configuration (.env, chiffré)"
RECIPIENT="$(lire_env BACKUP_AGE_RECIPIENT)"
PHRASE="$(lire_env BACKUP_PASSPHRASE)"
if [ -n "$RECIPIENT" ] && command -v age >/dev/null 2>&1; then
  age -r "$RECIPIENT" -o "$DEST/env.sauvegarde.age" .env
  ok "env.sauvegarde.age (chiffré avec votre clé publique age)"
elif [ -n "$PHRASE" ] && command -v gpg >/dev/null 2>&1; then
  # Phrase transmise par un descripteur de fichier : jamais dans la liste des processus
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 \
      --symmetric --cipher-algo AES256 -o "$DEST/env.sauvegarde.gpg" .env 3< <(printf '%s' "$PHRASE")
  ok "env.sauvegarde.gpg (chiffré ; phrase : BACKUP_PASSPHRASE, à noter hors du VPS)"
else
  cp .env "$DEST/env.sauvegarde"
  chmod 600 "$DEST/env.sauvegarde"
  avert "env.sauvegarde NON chiffré (gpg/age absent ou BACKUP_PASSPHRASE vide) : lisible par root seulement."
  avert "Installez gpg (apt-get install -y gnupg) puis relancez install.sh pour chiffrer."
fi
unset PHRASE

info "4/4 — Rotation : on garde les $GARDER dernières sauvegardes"
find "$KIT_DIR/backups" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort -r | tail -n +"$((GARDER + 1))" | while read -r ancien; do
  rm -rf "$ancien" && info "Supprimée : $(basename "$ancien")"
done

if [ "$HORS_SERVEUR" -eq 1 ]; then
  REMOTE="$(lire_env NEXUS_RCLONE_REMOTE)"; REMOTE="${REMOTE:-gdrive}"
  if ! command -v rclone >/dev/null 2>&1; then
    avert "rclone n'est pas installé : copie hors serveur impossible (voir README, « Sauvegardes »)."
  elif ! rclone listremotes 2>/dev/null | grep -qx "${REMOTE}:"; then
    avert "Le remote rclone « $REMOTE » n'existe pas : lancez « rclone config » (voir README)."
  else
    info "Copie hors serveur vers $REMOTE:nexus-sauvegardes/$(basename "$DEST")"
    if rclone copy "$DEST" "$REMOTE:nexus-sauvegardes/$(basename "$DEST")"; then
      ok "Copie hors serveur terminée"
      # Même rotation sur le stockage distant
      rclone lsf --dirs-only "$REMOTE:nexus-sauvegardes" 2>/dev/null | sed 's,/$,,' | grep '^20' \
        | sort -r | tail -n +"$((GARDER + 1))" | while read -r ancien; do
          rclone purge "$REMOTE:nexus-sauvegardes/$ancien" && info "Supprimée à distance : $ancien"
        done
    else
      avert "La copie hors serveur a échoué (la sauvegarde locale est intacte)."
    fi
  fi
fi

ok "Sauvegarde terminée : $DEST ($(du -sh "$DEST" | cut -f1))"
[ "$HORS_SERVEUR" -eq 1 ] || echo "   Copie hors du VPS : bash backup.sh --hors-serveur (Google Drive, voir README)."
