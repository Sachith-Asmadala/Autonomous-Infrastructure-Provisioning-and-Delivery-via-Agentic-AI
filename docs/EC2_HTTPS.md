# EC2 HTTPS change prepared for review

Current target: `54.66.191.38`, instance `i-0ef6abdc20358e225`, region
`ap-southeast-2`. Unauthenticated checks on 30 October 2026 returned HTTP 200
from `/` and `/api/v1/health`; both TLS and plain HTTP on port 443 were refused.
The supplied AWS output allows inbound 443 and reports healthy system/instance
checks. This points to a host listener/container/proxy configuration issue, not
an absent security-group rule. No credentials were sent to HTTP.

The workspace has no usable AWS credentials or supplied SSH key/host alias.
The following is a prepared deployment change, **not a claim that production
HTTPS has been installed**. Production commands require operator review and the
repository's human approval before execution. The operator will run these commands;
no remote production access is assumed.

## Certificate and deployment

A public IP can use HTTPS. Let's Encrypt now supports six-day IP certificates;
Certbot 5.4+ supports the webroot flow. This plan pins Certbot 5.9.0, keeps HTTP
available for ACME challenges, and requires automatic renewal. See
[Let's Encrypt's IP certificate instructions](https://letsencrypt.org/2026/03/11/shorter-certs-certbot).
Use a stable Elastic IP or a DNS name; changing the public IP invalidates this
certificate's identity.

Run the following in an **EC2 instance terminal** (SSH or EC2 Instance Connect),
from the application checkout. AWS CloudShell is a separate machine and cannot
configure the instance's Docker containers. The reviewed source files must first
be present in that checkout. Inspect the existing listener before enabling TLS:

```bash
sudo ss -lntp '( sport = :80 or sport = :443 )'
docker compose ps
```

Set `APP_HOST=54.66.191.38` in the production Compose environment. Set
`ACME_EMAIL` to an address controlled by the operator. Do not put a private key
or application token in these variables. Review the CA's terms before using
`--agree-tos` below.

```bash
export APP_HOST=54.66.191.38
export ACME_EMAIL=YOUR_CERTIFICATE_CONTACT_EMAIL

# Bootstrap serves /.well-known/acme-challenge/ without interrupting HTTP.
docker compose -f docker-compose.yml -f deploy/compose.tls-bootstrap.yml up -d --build frontend

# Validate issuance first against the staging CA (certificate is not trusted).
docker compose -f docker-compose.yml -f deploy/compose.tls-bootstrap.yml run --rm --no-deps certbot \
  certonly --staging --non-interactive --agree-tos --email "$ACME_EMAIL" \
  --preferred-profile shortlived --webroot --webroot-path /var/www/acme \
  --ip-address "$APP_HOST"

# After staging succeeds and production issuance is approved:
docker compose -f docker-compose.yml -f deploy/compose.tls-bootstrap.yml run --rm --no-deps certbot \
  certonly --non-interactive --agree-tos --email "$ACME_EMAIL" \
  --server https://acme-v02.api.letsencrypt.org/directory \
  --preferred-profile shortlived --webroot --webroot-path /var/www/acme \
  --ip-address "$APP_HOST" --force-renewal

docker compose -f docker-compose.yml -f deploy/compose.tls-bootstrap.yml -f deploy/compose.https.yml config --quiet
docker compose -f docker-compose.yml -f deploy/compose.tls-bootstrap.yml -f deploy/compose.https.yml up -d frontend backend
python3 scripts/verify_https.py "https://$APP_HOST" --output /tmp/agentic-https-verification.json
```

The HTTPS overlay publishes 443, redirects HTTP canonically, preserves ACME
challenges, enables TLS 1.2/1.3 and HSTS, and sets backend cookies to Secure.
For an IP address, browsers do not store HSTS policy; use the explicit HTTPS URL.
A DNS name is needed for browser HSTS enforcement ([RFC 6797](https://www.rfc-editor.org/rfc/rfc6797.html#section-8.1)).
Database volumes and authentication/RBAC remain in place. A successful TCP
connection or `curl -k` is not verification; the helper checks system-trusted
certificate validation, the IP/DNS identity, and the HTTPS health endpoint.

Schedule `APP_HOST=54.66.191.38 bash scripts/renew_tls.sh` every 12 hours from
the project checkout. Preserve the same Compose project/environment and files
for subsequent releases; the normal HTTP-only Compose command would omit TLS.
After successful issuance, persist `APP_HOST=54.66.191.38` and
`COMPOSE_FILE=docker-compose.yml:deploy/compose.tls-bootstrap.yml:deploy/compose.https.yml`
in the root `.env` used by Compose, preserving its other values. Do not persist
the HTTPS overlay before the certificate exists. This lets the existing deployment
script retain the HTTPS profile on subsequent releases. The local `/healthz`
probe checks Nginx liveness; it is separate from public certificate verification.
After HTTPS passes, set repository variable `PRODUCTION_HTTPS_ORIGIN` to
`https://54.66.191.38`. The existing deployment workflow will then verify that
public origin from GitHub's runner and preserve the certificate/health result as
an artifact. Invalid/untrusted certificates fail that step; no `-k` bypass exists.
Run renewal once and add a scheduled job with `crontab -e` (replace the checkout
path below with its absolute path on the instance):

```bash
APP_HOST=54.66.191.38 bash scripts/renew_tls.sh
crontab -e
# Add this line, using the actual checkout path:
0 */12 * * * cd /path/to/application && APP_HOST=54.66.191.38 bash scripts/renew_tls.sh >> /tmp/agentic-tls-renew.log 2>&1
```

Monitor renewal failures because IP certificates expire after six days.

If enabling TLS fails, restore the previous reviewed Compose configuration,
retain all named volumes, and investigate before retrying. Do not delete the
certificate or database volumes as a troubleshooting shortcut.

## Separate AWS findings

The supplied report also shows globally accessible SSH (`0.0.0.0/0` on 22)
and an unencrypted root EBS volume. Restrict SSH after verifying the operator's
and deployment runner's trusted access path; removing the broad rule blindly
can lock out the existing GitHub-hosted deployment runner. EBS encryption needs
an approved snapshot/encrypted-volume migration with rollback and a maintenance
window. Neither live AWS change has been performed from this workspace.

IMDSv2 is already required. Lack of an instance role explains why an SSM access
path cannot be assumed from the supplied output.
