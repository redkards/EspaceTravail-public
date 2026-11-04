#!/usr/bin/env bash
# Installe SERENITY P4 (25 % du VPS). BROUILLON — à valider (carte ADMIN JÉRÉMY).
# Usage : bash installer-serenity.sh [--retour]   (depuis le dossier qui contient ce script)
set -euo pipefail
DIR=/srv/p4/serenity
cd "$(dirname "$0")"
if [ "${1:-}" = "--retour" ]; then
  docker compose -p serenity -f docker-compose.serenity.yml down && echo "[OK] SERENITY arrêtée (données conservées dans $DIR/data)"; exit 0
fi
mountpoint -q /srv/p4 || { echo "[KO] /srv/p4 n'est pas montée"; exit 1; }
docker network inspect p1-nexus-net >/dev/null || { echo "[KO] réseau p1-nexus-net absent"; exit 1; }
mkdir -p "$DIR/data" && chown -R 65534:65534 "$DIR/data" && chmod 700 "$DIR/data"
if [ ! -f .env ]; then
  umask 077
  printf 'SERENITY_HMAC_KEY=%s\nSERENITY_TOKEN=%s\nSERENITY_ADMIN_TOKEN=%s\n' \
    "$(openssl rand -hex 32)" "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > .env
  echo "[OK] .env créé (secrets générés, jamais affichés)"
fi
chmod 600 .env
docker compose -p serenity -f docker-compose.serenity.yml up -d --build
for i in $(seq 1 20); do
  s=$(docker inspect -f '{{.State.Health.Status}}' serenity-serenity-1 2>/dev/null || echo "?")
  [ "$s" = healthy ] && { echo "[OK] SERENITY en bonne santé"; break; }; sleep 3
done
docker stats --no-stream --format 'SERENITY : CPU {{.CPUPerc}} · RAM {{.MemUsage}}' serenity-serenity-1
docker exec serenity-serenity-1 python -c "import urllib.request,json;print(json.loads(urllib.request.urlopen('http://127.0.0.1:8100/sante').read()))"
