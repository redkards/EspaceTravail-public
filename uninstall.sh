#!/usr/bin/env bash
# =============================================================================
#  uninstall.sh — arrête et supprime les conteneurs du Mini NEXUS MOTHERSHIP
#
#  Usage :
#     bash uninstall.sh            # arrête et supprime les conteneurs
#                                  # (les DONNÉES dans ./data et le .env sont CONSERVÉS)
#     bash uninstall.sh --purge    # supprime AUSSI ./data, .env, install.log et,
#                                  # après une 2e confirmation, ./backups (sauvegardes)
#     bash uninstall.sh --purge --yes   # sans confirmation (dangereux)
#
#  La partition P1 (/srv/p1) et les autres partitions ne sont jamais touchées.
#  Conseil : lancez « bash backup.sh » avant un --purge.
# =============================================================================
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURGE=0
OUI=0

info()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --yes|-y) OUI=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) erreur "Option inconnue : $1 (voir --help)" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || erreur "Lancez ce script en root."
cd "$KIT_DIR"
command -v docker >/dev/null 2>&1 || erreur "Docker n'est pas installé : rien à désinstaller."

echo
info "Étape 1/2 — Arrêt et suppression des conteneurs (projet p1-nexus)"
if [ -f .env ]; then
  # Tous les profils (MVP, local, complet) pour ne rien oublier
  docker compose --profile local --profile complet down --remove-orphans
else
  avert ".env absent : arrêt direct des conteneurs du projet p1-nexus"
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=p1-nexus")
  # shellcheck disable=SC2086
  [ -n "$ids" ] && docker rm -f $ids >/dev/null
  docker network rm p1-nexus-net >/dev/null 2>&1 || true
fi
ok "Conteneurs arrêtés et supprimés"

info "Étape 2/2 — Données"
if [ "$PURGE" -eq 1 ]; then
  avert "--purge : TOUTES les données seront effacées : $KIT_DIR/data"
  avert "(bases PostgreSQL, workflows n8n, modèles Ollama, certificats, livrables),"
  avert "ainsi que .env (secrets) et install.log (journal d'installation)."
  if [ "$OUI" -eq 0 ]; then
    read -r -p "Tapez SUPPRIMER pour confirmer : " rep || rep=""
    [ "$rep" = "SUPPRIMER" ] || erreur "Annulé : aucune donnée supprimée."
  fi
  rm -rf --one-file-system "${KIT_DIR:?}/data"
  rm -f "$KIT_DIR/.env" "$KIT_DIR/install.log"
  rm -f /etc/cron.d/nexus-mothership-sauvegarde
  ok "Données, .env, install.log et sauvegarde planifiée supprimés"
  if [ -d "$KIT_DIR/backups" ]; then
    avert "Il reste les SAUVEGARDES : $KIT_DIR/backups ($(du -sh "$KIT_DIR/backups" | cut -f1))."
    avert "Sans elles, plus aucun retour en arrière n'est possible."
    suppr=1
    if [ "$OUI" -eq 0 ]; then
      read -r -p "Tapez SUPPRIMER-SAUVEGARDES pour les effacer aussi (Entrée = garder) : " rep || rep=""
      [ "$rep" = "SUPPRIMER-SAUVEGARDES" ] || suppr=0
    fi
    if [ "$suppr" -eq 1 ]; then
      rm -rf --one-file-system "${KIT_DIR:?}/backups"
      ok "Sauvegardes supprimées"
    else
      ok "Sauvegardes conservées dans $KIT_DIR/backups"
    fi
  fi
else
  ok "Données conservées dans $KIT_DIR/data et secrets dans $KIT_DIR/.env"
  info "Pour tout réinstaller : bash install.sh"
fi
