#!/usr/bin/env bash
# =============================================================================
#  lancer.sh — Banc d'essai qualité du Mini NEXUS MOTHERSHIP
#
#  Lance les missions de référence une par une (séquentiel) sur une instance
#  nexus-core, attend leur fin, enregistre les mesures puis les note (noter.py).
#
#  Utilisation :
#    FONCTIONNEMENT=F1 SELECTION=rapide ./lancer.sh     # 8 missions représentatives
#    FONCTIONNEMENT=F2 ./lancer.sh                      # les 30 missions
#    SELECTION=BE-01,BE-05 ./lancer.sh                  # missions choisies
#
#  Variables :
#    FONCTIONNEMENT  F1 | F2 | F3 (défaut : « fonctionnement_defaut » du fichier
#                    de missions, sinon F2). F4 est PAYANT (Anthropic) : refusé
#                    sauf FORCER_F4=1 ; chaque lancement F4 doit en plus être
#                    validé dans le cockpit (décision N3 avec coût estimé).
#    SELECTION       vide = toutes ; « rapide » = selection_rapide du fichier ;
#                    ou liste d'identifiants séparés par des virgules.
#    MISSIONS        fichier de missions (défaut : missions.json à côté du script)
#    NEXUS_URL       défaut : https://$NEXUS_HOST (lu dans .env si besoin)
#    NEXUS_API_KEY   défaut : lue dans .env (ENV_FILE, ../.env,
#                    /srv/p1/nexus-mothership/.env, /opt/nexus-mothership/.env)
#    NEXUS_RESOLVE   facultatif, ex. srvXXXX.hstgr.cloud:443:IP_PUBLIQUE
#    DELAI_MAX_S     délai max par mission (défaut selon F : 300/900/1500/2400)
#    INTERVALLE_S    intervalle d'interrogation (défaut 10)
#    FICHIER_RESULTATS  défaut : resultats/<AAAA-MM-JJ>_<F>[_<nom>].json
#
#  Reprise : relancer la même commande le même jour reprend là où le banc
#  s'est arrêté (missions terminées conservées, missions en cours suivies
#  sans être recréées). Le banc ne valide JAMAIS une décision N3 : une mission
#  « en_attente_n3 » est comptée « arrêtée pour validation ».
# =============================================================================
set -euo pipefail

DOSSIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
erreur() { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }
info()   { printf '%s\n' "$*" >&2; }

command -v jq      >/dev/null 2>&1 || erreur "jq est introuvable (apt-get install -y jq)."
command -v curl    >/dev/null 2>&1 || erreur "curl est introuvable (apt-get install -y curl)."
command -v python3 >/dev/null 2>&1 || erreur "python3 est introuvable."

MISSIONS="${MISSIONS:-${DOSSIER}/missions.json}"
[[ -r "$MISSIONS" ]] || erreur "fichier de missions introuvable : $MISSIONS"
jq -e '.missions | type == "array" and length > 0' "$MISSIONS" >/dev/null \
  || erreur "$MISSIONS ne contient pas de tableau « missions » valide."

# --- Niveau de fonctionnement -------------------------------------------------------
F="${FONCTIONNEMENT:-$(jq -r '.fonctionnement_defaut // "F2"' "$MISSIONS")}"
F="${F^^}"
[[ "$F" =~ ^F[1-4]$ ]] || erreur "FONCTIONNEMENT invalide « $F » (F1, F2 ou F3 ; F4 avec FORCER_F4=1)."
if [[ "$F" == "F4" && "${FORCER_F4:-0}" != "1" ]]; then
  erreur "F4 est PAYANT (modèles Anthropic, jusqu'à 0,50 € par mission). Refusé par défaut.
Pour le mesurer quand même : FORCER_F4=1 FONCTIONNEMENT=F4 ./lancer.sh (et validez chaque lancement dans le cockpit)."
fi
[[ "$F" == "F4" ]] && info "ATTENTION : F4 est PAYANT. Chaque mission attend votre validation (coût estimé) dans le cockpit ; le banc ne valide rien lui-même."

case "$F" in F1) DEF=300 ;; F2) DEF=900 ;; F3) DEF=1500 ;; *) DEF=2400 ;; esac
DELAI_MAX_S="${DELAI_MAX_S:-$DEF}"
INTERVALLE_S="${INTERVALLE_S:-10}"
[[ "$DELAI_MAX_S" =~ ^[0-9]+$ && "$DELAI_MAX_S" -gt 0 ]] || erreur "DELAI_MAX_S doit être un entier positif."
[[ "$INTERVALLE_S" =~ ^[0-9]+$ && "$INTERVALLE_S" -gt 0 ]] || erreur "INTERVALLE_S doit être un entier positif."

# --- Clé API et URL (jamais affichées, jamais en ligne de commande) ------------------
lire_env() {  # lire_env NOM : valeur de NOM dans le premier .env lisible (sans l'exécuter)
  local nom="$1" f v
  for f in "${ENV_FILE:-}" "${DOSSIER}/../.env" /srv/p1/nexus-mothership/.env /opt/nexus-mothership/.env; do
    [[ -n "$f" && -r "$f" ]] || continue
    v="$(grep -E "^${nom}=" "$f" | tail -n 1 | cut -d= -f2-)" || true
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done
  return 1
}
CLE="${NEXUS_API_KEY:-$(lire_env NEXUS_API_KEY || true)}"
[[ -n "$CLE" ]] || erreur "NEXUS_API_KEY introuvable (variable ou fichier .env du kit ; ENV_FILE=chemin/.env)."
if [[ -z "${NEXUS_URL:-}" ]]; then
  HOTE="${NEXUS_HOST:-$(lire_env NEXUS_HOST || true)}"
  [[ -n "$HOTE" ]] || erreur "NEXUS_URL non définie et NEXUS_HOST introuvable dans .env."
  NEXUS_URL="https://${HOTE}"
fi
NEXUS_URL="${NEXUS_URL%/}"

umask 077
TMP_ENTETE="$(mktemp)"; TMP_REPONSE="$(mktemp)"; TMP_CORPS="$(mktemp)"
nettoyer() { rm -f "$TMP_ENTETE" "$TMP_REPONSE" "$TMP_CORPS"; }
trap nettoyer EXIT
trap 'info ""; info "Interrompu. Relancez la même commande pour reprendre (résultats déjà obtenus conservés)."; exit 130' INT TERM
chmod 600 "$TMP_ENTETE"
printf 'X-Nexus-Key: %s\n' "$CLE" > "$TMP_ENTETE"
unset CLE NEXUS_API_KEY

# api MÉTHODE CHEMIN [fichier_corps] → corps dans $TMP_REPONSE, code HTTP sur stdout (000 si injoignable)
api() {
  local args=(-sS -o "$TMP_REPONSE" -w '%{http_code}' --max-time 30 -X "$1"
              -H "@${TMP_ENTETE}" -H 'Accept: application/json')
  [[ -n "${NEXUS_RESOLVE:-}" ]] && args+=(--resolve "$NEXUS_RESOLVE")
  [[ -n "${3:-}" ]] && args+=(-H 'Content-Type: application/json' --data-binary "@$3")
  curl "${args[@]}" "${NEXUS_URL}$2" 2>/dev/null || printf '000'
}

# --- Contrôle de l'instance ------------------------------------------------------------
info "== Banc d'essai NEXUS — ${F} — $(basename "$MISSIONS") =="
code="$(api GET /api/sante)"
[[ "$code" == "200" ]] || erreur "/api/sante → HTTP ${code} sur ${NEXUS_URL} (NEXUS_URL ? NEXUS_RESOLVE ? conteneurs ?)."
SANTE="$(jq -c '{llm, fonctionnement_defaut}' "$TMP_REPONSE")"
code="$(api GET /api/fonctionnement)"
case "$code" in
  200) GRILLE="$(jq -c '[.niveaux[]? | {code, nom, fournisseur, budget_tokens, revisions_max, double_controle, delai_max_s, cout_max_eur}]' "$TMP_REPONSE")" ;;
  401|403) erreur "clé API refusée (HTTP ${code})." ;;
  *) GRILLE='[]' ;;
esac
info "Modèle : $(jq -r '.llm | "\(.fournisseur) / \(.modele)"' <<<"$SANTE")"

# --- Sélection -----------------------------------------------------------------------------
SELECTION="${SELECTION:-}"
if [[ -z "$SELECTION" ]]; then
  mapfile -t IDS < <(jq -r '.missions[].id' "$MISSIONS")
elif [[ "$SELECTION" == "rapide" ]]; then
  mapfile -t IDS < <(jq -r '.selection_rapide // [] | .[]' "$MISSIONS")
else
  mapfile -t IDS < <(tr ',' '\n' <<<"$SELECTION" | tr -d ' ' | grep -v '^$')
fi
(( ${#IDS[@]} > 0 )) || erreur "aucune mission sélectionnée."
for id in "${IDS[@]}"; do
  jq -e --arg i "$id" '.missions | any(.id == $i)' "$MISSIONS" >/dev/null || erreur "mission inconnue : $id"
done

# --- Fichier de résultats (création ou reprise) -------------------------------------------
mkdir -p "${DOSSIER}/resultats"
NOM="$(basename "$MISSIONS" .json)"; SUFFIXE=""
[[ "$(cd "$(dirname "$MISSIONS")" && pwd)/$(basename "$MISSIONS")" != "${DOSSIER}/missions.json" ]] \
  && SUFFIXE="_$(basename "$(dirname "$MISSIONS")")-${NOM}"
RES="${FICHIER_RESULTATS:-${DOSSIER}/resultats/$(date +%Y-%m-%d)_${F}${SUFFIXE}.json}"
if [[ -s "$RES" ]]; then
  jq -e '.resultats | type == "array"' "$RES" >/dev/null || erreur "$RES existe mais n'est pas un fichier de résultats valide."
  info "Reprise de $RES"
else
  jq -n --arg f "$F" --arg url "$NEXUS_URL" --arg m "$MISSIONS" --argjson s "$SANTE" --argjson g "$GRILLE" \
    --arg d "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{banc: "NEXUS banc d essai", version: 1, fonctionnement: $f, nexus_url: $url, missions_json: $m,
      debut: $d, fin: null, sante: $s, grille: $g, resultats: []}' > "$RES"
fi
maj_res() {  # maj_res FILTRE_JQ [args jq...] : modification atomique du fichier de résultats
  local filtre="$1"; shift
  jq "$@" "$filtre" "$RES" > "${RES}.tmp" && mv "${RES}.tmp" "$RES"
}
maj_res '.sante = $s | .grille = $g' --argjson s "$SANTE" --argjson g "$GRILLE"

STATUTS_FINAUX=" terminee echouee plafond_atteint a_reformuler en_attente_n3 en_attente_decision refusee suspendue validee revision "
est_final() {  # est_final STATUT ATTENTE
  [[ "$STATUTS_FINAUX" == *" $1 "* && "$2" != "lancement_f4" ]]
}
entree() { jq -c --arg i "$1" '.resultats[] | select(.id == $i)' "$RES"; }

# --- Boucle séquentielle -----------------------------------------------------------------------
n=0
for ID in "${IDS[@]}"; do
  n=$((n + 1))
  E="$(entree "$ID")"
  MID=""
  if [[ -n "$E" ]]; then
    st="$(jq -r '.statut // ""' <<<"$E")"; att="$(jq -r '.attente // ""' <<<"$E")"
    if est_final "$st" "$att"; then
      info "[$n/${#IDS[@]}] $ID : déjà obtenu ($st), conservé."
      continue
    fi
    MID="$(jq -r '.mission_id // ""' <<<"$E")"
  fi
  M="$(jq -c --arg i "$ID" '.missions[] | select(.id == $i)' "$MISSIONS")"
  if [[ -z "$MID" ]]; then
    # Le service n'est envoyé que si la mission l'impose (champ « service ») : sinon le routage est mesuré.
    jq -n --argjson m "$M" --arg f "$F" \
      '{titre: $m.titre, consigne: $m.consigne, projet: ($m.projet // "divers"), fonctionnement: $f,
        repli_f3: ($f != "F4")} + (if $m.service then {service: $m.service} else {} end)' > "$TMP_CORPS"
    code="$(api POST /api/missions "$TMP_CORPS")"
    if [[ "$code" != "202" ]]; then
      detail="$(jq -r '.detail // empty' "$TMP_REPONSE" 2>/dev/null | head -c 300 || true)"
      info "[$n/${#IDS[@]}] $ID : création refusée (HTTP $code) ${detail}"
      maj_res '(.resultats |= map(select(.id != $i))) | .resultats += [{id: $i, titre: $t, statut: "erreur_creation", http: $c, erreur: $e}]' \
        --arg i "$ID" --arg t "$(jq -r .titre <<<"$M")" --arg c "$code" --arg e "$detail"
      continue
    fi
    MID="$(jq -r '.id' "$TMP_REPONSE")"
    maj_res '(.resultats |= map(select(.id != $i))) | .resultats += [{id: $i, titre: $t, mission_id: ($mid|tonumber), statut: "lancee", lance_le: $d}]' \
      --arg i "$ID" --arg t "$(jq -r .titre <<<"$M")" --arg mid "$MID" --arg d "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    info "[$n/${#IDS[@]}] $ID : mission #$MID lancée."
  else
    info "[$n/${#IDS[@]}] $ID : reprise du suivi de la mission #$MID."
  fi

  debut=$SECONDS; st=""; att=""; signale_f4=0
  while :; do
    code="$(api GET "/api/missions/${MID}")"
    if [[ "$code" == "200" ]]; then
      st="$(jq -r '.statut' "$TMP_REPONSE")"; att="$(jq -r '.attente // ""' "$TMP_REPONSE")"
      est_final "$st" "$att" && break
      if [[ "$att" == "lancement_f4" && $signale_f4 == 0 ]]; then
        info "   → validez (ou refusez) le lancement F4 de la mission #$MID dans le cockpit (PAYANT)."
        signale_f4=1
      fi
    elif [[ "$code" == "404" ]]; then
      st="introuvable"; break
    fi
    if (( SECONDS - debut >= DELAI_MAX_S )); then
      st="delai_banc_depasse"; break
    fi
    sleep "$INTERVALLE_S"
  done
  duree_banc=$((SECONDS - debut))

  if [[ "$st" == "delai_banc_depasse" || "$st" == "introuvable" ]]; then
    maj_res '(.resultats[] | select(.id == $i)) |= (.statut = $s | .duree_banc_s = ($db|tonumber))' \
      --arg i "$ID" --arg s "$st" --arg db "$duree_banc"
    info "   → $st après ${duree_banc} s (relancer la commande reprendra le suivi)."
    continue
  fi
  maj_res '(.resultats[] | select(.id == $i)) |= (. + ($r[0] | {statut, service, niveau, projet, fonctionnement_demande,
             fonctionnement, fonctionnement_raison, tokens, tokens_entree, tokens_sortie, cout_eur, duree_s,
             revisions, attente, message, livrable_texte}) + {duree_banc_s: ($db|tonumber), fini_le: $d})' \
    --arg i "$ID" --slurpfile r "$TMP_REPONSE" --arg db "$duree_banc" --arg d "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  info "   → $st ($(jq -r '"\(.service // "-") · \(.niveau // "-") · \(.fonctionnement // "-") · \(.tokens // 0) tokens · \(.duree_s // 0) s"' "$TMP_REPONSE"))"
  [[ "$st" == "en_attente_n3" ]] && info "     (arrêtée pour validation : le banc ne valide jamais une décision N3)"
done

maj_res '.fin = $d' --arg d "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 "${DOSSIER}/noter.py" --missions "$MISSIONS" "$RES"
info ""
info "Résultats : $RES"
MOTIF="${SUFFIXE:+*${SUFFIXE}.json}"; MOTIF="${MOTIF:-*_F?.json}"
info "Rapport   : MISSIONS=$MISSIONS python3 ${DOSSIER}/rapport.py ${DOSSIER}/resultats/${MOTIF}"
