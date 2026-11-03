#!/usr/bin/env bash
# =============================================================================
#  hebdo.sh — Banc d'essai hebdomadaire du Mini NEXUS MOTHERSHIP (B5)
#
#  Une fois par semaine ISO :
#   1. choisit le niveau : F2 si un fournisseur cloud répond (/api/sante :
#      ollama_cloud ou anthropic), sinon F1 (modèle local) ;
#   2. lance la sélection rapide (8 missions) avec lancer.sh — résultats dans
#      resultats/hebdo/<AAAA-Wnn>_<F>.json (reprise automatique si interrompu) ;
#   3. produit le rapport de la semaine (resultats/hebdo/rapport_hebdo-<semaine>.md)
#   4. ajoute la semaine au tableau cumulatif resultats/tableau.json, lu par
#      tableau.html (tendances : notes, pièges, tokens, durée, taux N3, modèle).
#
#  Jamais de F4 (payant) : refusé même si FONCTIONNEMENT=F4.
#  Le banc ne valide jamais une décision N3 (voir lancer.sh).
#
#  Cron proposé (dimanche 04:17, après la veille cyber de 03:17) :
#    17 4 * * 0 root /srv/p1/nexus-mothership/banc-essai/hebdo.sh >/dev/null 2>&1
#
#  Variables facultatives :
#    FONCTIONNEMENT   force F1, F2 ou F3 (défaut : détection ci-dessus)
#    SELECTION        défaut « rapide » (voir lancer.sh)
#    SEMAINE          défaut : semaine ISO courante (AAAA-Wnn)
#    NEXUS_URL, NEXUS_RESOLVE, ENV_FILE, NEXUS_API_KEY : comme lancer.sh
#    RESULTATS_DIR    défaut : <ce dossier>/resultats
#    LANCEUR          défaut : <ce dossier>/lancer.sh (remplacé dans les tests)
#
#  Codes de sortie : 0 terminé · 1 configuration · 2 banc en échec (reprise au
#                    prochain lancement) · 4 déjà en cours
# =============================================================================
set -euo pipefail
umask 077

DOSSIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTATS_DIR="${RESULTATS_DIR:-${DOSSIER}/resultats}"
HEBDO_DIR="${RESULTATS_DIR}/hebdo"
JOURNAL="${RESULTATS_DIR}/hebdo.log"
LANCEUR="${LANCEUR:-${DOSSIER}/lancer.sh}"
SELECTION="${SELECTION:-rapide}"
SEMAINE="${SEMAINE:-$(date +%G-W%V)}"
mkdir -p "$HEBDO_DIR"

journal() { printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$JOURNAL"; printf '%s\n' "$*" >&2; }
echec()   { journal "ERREUR : $2"; exit "$1"; }

[[ "$SEMAINE" =~ ^[0-9]{4}-W[0-9]{2}$ ]] || echec 1 "SEMAINE invalide « $SEMAINE » (AAAA-Wnn)."
for outil in jq curl python3; do
  command -v "$outil" >/dev/null 2>&1 || echec 1 "$outil est introuvable."
done

# --- Une seule exécution à la fois -------------------------------------------------
if command -v flock >/dev/null 2>&1; then
  exec 9>"${RESULTATS_DIR}/.hebdo.verrou"
  flock -n 9 || echec 4 "un banc hebdomadaire est déjà en cours."
fi

# --- URL (sans clé : /api/sante est public) ----------------------------------------------
lire_env() {  # même règle que lancer.sh : lecture sans exécution du .env
  local nom="$1" f v
  for f in "${ENV_FILE:-}" "${DOSSIER}/../.env" /srv/p1/nexus-mothership/.env /opt/nexus-mothership/.env; do
    [[ -n "$f" && -r "$f" ]] || continue
    v="$(grep -E "^${nom}=" "$f" | tail -n 1 | cut -d= -f2-)" || true
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    if [[ -n "$v" ]]; then printf '%s' "$v"; return 0; fi
  done
  return 1
}
if [[ -z "${NEXUS_URL:-}" ]]; then
  HOTE="${NEXUS_HOST:-$(lire_env NEXUS_HOST || true)}"
  [[ -n "$HOTE" ]] || echec 1 "NEXUS_URL non définie et NEXUS_HOST introuvable dans .env."
  NEXUS_URL="https://${HOTE}"
fi
export NEXUS_URL="${NEXUS_URL%/}"

# --- Niveau de fonctionnement ----------------------------------------------------------------
F="${FONCTIONNEMENT:-}"
F="${F^^}"
if [[ -z "$F" ]]; then
  args=(-sS --max-time 20)
  [[ -n "${NEXUS_RESOLVE:-}" ]] && args+=(--resolve "$NEXUS_RESOLVE")
  sante="$(curl "${args[@]}" "${NEXUS_URL}/api/sante" 2>/dev/null || true)"
  fournisseur="$(jq -r '.llm.fournisseur // empty' <<<"$sante" 2>/dev/null || true)"
  [[ -n "$fournisseur" ]] || echec 2 "/api/sante injoignable sur ${NEXUS_URL} (NEXUS_RESOLVE ? conteneurs ?)."
  case "$fournisseur" in
    ollama_cloud|anthropic) F="F2" ;;
    *) F="F1" ;;
  esac
  journal "Fournisseur « ${fournisseur} » → niveau ${F}."
fi
case "$F" in
  F1|F2|F3) ;;
  F4) echec 1 "F4 est payant : jamais lancé par le banc hebdomadaire." ;;
  *) echec 1 "FONCTIONNEMENT invalide « $F » (F1, F2 ou F3)." ;;
esac

# --- Banc -------------------------------------------------------------------------------------------
RES="${HEBDO_DIR}/${SEMAINE}_${F}.json"
journal "== Banc hebdomadaire ${SEMAINE} — ${F} — sélection ${SELECTION} =="
set +e
FONCTIONNEMENT="$F" SELECTION="$SELECTION" FICHIER_RESULTATS="$RES" bash "$LANCEUR" 2>>"$JOURNAL"
code=$?
set -e
[[ $code -eq 0 ]] || echec 2 "lancer.sh a échoué (code ${code}) ; relancez : les résultats déjà obtenus sont gardés."
[[ -s "$RES" ]] || echec 2 "aucun fichier de résultats produit ($RES)."

python3 "${DOSSIER}/rapport.py" --sortie "$HEBDO_DIR" --nom "hebdo-${SEMAINE}" "$RES" >>"$JOURNAL" 2>&1 \
  || journal "Avertissement : rapport de la semaine non produit."
python3 "${DOSSIER}/tableau.py" --resultats "$RES" --semaine "$SEMAINE" --selection "$SELECTION" \
  --tableau "${RESULTATS_DIR}/tableau.json" >>"$JOURNAL" 2>&1 \
  || echec 2 "mise à jour de ${RESULTATS_DIR}/tableau.json impossible (voir $JOURNAL)."
journal "Terminé : ${RES} ; tableau ${RESULTATS_DIR}/tableau.json (ouvrir tableau.html)."
