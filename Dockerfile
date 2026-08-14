FROM python:3.12-slim

WORKDIR /srv/xevyte-agent

# psycopg2-binary + cryptography need these at build time on slim images
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/chroma

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD curl -fk https://localhost:8443/health || curl -f http://localhost:8443/health || exit 1

# Runs plain HTTP by default in-container; terminate TLS at the
# docker-compose reverse proxy (see docker-compose.yml) unless you mount
# real cert files and set SSL_KEYFILE/SSL_CERTFILE, in which case uvicorn
# serves HTTPS directly.
CMD ["sh", "-c", "\
    if [ -n \"$SSL_KEYFILE\" ] && [ -n \"$SSL_CERTFILE\" ]; then \
        uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile \"$SSL_KEYFILE\" --ssl-certfile \"$SSL_CERTFILE\"; \
    else \
        uvicorn app.main:app --host 0.0.0.0 --port 8443; \
    fi"]
