#!/usr/bin/env bash
# Produit un .env FACTICE (CI uniquement) à partir de .env.example : toutes les variables
# obligatoires reçoivent des valeurs bidon, jamais de vraie clé ni de secret.
# Utilisation : .github/scripts/env-factice.sh [.env.example] > ci.env
set -euo pipefail
source_env="${1:-.env.example}"
[[ -r "$source_env" ]] || { echo "introuvable : $source_env" >&2; exit 1; }

declare -A factice=(
  [NEXUS_HOST]="ci.exemple.invalid"
  [ACME_EMAIL]="ci@exemple.invalid"
  [POSTGRES_PASSWORD]="ci-factice-postgres"
  [NEXUS_API_KEY]="ci-factice-nexus-api-0000000000000000"
  [COCKPIT_PASSWORD]="ci-factice"
  # Empreinte bcrypt quelconque (format seulement) ; les $ sont protégés par les guillemets simples.
  [COCKPIT_PASSWORD_HASH]="'\$2a\$14\$cicicicicicicicicicicuK6vZxP0pZb5V3s1cicicicicicicicic'"
  [COCKPIT_INTERNAL]="ci-factice-interne-000000000000000000"
  [LEDGER_HMAC_KEY]="ci-factice-hmac-0000000000000000000000"
  [NTFY_TOPIC]="ci-factice-sujet"
  [N8N_BASIC_PASSWORD]="ci-factice"
  [N8N_BASIC_PASSWORD_HASH]="'\$2a\$14\$cicicicicicicicicicicuK6vZxP0pZb5V3s1cicicicicicicicic'"
  [N8N_ENCRYPTION_KEY]="ci-factice-n8n-000000000000000000"
)

while IFS= read -r ligne || [[ -n "$ligne" ]]; do
  if [[ "$ligne" =~ ^([A-Z0-9_]+)= ]]; then
    nom="${BASH_REMATCH[1]}"
    if [[ -n "${factice[$nom]+x}" ]]; then
      printf '%s=%s\n' "$nom" "${factice[$nom]}"
      unset "factice[$nom]"
      continue
    fi
  fi
  printf '%s\n' "$ligne"
done < "$source_env"
# Variables obligatoires absentes de l'exemple.
for nom in "${!factice[@]}"; do
  printf '%s=%s\n' "$nom" "${factice[$nom]}"
done
