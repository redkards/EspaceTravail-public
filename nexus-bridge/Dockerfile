# nexus-bridge — passerelle MCP (Claude · ChatGPT · Gemini) du Mini NEXUS MOTHERSHIP
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BRIDGE_DB=/data/bridge.db

WORKDIR /app

# Dépendances d'abord (cache Docker) ; pytest n'est pas nécessaire en production.
COPY requirements.txt .
RUN grep -v '^pytest' requirements.txt > /tmp/req.txt \
    && pip install -r /tmp/req.txt \
    && rm /tmp/req.txt

# Utilisateur non root (UID/GID 10001, comme nexus-core) et dossier de données.
RUN groupadd --system --gid 10001 nexus \
    && useradd --system --uid 10001 --gid nexus --home-dir /app --shell /usr/sbin/nologin nexus \
    && mkdir -p /data \
    && chown -R nexus:nexus /data

COPY --chown=nexus:nexus app ./app

USER nexus
EXPOSE 8000
VOLUME ["/data"]

# Sonde de santé interne (non publiée par Caddy).
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/sante', timeout=5)" || exit 1

# Un seul worker (limite 128 Mo). --no-access-log : le jeton peut figurer dans
# l'URL (/mcp/<jeton>) ; l'application écrit son propre journal, URL masquée.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
