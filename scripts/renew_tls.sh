#!/usr/bin/env bash
# Run from a scheduled host job every 12 hours after HTTPS is enabled.
set -euo pipefail

task_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$task_root"
: "${APP_HOST:?Set APP_HOST to the certificate IP address or DNS name}"
[[ "$APP_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo "Invalid APP_HOST" >&2; exit 2; }

compose=(docker compose -f docker-compose.yml -f deploy/compose.tls-bootstrap.yml -f deploy/compose.https.yml)
"${compose[@]}" run --rm --no-deps certbot renew --non-interactive --webroot --webroot-path /var/www/acme
# Reload only valid configuration; never restart the database or delete volumes.
"${compose[@]}" exec -T frontend nginx -t
"${compose[@]}" exec -T frontend nginx -s reload
