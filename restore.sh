#!/usr/bin/env bash
# =============================================================================
#  restore.sh — restaure une sauvegarde datée du Mini NEXUS MOTHERSHIP
#
#  Usage :
#     bash restore.sh                         # liste les sauvegardes disponibles
#     bash restore.sh 2026-11-03_033000       # restaure celle-ci (demande RESTAURER)
#     bash restore.sh 2026-11-03_033000 --avec-env   # remplace AUSSI .env (secrets)
#     bash restore.sh ... --yes               # sans confirmation
#
#  Déroulé : vérification des archives (avant toute coupure), arrêt de nexus-core
#  et nexus-bridge (+ n8n en mode complet), mise de côté des données actuelles dans
#  data/.avant-restauration-<date>/ (rien n'est effacé), restauration, droits
#  UID 10001, bases PostgreSQL (mode complet), redémarrage, contrôle de /api/sante.
#  Sans --avec-env, le .env actuel est conservé (sauf s'il n'existe plus).
# =============================================================================
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Permet aux tests de remplacer docker par un simulateur
DOCKER="${NEXUS_DOCKER:-docker}"
ATTENTE_MAX="${NEXUS_ATTENTE_MAX:-36}"   # contrôles de santé (x 5 s)
UID_NEXUS=10001
OUI=0
AVEC_ENV=0
NOM=""

info()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) OUI=1; shift ;;
    --avec-env) AVEC_ENV=1; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) erreur "Option inconnue : $1 (voir --help)" ;;
    *) NOM="$1"; shift ;;
  esac
done

[ "$(id -u)" -eq 0 ] || erreur "Lancez ce script en root."
cd "$KIT_DIR"
BACKUPS="$KIT_DIR/backups"

# --- Sans argument : liste ----------------------------------------------------------
if [ -z "$NOM" ]; then
  echo "Sauvegardes disponibles (la plus récente en haut) :"
  found=0
  while read -r d; do
    [ -n "$d" ] || continue
    found=1
    printf '   %s   (%s)\n' "$(basename "$d")" "$(du -sh "$d" | cut -f1)"
  done < <(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | sort -r)
  [ "$found" -eq 1 ] || echo "   (aucune : lancez d'abord « bash backup.sh »)"
  echo
  echo "Pour restaurer : bash restore.sh <nom>   ex. bash restore.sh $(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | sort -r | head -n 1 | xargs -r basename)"
  exit 0
fi

SRC="$BACKUPS/$(basename "$NOM")"
[ -d "$SRC" ] || erreur "Sauvegarde introuvable : $SRC (sans argument : liste des sauvegardes)."

lire_env() {
  [ -f .env ] || return 0
  { grep -E "^${1}=" .env || true; } | tail -n 1 | cut -d= -f2- | sed "s/^'//; s/'\$//"
}

# --- 1. Vérifications (le Mothership tourne encore) -----------------------------------
info "Étape 1/6 — Vérification de la sauvegarde $(basename "$SRC")"
STAGING="$KIT_DIR/data/.restauration-en-cours"
rm -rf "$STAGING"
mkdir -p "$KIT_DIR/data" "$STAGING"
chmod 700 "$KIT_DIR/data"
trap 'rm -rf "$STAGING"' EXIT
services_fichiers=()
for service in nexus-core nexus-bridge veille; do
  archive="$SRC/$service.tar.gz"
  if [ ! -f "$archive" ]; then
    [ "$service" = veille ] || avert "$service.tar.gz absent de la sauvegarde : $service ne sera pas modifié."
    continue
  fi
  tar -tzf "$archive" >/dev/null 2>&1 || erreur "Archive abîmée : $archive (rien n'a été modifié)."
  tar -C "$STAGING" -xzf "$archive"
  services_fichiers+=("$service")
done
# Anciennes sauvegardes : la copie cohérente s'appelait <base>-sauvegarde.db
for paire in nexus-core:nexus.db nexus-bridge:bridge.db veille:veille.db; do
  service="${paire%%:*}"; base="${paire#*:}"
  d="$STAGING/$service"
  [ -d "$d" ] || continue
  if [ -f "$d/${base%.db}-sauvegarde.db" ]; then
    mv -f "$d/${base%.db}-sauvegarde.db" "$d/$base"
  fi
  rm -f "$d/$base-wal" "$d/$base-shm" "$d/$base-journal"
  if [ -f "$d/$base" ] && command -v python3 >/dev/null 2>&1; then
    etat="$(python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0])" "$d/$base" 2>&1 || true)"
    [ "$etat" = "ok" ] || erreur "Base $base de la sauvegarde invalide ($etat) : rien n'a été modifié."
    rm -f "$d/$base-wal" "$d/$base-shm"
    ok "$service : base $base vérifiée (integrity_check = ok)"
  fi
done

# .env de la sauvegarde : restauré si --avec-env, ou si .env a disparu
ENV_RESTAURE=""
if [ "$AVEC_ENV" -eq 1 ] || [ ! -f .env ]; then
  ENV_RESTAURE="$STAGING/env"
  if [ -f "$SRC/env.sauvegarde.gpg" ]; then
    command -v gpg >/dev/null 2>&1 || erreur "gpg est nécessaire pour déchiffrer env.sauvegarde.gpg (apt-get install -y gnupg)."
    phrase="$(lire_env BACKUP_PASSPHRASE)"
    if [ -n "$phrase" ]; then
      gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 -d \
          -o "$ENV_RESTAURE" "$SRC/env.sauvegarde.gpg" 3< <(printf '%s' "$phrase") \
        || erreur "Déchiffrement impossible avec BACKUP_PASSPHRASE du .env actuel."
    else
      info "Saisissez la phrase BACKUP_PASSPHRASE notée lors de l'installation (masquée) :"
      gpg --quiet --pinentry-mode loopback -d -o "$ENV_RESTAURE" "$SRC/env.sauvegarde.gpg" \
        || erreur "Déchiffrement impossible : phrase incorrecte."
    fi
    unset phrase
  elif [ -f "$SRC/env.sauvegarde.age" ]; then
    [ -n "${NEXUS_AGE_IDENTITY:-}" ] || erreur "env.sauvegarde.age : indiquez votre clé privée age, ex. NEXUS_AGE_IDENTITY=/root/cle-age.txt bash restore.sh ..."
    age -d -i "$NEXUS_AGE_IDENTITY" -o "$ENV_RESTAURE" "$SRC/env.sauvegarde.age" || erreur "Déchiffrement age impossible."
  elif [ -f "$SRC/env.sauvegarde" ]; then
    cp "$SRC/env.sauvegarde" "$ENV_RESTAURE"
  else
    [ -f .env ] || erreur "Ni .env ni copie du .env dans la sauvegarde : relancez d'abord bash install.sh."
    avert "Pas de copie du .env dans la sauvegarde : .env actuel conservé."
    ENV_RESTAURE=""
  fi
  [ -z "$ENV_RESTAURE" ] || chmod 600 "$ENV_RESTAURE"
fi

PG_A_RESTAURER=()
for base in nexus n8n; do
  [ -f "$SRC/$base.sql.gz" ] || continue
  gzip -t "$SRC/$base.sql.gz" || erreur "Dump abîmé : $SRC/$base.sql.gz (rien n'a été modifié)."
  PG_A_RESTAURER+=("$base")
done
[ "${#services_fichiers[@]}" -gt 0 ] || [ "${#PG_A_RESTAURER[@]}" -gt 0 ] || [ -n "$ENV_RESTAURE" ] \
  || erreur "Cette sauvegarde ne contient rien à restaurer."
ok "Sauvegarde lisible : ${services_fichiers[*]:-} ${PG_A_RESTAURER[*]:+(PostgreSQL : ${PG_A_RESTAURER[*]})} ${ENV_RESTAURE:+(+ .env)}"

# --- 2. Confirmation ----------------------------------------------------------------------
STAMP="$(date +%Y-%m-%d_%H%M%S)"
COTE="$KIT_DIR/data/.avant-restauration-$STAMP"
echo
avert "Les données actuelles de : ${services_fichiers[*]:-aucun service} ${PG_A_RESTAURER[*]:++ PostgreSQL (${PG_A_RESTAURER[*]})}"
avert "seront remplacées par celles du $(basename "$SRC"). Les services seront coupés 1 à 2 minutes."
echo "    Les fichiers actuels sont mis de côté (pas effacés) dans : $COTE"
[ "${#PG_A_RESTAURER[@]}" -eq 0 ] || echo "    Attention : les bases PostgreSQL actuelles, elles, sont REMPLACÉES (pas de copie de côté)."
if [ "$OUI" -eq 0 ]; then
  [ -t 0 ] || erreur "Pas de terminal : relancez avec --yes pour confirmer."
  read -r -p "Tapez RESTAURER pour confirmer : " rep || rep=""
  [ "$rep" = "RESTAURER" ] || erreur "Annulé : rien n'a été modifié."
fi

# --- 3. Arrêt des services ------------------------------------------------------------------
info "Étape 2/6 — Arrêt des services qui écrivent les données"
a_arreter=(nexus-bridge nexus-core)
profils="$(lire_env COMPOSE_PROFILES)"
[[ ",$profils," == *",complet,"* ]] && a_arreter+=(n8n)
"$DOCKER" compose stop "${a_arreter[@]}" || erreur "Arrêt impossible (docker compose stop ${a_arreter[*]})."
ok "Arrêtés : ${a_arreter[*]}"

# --- 4. Restauration des fichiers -------------------------------------------------------------
info "Étape 3/6 — Restauration des fichiers"
mkdir -p "$COTE"; chmod 700 "$COTE"
for service in "${services_fichiers[@]}"; do
  if [ -d "data/$service" ]; then mv "data/$service" "$COTE/$service"; fi
  mv "$STAGING/$service" "data/$service"
  if [ "$service" = veille ]; then
    # Écrite par le collecteur (root, sur l'hôte), lue par nexus-core (UID 10001)
    chmod 755 "data/$service"; chmod 644 "data/$service"/*.db 2>/dev/null || true
    ok "data/$service restauré (lisible par nexus-core)"
    continue
  fi
  chown -R "$UID_NEXUS:$UID_NEXUS" "data/$service"
  chmod 750 "data/$service"
  ok "data/$service restauré (propriétaire UID $UID_NEXUS)"
done
if [ -n "$ENV_RESTAURE" ]; then
  [ -f .env ] && cp -p .env "$COTE/env.avant-restauration"
  cat "$ENV_RESTAURE" > .env.restauration && chmod 600 .env.restauration && mv -f .env.restauration .env
  ok ".env restauré (l'ancien est dans $COTE)"
fi

# --- 5. PostgreSQL (mode complet) --------------------------------------------------------------
info "Étape 4/6 — Bases PostgreSQL"
if [ "${#PG_A_RESTAURER[@]}" -gt 0 ]; then
  PGUSER="$(lire_env POSTGRES_USER)"; PGUSER="${PGUSER:-nexus}"
  "$DOCKER" compose up -d postgres
  for _ in $(seq 1 30); do
    "$DOCKER" compose exec -T postgres pg_isready -U "$PGUSER" >/dev/null 2>&1 && break
    sleep 2
  done
  for base in "${PG_A_RESTAURER[@]}"; do
    "$DOCKER" compose exec -T postgres psql -v ON_ERROR_STOP=1 -q -U "$PGUSER" -d postgres \
      -c "DROP DATABASE IF EXISTS \"$base\" WITH (FORCE);" -c "CREATE DATABASE \"$base\" OWNER \"$PGUSER\";"
    gunzip -c "$SRC/$base.sql.gz" | "$DOCKER" compose exec -T postgres psql -v ON_ERROR_STOP=1 -q -U "$PGUSER" -d "$base" >/dev/null
    ok "Base PostgreSQL « $base » restaurée"
  done
else
  ok "Aucune base PostgreSQL dans cette sauvegarde (mode MVP)"
fi

# --- 6. Redémarrage et contrôle ----------------------------------------------------------------
info "Étape 5/6 — Redémarrage"
"$DOCKER" compose up -d
info "Étape 6/6 — Contrôle de l'API (/api/sante)"
sante_ok=0
for _ in $(seq 1 "$ATTENTE_MAX"); do
  if "$DOCKER" compose exec -T nexus-core python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/sante', timeout=5)" >/dev/null 2>&1; then
    sante_ok=1; break
  fi
  sleep 5
done
echo
if [ "$sante_ok" -eq 1 ]; then
  ok "Restauration terminée : /api/sante répond. Vérifiez le cockpit."
  echo "    Données d'avant restauration (à supprimer plus tard si tout va bien) : $COTE"
else
  avert "nexus-core ne répond pas encore. Voir : docker compose logs --tail=50 nexus-core"
  echo "    Pour revenir en arrière : docker compose stop nexus-core nexus-bridge, puis"
  echo "    remettez les dossiers de $COTE dans data/ et lancez docker compose up -d."
  exit 1
fi
