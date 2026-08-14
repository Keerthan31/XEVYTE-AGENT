#!/usr/bin/env bash
# Generates a self-signed TLS cert for LOCAL DEV ONLY. Browsers/HTTP clients
# won't trust this — for staging/production, use a real cert (Let's
# Encrypt, your org's CA) terminated at a reverse proxy, or drop a real
# cert's key/cert files in here instead and point SSL_KEYFILE/SSL_CERTFILE
# at them.
set -euo pipefail
cd "$(dirname "$0")"

openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout key.pem -out cert.pem -days 365 \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo ""
echo "Wrote certs/key.pem and certs/cert.pem (self-signed, 365 days)."
echo "Set in .env:"
echo "  SSL_KEYFILE=certs/key.pem"
echo "  SSL_CERTFILE=certs/cert.pem"
