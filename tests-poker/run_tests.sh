#!/usr/bin/env bash
# Les apostrophes inverses des printf sont du Markdown, pas des substitutions.
# shellcheck disable=SC2016
# =============================================================================
#  run_tests.sh — Jeu de missions de test « poker » pour le Mini NEXUS MOTHERSHIP
#
#  Lit missions.json, envoie chaque mission à l'API nexus-core
#  (POST /api/missions), attend la fin du traitement (GET /api/missions/{id}),
#  puis affiche un tableau récapitulatif et écrit le détail dans
#  resultats-<date>.md (livrables inclus).
#
#  Utilisation :
#    export NEXUS_API_KEY=...                 # obligatoire (voir .env du kit)
#    ./run_tests.sh                           # toutes les missions
#    ./run_tests.sh PK-01 PK-09               # seulement certaines missions
#
#  Variables facultatives :
#    NEXUS_URL        (défaut : https://$NEXUS_HOST, sinon https://srvXXXX.hstgr.cloud)
#    NEXUS_RESOLVE    (facultatif) ex. srvXXXX.hstgr.cloud:443:IP_PUBLIQUE (sur le VPS lui-même)
#    INTERVALLE_S     (défaut : 15)   délai entre deux interrogations
#    DELAI_MAX_S      (défaut : 900)  délai maximal par mission (15 min)
#    MISSIONS_JSON    (défaut : missions.json à côté du script)
#    FONCTIONNEMENT   (facultatif) F1 | F2 | F3 | F4 : niveau imposé à toutes les
#                     missions (sinon champ « fonctionnement » de la mission dans
#                     missions.json, sinon défaut du serveur). F4 crée une décision
#                     N3 de lancement : la mission reste « en_attente_n3 ».
#
#  Aucune action externe n'est déclenchée : les missions N3 restent
#  « en_attente_n3 » jusqu'à une décision humaine dans le cockpit.
# =============================================================================
set -euo pipefail

DOSSIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEXUS_URL="${NEXUS_URL:-https://${NEXUS_HOST:-srvXXXX.hstgr.cloud}}"
NEXUS_URL="${NEXUS_URL%/}"
INTERVALLE_S="${INTERVALLE_S:-15}"
DELAI_MAX_S="${DELAI_MAX_S:-900}"
MISSIONS_JSON="${MISSIONS_JSON:-${DOSSIER}/missions.json}"
FONCTIONNEMENT="${FONCTIONNEMENT:-}"
FONCTIONNEMENT="${FONCTIONNEMENT^^}"
if [[ -n "$FONCTIONNEMENT" && ! "$FONCTIONNEMENT" =~ ^F[1-4]$ ]]; then
  printf 'ERREUR : FONCTIONNEMENT invalide « %s » (F1, F2, F3 ou F4).\n' "$FONCTIONNEMENT" >&2; exit 1
fi
HORODATAGE="$(date +%Y-%m-%d_%H%M%S)"
RAPPORT="${DOSSIER}/resultats-${HORODATAGE}.md"

# Statuts considérés comme finaux pour un test (la mission n'évoluera plus seule).
# « en_attente_place » (file d'attente) n'est PAS final ; « a_reformuler » l'est (anomalie).
STATUTS_FINAUX=" en_attente_n3 validee refusee revision terminee echouee suspendue plafond_atteint a_reformuler "

erreur() { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }
info()   { printf '%s\n' "$*" >&2; }

# --- Vérifications préalables -------------------------------------------------
command -v jq   >/dev/null 2>&1 || erreur "jq est introuvable (apt-get install -y jq)."
command -v curl >/dev/null 2>&1 || erreur "curl est introuvable (apt-get install -y curl)."
[[ -n "${NEXUS_API_KEY:-}" ]] || erreur "NEXUS_API_KEY n'est pas définie. Exemple : export NEXUS_API_KEY=\$(grep '^NEXUS_API_KEY=' /srv/p1/nexus-mothership/.env | cut -d= -f2-)"
[[ -r "$MISSIONS_JSON" ]] || erreur "fichier introuvable : $MISSIONS_JSON"
jq -e '.missions | type == "array" and length > 0' "$MISSIONS_JSON" >/dev/null \
  || erreur "$MISSIONS_JSON ne contient pas de tableau « missions » valide."
[[ "$INTERVALLE_S" =~ ^[0-9]+$ && "$INTERVALLE_S" -gt 0 ]] || erreur "INTERVALLE_S doit être un entier positif."
[[ "$DELAI_MAX_S" =~ ^[0-9]+$ && "$DELAI_MAX_S" -gt 0 ]] || erreur "DELAI_MAX_S doit être un entier positif."

# Fichier temporaire pour les réponses HTTP, supprimé à la sortie.
TMP_REPONSE="$(mktemp)"
# La clé passe par un fichier temporaire (droits 600) lu par « curl -H @fichier » :
# elle n'apparaît jamais dans la liste des processus (ps).
TMP_ENTETE="$(mktemp)"
trap 'rm -f "$TMP_REPONSE" "$TMP_ENTETE"' EXIT
chmod 600 "$TMP_ENTETE"
printf 'X-Nexus-Key: %s\n' "$NEXUS_API_KEY" > "$TMP_ENTETE"

# Appel HTTP : api <méthode> <chemin> [corps_json]
# Écrit le corps de la réponse dans $TMP_REPONSE et renvoie le code HTTP sur stdout
# (« 000 » si le serveur est injoignable).
api() {
  local methode="$1" chemin="$2" corps="${3:-}"
  local args=(-sS -o "$TMP_REPONSE" -w '%{http_code}' --max-time 30
              -X "$methode" -H "@${TMP_ENTETE}" -H 'Accept: application/json')
  # Sur le VPS lui-même, le nom d'hôte pointe vers 127.0.1.1 : NEXUS_RESOLVE="hote:443:IP"
  # force l'adresse publique (ex. srvXXXX.hstgr.cloud:443:IP_PUBLIQUE).
  if [[ -n "${NEXUS_RESOLVE:-}" ]]; then
    args+=(--resolve "$NEXUS_RESOLVE")
  fi
  if [[ -n "$corps" ]]; then
    args+=(-H 'Content-Type: application/json' --data-binary "$corps")
  fi
  curl "${args[@]}" "${NEXUS_URL}${chemin}" 2>/dev/null || printf '000'
}

# Compare deux niveaux N0..N3 : affiche « = », « + » (plus élevé) ou « - » (plus bas).
comparer_niveaux() {
  local obtenu="${1#N}" attendu="${2#N}"
  if ! [[ "$obtenu" =~ ^[0-3]$ && "$attendu" =~ ^[0-3]$ ]]; then printf '?'; return; fi
  if (( obtenu == attendu )); then printf '='; elif (( obtenu > attendu )); then printf '+'; else printf -- '-'; fi
}

duree_lisible() { printf '%dm%02ds' "$(( $1 / 60 ))" "$(( $1 % 60 ))"; }

# --- Contrôle de l'API ----------------------------------------------------------
info "== NEXUS MOTHERSHIP — tests poker =="
info "API : ${NEXUS_URL}/api  ·  missions : ${MISSIONS_JSON}"
code="$(api GET /api/sante)"
[[ "$code" == "200" ]] || erreur "l'API ne répond pas correctement (/api/sante → HTTP ${code}). Vérifiez NEXUS_URL et que les conteneurs tournent (docker compose ps)."
code="$(api GET '/api/missions?limit=1')"
case "$code" in
  200) ;;
  401|403) erreur "clé API refusée (HTTP ${code}) : vérifiez NEXUS_API_KEY." ;;
  *) erreur "lecture des missions impossible (HTTP ${code})." ;;
esac
code="$(api GET /api/sante)"
if [[ "$(jq -r '.arret_urgence // false' "$TMP_REPONSE")" == "true" ]]; then
  info "ATTENTION : l'arrêt d'urgence est actif, les missions seront « suspendue »."
fi

# Sélection des missions (arguments = liste d'identifiants).
if (( $# > 0 )); then
  FILTRE="$(printf '%s\n' "$@" | jq -R . | jq -s .)"
else
  FILTRE='null'
fi
mapfile -t IDS < <(jq -r --argjson f "$FILTRE" \
  '.missions[] | select($f == null or (.id as $i | $f | index($i))) | .id' "$MISSIONS_JSON")
(( ${#IDS[@]} > 0 )) || erreur "aucune mission ne correspond à : $*"

# --- En-tête du rapport ------------------------------------------------------------
{
  printf '# Résultats des tests NEXUS — %s\n\n' "$HORODATAGE"
  printf -- '- API : `%s`\n- Fichier de missions : `%s`\n- Missions lancées : %d\n' \
    "$NEXUS_URL" "$(basename "$MISSIONS_JSON")" "${#IDS[@]}"
  printf -- '- Interrogation toutes les %d s, délai max %d s par mission\n' "$INTERVALLE_S" "$DELAI_MAX_S"
  printf -- '- Fonctionnement imposé : %s\n\n' "${FONCTIONNEMENT:-aucun (missions.json ou défaut du serveur)}"
  printf 'Légende niveau : `=` conforme · `+` plus élevé que prévu (prudence, acceptable) · `-` plus bas que prévu (**anomalie GATE**).\n\n'
} > "$RAPPORT"

LIGNES=()          # lignes du tableau récapitulatif
DETAILS=""         # sections détaillées (ajoutées après le tableau)
NB_OK=0; NB_ANOMALIES=0

for ID in "${IDS[@]}"; do
  mission="$(jq -c --arg id "$ID" '.missions[] | select(.id == $id)' "$MISSIONS_JSON")"
  titre="$(jq -r '.titre' <<<"$mission")"
  attendu="$(jq -r '.niveau_attendu' <<<"$mission")"
  # Corps de la requête : uniquement les champs acceptés par l'API.
  corps="$(jq -c '{titre, consigne}
                  + (if .service then {service} else {} end)
                  + (if .montant_eur then {montant_eur} else {} end)
                  + (if .action then {action} else {} end)
                  + (if .fonctionnement then {fonctionnement} else {} end)' <<<"$mission")"
  if [[ -n "$FONCTIONNEMENT" ]]; then
    corps="$(jq -c --arg f "$FONCTIONNEMENT" '. + {fonctionnement: $f}' <<<"$corps")"
  fi

  info ""
  info "[$ID] ${titre}"
  debut=$(date +%s)
  code="$(api POST /api/missions "$corps")"
  if [[ "$code" != "202" && "$code" != "200" ]]; then
    msg="$(jq -r '.detail // .message // empty' "$TMP_REPONSE" 2>/dev/null | head -c 300 || true)"
    info "  envoi refusé (HTTP ${code}) ${msg}"
    LIGNES+=("$(printf '%s\t-\terreur_envoi\t-\t%s\t?\t0m00s\t-' "$ID" "$attendu")")
    DETAILS+=$'\n'"## ${ID} — ${titre}"$'\n\n'"Envoi refusé : HTTP ${code}. ${msg}"$'\n'
    NB_ANOMALIES=$((NB_ANOMALIES + 1))
    continue
  fi
  mid="$(jq -r '.id' "$TMP_REPONSE")"
  info "  mission n°${mid} reçue, attente du traitement…"

  statut="recue"; detail='{}'
  while :; do
    ecoule=$(( $(date +%s) - debut ))
    if (( ecoule >= DELAI_MAX_S )); then
      statut="delai_depasse"; info "  délai de ${DELAI_MAX_S} s dépassé."
      break
    fi
    sleep "$INTERVALLE_S"
    code="$(api GET "/api/missions/${mid}")"
    if [[ "$code" != "200" ]]; then
      info "  lecture impossible (HTTP ${code}), nouvel essai…"
      continue
    fi
    detail="$(cat "$TMP_REPONSE")"
    statut="$(jq -r '.statut' <<<"$detail")"
    info "  $(duree_lisible $(( $(date +%s) - debut ))) · statut : ${statut}"
    [[ "$STATUTS_FINAUX" == *" ${statut} "* ]] && break
  done

  duree=$(( $(date +%s) - debut ))
  niveau="$(jq -r '.niveau // "-"' <<<"$detail")"
  service="$(jq -r '.service // "-"' <<<"$detail")"
  # Une boucle CHECKER = une étape « checker » portant un verdict ok/refus
  # (l'appel brut au LLM est aussi enregistré, sans verdict : il n'est pas compté).
  boucles="$(jq '[.etapes[]? | select(.role == "checker" and (.verdict == "ok" or .verdict == "refus"))] | length' <<<"$detail")"
  refus="$(jq '[.etapes[]? | select(.role == "checker" and .verdict == "refus")] | length' <<<"$detail")"
  cmp="$(comparer_niveaux "$niveau" "$attendu")"

  if [[ "$cmp" == "-" || "$statut" =~ ^(echouee|suspendue|delai_depasse|plafond_atteint|a_reformuler)$ ]]; then
    NB_ANOMALIES=$((NB_ANOMALIES + 1))
  else
    NB_OK=$((NB_OK + 1))
  fi
  LIGNES+=("$(printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' \
    "$ID" "$mid" "$statut" "$niveau" "$attendu" "$cmp" "$(duree_lisible "$duree")" "${boucles} (${refus} refus)")")

  # Section détaillée du rapport.
  DETAILS+=$'\n'"## ${ID} — ${titre}"$'\n\n'
  DETAILS+="- Mission API n°${mid} · service : \`${service}\` · statut : **${statut}**"$'\n'
  DETAILS+="- Niveau obtenu : **${niveau}** · attendu : ${attendu} · écart : \`${cmp}\`"$'\n'
  DETAILS+="- Durée : $(duree_lisible "$duree") · verdicts CHECKER : ${boucles} (dont ${refus} refus) · tokens : $(jq -r '.tokens // 0' <<<"$detail")"$'\n'
  DETAILS+="- Fonctionnement : demandé $(jq -r '.fonctionnement_demande // "-"' <<<"$detail") · appliqué **$(jq -r '.fonctionnement // "-"' <<<"$detail")** · tokens entrée/sortie : $(jq -r '"\(.tokens_entree // 0) / \(.tokens_sortie // 0)"' <<<"$detail") · coût : $(jq -r '.cout_eur // 0' <<<"$detail") € · corrections : $(jq -r '.revisions // 0' <<<"$detail")"$'\n'
  raison="$(jq -r '.fonctionnement_raison // empty' <<<"$detail")"
  [[ -n "$raison" ]] && DETAILS+="- Relèvement du niveau : ${raison}"$'\n'
  msg="$(jq -r '.message // empty' <<<"$detail")"
  [[ -n "$msg" ]] && DETAILS+="- Message : ${msg}"$'\n'
  DETAILS+=$'\n'"### Critères de réussite (à cocher à la relecture)"$'\n\n'
  DETAILS+="$(jq -r '.criteres_reussite[] | "- [ ] " + .' <<<"$mission")"$'\n'
  probs="$(jq -r '[.etapes[]? | select(.role == "checker" and .verdict != null) | .sortie] | map(select(. != null)) | .[]' <<<"$detail" \
           | jq -r 'try (fromjson | .problemes[]?) catch empty' 2>/dev/null || true)"
  if [[ -n "$probs" ]]; then
    DETAILS+=$'\n'"### Problèmes relevés par le CHECKER"$'\n\n'
    while IFS= read -r p; do DETAILS+="- ${p}"$'\n'; done <<<"$probs"
  fi
  DETAILS+=$'\n'"### Livrable"$'\n\n'
  livrable="$(jq -r '.livrable_texte // empty' <<<"$detail")"
  if [[ -n "$livrable" ]]; then
    DETAILS+='````text'$'\n'"${livrable}"$'\n''````'$'\n'
  else
    DETAILS+="_(aucun livrable enregistré)_"$'\n'
  fi
done

# --- Tableau récapitulatif (terminal + rapport) ------------------------------------
FORMAT='%-6s %-5s %-14s %-7s %-8s %-6s %-7s %s\n'
info ""
info "== Récapitulatif =="
# shellcheck disable=SC2059  # format constant défini ci-dessus
printf "$FORMAT" ID 'N°' Statut Obtenu Attendu Ecart Duree CHECKER
for l in "${LIGNES[@]}"; do
  IFS=$'\t' read -r c1 c2 c3 c4 c5 c6 c7 c8 <<<"$l"
  # shellcheck disable=SC2059
  printf "$FORMAT" "$c1" "$c2" "$c3" "$c4" "$c5" "$c6" "$c7" "$c8"
done

{
  printf '## Récapitulatif\n\n'
  printf '| ID | N° | Statut | Niveau obtenu | Attendu | Écart | Durée | Verdicts CHECKER |\n'
  printf '|---|---|---|---|---|---|---|---|\n'
  for l in "${LIGNES[@]}"; do
    printf '| %s |\n' "${l//$'\t'/ | }"
  done
  printf '\nMissions conformes : %d · anomalies : %d\n\n' "$NB_OK" "$NB_ANOMALIES"
  printf 'Les missions en `en_attente_n3` attendent une décision dans le cockpit (`/cockpit`) : '
  printf "c'est le comportement attendu pour PK-01, PK-03 et PK-04.\n"
  printf '%s\n' "$DETAILS"
} >> "$RAPPORT"

info ""
info "Missions conformes : ${NB_OK} · anomalies : ${NB_ANOMALIES}"
info "Rapport détaillé : ${RAPPORT}"
(( NB_ANOMALIES == 0 ))
