#!/usr/bin/env bash
# =============================================================================
#  separer.sh — Prépare les 4 dépôts privés NEXUS à partir de ce dépôt (monodépôt SYFER),
#  en CONSERVANT l'historique git de chaque partie. N'envoie RIEN sur GitHub.
#
#  Dépôts produits (dans le dossier de sortie) :
#    nexus-bridge      nexus-bridge/ + protocole/                     (passerelle MCP + Protocole NEXUS v1)
#    nexus-agents      nexus-core/agents/ → agents/, nexus-core/fonctionnement.yaml → fonctionnement.yaml,
#                      nexus-core/chartes/ → chartes/ (si présent)  (bibliothèque des 93 rôles, données)
#    mini-mothership   tout le kit (nexus-core, install.sh, compose, Caddy, cockpit, banc-essai,
#                      automatisations, n8n, sauvegardes…) sauf outils-depots/
#    nexus-mothership  SPEC.md, README.md → docs/GUIDE-KIT.md, outils-depots/ (architecture et outillage)
#  Chacun reçoit en plus : LICENSE (propriétaire), README.md (s'il n'en a pas), CHANGELOG.md
#  (v1.0.0 = état actuel, généré depuis le git log de SES fichiers), VERSION, et l'étiquette v1.0.0.
#
#  Règles GATE / PRIME : ce sont du code Python (nexus-core/app/gate.py, pipeline.py, sentinel.py…),
#  pas des données : elles restent dans mini-mothership. nexus-agents ne contient que des fiches.
#  mini-mothership garde une COPIE de nexus-bridge/, protocole/ et nexus-core/agents/ (nécessaires
#  à docker compose et aux tests) ; la source de référence devient le dépôt dédié.
#
#  Moteur de réécriture (détecté) :
#    1. git filter-repo s'il est installé (recommandé : rapide, sûr) ;
#    2. sinon git filter-branch --index-filter (inclus dans git ; plus lent mais suffisant ici).
#    git subtree split n'est PAS utilisé : il n'extrait qu'UN dossier et ne sait ni combiner
#    plusieurs chemins (nexus-bridge/ + protocole/) ni renommer (agents/ à la racine).
#
#  Seul l'historique COMMITÉ est pris (clone de la branche) : commitez avant de séparer.
#
#  Utilisation :
#    outils-depots/separer.sh [--sortie DOSSIER] [--branche v2] [--remote-prefix git@github.com:redkards/]
#                             [--seulement nexus-bridge,nexus-agents] [--moteur auto|filter-repo|filter-branch]
#                             [--force]
#  --remote-prefix P : ajoute le remote « origin » = P<nom>.git et affiche les commandes de push
#                      (jamais exécutées par ce script).
#  Codes de sortie : 0 ok · 1 usage/configuration · 2 échec de réécriture
# =============================================================================
set -euo pipefail
export LC_ALL=C.UTF-8 2>/dev/null || true

DOSSIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "${DOSSIER}/.." && pwd)"
SORTIE="${SOURCE}/../depots-separes"
BRANCHE=""
REMOTE_PREFIX=""
SEULEMENT=""
MOTEUR="auto"
FORCE=0
DEPOTS=(nexus-bridge nexus-agents mini-mothership nexus-mothership)
ANNEE="2026"
TITULAIRE="redkards"

erreur() { printf 'ERREUR : %s\n' "$*" >&2; exit "${2:-1}"; }
info()   { printf '%s\n' "$*" >&2; }

while (( $# )); do
  case "$1" in
    --sortie) SORTIE="${2:?--sortie DOSSIER}"; shift 2 ;;
    --branche) BRANCHE="${2:?--branche NOM}"; shift 2 ;;
    --remote-prefix) REMOTE_PREFIX="${2:?--remote-prefix PREFIXE}"; shift 2 ;;
    --seulement) SEULEMENT="${2:?--seulement liste}"; shift 2 ;;
    --moteur) MOTEUR="${2:?--moteur auto|filter-repo|filter-branch}"; shift 2 ;;
    --source) SOURCE="$(cd "${2:?--source DOSSIER}" && pwd)"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^#  \{0,1\}//'; exit 0 ;;
    *) erreur "option inconnue : $1 (voir --help)" ;;
  esac
done

command -v git >/dev/null 2>&1 || erreur "git est introuvable."
git -C "$SOURCE" rev-parse --git-dir >/dev/null 2>&1 || erreur "$SOURCE n'est pas un dépôt git."
[[ -n "$BRANCHE" ]] || BRANCHE="$(git -C "$SOURCE" rev-parse --abbrev-ref HEAD)"
git -C "$SOURCE" rev-parse --verify -q "refs/heads/${BRANCHE}" >/dev/null || erreur "branche inconnue : $BRANCHE"
if [[ -n "$(git -C "$SOURCE" status --porcelain 2>/dev/null)" ]]; then
  info "ATTENTION : modifications non commitées dans $SOURCE — elles ne seront PAS dans les dépôts produits."
fi

case "$MOTEUR" in
  auto) if git filter-repo --version >/dev/null 2>&1; then MOTEUR="filter-repo"; else MOTEUR="filter-branch"; fi ;;
  filter-repo) git filter-repo --version >/dev/null 2>&1 || erreur "git filter-repo n'est pas installé (pip install git-filter-repo)." ;;
  filter-branch) ;;
  *) erreur "moteur inconnu : $MOTEUR" ;;
esac
if [[ -n "$SEULEMENT" ]]; then
  IFS=',' read -r -a DEPOTS <<<"$SEULEMENT"
  for d in "${DEPOTS[@]}"; do
    [[ " nexus-bridge nexus-agents mini-mothership nexus-mothership " == *" $d "* ]] || erreur "dépôt inconnu : $d"
  done
fi
if [[ -n "$REMOTE_PREFIX" && ! "$REMOTE_PREFIX" =~ ^(git@[A-Za-z0-9.-]+:|https://|ssh://|file://|/)[^[:space:]]*$ ]]; then
  erreur "--remote-prefix invalide : $REMOTE_PREFIX (ex. git@github.com:redkards/)"
fi
mkdir -p "$SORTIE"
SORTIE="$(cd "$SORTIE" && pwd)"
case "$SORTIE/" in "$SOURCE"/*) erreur "le dossier de sortie doit être HORS du dépôt source." ;; esac

info "Source : $SOURCE (branche $BRANCHE, $(git -C "$SOURCE" rev-list --count "$BRANCHE") commits) — moteur : $MOTEUR"

# --- Règles de chaque dépôt : « source<TAB>destination » ; « - chemin » = exclure ; « . » = tout ----------
regles() {
  case "$1" in
    nexus-bridge)     printf 'nexus-bridge/\tnexus-bridge/\nprotocole/\tprotocole/\n' ;;
    nexus-agents)     printf 'nexus-core/agents/\tagents/\nnexus-core/fonctionnement.yaml\tfonctionnement.yaml\nnexus-core/chartes/\tchartes/\n' ;;
    mini-mothership)  printf '.\t.\n- outils-depots/\n' ;;
    nexus-mothership) printf 'SPEC.md\tSPEC.md\nREADME.md\tdocs/GUIDE-KIT.md\noutils-depots/\toutils-depots/\n' ;;
  esac
}

description() {
  case "$1" in
    nexus-bridge) echo "Passerelle MCP commune (Claude · ChatGPT · Gemini) entre les IA et le Mothership, et Protocole NEXUS v1 (schémas JSON, validateur, exemples réels)." ;;
    nexus-agents) echo "Bibliothèque des 93 rôles d'agents NEXUS (fiches YAML) et grille des niveaux de fonctionnement F1–F4. Données seulement : les règles GATE/PRIME sont du code et restent dans mini-mothership." ;;
    mini-mothership) echo "Kit installable Mini NEXUS MOTHERSHIP : nexus-core (FastAPI/SQLite), cockpit, install.sh, docker compose, Caddy, banc d'essai, automatisations, sauvegardes." ;;
    nexus-mothership) echo "Architecture et documentation de haut niveau de NEXUS MOTHERSHIP (spécification, guide du kit, outillage de séparation des dépôts)." ;;
  esac
}

# --- Réécriture --------------------------------------------------------------------------------------------
filtrer_filter_repo() {  # $1 dépôt, dans le clone courant
  local args=() src dst
  if regles "$1" | grep -q '^\.'; then
    while IFS= read -r l; do [[ "$l" == "- "* ]] && args+=(--path "${l#- }"); done < <(regles "$1")
    git filter-repo --force --quiet "${args[@]}" --invert-paths
    return
  fi
  while IFS=$'\t' read -r src dst; do
    args+=(--path "$src")
    [[ "$src" != "$dst" ]] && args+=(--path-rename "${src}:${dst}")
  done < <(regles "$1")
  git filter-repo --force --quiet "${args[@]}"
}

filtrer_filter_branch() {  # $1 dépôt, dans le clone courant
  local fichier_regles filtre
  fichier_regles="$(pwd)/.git/separer-regles"
  filtre="$(pwd)/.git/separer-filtre.sh"
  regles "$1" > "$fichier_regles"
  # Filtre d'index : garde/renomme les chemins selon les règles (awk : aucune dépendance).
  cat > "$filtre" <<'FILTRE'
#!/usr/bin/env bash
set -euo pipefail
git ls-files -s | awk -v regles="$1" '
  BEGIN { FS = "\t"; n = 0; nx = 0
          while ((getline l < regles) > 0) {
            if (l ~ /^- /) { ex[++nx] = substr(l, 3); continue }
            split(l, p, "\t"); src[++n] = p[1]; dst[n] = p[2] } }
  { chemin = $2
    for (i = 1; i <= nx; i++) if (chemin == ex[i] || (ex[i] ~ /\/$/ && index(chemin, ex[i]) == 1)) next
    for (i = 1; i <= n; i++) {
      if (src[i] == ".") { print; next }
      if (chemin == src[i]) { print $1 "\t" dst[i]; next }
      if (src[i] ~ /\/$/ && index(chemin, src[i]) == 1) { print $1 "\t" dst[i] substr(chemin, length(src[i]) + 1); next }
    } }' > "$GIT_INDEX_FILE.liste"
rm -f "$GIT_INDEX_FILE.nouveau"
GIT_INDEX_FILE="$GIT_INDEX_FILE.nouveau" git update-index --index-info < "$GIT_INDEX_FILE.liste"
# Aucun fichier retenu : index absent → arbre vide (commit élagué par --prune-empty).
if [[ -f "$GIT_INDEX_FILE.nouveau" ]]; then mv "$GIT_INDEX_FILE.nouveau" "$GIT_INDEX_FILE"; else rm -f "$GIT_INDEX_FILE"; fi
rm -f "$GIT_INDEX_FILE.liste"
FILTRE
  chmod +x "$filtre"
  FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --prune-empty \
    --index-filter "'$filtre' '$fichier_regles'" -- "$BRANCHE" >/dev/null 2>&1 \
    || erreur "git filter-branch a échoué pour $1." 2
  git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d
  rm -f "$fichier_regles" "$filtre"
}

# --- Fichiers de dépôt ----------------------------------------------------------------------------------------
ecrire_licence() {
  cat > LICENSE <<EOF
Tous droits réservés — © ${ANNEE} ${TITULAIRE}

Ce logiciel, sa documentation et ses données (« le Logiciel ») sont la propriété exclusive de
${TITULAIRE}. Aucune licence n'est accordée. Toute reproduction, diffusion, modification,
publication, location, revente ou utilisation, totale ou partielle, est interdite sans
l'autorisation écrite préalable du titulaire des droits.

Le Logiciel est fourni « en l'état », sans garantie d'aucune sorte. Le titulaire ne pourra être
tenu responsable d'aucun dommage résultant de son utilisation.

Dépôt privé : son accès ne vaut pas autorisation d'usage.
EOF
}

ecrire_readme() {  # $1 dépôt
  [[ -f README.md ]] && return 0
  {
    printf '# %s\n\n%s\n\n' "$1" "$(description "$1")"
    printf 'Version : voir `VERSION` (1.0.0). Historique : `CHANGELOG.md`. Licence : propriétaire (`LICENSE`).\n\n'
    case "$1" in
      nexus-bridge)
        printf '## Tests\n\n```bash\ncd nexus-bridge && python3 -m pip install -r requirements.txt && python3 -m pytest -q\ncd ../protocole && python3 -m pytest -q   # rejoue l'\''instantané exemples/ (nexus-core absent)\n```\n\nProtocole : `protocole/README.md` (versionnement SemVer, compatibilité produits ↔ protocole).\n' ;;
      nexus-agents)
        printf '## Contenu\n\n- `agents/` : %s fiches YAML (noyau, directeurs, services × COLLECTOR/ANALYST/CHECKER/EXECUTOR) ;\n- `fonctionnement.yaml` : niveaux F1–F4 ;\n- `chartes/` : chartes (si présentes).\n\nValidation : `python3 <nexus-bridge>/protocole/valider.py --agents agents` (schéma `agent` du Protocole NEXUS v1).\nDans le kit, ces fichiers sont copiés dans `nexus-core/agents/` et `nexus-core/fonctionnement.yaml`.\n' \
          "$(find agents -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')" ;;
      nexus-mothership)
        printf '## Contenu\n\n- `SPEC.md` : spécification de haut niveau ;\n- `docs/GUIDE-KIT.md` : guide d'\''installation du kit (historique de l'\''ancien README) ;\n- `outils-depots/` : séparation du monodépôt SYFER en 4 dépôts.\n\nProduits : nexus-bridge, nexus-agents, mini-mothership (protocole commun : Protocole NEXUS v1).\n' ;;
    esac
  } > README.md
}

ecrire_changelog() {  # $1 dépôt ; résumé fidèle du git log du dépôt réécrit
  local total wip debut fin
  total="$(git rev-list --count HEAD)"
  wip="$(git log --format=%s | grep -c '^WIP' || true)"
  debut="$(git log --reverse --format=%ad --date=short | head -1)"
  fin="$(git log -1 --format=%ad --date=short)"
  {
    printf '# Changelog — %s\n\nFormat : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions : SemVer.\n\n' "$1"
    printf '## [1.0.0] — %s\n\nPremière version autonome, extraite du monodépôt SYFER (branche `%s`) avec son historique :\n' "$fin" "$BRANCHE"
    printf '%s commit(s) du %s au %s, dont %s commit(s) intermédiaire(s) « WIP ».\n\n' "$total" "$debut" "$fin" "$wip"
    printf '%s\n\n### Étapes (commits publiés, du plus ancien au plus récent)\n\n' "$(description "$1")"
    git log --reverse --format='- %ad — %s' --date=short | grep -v -- '— WIP' || printf -- '- (aucun commit hors WIP)\n'
    printf '\n'
  } > CHANGELOG.md
}

finaliser() {  # $1 dépôt
  ecrire_licence
  ecrire_readme "$1"
  ecrire_changelog "$1"
  printf '1.0.0\n' > VERSION
  git add LICENSE README.md CHANGELOG.md VERSION
  local nom courriel
  nom="$(git -C "$SOURCE" config user.name || echo "$TITULAIRE")"
  courriel="$(git -C "$SOURCE" config user.email || echo "${TITULAIRE}@users.noreply.github.com")"
  GIT_AUTHOR_NAME="$nom" GIT_AUTHOR_EMAIL="$courriel" GIT_COMMITTER_NAME="$nom" GIT_COMMITTER_EMAIL="$courriel" \
    git commit -q -m "$1 v1.0.0 : licence, README, CHANGELOG, VERSION (séparation du monodépôt SYFER)"
  git tag -a v1.0.0 -m "$1 v1.0.0"
}

# --- Boucle principale ---------------------------------------------------------------------------------------
declare -a RESUME=()
for depot in "${DEPOTS[@]}"; do
  cible="${SORTIE}/${depot}"
  if [[ -e "$cible" ]]; then
    (( FORCE )) || erreur "$cible existe déjà (--force pour le remplacer)."
    rm -rf "$cible"
  fi
  info "== ${depot} =="
  git clone -q --no-local --no-tags --single-branch --branch "$BRANCHE" "$SOURCE" "$cible"
  (
    cd "$cible"
    git remote remove origin
    git symbolic-ref --delete refs/remotes/origin/HEAD 2>/dev/null || true
    rm -rf .git/refs/remotes/origin
    if [[ "$MOTEUR" == "filter-repo" ]]; then filtrer_filter_repo "$depot"; else filtrer_filter_branch "$depot"; fi
    git checkout -q -B main 2>/dev/null || git checkout -q -b main
    [[ "$BRANCHE" != "main" ]] && git branch -D "$BRANCHE" >/dev/null 2>&1 || true
    git reset -q --hard
    [[ -n "$(git ls-files)" ]] || erreur "$depot : aucun fichier après filtrage." 2
    finaliser "$depot"
    git reflog expire --expire=now --all
    git gc -q --prune=now
    if [[ -n "$REMOTE_PREFIX" ]]; then
      git remote add origin "${REMOTE_PREFIX}${depot}.git"
    fi
  )
  commits="$(git -C "$cible" rev-list --count HEAD)"
  taille="$(du -sh "$cible/.git" | cut -f1)"
  fichiers="$(git -C "$cible" ls-files | wc -l | tr -d ' ')"
  RESUME+=("$(printf '%-17s %5s commits  %5s fichiers  .git %6s' "$depot" "$commits" "$fichiers" "$taille")")
done

info ""
info "Dépôts prêts dans ${SORTIE} (rien n'a été envoyé) :"
printf '%s\n' "${RESUME[@]}"
if [[ -n "$REMOTE_PREFIX" ]]; then
  info ""
  info "Pour publier (après création des dépôts PRIVÉS sur GitHub) :"
  for depot in "${DEPOTS[@]}"; do
    info "  git -C '${SORTIE}/${depot}' push -u origin main --follow-tags"
  done
fi
