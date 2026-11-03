#!/usr/bin/env bash
# =============================================================================
#  lancer-mission.sh — Lance une mission NEXUS pour un projet du propriétaire
#
#  Utilisation :
#    ./lancer-mission.sh <projet> <numero_modele> [cle=valeur ...]
#    ./lancer-mission.sh <projet> libre titre="..." consigne="..." [service=...] [action=...]
#    ./lancer-mission.sh --liste [projet]        # affiche les modèles disponibles
#
#  Exemples :
#    ./lancer-mission.sh redkards 1 saison=1 episode=4 titre_episode="La Table" \
#        situation="premier tournoi sérieux, il arrive en retard"
#    ./lancer-mission.sh turf libre titre="Plan de la semaine" \
#        consigne="Établis une checklist pour ..." service=OPS-CORE/projets
#
#  Le code <projet> est envoyé dans le champ « projet » de la mission.
#  Codes : paradoxx nexus poker-winners poker-feeling redkards top-solver
#          youtube-poker-winner freelance-ia esct-boxe turf divers
#
#  Variables :
#    NEXUS_API_KEY   (obligatoire) clé API du kit (voir .env)
#    NEXUS_URL       (défaut : https://$NEXUS_HOST, sinon https://srvXXXX.hstgr.cloud)
#    NEXUS_RESOLVE   (facultatif) ex. srvXXXX.hstgr.cloud:443:IP_PUBLIQUE
#                    utile quand le script tourne sur le VPS lui-même
#    MODELES_JSON    (défaut : missions-modeles.json à côté du script)
#    SIMULATION=1    affiche le JSON sans l'envoyer
#    FONCTIONNEMENT  (facultatif) F1 Éclair | F2 Standard | F3 Renforcé | F4 Expert
#                    (défaut : celui du serveur, NEXUS_FONCTIONNEMENT_DEFAUT).
#                    F4 est payant : une décision N3 avec le coût estimé est créée,
#                    la mission ne démarre qu'après validation dans le cockpit.
#    REPLI_F3        (défaut 1) si F4 est indisponible, lancer en F3 ; 0 = refuser
#
#  Aucune action externe : une mission N3 reste « en_attente_n3 » jusqu'à
#  la décision du propriétaire dans le cockpit (/cockpit).
# =============================================================================
set -euo pipefail

DOSSIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEXUS_URL="${NEXUS_URL:-https://${NEXUS_HOST:-srvXXXX.hstgr.cloud}}"
NEXUS_URL="${NEXUS_URL%/}"
MODELES_JSON="${MODELES_JSON:-${DOSSIER}/missions-modeles.json}"
PROJETS_VALIDES=" paradoxx nexus poker-winners poker-feeling redkards top-solver youtube-poker-winner freelance-ia esct-boxe turf divers "

erreur() { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }
FONCTIONNEMENT="${FONCTIONNEMENT:-}"
FONCTIONNEMENT="${FONCTIONNEMENT^^}"
[[ -z "$FONCTIONNEMENT" || "$FONCTIONNEMENT" =~ ^F[1-4]$ ]] \
  || { printf 'ERREUR : FONCTIONNEMENT invalide « %s » (F1, F2, F3 ou F4).\n' "$FONCTIONNEMENT" >&2; exit 1; }
REPLI_F3="${REPLI_F3:-1}"
info()   { printf '%s\n' "$*" >&2; }

usage() {
  sed -n '3,30p' "${BASH_SOURCE[0]}" | sed 's/^#  \{0,1\}//' >&2
  exit 1
}

command -v jq >/dev/null 2>&1 || erreur "jq est introuvable (apt-get install -y jq)."
[[ -r "$MODELES_JSON" ]] || erreur "fichier introuvable : $MODELES_JSON"

# --- Liste des modèles -----------------------------------------------------------
if [[ "${1:-}" == "--liste" ]]; then
  jq -r --arg p "${2:-}" '.modeles[] | select($p == "" or .projet == $p)
    | "\(.projet) \(.numero)  [\(.niveau_attendu)] \(.service)\n    \(.titre)\n    clés : \([.titre, .consigne] | join(" ") | [scan("\\{\\{([a-z_]+)\\}\\}")[0]] | unique | join(", "))"' \
    "$MODELES_JSON"
  exit 0
fi

(( $# >= 2 )) || usage
PROJET="$1"; NUMERO="$2"; shift 2
[[ "$PROJETS_VALIDES" == *" ${PROJET} "* ]] || erreur "code projet inconnu : « ${PROJET} ». Codes valides :${PROJETS_VALIDES}"

# --- Valeurs cle=valeur ---------------------------------------------------------------
VALEURS='{}'
for paire in "$@"; do
  [[ "$paire" == *=* ]] || erreur "argument invalide « ${paire} » (format attendu : cle=valeur)."
  cle="${paire%%=*}"; val="${paire#*=}"
  [[ "$cle" =~ ^[a-z_]+$ ]] || erreur "clé invalide « ${cle} » (minuscules et _ uniquement)."
  VALEURS="$(jq -c --arg k "$cle" --arg v "$val" '. + {($k): $v}' <<<"$VALEURS")"
done

# --- Construction de la mission ------------------------------------------------------------
if [[ "$NUMERO" == "libre" ]]; then
  for k in titre consigne; do
    [[ "$(jq -r --arg k "$k" '.[$k] // ""' <<<"$VALEURS")" != "" ]] || erreur "mission libre : « ${k}=... » est obligatoire."
  done
  CORPS="$(jq -c --arg p "$PROJET" '{projet: $p, titre, consigne}
            + (if .service then {service} else {} end)
            + (if .action then {action} else {} end)' <<<"$VALEURS")"
  ATTENDU="(classé par le GATE)"
else
  [[ "$NUMERO" =~ ^[0-9]+$ ]] || erreur "numéro de modèle invalide : « ${NUMERO} » (entier ou « libre »)."
  MODELE="$(jq -c --arg p "$PROJET" --argjson n "$NUMERO" \
            'first(.modeles[] | select(.projet == $p and .numero == $n)) // empty' "$MODELES_JSON")"
  if [[ -z "$MODELE" ]]; then
    erreur "aucun modèle n°${NUMERO} pour « ${PROJET} ». Voir : $0 --liste ${PROJET} (ou utilisez « libre »)."
  fi
  # Remplacement des {{cle}} dans le titre et la consigne (texte littéral, sans interprétation).
  CORPS="$(jq -c --argjson v "$VALEURS" '
      def remplir: reduce ($v | to_entries[]) as $e (.; gsub("\\{\\{" + $e.key + "\\}\\}"; $e.value; "g"));
      {projet, titre: (.titre | remplir), consigne: (.consigne | remplir)}
      + (if .service then {service} else {} end)
      + (if .action then {action} else {} end)
      + (if .montant_eur then {montant_eur} else {} end)' <<<"$MODELE")"
  # gsub interprète « \ » et « $ » dans la valeur de remplacement : on vérifie le résultat.
  MANQUANTS="$(jq -r '[.titre, .consigne] | join(" ") | [scan("\\{\\{([a-z_]+)\\}\\}")[0]] | unique | join(", ")' <<<"$CORPS")"
  [[ -z "$MANQUANTS" ]] || erreur "valeurs manquantes : ${MANQUANTS} (ajoutez cle=valeur)."
  ATTENDU="$(jq -r '.niveau_attendu' <<<"$MODELE")"
fi

# Niveau de fonctionnement (facultatif) et repli F3 pour F4.
if [[ -n "$FONCTIONNEMENT" ]]; then
  CORPS="$(jq -c --arg f "$FONCTIONNEMENT" --argjson r "$([[ "$REPLI_F3" == "0" ]] && echo false || echo true)" \
            '. + {fonctionnement: $f, repli_f3: $r}' <<<"$CORPS")"
fi

info "== NEXUS — mission projet « ${PROJET} » =="
info "Titre : $(jq -r '.titre' <<<"$CORPS")"
info "Service : $(jq -r '.service // "(choisi par PRIME)"' <<<"$CORPS") · niveau attendu : ${ATTENDU}"
info "Fonctionnement : ${FONCTIONNEMENT:-défaut du serveur}"

if [[ "${SIMULATION:-0}" == "1" ]]; then
  info "SIMULATION : rien n'est envoyé. Corps JSON :"
  jq . <<<"$CORPS"
  exit 0
fi

command -v curl >/dev/null 2>&1 || erreur "curl est introuvable (apt-get install -y curl)."
[[ -n "${NEXUS_API_KEY:-}" ]] || erreur "NEXUS_API_KEY n'est pas définie. Exemple : export NEXUS_API_KEY=\$(grep '^NEXUS_API_KEY=' /srv/p1/nexus-mothership/.env | cut -d= -f2-)"

TMP_REPONSE="$(mktemp)"
# La clé passe par un fichier temporaire (droits 600) lu par « curl -H @fichier » :
# elle n'apparaît jamais dans la liste des processus (ps).
TMP_ENTETE="$(mktemp)"
trap 'rm -f "$TMP_REPONSE" "$TMP_ENTETE"' EXIT
chmod 600 "$TMP_ENTETE"
printf 'X-Nexus-Key: %s\n' "$NEXUS_API_KEY" > "$TMP_ENTETE"

ARGS=(-sS -o "$TMP_REPONSE" -w '%{http_code}' --max-time 30 -X POST
      -H "@${TMP_ENTETE}" -H 'Accept: application/json'
      -H 'Content-Type: application/json' --data-binary "$CORPS")
if [[ -n "${NEXUS_RESOLVE:-}" ]]; then
  ARGS+=(--resolve "$NEXUS_RESOLVE")
fi
# En cas d'échec réseau, curl écrit déjà « 000 » via -w : on ne l'ajoute pas une 2e fois.
code="$(curl "${ARGS[@]}" "${NEXUS_URL}/api/missions" 2>/dev/null)" || true
[[ "$code" =~ ^[0-9]{3}$ ]] || code="000"

case "$code" in
  200|202)
    mid="$(jq -r '.id // "?"' "$TMP_REPONSE")"
    statut="$(jq -r '.statut // "recue"' "$TMP_REPONSE")"
    info "Mission n°${mid} envoyée (statut : ${statut}, fonctionnement : $(jq -r '.fonctionnement // "?"' "$TMP_REPONSE"))."
    msg="$(jq -r '.message // empty' "$TMP_REPONSE")"
    [[ -z "$msg" ]] || info "Note : ${msg}"
    info "Suivi : ${NEXUS_URL}/cockpit  ·  API : GET ${NEXUS_URL}/api/missions/${mid}"
    ;;
  000) erreur "serveur injoignable (${NEXUS_URL}). Sur le VPS, essayez NEXUS_RESOLVE=srvXXXX.hstgr.cloud:443:IP_PUBLIQUE." ;;
  401|403) erreur "clé API refusée (HTTP ${code}) : vérifiez NEXUS_API_KEY." ;;
  *)
    msg="$(jq -r '.detail // .message // empty' "$TMP_REPONSE" 2>/dev/null | head -c 300 || true)"
    erreur "envoi refusé (HTTP ${code}) ${msg}"
    ;;
esac
