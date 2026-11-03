#!/usr/bin/env bash
# =============================================================================
#  install.sh — installation en une commande du Mini NEXUS MOTHERSHIP (partition P1)
#
#  À lancer EN ROOT depuis le dossier du kit :
#     cd /srv/p1/nexus-mothership && bash install.sh
#
#  Tout est GRATUIT : aucune option payante n'est proposée par ce script.
#
#  IA (par défaut : Ollama Cloud, offre gratuite + repli sur l'IA locale) :
#     (défaut)       demande la clé Ollama Cloud ; sans clé -> IA locale seule
#     --cloud        Ollama Cloud sans poser la question « Utiliser Ollama Cloud ? »
#     --local        IA locale seule (qwen2.5:3b), sans Ollama Cloud
#     --sans-repli   Ollama Cloud SANS IA locale de secours (MVP ≈ 0,5 Go de RAM)
#     --repli-local  Ollama Cloud + IA locale de secours (déjà le comportement par défaut)
#     --cle-fichier CHEMIN  lit la clé Ollama Cloud dans un fichier (pratique au
#                    téléphone : nano /root/cle-ollama.txt), puis propose de l'effacer
#     La clé n'est jamais passée en argument : saisie masquée ou --cle-fichier.
#     Elle n'est enregistrée qu'après un appel AUTHENTIFIÉ réussi à Ollama Cloud.
#
#  Modes :
#     (défaut)       MVP : cockpit + agents (SQLite). Ports 80 et 443.
#     --complet      version complète : + PostgreSQL, Redis, n8n, Uptime Kuma, ntfy
#                    (ports 80, 443, 8443, 8444, 8445)
#     --sans-partition  test rapide sans partition P1 : kit dans /opt/nexus-mothership
#
#  Autres options :
#     --host NOM     nom d'hôte public, ex. srvXXXX.hstgr.cloud (défaut : hostname -f, sinon demandé)
#     --email ADR    e-mail pour les certificats Let's Encrypt
#     --model NOM    modèle principal (cloud : défaut gemma4:31b ; local : qwen2.5:3b)
#     --yes          répond « oui » aux questions (mode non interactif)
#     -h, --help     affiche cette aide
#
#  Passer de MVP à complet : relancer « bash install.sh --complet » (secrets conservés).
#  Revenir en MVP : « bash install.sh » (les services complets sont arrêtés,
#  leurs données restent dans ./data).
#
#  Idempotent : relançable sans risque. Si .env existe, les secrets ne sont PAS
#  régénérés (seules les variables manquantes sont ajoutées).
#  Aucun secret n'est affiché ni écrit dans install.log : le récapitulatif indique
#  la commande « grep … .env » à taper pour les revoir.
#  Ce script ne modifie JAMAIS le pare-feu (ufw ou Hostinger) : il vérifie et
#  affiche les commandes à lancer si besoin.
# =============================================================================
set -euo pipefail

# --- Constantes ------------------------------------------------------------------
DOSSIER_P1="/srv/p1/nexus-mothership"
DOSSIER_SANS_PARTITION="/opt/nexus-mothership"
POINT_P1="/srv/p1"
IMAGE_CADDY="caddy:2.8"
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$KIT_DIR/.env"
LOG_FILE="$KIT_DIR/install.log"
TOTAL_ETAPES=13

ARG_HOST=""
ARG_EMAIL=""
ARG_MODEL=""
ARG_CLE_FICHIER=""
OUI=0
COMPLET=0
SANS_PARTITION=0
CHOIX_IA=""        # vide = demander ; cloud ; local
REPLI=1            # 1 = IA locale de secours (profil « local »)
MODELE_CLOUD_DEFAUT="gemma4:31b"
MODELE_LOCAL="qwen2.5:3b"
OLLAMA_CLOUD_URL="https://ollama.com"

# --- Affichage ---------------------------------------------------------------------
ETAPE=0
etape() { ETAPE=$((ETAPE + 1)); printf '\n\033[1;36m━━ Étape %d/%d — %s\033[0m\n' "$ETAPE" "$TOTAL_ETAPES" "$*"; }
info()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
avert() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
erreur(){ printf '\033[1;31m[ERREUR]\033[0m %s\n' "$*" >&2; exit 1; }

# Question oui/non. Retourne 0 pour oui. Avec --yes ou sans terminal : réponse par défaut ($2).
demander() {
  local question="$1" defaut="${2:-n}" rep invite="[o/N]"
  if [ "$OUI" -eq 1 ]; then [ "$defaut" = "o" ]; return; fi
  if [ ! -t 0 ]; then [ "$defaut" = "o" ]; return; fi
  [ "$defaut" = "o" ] && invite="[O/n]"
  read -r -p "$question $invite " rep || rep=""
  [ -n "$rep" ] || { [ "$defaut" = "o" ]; return; }
  case "$rep" in o|O|oui|OUI|y|Y) return 0 ;; *) return 1 ;; esac
}

aide() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# --- Arguments ---------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --host)   [ $# -ge 2 ] || erreur "--host attend une valeur"; ARG_HOST="$2"; shift 2 ;;
    --host=*) ARG_HOST="${1#*=}"; shift ;;
    --email)  [ $# -ge 2 ] || erreur "--email attend une valeur"; ARG_EMAIL="$2"; shift 2 ;;
    --email=*) ARG_EMAIL="${1#*=}"; shift ;;
    --model)  [ $# -ge 2 ] || erreur "--model attend une valeur"; ARG_MODEL="$2"; shift 2 ;;
    --model=*) ARG_MODEL="${1#*=}"; shift ;;
    --cle-fichier) [ $# -ge 2 ] || erreur "--cle-fichier attend un chemin"; ARG_CLE_FICHIER="$2"; CHOIX_IA="${CHOIX_IA:-cloud}"; shift 2 ;;
    --cle-fichier=*) ARG_CLE_FICHIER="${1#*=}"; CHOIX_IA="${CHOIX_IA:-cloud}"; shift ;;
    --yes|-y) OUI=1; shift ;;
    --complet) COMPLET=1; shift ;;
    --mvp) COMPLET=0; shift ;;
    --sans-partition) SANS_PARTITION=1; shift ;;
    --cloud) CHOIX_IA="cloud"; shift ;;
    --local) CHOIX_IA="local"; shift ;;
    --sans-repli) REPLI=0; shift ;;
    --repli-local) REPLI=1; shift ;;
    -h|--help) aide ;;
    *) erreur "Option inconnue : $1 (voir --help)" ;;
  esac
done

# --- Mode choisi ----------------------------------------------------------------------
if [ "$COMPLET" -eq 1 ]; then
  MODE="complet"
  PORTS_PUBLICS=(80 443 8443 8444 8445)
  TOTAL_ETAPES=14
else
  MODE="MVP"
  PORTS_PUBLICS=(80 443)
  TOTAL_ETAPES=13
fi
if [ "$SANS_PARTITION" -eq 1 ]; then
  DOSSIER_ATTENDU="$DOSSIER_SANS_PARTITION"
else
  DOSSIER_ATTENDU="$DOSSIER_P1"
fi

# --- Ancien journal : purge des secrets écrits par les versions précédentes -------------
# Les anciennes versions affichaient mots de passe et clé API dans le récapitulatif, donc
# dans install.log. On repère ces lignes (libellés connus + valeurs secrètes du .env)
# et on propose de réécrire le journal sans elles. Les secrets ne sont jamais affichés.
purger_journal() {
  [ -s "$LOG_FILE" ] || return 0
  local motifs tmp regex
  regex='mot de passe +: [0-9a-f]|Clé API \(X-Nexus-Key\): *[0-9a-f]|1re barrière +: .* / [0-9a-f]|Notifications ntfy +: https?://|> topic nexus-'
  motifs="$(mktemp)"; chmod 600 "$motifs"
  if [ -f "$ENV_FILE" ]; then
    { grep -E '^(COCKPIT_PASSWORD|NEXUS_API_KEY|N8N_BASIC_PASSWORD|N8N_ENCRYPTION_KEY|POSTGRES_PASSWORD|OLLAMA_API_KEY|BRIDGE_TOKEN_[A-Z]+|NTFY_TOPIC|NTFY_PASSWORD|COCKPIT_INTERNAL|LEDGER_HMAC_KEY|BACKUP_PASSPHRASE)=' "$ENV_FILE" || true; } \
      | cut -d= -f2- | sed "s/^'//; s/'\$//" | awk 'length($0) >= 8' > "$motifs"
  fi
  if grep -qE "$regex" "$LOG_FILE" || { [ -s "$motifs" ] && grep -qF -f "$motifs" "$LOG_FILE"; }; then
    avert "install.log contient des secrets écrits par une ancienne version du script."
    if demander "Réécrire install.log sans ces lignes (recommandé) ?" o; then
      tmp="$(mktemp)"; chmod 600 "$tmp"
      { grep -vE "$regex" "$LOG_FILE" || true; } \
        | { if [ -s "$motifs" ]; then grep -vF -f "$motifs" || true; else cat; fi; } > "$tmp"
      cat "$tmp" > "$LOG_FILE"; rm -f "$tmp"
      ok "install.log réécrit sans les lignes sensibles"
    else
      avert "install.log conservé tel quel : supprimez-le vous-même (rm $LOG_FILE)."
    fi
  fi
  rm -f "$motifs"
}
purger_journal

# --- Journal : tout est copié dans install.log (AUCUN secret n'y est écrit) -----------
touch "$LOG_FILE" && chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
echo
echo "=== Installation NEXUS MOTHERSHIP (mode $MODE) — $(date '+%d/%m/%Y %H:%M:%S') ==="

# --- Outils .env ---------------------------------------------------------------------
# Lit une variable du .env (retire les apostrophes éventuelles)
lire_env() {
  local cle="$1"
  [ -f "$ENV_FILE" ] || return 0
  # « || true » : une variable absente renvoie une chaîne vide (sans arrêter le script)
  { grep -E "^${cle}=" "$ENV_FILE" || true; } | tail -n 1 | cut -d= -f2- | sed "s/^'//; s/'\$//"
}
# Ajoute une variable au .env seulement si elle est absente (idempotence)
assurer_env() {
  local cle="$1" valeur="$2"
  if ! grep -qE "^${cle}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$cle" "$valeur" >> "$ENV_FILE"
    return 0
  fi
  return 1
}
# Supprime une variable du .env (utilisé pour repasser du mode complet au MVP)
retirer_env() {
  local cle="$1" tmp
  grep -qE "^${cle}=" "$ENV_FILE" || return 0
  tmp="$(mktemp)"
  grep -vE "^${cle}=" "$ENV_FILE" > "$tmp" || true
  cat "$tmp" > "$ENV_FILE" && rm -f "$tmp"
}
# Remplace (ou ajoute) une variable. La valeur n'est passée qu'à printf (commande
# interne de bash) : elle n'apparaît jamais dans la liste des processus.
remplacer_env() {
  local cle="$1" valeur="$2"
  retirer_env "$cle"
  printf '%s=%s\n' "$cle" "$valeur" >> "$ENV_FILE"
}
secret() { openssl rand -hex "${1:-24}"; }
# Hash bcrypt calculé par Caddy ; le mot de passe passe par l'entrée standard
# (il n'apparaît pas dans la liste des processus).
hash_bcrypt() { printf '%s\n' "$1" | docker run --rm -i "$IMAGE_CADDY" caddy hash-password | tr -d '\r\n'; }

# =============================================================================
etape "Vérification du système"
# =============================================================================
[ "$(id -u)" -eq 0 ] || erreur "Lancez ce script en root (le terminal web hPanel est déjà root)."
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] || erreur "Système non pris en charge (${PRETTY_NAME:-inconnu}). Ubuntu 22.04 ou 24.04 requis."
  ok "Système : ${PRETTY_NAME}"
else
  erreur "Impossible de lire /etc/os-release."
fi
# Outils nécessaires (normalement déjà présents sur Ubuntu) : commande -> paquet
paquets=()
for paire in curl:curl openssl:openssl awk:gawk ss:iproute2 mountpoint:util-linux jq:jq; do
  command -v "${paire%%:*}" >/dev/null 2>&1 || paquets+=("${paire#*:}")
done
if [ "${#paquets[@]}" -gt 0 ]; then
  info "Installation des outils manquants : ${paquets[*]}"
  if ! { apt-get update -qq && apt-get install -y -qq "${paquets[@]}" >/dev/null; }; then
    erreur "Impossible d'installer : ${paquets[*]}"
  fi
fi
ram_totale=$(free -m | awk '/^Mem:/ {print $2}')
ram_dispo=$(free -m | awk '/^Mem:/ {print $7}')
info "Mémoire : ${ram_totale} Mo au total, ${ram_dispo} Mo disponibles (le Mothership en réserve au plus 5 Go)"
info "Disque / : $(df -h / | awk 'NR==2 {print $4 " libres sur " $2}')"
[ "$ram_dispo" -ge 3000 ] || avert "Moins de 3 Go de RAM disponibles : le modèle local risque d'être lent."

# =============================================================================
etape "Vérification de la partition P1 et du dossier d'installation"
# =============================================================================
if [ "$SANS_PARTITION" -eq 1 ]; then
  avert "Option --sans-partition : installation de TEST, sans la partition P1."
  echo "    Les données iront dans $DOSSIER_SANS_PARTITION/data (disque système, sans limite de taille)."
elif mountpoint -q "$POINT_P1"; then
  ok "$POINT_P1 est bien une partition montée ($(df -h "$POINT_P1" | awk 'NR==2 {print $4 " libres sur " $2}'))"
else
  avert "$POINT_P1 n'est pas une partition montée."
  echo "    Le Mothership doit s'installer dans la partition P1 (20 Go réservés)."
  echo "    Créez d'abord les 4 partitions avec :"
  echo "        bash $KIT_DIR/partitions.sh --dry-run   # pour voir ce qui sera fait"
  echo "        bash $KIT_DIR/partitions.sh             # pour les créer"
  echo "    Ou, pour un simple test sans partition :"
  echo "        git clone ... $DOSSIER_SANS_PARTITION && cd $DOSSIER_SANS_PARTITION && bash install.sh --sans-partition"
  if [ "$OUI" -eq 0 ] && [ -t 0 ] && demander "Lancer partitions.sh maintenant ?" n; then
    bash "$KIT_DIR/partitions.sh"
    mountpoint -q "$POINT_P1" || erreur "$POINT_P1 n'est toujours pas monté."
  else
    erreur "Installation interrompue : créez les partitions (ou utilisez --sans-partition), voir README."
  fi
fi
if [ "$KIT_DIR" != "$DOSSIER_ATTENDU" ]; then
  avert "Le kit est dans $KIT_DIR et non dans $DOSSIER_ATTENDU."
  echo "    Les données seraient stockées ailleurs que prévu. Pour corriger :"
  echo "        mv $KIT_DIR $DOSSIER_ATTENDU && cd $DOSSIER_ATTENDU && bash install.sh $*"
  demander "Continuer quand même dans $KIT_DIR ?" n || erreur "Installation interrompue (aucune modification)."
fi
cd "$KIT_DIR"
[ -d "$KIT_DIR/nexus-core" ] || erreur "Dossier nexus-core/ introuvable dans $KIT_DIR (kit incomplet)."
ok "Dossier d'installation : $KIT_DIR"

# =============================================================================
etape "Installation de Docker (si nécessaire)"
# =============================================================================
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "Docker déjà installé : $(docker --version | cut -d, -f1), $(docker compose version --short 2>/dev/null || echo compose)"
else
  info "Installation de Docker depuis le dépôt officiel (2 à 3 minutes)…"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg >/dev/null
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  systemctl enable --now docker >/dev/null 2>&1 || true
  ok "Docker installé : $(docker --version | cut -d, -f1)"
fi
docker info >/dev/null 2>&1 || erreur "Le service Docker ne répond pas (essayez : systemctl restart docker)."

# =============================================================================
etape "Vérification des ports ${PORTS_PUBLICS[*]} (mode $MODE)"
# =============================================================================
# Si notre propre Caddy tourne déjà (réinstallation), les ports sont normalement pris par lui.
notre_caddy=$(docker ps -q --filter "label=com.docker.compose.project=p1-nexus" --filter "label=com.docker.compose.service=caddy" 2>/dev/null || true)
# Adresse IPv4 publique sur laquelle Caddy écoute (évite les conflits avec Tailscale,
# qui écoute sur sa propre adresse 100.x). Surchargeable par NEXUS_BIND_IP dans .env.
BIND_IP="$(lire_env NEXUS_BIND_IP)"
if [ -z "$BIND_IP" ]; then
  BIND_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}')"
  [ -n "$BIND_IP" ] || BIND_IP="0.0.0.0"
fi
ok "Caddy écoutera sur l'adresse $BIND_IP"
ports_occupes=()
for p in "${PORTS_PUBLICS[@]}"; do
  # Seules les écoutes sur l'adresse publique ou sur toutes les adresses gênent Caddy
  if ss -H -ltn "sport = :$p" 2>/dev/null | awk '{print $4}' \
     | grep -Eq "^(${BIND_IP//./\\.}|0\.0\.0\.0|\*|\[::\]):$p\$"; then
    ports_occupes+=("$p")
  fi
done
if [ "${#ports_occupes[@]}" -gt 0 ] && [ -z "$notre_caddy" ]; then
  avert "Ports déjà utilisés par un autre programme : ${ports_occupes[*]}"
  for p in "${ports_occupes[@]}"; do
    echo "    Port $p : $(ss -H -ltnp "sport = :$p" 2>/dev/null | awk '{print $NF}' | head -n 1)"
  done
  echo
  echo "    Le script ne modifie rien. Causes fréquentes et solutions :"
  echo "      - Apache ou Nginx préinstallé :  systemctl disable --now apache2 nginx"
  echo "      - Un autre conteneur Docker   :  docker ps   (puis l'arrêter si inutile)"
  echo "    Libérez ces ports puis relancez : bash install.sh"
  exit 1
fi
ok "Ports disponibles (ou déjà utilisés par le Caddy du Mothership)"

# =============================================================================
etape "Vérification du pare-feu (aucune modification automatique)"
# =============================================================================
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  manquants=()
  for p in 22 "${PORTS_PUBLICS[@]}"; do
    ufw status 2>/dev/null | grep -qE "^${p}(/tcp)?[[:space:]]+ALLOW" || manquants+=("$p")
  done
  if [ "${#manquants[@]}" -gt 0 ]; then
    avert "ufw est actif et ces ports ne sont pas ouverts : ${manquants[*]}"
    echo "    Commandes à lancer vous-même si vous êtes d'accord :"
    for p in "${manquants[@]}"; do echo "        ufw allow ${p}/tcp"; done
  else
    ok "ufw est actif et les ports nécessaires sont ouverts"
  fi
else
  ok "ufw n'est pas actif sur le VPS (rien à faire de ce côté)"
fi
avert "Rappel : ouvrez aussi les ports TCP ${PORTS_PUBLICS[*]} dans le pare-feu Hostinger"
echo "    (hPanel > VPS > Sécurité > Pare-feu), sinon les pages ne s'afficheront pas."

# =============================================================================
etape "Nom d'hôte et e-mail"
# =============================================================================
hote_actuel="$(lire_env NEXUS_HOST)"
if [ -n "$ARG_HOST" ]; then
  NEXUS_HOST="$ARG_HOST"
elif [ -n "$hote_actuel" ]; then
  NEXUS_HOST="$hote_actuel"
else
  NEXUS_HOST="$(hostname -f 2>/dev/null || true)"
  case "$NEXUS_HOST" in
    *.*) ;;                                   # c'est bien un nom complet (FQDN)
    *) NEXUS_HOST="" ;;
  esac
  if [ "$OUI" -eq 0 ] && [ -t 0 ]; then
    echo "    Nom d'hôte : hPanel > VPS > Vue d'ensemble (ex. srvXXXX.hstgr.cloud)."
    read -r -p "Nom d'hôte public du VPS [${NEXUS_HOST:-à saisir}] : " rep || rep=""
    [ -n "$rep" ] && NEXUS_HOST="$rep"
  fi
  [ -n "$NEXUS_HOST" ] || erreur "Nom d'hôte introuvable : relancez avec --host srvXXXX.hstgr.cloud"
fi
[[ "$NEXUS_HOST" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || erreur "Nom d'hôte invalide : « $NEXUS_HOST »"
ok "Nom d'hôte : $NEXUS_HOST"

email_actuel="$(lire_env ACME_EMAIL)"
if [ -n "$ARG_EMAIL" ]; then
  ACME_EMAIL="$ARG_EMAIL"
elif [ -n "$email_actuel" ]; then
  ACME_EMAIL="$email_actuel"
elif [ "$OUI" -eq 0 ] && [ -t 0 ]; then
  read -r -p "Votre e-mail (avertissements Let's Encrypt) : " ACME_EMAIL || ACME_EMAIL=""
else
  erreur "E-mail requis : relancez avec --email vous@exemple.fr"
fi
[[ "$ACME_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || erreur "E-mail invalide : « $ACME_EMAIL »"
ok "E-mail : $ACME_EMAIL"

# =============================================================================
etape "Création ou mise à jour du fichier .env (secrets)"
# =============================================================================
info "Téléchargement de l'image Caddy pour calculer les mots de passe chiffrés…"
docker pull -q "$IMAGE_CADDY" >/dev/null
if [ -f "$ENV_FILE" ]; then
  ok ".env existe déjà : secrets conservés"
  [ -n "$ARG_HOST" ]  && remplacer_env NEXUS_HOST "$NEXUS_HOST"  && info "NEXUS_HOST mis à jour"
  [ -n "$ARG_EMAIL" ] && remplacer_env ACME_EMAIL "$ACME_EMAIL" && info "ACME_EMAIL mis à jour"
  [ -n "$ARG_MODEL" ] && grep -q '^NEXUS_MODEL=' "$ENV_FILE" && remplacer_env NEXUS_MODEL "$ARG_MODEL" && info "NEXUS_MODEL mis à jour"
else
  umask 077
  {
    echo "# Généré par install.sh le $(date '+%d/%m/%Y %H:%M') — NE PAS PARTAGER"
    echo "# Les hash bcrypt sont entre apostrophes pour protéger les caractères \$."
  } > "$ENV_FILE"
  ok "Nouveau fichier .env créé"
fi
chmod 600 "$ENV_FILE"

ajoute=0
assurer_env COMPOSE_PROJECT_NAME p1-nexus && ajoute=1
assurer_env NEXUS_HOST "$NEXUS_HOST" && ajoute=1
assurer_env ACME_EMAIL "$ACME_EMAIL" && ajoute=1
assurer_env POSTGRES_USER nexus && ajoute=1
assurer_env POSTGRES_PASSWORD "$(secret 24)" && ajoute=1
assurer_env POSTGRES_DB nexus && ajoute=1
assurer_env REDIS_URL "redis://redis:6379/0" && ajoute=1
assurer_env NEXUS_API_KEY "$(secret 32)" && ajoute=1
assurer_env COCKPIT_USER decideur && ajoute=1
assurer_env COCKPIT_PASSWORD "$(secret 9)" && ajoute=1
if ! grep -q '^COCKPIT_PASSWORD_HASH=' "$ENV_FILE"; then
  assurer_env COCKPIT_PASSWORD_HASH "'$(hash_bcrypt "$(lire_env COCKPIT_PASSWORD)")'"; ajoute=1
fi
assurer_env N8N_ENCRYPTION_KEY "$(secret 32)" && ajoute=1
assurer_env N8N_BASIC_USER admin && ajoute=1
assurer_env N8N_BASIC_PASSWORD "$(secret 9)" && ajoute=1
if ! grep -q '^N8N_BASIC_PASSWORD_HASH=' "$ENV_FILE"; then
  assurer_env N8N_BASIC_PASSWORD_HASH "'$(hash_bcrypt "$(lire_env N8N_BASIC_PASSWORD)")'"; ajoute=1
fi
assurer_env OLLAMA_URL "http://ollama:11434" && ajoute=1
assurer_env OLLAMA_CLOUD_URL "$OLLAMA_CLOUD_URL" && ajoute=1
assurer_env NEXUS_MODEL_CHECKER "" && ajoute=1
# Version gratuite : budget payant à 0 (aucune dépense possible)
assurer_env BUDGET_MONTHLY_EUR 0 && ajoute=1
assurer_env LLM_EUR_PAR_1K_TOKENS 0 && ajoute=1
assurer_env BUDGET_TASK_TOKENS 20000 && ajoute=1
assurer_env LLM_MAX_CHARS 12000 && ajoute=1
assurer_env OLLAMA_NUM_CTX 8192 && ajoute=1
assurer_env N3_TIMEOUT_HOURS 24 && ajoute=1
assurer_env N3_DAILY_CAP 15 && ajoute=1
assurer_env NEXUS_FONCTIONNEMENT_DEFAUT F2 && ajoute=1
assurer_env EUR_PAR_USD 0.92 && ajoute=1
# Vide = nombre de missions parallèles choisi automatiquement par nexus-core
assurer_env NEXUS_MAX_MISSIONS "" && ajoute=1
# Secret interne Caddy -> nexus-core (en-tête X-Cockpit-Auth) et clé HMAC du LEDGER
assurer_env COCKPIT_INTERNAL "$(secret 32)" && ajoute=1
assurer_env LEDGER_HMAC_KEY "$(secret 32)" && ajoute=1
# Décideur mobile : code à 6 chiffres, généré UNE fois (jamais régénéré s'il existe)
if ! grep -qE '^COCKPIT_CODE_DECIDEUR=[0-9]{6}$' "$ENV_FILE"; then
  remplacer_env COCKPIT_CODE_DECIDEUR "$(printf '%06d' $(( $(od -An -N4 -tu4 /dev/urandom) % 1000000 )))"
  rm -f "$KIT_DIR/data/.code-decideur-affiche"
  ajoute=1
fi
assurer_env NEXUS_SESSIONS_N3 "12:30,19:00" && ajoute=1
# Secret HMAC des exports vers le QG (webhook signé) ; l'URL NEXUS_WEBHOOK_QG reste à remplir
assurer_env NEXUS_WEBHOOK_SECRET "$(secret 32)" && ajoute=1
[ -n "$(lire_env NEXUS_WEBHOOK_SECRET)" ] || { remplacer_env NEXUS_WEBHOOK_SECRET "$(secret 32)"; ajoute=1; }
assurer_env NEXUS_WEBHOOK_QG "" && ajoute=1
assurer_env VEILLE_CONTACT "" && ajoute=1
assurer_env NEXUS_MEMOIRE_AUTO 1 && ajoute=1
# Alertes N3 sur le téléphone (gratuit). MVP : service public ntfy.sh ; mode complet :
# serveur ntfy du kit (docker-compose.complet.yml force alors http://ntfy).
assurer_env NTFY_URL "https://ntfy.sh" && ajoute=1
case "$(lire_env NTFY_URL)" in
  ""|http://ntfy|http://ntfy/) remplacer_env NTFY_URL "https://ntfy.sh"; ajoute=1 ;;
esac
assurer_env NTFY_TOPIC "nexus-$(secret 8)" && ajoute=1
[ -n "$(lire_env NTFY_TOPIC)" ] || { remplacer_env NTFY_TOPIC "nexus-$(secret 8)"; ajoute=1; }
assurer_env NTFY_USER proprietaire && ajoute=1
assurer_env NTFY_PASSWORD "$(secret 12)" && ajoute=1
# Sauvegardes : phrase secrète gpg pour chiffrer env.sauvegarde ; remote rclone facultatif
assurer_env BACKUP_PASSPHRASE "$(secret 16)" && ajoute=1
assurer_env BACKUP_AGE_RECIPIENT "" && ajoute=1
assurer_env NEXUS_RCLONE_REMOTE gdrive && ajoute=1
# Passerelle nexus-bridge : un jeton par IA (64 caractères hexadécimaux). Ajoutés
# seulement s'ils manquent : un jeton existant n'est jamais remplacé.
for ia in CLAUDE CHATGPT GEMINI PROPRIETAIRE; do
  assurer_env "BRIDGE_TOKEN_$ia" "$(secret 32)" && ajoute=1
done
assurer_env BRIDGE_LIMITE_PAR_MINUTE 60 && ajoute=1
# Pour information : utilisée seulement en mode complet (docker-compose.complet.yml).
# En MVP, nexus-core utilise SQLite (sqlite:////data/nexus.db, fixé dans docker-compose.yml).
assurer_env DATABASE_URL "postgresql+psycopg://nexus:$(lire_env POSTGRES_PASSWORD)@postgres:5432/nexus" && ajoute=1
if [ "$ajoute" -eq 1 ]; then ok "Variables manquantes ajoutées au .env"; else ok ".env complet"; fi

# =============================================================================
assurer_env NEXUS_BIND_IP "$BIND_IP" || true

# =============================================================================
etape "Choix de l'IA (gratuit : Ollama Cloud + IA locale de secours)"
# =============================================================================
# --- debut fonctions cle (testées isolément) ---------------------------------------
# Saisie robuste : une lecture impossible (console coupée, pas de terminal) renvoie
# une chaîne vide au lieu d'arrêter le script. $1 = invite, $2 = « s » pour masquer.
lire_saisie() {
  local invite="$1" masque="${2:-}" valeur=""
  [ -t 0 ] || { printf ''; return 0; }
  if [ "$masque" = "s" ]; then
    IFS= read -r -s -p "$invite" valeur 2>/dev/null || valeur=""
    echo >&2
  else
    IFS= read -r -p "$invite" valeur 2>/dev/null || valeur=""
  fi
  printf '%s' "$valeur"
}
# Nettoie une clé collée : retire espaces, tabulations, retours chariot / ligne,
# puis les guillemets simples ou doubles qui l'entourent.
nettoyer_cle() {
  local c
  c="$(printf '%s' "$1" | tr -d ' \t\r\n')"
  c="${c#\"}"; c="${c%\"}"; c="${c#\'}"; c="${c%\'}"
  printf '%s' "$c"
}
# Forme plausible : au moins 20 caractères, sans guillemet ni espace restant.
cle_plausible() {
  [ "${#1}" -ge 20 ] && [[ "$1" != *[\"\'[:space:]]* ]]
}
# Appel AUTHENTIFIÉ minimal : POST /api/chat (1 token) avec le modèle $2.
# La clé ($1) passe par l'entrée standard (« -H @- ») : jamais dans ps ni à l'écran.
# Résultat dans CODE_HTTP : 200 = clé valide ; 401/403 = clé refusée ; autre = indéterminé.
verifier_cle_cloud() {
  local cle="$1" modele="$2" corps
  corps="$(jq -cn --arg m "$modele" '{model: $m, messages: [{role: "user", content: "OK"}], stream: false, options: {num_predict: 1}}')"
  CODE_HTTP=$(printf 'Authorization: Bearer %s\n' "$cle" \
    | curl -s -m 60 -o /dev/null -w '%{http_code}' -H @- -H 'Content-Type: application/json' \
        --data-binary "$corps" "$OLLAMA_CLOUD_URL/api/chat" 2>/dev/null) || true
  [[ "$CODE_HTTP" =~ ^[0-9]{3}$ ]] || CODE_HTTP=000
}
# Liste des modèles (endpoint public, ne prouve PAS que la clé est bonne).
lister_modeles_cloud() {
  curl -s -m 20 "$OLLAMA_CLOUD_URL/api/tags" 2>/dev/null | jq -r '.models[]?.name // empty' 2>/dev/null || true
}
# --- fin fonctions cle --------------------------------------------------------------

cle_existante="$(lire_env OLLAMA_API_KEY)"
if [ "$CHOIX_IA" = "local" ]; then
  utiliser_cloud=0
elif [ "$CHOIX_IA" = "cloud" ] || [ -n "$cle_existante" ]; then
  utiliser_cloud=1
elif [ "$OUI" -eq 0 ] && [ -t 0 ]; then
  echo "    Ollama Cloud (offre gratuite) donne accès à de gros modèles sans charger le VPS."
  rep="$(lire_saisie "Utiliser Ollama Cloud ? [O/n] ")"
  case "$rep" in n|N|non|NON) utiliser_cloud=0 ;; *) utiliser_cloud=1 ;; esac
else
  utiliser_cloud=1
fi

cloud_ok=0
cloud_inchange=0
CODE_HTTP=""
if [ "$utiliser_cloud" -eq 1 ]; then
  # 1) Modèles disponibles et modèle choisi (avant le test de la clé)
  mapfile -t modeles < <(lister_modeles_cloud)
  modele_actuel="$(lire_env NEXUS_MODEL)"
  choix=""
  for candidat in "$ARG_MODEL" "$modele_actuel" "$MODELE_CLOUD_DEFAUT"; do
    [ -n "$candidat" ] || continue
    if [ "${#modeles[@]}" -eq 0 ] || printf '%s\n' "${modeles[@]}" | grep -qxF "$candidat"; then choix="$candidat"; break; fi
  done
  [ -n "$choix" ] || choix="${modeles[0]:-$MODELE_CLOUD_DEFAUT}"
  if [ -n "$ARG_MODEL" ] && [ "$choix" != "$ARG_MODEL" ]; then
    avert "Modèle « $ARG_MODEL » absent de la liste : « $choix » sera utilisé."
  fi

  # 2) Clé à tester : fichier (--cle-fichier) > saisie > clé déjà dans .env
  nouvelle_cle=""
  if [ -n "$ARG_CLE_FICHIER" ]; then
    [ -r "$ARG_CLE_FICHIER" ] || erreur "Fichier de clé illisible : $ARG_CLE_FICHIER"
    nouvelle_cle="$(nettoyer_cle "$(cat "$ARG_CLE_FICHIER")")"
  elif [ -n "$cle_existante" ]; then
    verifier_cle_cloud "$cle_existante" "$choix"
    case "$CODE_HTTP" in
      200) ok "Clé Ollama Cloud déjà présente dans .env : acceptée par Ollama (non affichée)" ;;
      401|403)
        avert "La clé Ollama Cloud du .env est REFUSÉE par Ollama (code $CODE_HTTP)."
        if [ "$CHOIX_IA" = "cloud" ] && [ -t 0 ] && [ "$OUI" -eq 0 ] && demander "La remplacer maintenant ?" o; then
          echo "    Collez la nouvelle clé (saisie masquée, Entrée vide = annuler)."
          nouvelle_cle="$(nettoyer_cle "$(lire_saisie "    Clé Ollama Cloud : " s)")"
        else
          echo "    Pour la remplacer : bash install.sh --cloud   (ou --cle-fichier, voir README)"
        fi ;;
      *) avert "Vérification de la clé impossible (code $CODE_HTTP) : réglages IA actuels conservés."
         [ "$(lire_env LLM_PROVIDER)" = "ollama_cloud" ] && cloud_inchange=1 ;;
    esac
  else
    if [ -t 0 ] && [ "$OUI" -eq 0 ]; then
      echo "    Créez une clé (gratuite) sur https://ollama.com/settings/keys puis collez-la ici."
      echo "    La saisie est masquée : rien ne s'affiche, c'est normal. Entrée vide = passer."
      echo "    Au téléphone, plus sûr : bash install.sh --cloud --cle-fichier /root/cle-ollama.txt"
      nouvelle_cle="$(nettoyer_cle "$(lire_saisie "    Clé Ollama Cloud : " s)")"
    else
      avert "Pas de terminal interactif : utilisez --cle-fichier pour fournir la clé Ollama Cloud."
    fi
  fi

  # 3) Nouvelle clé : forme, puis appel authentifié ; enregistrée SEULEMENT si acceptée
  if [ -n "$nouvelle_cle" ]; then
    if ! cle_plausible "$nouvelle_cle"; then
      avert "Ce texte (${#nouvelle_cle} caractères) n'est pas une clé Ollama Cloud (20 caractères minimum)."
      echo "    Copiez la clé entière depuis https://ollama.com/settings/keys. Rien n'a été modifié."
    else
      verifier_cle_cloud "$nouvelle_cle" "$choix"
      case "$CODE_HTTP" in
        200)
          remplacer_env OLLAMA_API_KEY "'$nouvelle_cle'"
          chmod 600 "$ENV_FILE"
          ok "Clé acceptée par Ollama et enregistrée dans .env (lisible par root uniquement)" ;;
        401|403)
          avert "Clé refusée par Ollama (code $CODE_HTTP) : rien n'a été modifié." ;;
        *)
          avert "Vérification impossible (code $CODE_HTTP : réseau, quota ou modèle « $choix ») : rien n'a été modifié." ;;
      esac
    fi
    if [ -n "$ARG_CLE_FICHIER" ] && demander "Effacer le fichier $ARG_CLE_FICHIER (recommandé) ?" o; then
      if command -v shred >/dev/null 2>&1; then shred -u "$ARG_CLE_FICHIER"; else rm -f "$ARG_CLE_FICHIER"; fi
      ok "Fichier de clé effacé"
    fi
  elif [ -z "$cle_existante" ]; then
    avert "Aucune clé Ollama Cloud fournie."
  fi
  # Nouvelle clé refusée mais une clé existait déjà : on vérifie l'ancienne (conservée)
  if [ -n "$nouvelle_cle" ] && [ "$CODE_HTTP" != "200" ] && [ -n "$cle_existante" ]; then
    verifier_cle_cloud "$cle_existante" "$choix"
    [ "$CODE_HTTP" = "200" ] && ok "La clé déjà enregistrée reste valide : elle est conservée."
  fi
  unset nouvelle_cle

  # 4) Bascule vers Ollama Cloud UNIQUEMENT si la clé enregistrée vient d'être acceptée
  if [ "$CODE_HTTP" = "200" ] && [ -n "$(lire_env OLLAMA_API_KEY)" ]; then
    if [ "$OUI" -eq 0 ] && [ -t 0 ] && [ -z "$ARG_MODEL" ]; then
      [ "${#modeles[@]}" -eq 0 ] || { info "Modèles disponibles :"; printf '      %s\n' "${modeles[@]:0:25}"; }
      rep="$(lire_saisie "    Modèle à utiliser [$choix] : ")"
      [ -n "$rep" ] && choix="$rep"
    fi
    cloud_ok=1
    remplacer_env LLM_PROVIDER ollama_cloud
    remplacer_env NEXUS_MODEL "$choix"
    ok "Fournisseur : Ollama Cloud — modèle $choix"
  elif [ "$cloud_inchange" -eq 1 ]; then
    cloud_ok=1
    ok "Ollama Cloud conservé (modèle $(lire_env NEXUS_MODEL)) ; nouvelle vérification au prochain lancement"
  fi
fi

if [ "$cloud_ok" -eq 1 ]; then
  if [ "$REPLI" -eq 1 ]; then
    remplacer_env LLM_FALLBACK ollama
    ok "Repli : IA locale $MODELE_LOCAL si Ollama Cloud ne répond pas (≈ 3,5 Go de RAM réservés)"
  else
    remplacer_env LLM_FALLBACK aucun
    ok "Sans repli local (--sans-repli) : le Mothership n'utilise qu'Ollama Cloud"
  fi
else
  # Pas de cloud validé : on continue en local seul (gratuit, sur le VPS)
  [ "$REPLI" -eq 0 ] && avert "--sans-repli ignoré : sans Ollama Cloud, l'IA locale est indispensable."
  REPLI=1
  remplacer_env LLM_PROVIDER ollama
  remplacer_env LLM_FALLBACK aucun
  if [ -n "$ARG_MODEL" ]; then MODELE_LOCAL="$ARG_MODEL"; fi
  remplacer_env NEXUS_MODEL "$MODELE_LOCAL"
  ok "Fournisseur : IA locale seule — modèle $MODELE_LOCAL"
fi
remplacer_env NEXUS_MODEL_LOCAL "$MODELE_LOCAL"

# Profils docker compose : « local » (IA locale) et/ou « complet »
anciens_profils="$(lire_env COMPOSE_PROFILES)"
profils=()
[ "$COMPLET" -eq 1 ] && profils+=(complet)
[ "$REPLI" -eq 1 ] && profils+=(local)
nouveaux_profils="$(IFS=,; echo "${profils[*]}")"
# Services d'un profil retiré : arrêtés et supprimés (leurs données restent dans ./data)
arreter_profil() {
  local profil="$1"; shift
  if [[ ",$anciens_profils," == *",$profil,"* ]] && [[ ",$nouveaux_profils," != *",$profil,"* ]]; then
    info "Arrêt des services du profil « $profil » (données conservées)…"
    docker compose --profile "$profil" stop "$@" >/dev/null 2>&1 || true
    docker compose --profile "$profil" rm -f "$@" >/dev/null 2>&1 || true
  fi
}
arreter_profil complet postgres redis n8n uptime-kuma ntfy
arreter_profil local ollama
remplacer_env COMPOSE_PROFILES "$nouveaux_profils"
if [ "$COMPLET" -eq 1 ]; then
  remplacer_env COMPOSE_FILE "docker-compose.yml:docker-compose.complet.yml"
else
  retirer_env COMPOSE_FILE
fi
chmod 600 "$ENV_FILE"
ok "Mode $MODE — profils actifs : ${nouveaux_profils:-aucun (caddy + nexus-core seulement)}"
NEXUS_MODEL="$(lire_env NEXUS_MODEL)"
docker compose config -q || erreur "docker-compose.yml ou .env invalide (voir le message ci-dessus)."
ok "Configuration Docker Compose valide"

# =============================================================================
etape "Préparation des dossiers de données ($KIT_DIR/data)"
# =============================================================================
for d in caddy/data caddy/config ollama nexus-core/livrables nexus-bridge postgres redis n8n uptime-kuma ntfy; do
  mkdir -p "$KIT_DIR/data/$d"
done
chmod 700 "$KIT_DIR/data"
# Base de veille : écrite par le collecteur (root, cron sur l'hôte), lue par nexus-core
mkdir -p "$KIT_DIR/data/veille" "$KIT_DIR/veille/journal"
chmod 755 "$KIT_DIR/data/veille"
# Dossier des sauvegardes (backup.sh / restore.sh), lisible par root seulement
mkdir -p "$KIT_DIR/backups"
chmod 700 "$KIT_DIR/backups"
chown -R 1000:1000 "$KIT_DIR/data/n8n"     # n8n tourne avec l'utilisateur « node » (uid 1000)
chmod +x "$KIT_DIR/postgres/initdb/"*.sh 2>/dev/null || true
ok "Données stockées dans $KIT_DIR/data/<service>"

# =============================================================================
etape "Construction et démarrage des services (5 à 15 minutes la première fois)"
# =============================================================================
docker compose build nexus-core nexus-bridge
# nexus-core tourne avec l'utilisateur non root « nexus » (UID/GID 10001)
chown -R 10001:10001 "$KIT_DIR/data/nexus-core"
# nexus-bridge tourne aussi avec l'UID/GID 10001 (base SQLite bridge.db)
chown -R 10001:10001 "$KIT_DIR/data/nexus-bridge"
docker compose up -d
info "Attente que les services soient prêts…"
pret=0
# Santé d'un service (« healthy », « starting », vide si absent)
sante() { docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")" 2>/dev/null || true; }
for _ in $(seq 1 60); do
  if [ "$(sante nexus-core)" = "healthy" ] && { [ "$COMPLET" -eq 0 ] || [ "$(sante n8n)" = "healthy" ]; }; then
    pret=1; break
  fi
  sleep 10
done
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
if [ "$pret" -eq 1 ]; then ok "Services démarrés"; else avert "Certains services ne sont pas encore « healthy » (voir : docker compose logs -f)"; fi

# =============================================================================
etape "IA locale : téléchargement du modèle $MODELE_LOCAL (environ 2 Go)"
# =============================================================================
if [ "$REPLI" -eq 0 ]; then
  ok "Ignoré : pas d'IA locale (--sans-repli)"
elif docker compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qxF "$MODELE_LOCAL"; then
  ok "Modèle $MODELE_LOCAL déjà présent"
elif docker compose exec -T ollama ollama pull "$MODELE_LOCAL"; then
  ok "Modèle $MODELE_LOCAL téléchargé"
else
  avert "Échec du téléchargement. Réessayez : docker compose exec ollama ollama pull $MODELE_LOCAL"
fi

if [ "$COMPLET" -eq 1 ]; then
# =============================================================================
etape "Import des workflows n8n"
# =============================================================================
# Les workflows ont des identifiants fixes : un nouvel import remplace sans dupliquer.
if docker compose exec -T n8n n8n import:workflow --separate --input=/workflows; then
  ok "3 workflows importés (désactivés : à activer dans n8n quand vous le souhaitez)"
else
  avert "Import n8n échoué. Réessayez plus tard : docker compose exec n8n n8n import:workflow --separate --input=/workflows"
fi
fi

# =============================================================================
etape "Alertes N3 sur le téléphone et sauvegarde quotidienne"
# =============================================================================
TOPIC="$(lire_env NTFY_TOPIC)"
if [ "$COMPLET" -eq 1 ]; then
  # Serveur ntfy du kit en accès « deny-all » : on ouvre UNIQUEMENT le sujet secret,
  # en écriture anonyme (nexus-core, n8n) et en lecture pour le compte NTFY_USER.
  NTFY_USER="$(lire_env NTFY_USER)"; NTFY_USER="${NTFY_USER:-proprietaire}"
  ntfy_ok=1
  for _ in $(seq 1 12); do
    docker compose exec -T ntfy ntfy user list >/dev/null 2>&1 && break
    sleep 5
  done
  if docker compose exec -T ntfy ntfy user list 2>/dev/null | grep -q "user $NTFY_USER "; then
    ok "Compte ntfy « $NTFY_USER » déjà présent (mot de passe inchangé)"
  else
    # Mot de passe transmis par l'entrée standard (jamais dans la ligne de commande)
    printf '%s\n' "$(lire_env NTFY_PASSWORD)" \
      | docker compose exec -T ntfy sh -c 'read -r NTFY_PASSWORD; export NTFY_PASSWORD; exec ntfy user add "$1"' sh "$NTFY_USER" >/dev/null \
      || ntfy_ok=0
  fi
  docker compose exec -T ntfy ntfy access "$NTFY_USER" "$TOPIC" read-only >/dev/null 2>&1 || ntfy_ok=0
  docker compose exec -T ntfy ntfy access everyone "$TOPIC" write-only >/dev/null 2>&1 || ntfy_ok=0
  if [ "$ntfy_ok" -eq 1 ]; then
    ok "ntfy : accès refusé par défaut, sujet ouvert en lecture pour « $NTFY_USER » seulement"
  else
    avert "Réglage des droits ntfy incomplet. Relancez « bash install.sh --complet » plus tard."
  fi
else
  ok "Alertes N3 via le service gratuit ntfy.sh (sujet secret : voir « grep NTFY_TOPIC .env »)"
fi

# Sauvegarde quotidienne à 03:30 (fichier /etc/cron.d, facile à retirer)
CRON_FILE="/etc/cron.d/nexus-mothership-sauvegarde"
if [ -f "$CRON_FILE" ]; then
  ok "Sauvegarde quotidienne déjà planifiée ($CRON_FILE)"
elif demander "Planifier une sauvegarde automatique chaque nuit à 3 h 30 ?" n; then
  printf '%s\n' "# Sauvegarde quotidienne du Mini NEXUS MOTHERSHIP (créé par install.sh)" \
    "30 3 * * * root /bin/bash $KIT_DIR/backup.sh >> $KIT_DIR/backups/backup.log 2>&1" > "$CRON_FILE"
  chmod 644 "$CRON_FILE"
  ok "Sauvegarde quotidienne planifiée (7 dernières conservées dans $KIT_DIR/backups)"
else
  info "Sauvegarde automatique non planifiée. Pour l'ajouter : relancez install.sh et répondez « o »."
fi

# Exercice de restauration mensuel sur P2 (1er dimanche du mois, 04:47).
# Attention : en cron, « 47 4 1-7 * 0 » voudrait dire « jours 1 à 7 OU chaque dimanche » ;
# on planifie donc les jours 1 à 7 et la commande ne s'exécute que le dimanche (%u = 7).
CRON_EXERCICE="/etc/cron.d/nexus-exercice-restauration"
if [ ! -f "$KIT_DIR/exercice-restauration.sh" ]; then
  info "Exercice de restauration : script absent, étape ignorée."
elif [ -f "$CRON_EXERCICE" ]; then
  ok "Exercice de restauration mensuel déjà planifié ($CRON_EXERCICE)"
elif demander "Planifier un exercice de restauration chaque mois (1er dimanche, 4 h 47, partition P2) ?" n; then
  if ! mountpoint -q /srv/p2; then
    avert "/srv/p2 n'est pas montée : l'exercice échouera proprement tant que P2 manque (partitions.sh)."
  fi
  printf '%s\n' "# Exercice de restauration mensuel du Mini NEXUS MOTHERSHIP (créé par install.sh)" \
    "47 4 1-7 * * root [ \"\$(date +\%u)\" = 7 ] && /bin/bash $KIT_DIR/exercice-restauration.sh >> $KIT_DIR/backups/exercice-restauration.log 2>&1" > "$CRON_EXERCICE"
  chmod 644 "$CRON_EXERCICE"
  ok "Exercice de restauration planifié (rapport dans backups/exercices, alerte ntfy)"
else
  info "Exercice de restauration non planifié. Pour l'ajouter : relancez install.sh et répondez « o »."
fi

# Tâche planifiée proposée (o/N) : $1 fichier cron.d, $2 question, $3 ligne cron,
# $4 script requis, $5 message de succès. Idempotent : un fichier existant est conservé.
proposer_cron() {
  local fichier="$1" question="$2" ligne="$3" requis="$4" succes="$5"
  if [ ! -e "$requis" ]; then
    info "$(basename "$fichier") : $requis absent, étape ignorée."
  elif [ -f "$fichier" ]; then
    ok "Déjà planifié : $fichier"
  elif demander "$question" n; then
    printf '%s\n' "# Créé par install.sh (Mini NEXUS MOTHERSHIP) — supprimé par uninstall.sh --purge" "$ligne" > "$fichier"
    chmod 644 "$fichier"
    ok "$succes"
  else
    info "Non planifié ($(basename "$fichier")). Pour l'ajouter : relancez install.sh et répondez « o »."
  fi
}

# Banc d'essai hebdomadaire (dimanche 04:17, après la veille cyber de 03:17)
proposer_cron /etc/cron.d/nexus-banc-hebdo \
  "Planifier le banc d'essai chaque dimanche à 4 h 17 (qualité des agents, gratuit) ?" \
  "17 4 * * 0 root /bin/bash $KIT_DIR/banc-essai/hebdo.sh >/dev/null 2>&1" \
  "$KIT_DIR/banc-essai/hebdo.sh" "Banc d'essai hebdomadaire planifié (tableau : banc-essai/tableau.html)"

# Attaque simulée mensuelle (2e dimanche, 05:17) : teste le bouclier anti-injection.
# « 8-14 * * » + test du dimanche dans la commande (en cron, jour du mois ET jour de la
# semaine renseignés = l'un OU l'autre).
proposer_cron /etc/cron.d/nexus-attaque-simulee \
  "Planifier l'attaque simulée du bouclier chaque mois (2e dimanche, 5 h 17) ?" \
  "17 5 8-14 * * root [ \"\$(date +\%u)\" = 7 ] && /usr/bin/python3 $KIT_DIR/securite-ia/attaque_simulee.py --mode complet >> /var/log/nexus-securite-ia.log 2>&1" \
  "$KIT_DIR/securite-ia/attaque_simulee.py" "Attaque simulée mensuelle planifiée (rapports : securite-ia/resultats)"

# Veille toutes les 6 h (commande de veille/README.md ; base dans data/veille, sauvegardée)
if [ -f "$KIT_DIR/veille/collecteur.py" ] && [ ! -f /etc/cron.d/nexus-veille ]; then
  python3 -c 'import yaml' 2>/dev/null \
    || avert "Veille : PyYAML manque sur le VPS (apt-get install -y python3-yaml) avant de la planifier."
  if [ -z "$(lire_env VEILLE_CONTACT)" ] && [ "$OUI" -eq 0 ] && [ -t 0 ]; then
    echo "    La veille s'annonce aux sites lus avec une adresse de contact (page web, pas d'e-mail personnel)."
    rep="$(lire_saisie "    Page de contact [https://github.com/redkards/espacetravail-public] : ")"
    remplacer_env VEILLE_CONTACT "${rep:-https://github.com/redkards/espacetravail-public}"
  fi
fi
CONTACT_VEILLE="$(lire_env VEILLE_CONTACT)"; CONTACT_VEILLE="${CONTACT_VEILLE:-https://github.com/redkards/espacetravail-public}"
proposer_cron /etc/cron.d/nexus-veille \
  "Planifier la veille (sources officielles, toutes les 6 h, gratuit) ?" \
  "17 */6 * * * root cd $KIT_DIR/veille && VEILLE_DB=$KIT_DIR/data/veille/veille.db VEILLE_CONTACT=\"$CONTACT_VEILLE\" /usr/bin/python3 collecteur.py collecter >> $KIT_DIR/veille/journal/cron.log 2>&1" \
  "$KIT_DIR/veille/collecteur.py" "Veille planifiée toutes les 6 h (base : data/veille/veille.db)"

# Veille cyber hebdomadaire (dimanche 03:17) : missions CYBER-FORTRESS veille + audit
CRON_CYBER="/etc/cron.d/nexus-veille-cyber"
SCRIPT_CYBER="$KIT_DIR/automatisations/veille-cyber.sh"
if [ ! -f "$SCRIPT_CYBER" ]; then
  info "Veille cyber : script $SCRIPT_CYBER absent (kit ancien), étape ignorée."
elif [ -f "$CRON_CYBER" ]; then
  ok "Veille cyber hebdomadaire déjà planifiée ($CRON_CYBER)"
elif demander "Planifier la veille cyber automatique chaque dimanche à 3 h 17 ?" n; then
  manquants_cyber=()
  for outil in curl python3 flock; do command -v "$outil" >/dev/null 2>&1 || manquants_cyber+=("$outil"); done
  if [ "${#manquants_cyber[@]}" -gt 0 ]; then
    avert "Veille cyber non planifiée : outils manquants (${manquants_cyber[*]}). apt-get install -y curl python3 util-linux"
  else
    # Sur le VPS lui-même, le nom d'hôte peut pointer vers 127.0.1.1 : on force l'adresse
    # où Caddy écoute (BIND_IP, ou 127.0.0.1 s'il écoute sur toutes les adresses).
    ip_cyber="$BIND_IP"; [ "$ip_cyber" = "0.0.0.0" ] && ip_cyber="127.0.0.1"
    printf '%s\n' "# Veille cyber hebdomadaire du Mini NEXUS MOTHERSHIP (créé par install.sh)" \
      "17 3 * * 0 root NEXUS_RESOLVE=$NEXUS_HOST:443:$ip_cyber /bin/bash $SCRIPT_CYBER >/dev/null 2>&1" > "$CRON_CYBER"
    chmod 644 "$CRON_CYBER"
    ok "Veille cyber planifiée (rapport dans le cockpit, alerte ntfy « Rapport cyber hebdo prêt »)"
  fi
else
  info "Veille cyber non planifiée. Pour l'ajouter : relancez install.sh et répondez « o »."
fi

# =============================================================================
etape "Mission de test"
# =============================================================================
MARQUEUR="$KIT_DIR/data/.mission-test-envoyee"
if [ -f "$MARQUEUR" ]; then
  ok "Mission de test déjà envoyée lors d'une installation précédente"
elif [ "$pret" -eq 1 ]; then
  if docker compose exec -T nexus-core python - <<'PY'
import json, os, urllib.request as u
corps = json.dumps({"titre": "Rédige une checklist de démarrage du Mothership",
                    "consigne": "Rédige une checklist de démarrage du Mothership",
                    "service": "OPS-CORE/projets"}).encode()
req = u.Request("http://127.0.0.1:8000/api/missions", data=corps, method="POST",
                headers={"Content-Type": "application/json", "X-Nexus-Key": os.environ["NEXUS_API_KEY"]})
print(u.urlopen(req, timeout=30).read().decode()[:300])
PY
  then
    touch "$MARQUEUR"; ok "Mission de test envoyée : suivez-la dans le cockpit"
  else
    avert "La mission de test n'a pas pu être envoyée (nexus-core pas prêt ?)."
  fi
else
  avert "Mission de test reportée : nexus-core n'est pas encore prêt. Relancez install.sh plus tard."
fi

# =============================================================================
#  Récapitulatif — AUCUN secret affiché (ni écrit dans install.log)
# =============================================================================
if [ "$SANS_PARTITION" -eq 1 ]; then EMPLACEMENT="test sans partition"; else EMPLACEMENT="partition P1"; fi
cat <<EOF

╔══════════════════════════════════════════════════════════════════════════╗
║        NEXUS MOTHERSHIP — INSTALLATION TERMINÉE
║        mode $MODE · $EMPLACEMENT
╚══════════════════════════════════════════════════════════════════════════╝
  Les secrets ne sont jamais affichés ici. Pour les voir, dans ce dossier :
      cd $KIT_DIR

  Cockpit (décisions)  : https://$NEXUS_HOST/cockpit
      identifiant      : $(lire_env COCKPIT_USER)
      mot de passe     : voir « grep COCKPIT_PASSWORD .env »
  Décideur mobile      : https://$NEXUS_HOST/cockpit/decideur
      code à 6 chiffres: voir « grep COCKPIT_CODE_DECIDEUR .env »
  Santé de l'API       : https://$NEXUS_HOST/api/sante
  Clé API (X-Nexus-Key): voir « grep NEXUS_API_KEY .env »
  IA                   : $(if [ "$cloud_ok" -eq 1 ]; then echo "Ollama Cloud (gratuit) — $NEXUS_MODEL"; else echo "locale — $NEXUS_MODEL"; fi)
  Repli local          : $(if [ "$REPLI" -eq 1 ] && [ "$cloud_ok" -eq 1 ]; then echo "oui ($MODELE_LOCAL)"; else echo "non"; fi)
EOF
if [ "$COMPLET" -eq 1 ]; then
cat <<EOF

  n8n (automatisations): https://$NEXUS_HOST:8443
      1re barrière     : $(lire_env N8N_BASIC_USER) / voir « grep N8N_BASIC_PASSWORD .env »
      puis créez votre compte propriétaire n8n à la première visite
  Uptime Kuma (suivi)  : https://$NEXUS_HOST:8444   (mêmes identifiants que le cockpit)
  Alertes N3 (ntfy)    : appli Android « ntfy » > + > autre serveur https://$NEXUS_HOST:8445
      sujet, compte et mot de passe : voir « grep NTFY_ .env »
EOF
else
cat <<EOF

  Alertes N3 (ntfy)    : appli Android « ntfy » > + > sujet : voir « grep NTFY_TOPIC .env »
      (serveur ntfy.sh, gratuit ; le sujet est secret)
  Version complète (n8n, surveillance, ntfy privé) : bash install.sh --complet
EOF
fi
cat <<EOF

  Passerelle Claude · ChatGPT · Gemini :
      suivi (lecture)  : https://$NEXUS_HOST/bridge   (identifiants du cockpit)
      URL à coller     : bash $KIT_DIR/bridge-connecteurs.sh
      jetons (secrets) : voir « grep BRIDGE_TOKEN .env »

  Sauvegarde           : bash backup.sh   ·   restauration : bash restore.sh
      phrase de chiffrement (à noter hors du VPS) : voir « grep BACKUP_PASSPHRASE .env »
  Journal d'installation (sans secrets) : $LOG_FILE
  Rappel pare-feu Hostinger : ouvrir TCP ${PORTS_PUBLICS[*]}
  (le premier certificat HTTPS peut prendre 1 à 2 minutes)
════════════════════════════════════════════════════════════════════════════
EOF

# Code Décideur : affiché UNE seule fois, directement sur l'écran (/dev/tty), donc
# jamais copié dans install.log. Ensuite : grep COCKPIT_CODE_DECIDEUR .env
MARQUE_CODE="$KIT_DIR/data/.code-decideur-affiche"
if [ ! -f "$MARQUE_CODE" ] && { : > /dev/tty; } 2>/dev/null; then
  {
    printf '\n  \033[1;33mCode Décideur (à noter MAINTENANT, il ne sera plus affiché) : %s\033[0m\n' "$(lire_env COCKPIT_CODE_DECIDEUR)"
    printf '  Il est demandé pour valider une décision à risque élevé sur /cockpit/decideur.\n\n'
  } > /dev/tty
  touch "$MARQUE_CODE"; chmod 600 "$MARQUE_CODE"
fi
