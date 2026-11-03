#!/usr/bin/env bash
# =============================================================================
#  veille-cyber.sh — Veille et audit cyber hebdomadaires du Mini NEXUS MOTHERSHIP
#
#  1. Collecte LOCALE et FILTRÉE de la configuration du kit (aucun secret) :
#     système, versions d'images, services, options compose (sans variables
#     d'environnement), en-têtes de sécurité Caddy, dépendances Python.
#  2. Lance via l'API deux missions sur le projet « nexus », niveau F3 :
#     CYBER-FORTRESS/veille (pile du kit) et CYBER-FORTRESS/audit (configuration).
#  3. Attend leur fin, puis envoie une notification ntfy générique
#     « Rapport cyber hebdo prêt » avec un lien vers le cockpit.
#
#  Idempotent : une seule paire de missions par semaine ISO (fichier d'état) ;
#  une exécution interrompue reprend l'attente au lancement suivant.
#  Sécurité : la clé API est lue dans .env et passée à curl par un fichier
#  temporaire (jamais en ligne de commande) ; le journal ne contient aucun secret.
#
#  Utilisation :
#    ./veille-cyber.sh             # exécution complète
#    ./veille-cyber.sh --collecte  # affiche seulement la collecte filtrée
#
#  Variables facultatives :
#    KIT_DIR        dossier du kit (défaut : dossier parent de ce script)
#    ENV_FILE       fichier .env (défaut : $KIT_DIR/.env)
#    NEXUS_URL      URL de l'API (défaut : https://$NEXUS_HOST)
#    NEXUS_RESOLVE  ex. hote:443:<IP> (script lancé sur le VPS lui-même)
#    NTFY_URL_HOTE  URL ntfy joignable depuis l'hôte (défaut : https://$NEXUS_HOST:8445
#                   si NTFY_URL désigne le conteneur interne « http://ntfy »)
#    INTERVALLE_S   (défaut 20) · DELAI_MAX_S (défaut 2700 = 45 min)
#    DOCKER_BIN     (défaut docker) · ETAT_DIR (défaut : dossier de ce script)
#
#  Codes de sortie : 0 terminé · 1 configuration · 2 API · 3 délai dépassé
#                    (reprise au prochain lancement) · 4 déjà en cours
#
#  Cron proposé (dimanche 03:17) :
#    17 3 * * 0 root /srv/p1/nexus-mothership/automatisations/veille-cyber.sh >/dev/null 2>&1
# =============================================================================
set -euo pipefail
umask 077

DOSSIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_DIR="${KIT_DIR:-$(dirname "$DOSSIER")}"
ENV_FILE="${ENV_FILE:-${KIT_DIR}/.env}"
ETAT_DIR="${ETAT_DIR:-$DOSSIER}"
JOURNAL="${ETAT_DIR}/veille-cyber.log"
ETAT="${ETAT_DIR}/.veille-cyber.etat"
VERROU="${ETAT_DIR}/.veille-cyber.verrou"
INTERVALLE_S="${INTERVALLE_S:-20}"
DELAI_MAX_S="${DELAI_MAX_S:-2700}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
STATUTS_FINAUX=" terminee en_attente_n3 a_reformuler echouee plafond_atteint refusee suspendue validee "

journal() { printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$JOURNAL"; printf '%s\n' "$*" >&2; }
echec()   { journal "ERREUR : $2"; exit "$1"; }

# Lit une variable dans .env SANS l'exécuter (pas de « source »).
lire_env() {
  [[ -r "$ENV_FILE" ]] || return 0
  { grep -E "^$1=" "$ENV_FILE" || true; } | tail -n1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]$//"
}

# --- Collecte filtrée -------------------------------------------------------------------
filtrer_secrets() {
  # Supprime toute ligne qui ressemble à un secret ; tronque les lignes longues.
  grep -viE '(password|passwd|secret|token|api[_-]?key|_key=|hash|private|bearer|authorization|cookie|\$2[aby]\$|sk-[a-z0-9]|ghp_|AKIA)' \
    | grep -vE '[A-Za-z0-9+/=_-]{32,}' | cut -c1-200 || true
}

options_compose() {
  # Services et options utiles à l'audit ; blocs environment:/env_file: ignorés en entier.
  awk '
    BEGIN { saut = -1; ports = -1 }
    function indent(l) { match(l, /^ */); return RLENGTH }
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    {
      i = indent($0)
      if (saut >= 0 && i > saut) next
      saut = -1
      if ($0 ~ /^[[:space:]]*(environment|env_file|secrets|labels|command|entrypoint|healthcheck)[[:space:]]*:/) { saut = i; next }
      if (i == 2 && $0 ~ /^  [A-Za-z0-9_.-]+:[[:space:]]*$/) { print "service " $1; next }
      if ($0 ~ /^[[:space:]]*(image|mem_limit|cpus|read_only|user|privileged|network_mode|restart|security_opt|cap_drop|cap_add|pids_limit)[[:space:]]*:/) { sub(/^ +/, "  "); print; next }
      if ($0 ~ /^[[:space:]]*ports[[:space:]]*:/) { print "  ports:"; ports = i; next }
      if (ports >= 0 && i > ports && $0 ~ /^[[:space:]]*- /) { sub(/^ +/, "    "); print; next }
      ports = -1
    }' "$1"
}

entetes_caddy() {
  grep -hE '^[[:space:]]*(header|Strict-Transport-Security|X-Frame-Options|X-Content-Type-Options|Content-Security-Policy|Referrer-Policy|Permissions-Policy|-Server|tls|encode)' "$1" \
    | sed 's/^[[:space:]]*/  /' || true
  grep -qiE 'basic_?auth' "$1" && printf '  basic_auth : présent (empreinte non transmise)\n' || true
}

collecter() {
  printf '== Système ==\n'
  [[ -r /etc/os-release ]] && grep -E '^PRETTY_NAME=' /etc/os-release | cut -d= -f2- | tr -d '"' | sed 's/^/  /'
  printf '  noyau : %s\n' "$(uname -r)"
  if command -v "$DOCKER_BIN" >/dev/null 2>&1 && "$DOCKER_BIN" info >/dev/null 2>&1; then
    printf '  docker : %s\n' "$("$DOCKER_BIN" version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
    printf '  compose : %s\n' "$("$DOCKER_BIN" compose version --short 2>/dev/null || echo '?')"
    printf '== Conteneurs en service ==\n'
    "$DOCKER_BIN" ps --format '  {{.Names}} {{.Image}} {{.Status}}' 2>/dev/null || true
  else
    printf '  docker : indisponible pour ce script (collecte statique seulement)\n'
  fi
  for f in "$KIT_DIR"/docker-compose*.yml; do
    [[ -r "$f" ]] || continue
    printf '== Options compose (%s, sans variables d'"'"'environnement) ==\n' "$(basename "$f")"
    options_compose "$f"
  done
  for f in "$KIT_DIR"/Caddyfile*; do
    [[ -r "$f" ]] || continue
    printf '== En-têtes et TLS Caddy (%s) ==\n' "$(basename "$f")"
    entetes_caddy "$f"
  done
  for f in "$KIT_DIR"/nexus-core/requirements.txt "$KIT_DIR"/nexus-bridge/requirements.txt; do
    [[ -r "$f" ]] || continue
    printf '== Dépendances Python (%s) ==\n' "${f#"$KIT_DIR"/}"
    grep -E '^[][A-Za-z0-9_.-]+==' "$f" | sed 's/^/  /' || true
  done
}

if [[ "${1:-}" == "--collecte" ]]; then
  collecter | filtrer_secrets
  exit 0
fi

# --- Exécution complète -------------------------------------------------------------------
mkdir -p "$ETAT_DIR"
command -v curl >/dev/null 2>&1 || { echo "curl est introuvable." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 est introuvable." >&2; exit 1; }

exec 9>"$VERROU"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
  journal "Une exécution est déjà en cours : abandon."; exit 4
fi

NEXUS_HOST="${NEXUS_HOST:-$(lire_env NEXUS_HOST)}"
NEXUS_URL="${NEXUS_URL:-${NEXUS_HOST:+https://${NEXUS_HOST}}}"
NEXUS_URL="${NEXUS_URL%/}"
[[ -n "$NEXUS_URL" ]] || echec 1 "NEXUS_HOST introuvable (ENV_FILE=${ENV_FILE}) et NEXUS_URL non défini."
CLE="${NEXUS_API_KEY:-$(lire_env NEXUS_API_KEY)}"
[[ -n "$CLE" ]] || echec 1 "NEXUS_API_KEY introuvable dans ${ENV_FILE}."

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# En-tête de la clé dans un fichier temporaire (mode 600) : jamais visible dans « ps ».
printf 'X-Nexus-Key: %s\n' "$CLE" >"$TMP/entetes"
unset CLE NEXUS_API_KEY

api() {  # api <méthode> <chemin> [fichier_corps] → corps dans $TMP/reponse, code HTTP sur stdout
  local args=(-sS -o "$TMP/reponse" -w '%{http_code}' --max-time 30 -X "$1" -H @"$TMP/entetes"
              -H 'Accept: application/json')
  [[ -n "${3:-}" ]] && args+=(-H 'Content-Type: application/json' --data-binary @"$3")
  [[ -n "${NEXUS_RESOLVE:-}" ]] && args+=(--resolve "$NEXUS_RESOLVE")
  curl "${args[@]}" "${NEXUS_URL}$2" 2>/dev/null || true
}
champ() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2], ""))' "$TMP/reponse" "$1" 2>/dev/null || true; }

SEMAINE="$(date +%G-W%V)"
VEILLE_ID=""; AUDIT_ID=""; NOTIFIE=0
if [[ -r "$ETAT" ]] && grep -q "^semaine=${SEMAINE}$" "$ETAT"; then
  VEILLE_ID="$(grep '^veille=' "$ETAT" | cut -d= -f2)"
  AUDIT_ID="$(grep '^audit=' "$ETAT" | cut -d= -f2)"
  NOTIFIE="$(grep '^notifie=' "$ETAT" | cut -d= -f2)"
fi
ecrire_etat() { printf 'semaine=%s\nveille=%s\naudit=%s\nnotifie=%s\n' "$SEMAINE" "$VEILLE_ID" "$AUDIT_ID" "$NOTIFIE" >"$ETAT"; }

if [[ "$NOTIFIE" == "1" ]]; then
  journal "Semaine ${SEMAINE} déjà traitée (missions ${VEILLE_ID} et ${AUDIT_ID}) : rien à faire."; exit 0
fi

code="$(api GET /api/sante)"
[[ "$code" == "200" ]] || echec 2 "API injoignable (${NEXUS_URL}/api/sante → HTTP ${code:-000})."

COLLECTE="$(collecter | filtrer_secrets)"
printf '%s\n' "$COLLECTE" >"$TMP/collecte"

creer_mission() {  # creer_mission <service> <titre> <consigne> → id
  python3 - "$1" "$2" "$3" "$TMP/collecte" >"$TMP/corps.json" <<'PY'
import json, sys
service, titre, consigne, collecte = sys.argv[1], sys.argv[2], sys.argv[3], open(sys.argv[4], encoding="utf-8").read()
print(json.dumps({"titre": titre, "service": service, "projet": "nexus", "fonctionnement": "F3",
                  "consigne": consigne + "\n\nÉléments collectés automatiquement (filtrés, sans secret) :\n" + collecte},
                 ensure_ascii=False))
PY
  local c
  c="$(api POST /api/missions "$TMP/corps.json")"
  [[ "$c" == "200" || "$c" == "202" ]] || echec 2 "création de la mission ${1} refusée (HTTP ${c:-000})."
  champ id
}

if [[ -z "$VEILLE_ID" ]]; then
  VEILLE_ID="$(creer_mission CYBER-FORTRESS/veille "Veille cyber hebdomadaire — ${SEMAINE}" \
    "Établis la note de veille vulnérabilités pour la pile du kit (Ubuntu, Docker, Caddy, Ollama, n8n, Python/FastAPI, SQLite) à partir des versions ci-dessous. Pas d'accès web : n'invente aucune CVE ; marque « référence à vérifier » tout identifiant non fourni. Priorise et liste les mises à jour à planifier.")"
  ecrire_etat; journal "Mission veille créée : n°${VEILLE_ID} (${SEMAINE}, F3)."
fi
if [[ -z "$AUDIT_ID" ]]; then
  AUDIT_ID="$(creer_mission CYBER-FORTRESS/audit "Audit cyber hebdomadaire de la configuration — ${SEMAINE}" \
    "Réalise l'audit de sécurité de la configuration du kit décrite ci-dessous (services, images, ports, limites, options compose, en-têtes Caddy). Pour chaque constat : gravité, preuve tirée des éléments, correction proposée. Posture défensive ; aucune action n'est exécutée.")"
  ecrire_etat; journal "Mission audit créée : n°${AUDIT_ID} (${SEMAINE}, F3)."
fi

attendre() {  # attendre <id> → statut final
  local debut statut c
  debut=$(date +%s)
  while :; do
    c="$(api GET "/api/missions/$1")"
    if [[ "$c" == "200" ]]; then
      statut="$(champ statut)"
      [[ "$STATUTS_FINAUX" == *" ${statut} "* ]] && { printf '%s' "$statut"; return 0; }
    fi
    (( $(date +%s) - debut >= DELAI_MAX_S )) && return 3
    sleep "$INTERVALLE_S"
  done
}

STATUT_VEILLE="$(attendre "$VEILLE_ID")" || echec 3 "délai dépassé pour la mission ${VEILLE_ID} (reprise au prochain lancement)."
STATUT_AUDIT="$(attendre "$AUDIT_ID")" || echec 3 "délai dépassé pour la mission ${AUDIT_ID} (reprise au prochain lancement)."
journal "Missions terminées : veille n°${VEILLE_ID} → ${STATUT_VEILLE} ; audit n°${AUDIT_ID} → ${STATUT_AUDIT}."

# --- Notification ntfy générique -----------------------------------------------------------
NTFY_TOPIC="${NTFY_TOPIC:-$(lire_env NTFY_TOPIC)}"
NTFY_URL_HOTE="${NTFY_URL_HOTE:-}"
if [[ -z "$NTFY_URL_HOTE" ]]; then
  NTFY_URL_HOTE="$(lire_env NTFY_URL)"
  [[ -z "$NTFY_URL_HOTE" || "$NTFY_URL_HOTE" == http://ntfy* ]] && NTFY_URL_HOTE="${NEXUS_HOST:+https://${NEXUS_HOST}:8445}"
fi
if [[ -n "$NTFY_TOPIC" && -n "$NTFY_URL_HOTE" ]]; then
  lien="${NEXUS_HOST:+https://${NEXUS_HOST}/cockpit}"
  args=(-sS -o /dev/null -w '%{http_code}' --max-time 15 -H 'Title: NEXUS : rapport cyber hebdo' -H 'Tags: shield'
        --data-binary 'Rapport cyber hebdo pret.')
  [[ -n "$lien" ]] && args+=(-H "Click: ${lien}")
  c="$(curl "${args[@]}" "${NTFY_URL_HOTE%/}/${NTFY_TOPIC}" 2>/dev/null || true)"
  if [[ "$c" == "200" ]]; then journal "Notification ntfy envoyée."; else journal "Notification ntfy impossible (HTTP ${c:-000})."; fi
else
  journal "ntfy non configuré : aucune notification."
fi
NOTIFIE=1; ecrire_etat
exit 0
