# nexus-core — service Python du Mini NEXUS MOTHERSHIP
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NEXUS_DATA_DIR=/data

WORKDIR /app

# Dépendances d'abord (cache Docker) ; pytest n'est pas nécessaire en production.
COPY requirements.txt .
RUN grep -v '^pytest' requirements.txt > /tmp/req.txt \
    && pip install -r /tmp/req.txt \
    && rm /tmp/req.txt

# Utilisateur non root (UID/GID 10001) et dossier de données.
RUN groupadd --system --gid 10001 nexus \
    && useradd --system --uid 10001 --gid nexus --home-dir /app --shell /usr/sbin/nologin nexus \
    && mkdir -p /data/livrables \
    && chown -R nexus:nexus /data

COPY --chown=nexus:nexus app ./app
COPY --chown=nexus:nexus agents ./agents
COPY --chown=nexus:nexus projets.yaml ./projets.yaml

USER nexus
EXPOSE 8000
VOLUME ["/data"]

# Sonde de santé : /api/sante répond sans clé.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/sante', timeout=5)" || exit 1

# Un seul worker : empreinte mémoire faible (limite 384 Mo).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
