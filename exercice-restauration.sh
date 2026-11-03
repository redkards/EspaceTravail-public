#!/usr/bin/env bash
# =============================================================================
#  exercice-restauration.sh — exercice de restauration mensuel sur la partition P2
#
#  Prend la DERNIÈRE sauvegarde de ./backups, la restaure dans une copie jetable
#  /srv/p2/exercice-restauration et la fait tourner à part (projet « p2-exercice ») :
#    - aucun port publié sur l'hôte, ni Caddy, ni ntfy, ni cron, ni Ollama
#      (IA factice) ; réseau Docker isolé « p2-exercice-net » (interne) ;
#    - images du kit réutilisées (construites seulement si absentes) ;
#    - limites P2 : nexus-core 384 Mo / 0,1 vCPU + nexus-bridge 128 Mo / 0,05 vCPU
#      = 512 Mo et 0,15 vCPU maximum ;
#    - P1 (conteneurs, réseau, données) n'est JAMAIS touchée.
#  Vérifications : /api/sante OK ; missions et entrées LEDGER identiques à la
#  sauvegarde ; chaîne LEDGER (HMAC) valide ; env.sauvegarde.gpg déchiffrable avec
#  BACKUP_PASSPHRASE ; nexus-bridge répond.
#  Ensuite tout est arrêté et effacé (conteneurs, réseau, dossier), même en cas
#  d'échec. Rapport daté dans backups/exercices/ (sans aucun secret) et alerte ntfy
#  générique « Restauration testée : OK » ou « ÉCHEC exercice de restauration ».
#
#  Usage : bash exercice-restauration.sh        (cron mensuel proposé par install.sh)
#  Codes de sortie : 0 exercice réussi · 1 configuration (pas de .env, pas de
#  sauvegarde, docker absent) · 2 vérification échouée · 3 P2 non montée ·
#  4 un exercice est déjà en cours.
# =============================================================================
# Fonctions appelées par « trap » (terminer, notifier) : shellcheck les croit inutilisées.
# shellcheck disable=SC2317
set -euo pipefail
umask 077

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$KIT_DIR/.env"
BACKUPS="$KIT_DIR/backups"
RAPPORTS="$BACKUPS/exercices"
P2="${NEXUS_P2:-/srv/p2}"
TRAVAIL="$P2/exercice-restauration"
# Tests : simulateur docker, et montage de P2 non exigé
DOCKER="${NEXUS_DOCKER:-docker}"
EXIGER_MONTAGE="${NEXUS_EXERCICE_EXIGER_MONTAGE:-1}"
ATTENTE_MAX="${NEXUS_ATTENTE_MAX:-90}"   # x 2 s (P2 : 0,15 vCPU, démarrage lent)
PROJET="p2-exercice"
RESEAU="p2-exercice-net"
C_CORE="p2-exercice-nexus-core"
C_BRIDGE="p2-exercice-nexus-bridge"
UID_NEXUS=10001

info()  { printf '[i] %s\n' "$*"; }
ok()    { printf '[OK] %s\n' "$*"; }
avert() { printf '[!] %s\n' "$*"; }

DEBUT="$(date '+%Y-%m-%d %H:%M:%S')"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
RESULTATS=()        # lignes du rapport
CODE_SORTIE=0
SAUVEGARDE="(aucune)"
NOTIFIER=1

lire_env() {
  local f="${2:-$ENV_FILE}"
  [ -r "$f" ] || return 0
  { grep -E "^${1}=" "$f" || true; } | tail -n 1 | cut -d= -f2- | sed "s/^'//; s/'\$//"
}
noter()  { RESULTATS+=("OK     $*"); ok "$*"; }
echec()  { RESULTATS+=("ECHEC  $*"); avert "ÉCHEC : $*"; [ "$CODE_SORTIE" -ne 0 ] || CODE_SORTIE="${2:-2}"; }
fin()    { CODE_SORTIE="$2"; RESULTATS+=("ECHEC  $1"); avert "$1"; exit "$2"; }

# --- Nettoyage complet (aussi utilisé au début : idempotent) --------------------------
nettoyer() {
  "$DOCKER" rm -f "$C_CORE" "$C_BRIDGE" >/dev/null 2>&1 || true
  "$DOCKER" network rm "$RESEAU" >/dev/null 2>&1 || true
  case "$TRAVAIL" in */exercice-restauration) rm -rf --one-file-system "$TRAVAIL" ;; esac
}

# --- Notification ntfy générique (aucun détail) ---------------------------------------
notifier() {
  local titre="$1" url topic profils ip args=()
  topic="$(lire_env NTFY_TOPIC)"
  [ -n "$topic" ] || { info "NTFY_TOPIC vide : pas de notification."; return 0; }
  command -v curl >/dev/null 2>&1 || return 0
  url="$(lire_env NTFY_URL)"; url="${url:-https://ntfy.sh}"
  profils="$(lire_env COMPOSE_PROFILES)"
  if [[ ",$profils," == *",complet,"* ]] || [ "$url" = "http://ntfy" ]; then
    # Mode complet : serveur ntfy du kit, joint par Caddy sur l'hôte
    url="https://$(lire_env NEXUS_HOST):8445"
    ip="$(lire_env NEXUS_BIND_IP)"; [ -n "$ip" ] && [ "$ip" != "0.0.0.0" ] || ip="127.0.0.1"
    args+=(--resolve "$(lire_env NEXUS_HOST):8445:$ip")
  fi
  # Titre ASCII (en-tête HTTP) ; le texte accentué est dans le corps du message
  if curl -s -m 20 -o /dev/null "${args[@]}" -H "Title: NEXUS - exercice de restauration" -H "Tags: floppy_disk" \
       --data-binary "$titre — rapport dans backups/exercices (VPS)." "${url%/}/$topic"; then
    info "Notification envoyée."
  else
    avert "Notification ntfy impossible."
  fi
}

# --- Fin : nettoyage, rapport, notification (même en cas d'échec) ----------------------
terminer() {
  local code=$? titre
  [ "$CODE_SORTIE" -ne 0 ] || CODE_SORTIE="$code"
  set +e
  info "Nettoyage : conteneurs, réseau et dossier de l'exercice"
  nettoyer
  if [ -d "$TRAVAIL" ]; then RESULTATS+=("ECHEC  dossier $TRAVAIL non effacé"); CODE_SORTIE=2; fi
  [ "$NOTIFIER" -eq 1 ] || exit "$CODE_SORTIE"
  if [ "$CODE_SORTIE" -eq 0 ]; then titre="Restauration testée : OK"; else titre="ÉCHEC exercice de restauration"; fi
  mkdir -p "$RAPPORTS"; chmod 700 "$RAPPORTS"
  {
    echo "Exercice de restauration — $DEBUT → $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Sauvegarde testée : $SAUVEGARDE"
    echo "Résultat : $titre (code $CODE_SORTIE)"
    echo
    printf '%s\n' "${RESULTATS[@]}"
  } > "$RAPPORTS/exercice-$STAMP.txt"
  info "Rapport : $RAPPORTS/exercice-$STAMP.txt"
  # 12 derniers rapports conservés
  find "$RAPPORTS" -maxdepth 1 -name 'exercice-*.txt' | sort -r | tail -n +13 | xargs -r rm -f
  notifier "$titre"
  exit "$CODE_SORTIE"
}

# --- 0. Verrou : un seul exercice à la fois ---------------------------------------------
[ -f "$ENV_FILE" ] || { echo "[ERREUR] .env introuvable : le Mothership n'est pas installé ici." >&2; exit 1; }
mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
exec 9>"$BACKUPS/.exercice-restauration.verrou"
if ! flock -n 9; then echo "[!] Un exercice de restauration est déjà en cours." >&2; exit 4; fi
trap terminer EXIT
trap 'exit 130' INT TERM

echo "=== Exercice de restauration (P2) — $DEBUT ==="

# --- 1. Prérequis --------------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || fin "Lancez ce script en root." 1
command -v "$DOCKER" >/dev/null 2>&1 || fin "Docker introuvable." 1
if [ "$EXIGER_MONTAGE" = "1" ] && ! mountpoint -q "$P2"; then
  fin "La partition P2 ($P2) n'est pas montée : exercice annulé (voir partitions.sh)." 3
fi
SRC="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | sort | tail -n 1)"
[ -n "$SRC" ] || fin "Aucune sauvegarde dans $BACKUPS (lancez bash backup.sh)." 1
SAUVEGARDE="$(basename "$SRC")"
info "Sauvegarde testée : $SAUVEGARDE"
nettoyer
mkdir -p "$TRAVAIL/data"; chmod 700 "$TRAVAIL"

# --- 2. Déchiffrement du .env sauvegardé ------------------------------------------------------
ENV_SAUVE="$TRAVAIL/env.sauvegarde"
if [ -f "$SRC/env.sauvegarde.gpg" ]; then
  phrase="$(lire_env BACKUP_PASSPHRASE)"
  if [ -z "$phrase" ]; then
    echec "BACKUP_PASSPHRASE absente du .env : env.sauvegarde.gpg non testé"
  elif gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 -d \
         -o "$ENV_SAUVE" "$SRC/env.sauvegarde.gpg" 3< <(printf '%s' "$phrase") 2>/dev/null; then
    noter "env.sauvegarde.gpg déchiffré avec BACKUP_PASSPHRASE"
  else
    echec "env.sauvegarde.gpg NON déchiffrable avec BACKUP_PASSPHRASE"
  fi
  unset phrase
elif [ -f "$SRC/env.sauvegarde.age" ]; then
  RESULTATS+=("INFO   env.sauvegarde.age : clé privée age hors du VPS, déchiffrement non testé")
elif [ -f "$SRC/env.sauvegarde" ]; then
  cp "$SRC/env.sauvegarde" "$ENV_SAUVE"
  RESULTATS+=("INFO   env.sauvegarde non chiffré (gpg absent lors de la sauvegarde)")
else
  echec "aucune copie du .env dans la sauvegarde"
fi
# Clé HMAC du LEDGER : celle de la sauvegarde (preuve qu'elle se suffit), sinon l'actuelle
CLE_LEDGER="$(lire_env LEDGER_HMAC_KEY "$ENV_SAUVE")"
[ -n "$CLE_LEDGER" ] || CLE_LEDGER="$(lire_env LEDGER_HMAC_KEY)"

# --- 3. Extraction des données -----------------------------------------------------------------
for service in nexus-core nexus-bridge; do
  archive="$SRC/$service.tar.gz"
  [ -f "$archive" ] || { echec "$service.tar.gz absent de la sauvegarde"; continue; }
  tar -C "$TRAVAIL/data" -xzf "$archive" || { echec "archive $service.tar.gz illisible"; continue; }
done
for paire in nexus-core:nexus.db nexus-bridge:bridge.db; do
  d="$TRAVAIL/data/${paire%%:*}"; base="${paire#*:}"
  [ -d "$d" ] || continue
  [ -f "$d/${base%.db}-sauvegarde.db" ] && mv -f "$d/${base%.db}-sauvegarde.db" "$d/$base"
  rm -f "$d/$base-wal" "$d/$base-shm" "$d/$base-journal"
done
DB="$TRAVAIL/data/nexus-core/nexus.db"
[ -f "$DB" ] || fin "nexus.db absente de la sauvegarde : rien à vérifier." 2
chown -R "$UID_NEXUS:$UID_NEXUS" "$TRAVAIL/data"

# Référence lue AVANT démarrage (nexus-core ajoute ensuite une entrée « demarrage »)
REF="$(python3 - "$DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
m = c.execute("select count(*) from missions").fetchone()[0]
n, mx = c.execute("select count(*), coalesce(max(id), 0) from ledger").fetchone()
h = c.execute("select hash from ledger where id = ?", (mx,)).fetchone()
print(m, n, mx, h[0] if h else "-")
PY
)" || fin "Lecture de nexus.db impossible (base abîmée ?)." 2
read -r REF_MISSIONS REF_LEDGER REF_MAXID REF_HASH <<<"$REF"
info "Sauvegarde : $REF_MISSIONS missions, $REF_LEDGER entrées LEDGER"

# --- 4. Images (réutilisées ; construites sous un nom à part si absentes) ---------------------------
image_pour() {
  local service="$1" img="p1-nexus/$1:local"
  if "$DOCKER" image inspect "$img" >/dev/null 2>&1; then printf '%s' "$img"; return 0; fi
  img="$PROJET/$service:local"
  "$DOCKER" image inspect "$img" >/dev/null 2>&1 \
    || "$DOCKER" build -q -t "$img" "$KIT_DIR/$service" >/dev/null || return 1
  printf '%s' "$img"
}
IMG_CORE="$(image_pour nexus-core)" || fin "Image nexus-core introuvable et construction impossible." 1
IMG_BRIDGE="$(image_pour nexus-bridge)" || fin "Image nexus-bridge introuvable et construction impossible." 1

# --- 5. Démarrage isolé : réseau interne, aucun port, IA factice, 512 Mo -------------------------
# Secrets jetables propres à l'exercice, passés par fichier (jamais en ligne de commande).
ENV_CORE="$TRAVAIL/core.env"; ENV_BRIDGE="$TRAVAIL/bridge.env"
JETON="$(openssl rand -hex 32)"
cat > "$ENV_CORE" <<EOF
TZ=Europe/Paris
NEXUS_HOST=exercice.invalid
DATABASE_URL=sqlite:////data/nexus.db
REDIS_URL=
NEXUS_API_KEY=$(openssl rand -hex 32)
COCKPIT_INTERNAL=$(openssl rand -hex 32)
LEDGER_HMAC_KEY=$CLE_LEDGER
LLM_PROVIDER=fake
LLM_FALLBACK=aucun
NTFY_URL=
NTFY_TOPIC=
NEXUS_TACHES_FOND=0
NEXUS_MEMOIRE_AUTO=0
EOF
cat > "$ENV_BRIDGE" <<EOF
TZ=Europe/Paris
BRIDGE_DB=/data/bridge.db
BRIDGE_TOKEN_CLAUDE=$JETON
NEXUS_CORE_URL=http://$C_CORE:8000
NEXUS_API_KEY=$(lire_env NEXUS_API_KEY "$ENV_CORE")
EOF
unset CLE_LEDGER JETON
"$DOCKER" network create --internal --label "com.docker.compose.project=$PROJET" "$RESEAU" >/dev/null \
  || fin "Création du réseau $RESEAU impossible." 2
commun=(-d --network "$RESEAU" --label "com.docker.compose.project=$PROJET"
        --security-opt no-new-privileges:true --cap-drop ALL --read-only --restart no)
"$DOCKER" run "${commun[@]}" --name "$C_CORE" --memory 384m --cpus 0.1 --tmpfs /tmp:size=64m \
  --env-file "$ENV_CORE" -v "$TRAVAIL/data/nexus-core:/data" "$IMG_CORE" >/dev/null \
  || fin "Démarrage de nexus-core (exercice) impossible." 2
if [ -d "$TRAVAIL/data/nexus-bridge" ]; then
  "$DOCKER" run "${commun[@]}" --name "$C_BRIDGE" --memory 128m --cpus 0.05 --tmpfs /tmp:size=16m \
    --env-file "$ENV_BRIDGE" -v "$TRAVAIL/data/nexus-bridge:/data" "$IMG_BRIDGE" >/dev/null \
    || echec "démarrage de nexus-bridge (exercice) impossible"
fi
rm -f "$ENV_CORE" "$ENV_BRIDGE"

# --- 6. Vérifications par docker exec --------------------------------------------------------------
sante=0
for _ in $(seq 1 "$ATTENTE_MAX"); do
  if "$DOCKER" exec "$C_CORE" python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/sante', timeout=5)" >/dev/null 2>&1; then
    sante=1; break
  fi
  sleep 2
done
if [ "$sante" -eq 1 ]; then noter "nexus-core démarre sur la copie : /api/sante OK"; else echec "/api/sante ne répond pas"; fi

if [ "$sante" -eq 1 ]; then
  # Script exécuté DANS le conteneur ; la clé API y est lue dans l'environnement.
  MESURE="$("$DOCKER" exec -i "$C_CORE" python - "$REF_MAXID" <<'PY' 2>/dev/null || true
import json, os, sqlite3, sys, urllib.request as u
mx = int(sys.argv[1])
c = sqlite3.connect("file:/data/nexus.db?mode=ro", uri=True)
m = c.execute("select count(*) from missions").fetchone()[0]
n = c.execute("select count(*) from ledger where id <= ?", (mx,)).fetchone()[0]
h = c.execute("select hash from ledger where id = ?", (mx,)).fetchone()
req = u.Request("http://127.0.0.1:8000/api/ledger/verifier",
                headers={"X-Nexus-Key": os.environ.get("NEXUS_API_KEY", "")})
v = json.loads(u.urlopen(req, timeout=60).read())
print(m, n, h[0] if h else "-", "oui" if v.get("valide") else "non",
      "oui" if v.get("hmac_actif") else "non", v.get("entrees", "?"))
PY
)"
  read -r M_MISSIONS M_LEDGER M_HASH M_VALIDE M_HMAC M_TOTAL <<<"${MESURE:-x x x x x x}"
  if [ "$M_MISSIONS" = "$REF_MISSIONS" ]; then noter "missions : $M_MISSIONS (identique à la sauvegarde)"
  else echec "missions : $M_MISSIONS restaurées pour $REF_MISSIONS sauvegardées"; fi
  if [ "$M_LEDGER" = "$REF_LEDGER" ] && [ "$M_HASH" = "$REF_HASH" ]; then
    noter "LEDGER : $M_LEDGER entrées identiques à la sauvegarde (dernier hash conforme)"
  else
    echec "LEDGER : $M_LEDGER entrées / hash différent de la sauvegarde ($REF_LEDGER)"
  fi
  if [ "$M_VALIDE" = "oui" ] && [ "$M_HMAC" = "oui" ]; then
    noter "chaîne LEDGER vérifiée (HMAC actif, $M_TOTAL entrées)"
  elif [ "$M_VALIDE" = "oui" ]; then
    echec "chaîne LEDGER valide mais SANS HMAC (LEDGER_HMAC_KEY absente de la sauvegarde)"
  else
    echec "chaîne LEDGER invalide ou vérification impossible"
  fi
fi
if "$DOCKER" ps -q --filter "name=^${C_BRIDGE}\$" 2>/dev/null | grep -q .; then
  bridge=0
  for _ in $(seq 1 15); do
    if "$DOCKER" exec "$C_BRIDGE" python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/sante', timeout=5)" >/dev/null 2>&1; then
      bridge=1; break
    fi
    sleep 2
  done
  if [ "$bridge" -eq 1 ]; then noter "nexus-bridge démarre sur la copie (mémoire commune)"; else echec "nexus-bridge ne répond pas"; fi
fi

if [ "$CODE_SORTIE" -eq 0 ]; then ok "Exercice réussi."; else avert "Exercice en échec (voir le rapport)."; fi
exit "$CODE_SORTIE"
