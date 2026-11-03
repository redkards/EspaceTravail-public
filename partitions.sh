#!/usr/bin/env bash
# =============================================================================
#  partitions.sh — découpe le VPS en 4 partitions isolées (P1 à P4)
#
#  Principe : on NE touche PAS au disque système. On crée 4 fichiers image ext4
#  de taille fixe (/srv/images/p1.img … p4.img), montés en « loop » sur
#  /srv/p1 … /srv/p4, et déclarés dans /etc/fstab (remontés au redémarrage).
#
#  Usage :
#    sudo bash partitions.sh                 # 4 × 20 Go (par défaut)
#    sudo bash partitions.sh --size 20G      # taille de chaque partition
#    sudo bash partitions.sh --dry-run       # affiche seulement ce qui serait fait
#
#  Idempotent : une image déjà créée n'est jamais reformatée ; une ligne fstab
#  déjà présente n'est pas dupliquée ; un montage existant est conservé.
#  Variables de test (facultatives) : NEXUS_PART_BASE (défaut /srv),
#  NEXUS_FSTAB (défaut /etc/fstab).
# =============================================================================
set -euo pipefail

TAILLE="20G"
SIMULATION=0
NB=4
BASE="${NEXUS_PART_BASE:-/srv}"
FSTAB="${NEXUS_FSTAB:-/etc/fstab}"
IMAGES="$BASE/images"

# --- Affichage ---------------------------------------------------------------
info()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

# Exécute une commande, ou l'affiche seulement en mode --dry-run
faire() {
  if [ "$SIMULATION" -eq 1 ]; then
    printf '   (simulation) %s\n' "$*"
  else
    "$@"
  fi
}

aide() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

# --- Arguments ---------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --size)    [ $# -ge 2 ] || erreur "--size attend une valeur (ex. 20G)"; TAILLE="$2"; shift 2 ;;
    --size=*)  TAILLE="${1#*=}"; shift ;;
    --dry-run) SIMULATION=1; shift ;;
    -h|--help) aide ;;
    *) erreur "Option inconnue : $1 (voir --help)" ;;
  esac
done

# Taille : un entier suivi de G (Go) ou M (Mo)
case "$TAILLE" in
  *[0-9]G) TAILLE_GO="${TAILLE%G}" ;;
  *[0-9]M) TAILLE_GO=$(( (${TAILLE%M} + 1023) / 1024 )) ;;
  *) erreur "Taille invalide « $TAILLE » : utilisez par exemple 20G ou 1024M." ;;
esac
if ! [[ "$TAILLE_GO" =~ ^[0-9]+$ ]] || [ "$TAILLE_GO" -lt 1 ]; then erreur "Taille invalide « $TAILLE »."; fi

echo
info "Partitions NEXUS : $NB × $TAILLE dans $IMAGES, montées sur $BASE/p1 … $BASE/p$NB"
[ "$SIMULATION" -eq 1 ] && avert "Mode SIMULATION (--dry-run) : rien ne sera modifié."

# --- 1. Vérifications ----------------------------------------------------------
info "Étape 1/4 — Vérifications"
if [ "$SIMULATION" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  erreur "Ce script doit être lancé en root (le terminal hPanel est déjà root)."
fi
for cmd in fallocate mkfs.ext4 mount mountpoint df awk; do
  command -v "$cmd" >/dev/null 2>&1 || erreur "Commande manquante : $cmd"
done

# Espace déjà réservé par des images existantes (elles ne seront pas recréées)
manquantes=0
for i in $(seq 1 "$NB"); do
  [ -f "$IMAGES/p$i.img" ] || manquantes=$((manquantes + 1))
done

# Règle : espace libre sur / >= (4 × taille) + 10 Go (marge pour le système et Docker).
# Si certaines images existent déjà, seules les manquantes consomment de l'espace.
requis_go=$(( manquantes * TAILLE_GO + 10 ))
libre_go=$(df -BG --output=avail / | tail -n 1 | tr -dc '0-9')
info "Espace libre sur / : ${libre_go} Go — requis : ${requis_go} Go (${manquantes} image(s) à créer × ${TAILLE_GO} Go + 10 Go de marge)"
if [ "$manquantes" -gt 0 ] && [ "$libre_go" -lt "$requis_go" ]; then
  erreur "Espace insuffisant : ${libre_go} Go libres < ${requis_go} Go requis. Libérez de l'espace ou réduisez --size."
fi
ok "Vérifications terminées"

# --- 2. Création des images ------------------------------------------------------
info "Étape 2/4 — Création des fichiers image ext4"
faire mkdir -p "$IMAGES"
faire chmod 700 "$IMAGES"
for i in $(seq 1 "$NB"); do
  img="$IMAGES/p$i.img"
  if [ -f "$img" ]; then
    ok "p$i : $img existe déjà — conservé (jamais reformaté)"
    continue
  fi
  info "p$i : création de $img ($TAILLE)…"
  faire fallocate -l "$TAILLE" "$img"
  faire chmod 600 "$img"
  faire mkfs.ext4 -F -q -L "nexus-p$i" -m 1 "$img"
  ok "p$i : image créée et formatée (étiquette nexus-p$i)"
done

# --- 3. /etc/fstab ---------------------------------------------------------------
info "Étape 3/4 — Déclaration dans $FSTAB (remontage automatique au démarrage)"
a_ajouter=()
for i in $(seq 1 "$NB"); do
  img="$IMAGES/p$i.img"
  # Doublon ? on cherche une ligne active qui monte déjà cette image
  if [ -f "$FSTAB" ] && awk -v img="$img" '$1 == img && $0 !~ /^[[:space:]]*#/ {found=1} END {exit !found}' "$FSTAB"; then
    ok "p$i : déjà présent dans $FSTAB"
  else
    a_ajouter+=("$img $BASE/p$i ext4 loop,nofail,defaults 0 2")
  fi
done
if [ "${#a_ajouter[@]}" -gt 0 ]; then
  sauvegarde="$FSTAB.bak-$(date +%Y%m%d-%H%M%S)"
  info "Sauvegarde de $FSTAB vers $sauvegarde"
  faire cp -a "$FSTAB" "$sauvegarde"
  for ligne in "${a_ajouter[@]}"; do
    if [ "$SIMULATION" -eq 1 ]; then
      printf '   (simulation) ajout dans %s : %s\n' "$FSTAB" "$ligne"
    else
      printf '%s\n' "$ligne" >> "$FSTAB"
    fi
  done
  [ "$SIMULATION" -eq 1 ] || ok "${#a_ajouter[@]} ligne(s) ajoutée(s) à $FSTAB"
fi

# --- 4. Montage ------------------------------------------------------------------
info "Étape 4/4 — Montage des partitions"
for i in $(seq 1 "$NB"); do
  point="$BASE/p$i"
  faire mkdir -p "$point"
  if mountpoint -q "$point"; then
    ok "p$i : $point déjà monté"
    continue
  fi
  # Dossier déjà rempli (ex. kit cloné dans /srv/p1/nexus-mothership AVANT les partitions) :
  # son contenu est mis de côté, puis recopié DANS la partition après le montage.
  attente=""
  if [ -n "$(ls -A "$point" 2>/dev/null)" ]; then
    attente="$BASE/.p$i-avant-montage"
    info "p$i : $point contient déjà des fichiers, ils seront déplacés dans la partition"
    faire mkdir -p "$attente"
    if [ "$SIMULATION" -eq 1 ]; then
      printf '   (simulation) déplacement de %s/* vers %s puis retour dans la partition\n' "$point" "$attente"
    else
      find "$point" -mindepth 1 -maxdepth 1 -exec mv -t "$attente" {} +
    fi
  fi
  faire mount -o loop,defaults "$IMAGES/p$i.img" "$point"
  if [ -n "$attente" ] && [ "$SIMULATION" -eq 0 ]; then
    cp -a "$attente"/. "$point"/ && rm -rf "$attente"
    ok "p$i : fichiers existants replacés dans la partition"
  fi
  [ "$SIMULATION" -eq 1 ] || ok "p$i : monté sur $point"
done

# --- Résumé ----------------------------------------------------------------------
echo
if [ "$SIMULATION" -eq 1 ]; then
  avert "Simulation terminée : aucune modification effectuée. Relancez sans --dry-run pour appliquer."
else
  info "Résumé des partitions :"
  points=()
  for i in $(seq 1 "$NB"); do points+=("$BASE/p$i"); done
  df -h "${points[@]}"
  echo
  ok "Partitions prêtes. P1 accueillera le Mini Mothership : $BASE/p1/nexus-mothership"
fi
