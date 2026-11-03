#!/usr/bin/env bash
# =============================================================================
#  backup.sh — sauvegarde du Mini NEXUS MOTHERSHIP dans ./backups/<date>/
#
#  Contenu de chaque sauvegarde :
#    - nexus-core.tar.gz     : livrables + base SQLite nexus.db (mode MVP)
#    Mode complet uniquement :
#    - nexus.sql.gz          : base PostgreSQL « nexus » (missions, décisions, ledger)
#    - n8n.sql.gz            : base PostgreSQL « n8n »
#    - n8n-workflows/        : export JSON des workflows n8n
#    - env.sauvegarde        : copie du .env (SECRETS : à garder en lieu sûr)
#
#  Usage :  bash backup.sh            (garde les 14 dernières sauvegardes)
#           bash backup.sh --garder 30
#  Planification quotidienne (03:30) :  crontab -e  puis ajouter
#     30 3 * * * /srv/p1/nexus-mothership/backup.sh >> /srv/p1/nexus-mothership/backups/backup.log 2>&1
# =============================================================================
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GARDER=14

info()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --garder) [ $# -ge 2 ] || erreur "--garder attend un nombre"; GARDER="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) erreur "Option inconnue : $1 (voir --help)" ;;
  esac
done
if ! [[ "$GARDER" =~ ^[0-9]+$ ]] || [ "$GARDER" -lt 1 ]; then erreur "--garder doit être un nombre >= 1"; fi

cd "$KIT_DIR"
[ -f .env ] || erreur ".env introuvable : le Mothership n'est pas installé ici."
PGUSER="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)"
PGUSER="${PGUSER:-nexus}"

DEST="$KIT_DIR/backups/$(date +%Y-%m-%d_%H%M%S)"
umask 077
mkdir -p "$DEST"
info "Sauvegarde vers $DEST"

info "1/3 — nexus-core (livrables et base SQLite du mode MVP)"
if [ -d data/nexus-core ]; then
  # SQLite : copie cohérente via l'API de sauvegarde Python si nexus-core tourne
  if docker compose ps --status running -q nexus-core 2>/dev/null | grep -q . \
     && [ -f data/nexus-core/nexus.db ]; then
    docker compose exec -T nexus-core python -c "import sqlite3; s=sqlite3.connect('/data/nexus.db'); d=sqlite3.connect('/data/nexus-sauvegarde.db'); s.backup(d); d.close(); s.close()" \
      || avert "Copie à chaud de SQLite impossible : copie brute du fichier."
  fi
  tar -C data -czf "$DEST/nexus-core.tar.gz" nexus-core
  rm -f data/nexus-core/nexus-sauvegarde.db
  ok "nexus-core.tar.gz ($(du -h "$DEST/nexus-core.tar.gz" | cut -f1))"
fi

info "2/3 — Bases PostgreSQL et workflows n8n (mode complet)"
if docker compose ps --status running -q postgres 2>/dev/null | grep -q .; then
  for base in nexus n8n; do
    docker compose exec -T postgres pg_dump -U "$PGUSER" -d "$base" --no-owner | gzip -9 > "$DEST/$base.sql.gz"
    ok "$base.sql.gz ($(du -h "$DEST/$base.sql.gz" | cut -f1))"
  done
else
  info "PostgreSQL non démarré (mode MVP) : rien à faire"
fi
if docker compose ps --status running -q n8n 2>/dev/null | grep -q .; then
  mkdir -p "$DEST/n8n-workflows"
  if docker compose exec -T n8n sh -c 'rm -rf /tmp/export && mkdir -p /tmp/export && n8n export:workflow --all --separate --output=/tmp/export >/dev/null && tar -C /tmp/export -cf - .' \
       | tar -C "$DEST/n8n-workflows" -xf -; then
    ok "Workflows n8n exportés ($(find "$DEST/n8n-workflows" -name '*.json' | wc -l) fichiers)"
  else
    avert "Export JSON des workflows impossible (la base n8n.sql.gz suffit pour restaurer)."
  fi
fi

info "3/3 — Configuration"
cp .env "$DEST/env.sauvegarde"
ok "Copie du .env (contient des secrets)"

info "Rotation : on garde les $GARDER dernières sauvegardes"
find "$KIT_DIR/backups" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort -r | tail -n +"$((GARDER + 1))" | while read -r ancien; do
  rm -rf "$ancien" && info "Supprimée : $(basename "$ancien")"
done

ok "Sauvegarde terminée : $DEST ($(du -sh "$DEST" | cut -f1))"
echo "   Pour copier sur votre PC : téléchargez ce dossier via le gestionnaire de fichiers"
echo "   ou « scp -r root@VOTRE_VPS:$DEST . » depuis un ordinateur."
