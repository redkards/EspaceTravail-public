#!/bin/bash
# Exécuté UNE seule fois par l'image PostgreSQL, au premier démarrage (volume vide).
# Crée la base « n8n » (en plus de « nexus ») et active pgvector dans « nexus ».
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	SELECT 'CREATE DATABASE n8n OWNER "$POSTGRES_USER"'
	WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
	CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

echo "[init] Bases « $POSTGRES_DB » et « n8n » prêtes."
