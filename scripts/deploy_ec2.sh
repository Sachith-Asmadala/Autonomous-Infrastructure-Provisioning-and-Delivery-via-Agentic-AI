#!/usr/bin/env bash
# Run via SSH stdin from the CI-tested revision. Never enable shell tracing.
set -euo pipefail

deploy_sha=${1:?Usage: bash scripts/deploy_ec2.sh CI_TESTED_SHA}
[[ "$deploy_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid deployment revision." >&2; exit 1; }
cd "${EC2_PROJECT_DIR:-$HOME/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI}"
for command in git docker curl python3 flock; do
  command -v "$command" > /dev/null || { echo "Missing prerequisite: $command" >&2; exit 1; }
done
docker compose version > /dev/null
exec 9> "$(git rev-parse --git-path ec2-deploy.lock)"
flock -n 9 || { echo "Another deployment holds the EC2 lock." >&2; exit 1; }

scratch_dir=$(mktemp -d)
cleanup() {
  result=$?
  trap - EXIT
  docker compose -f docker-compose.yml ps || true
  rm -rf "$scratch_dir"
  if [ "$result" -ne 0 ]; then
    echo "Deployment failed; inspect service logs on EC2. No volumes were removed." >&2
  fi
  exit "$result"
}
trap cleanup EXIT

git fetch origin main
latest_sha=$(git rev-parse origin/main)
if [ "$latest_sha" != "$deploy_sha" ]; then
  echo "Main changed after the CI gate. Refusing to deploy an untested revision." >&2
  exit 1
fi
previous_sha=$(git rev-parse HEAD)
success_marker=$(git rev-parse --git-path ec2-deploy.current)
if [ -f "$success_marker" ]; then
  previous_sha=$(cat "$success_marker")
  [[ "$previous_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid successful deployment marker." >&2; exit 1; }
  git cat-file -e "${previous_sha}^{commit}"
fi

# Validate both trees and target ignore rules BEFORE any force checkout/reset.
# Save only hashes, never secret contents, and verify them again afterwards.
python3 - "$deploy_sha" "$scratch_dir" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sha, scratch = sys.argv[1:]
scratch = Path(scratch)

def protected(name):
    parts = Path(name).parts
    return any(p == '.env' or (p.startswith('.env.') and p != '.env.example') for p in parts) or name.endswith(('.pem', '.key'))

current = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
target = subprocess.check_output(['git', 'ls-tree', '-rz', '--name-only', sha]).decode().split('\0')
if any(protected(name) for name in current + target if name):
    sys.exit('Refusing deployment: a protected secret path is tracked in the current or target tree.')
ignore_repo = scratch / 'ignore-check'
ignore_repo.mkdir()
subprocess.run(['git', 'init', '-q', str(ignore_repo)], check=True)
ignore = subprocess.check_output(['git', 'show', f'{sha}:.gitignore'])
(ignore_repo / '.gitignore').write_bytes(ignore)
files = [p for root in (Path('.'), Path('backend'), Path('frontend')) for p in root.glob('.env*')
         if p.name != '.env.example' and p.is_file()]
for path in files:
    if any(str(parent) in target for parent in path.parents if parent != Path('.')):
        sys.exit('Refusing deployment: a tracked target file would replace a secret directory.')
for name in target:
    if name and name != '.gitignore' and Path(name).name == '.gitignore':
        destination = ignore_repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(subprocess.check_output(['git', 'show', f'{sha}:{name}']))
probes = ['.env', 'backend/.env', 'frontend/.env', 'deploy.pem', 'deploy.key'] + [str(p) for p in files]
for name in probes:
    for cwd in (Path.cwd(), ignore_repo):
        result = subprocess.run(['git', '-c', 'core.excludesFile=/dev/null', 'check-ignore', '--no-index', '-q', name], cwd=cwd)
        if result.returncode != 0:
            sys.exit('Refusing deployment: current or target ignore rules do not protect secret files.')
digests = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(scratch / 'secret-digests.json').write_text(json.dumps(digests))
PY

test -f backend/.env || { echo "Missing EC2 backend/.env; provision it once before deployment." >&2; exit 1; }
docker compose -f docker-compose.yml config --quiet

# Record attached data volumes using the existing Compose project, before
# changing container names. A project/volume rename must never create an empty DB.
existing_volume() {
  local container_id
  container_id=$(docker compose -f docker-compose.yml ps -a -q "$1")
  if [ -n "$container_id" ]; then
    docker inspect --format "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" "$container_id"
  fi
}
postgres_volume=$(existing_volume db /var/lib/postgresql/data)
redis_volume=$(existing_volume redis /data)

# Only tracked source is replaced. No git clean; env files passed the preflight.
git checkout -f main
git reset --hard "$deploy_sha"
python3 - "$scratch_dir/secret-digests.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

for name, digest in json.loads(Path(sys.argv[1]).read_text()).items():
    path = Path(name)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        sys.exit('A production environment file changed; deployment stopped.')
print('Production environment files preserved.')
PY

docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml config --format json | python3 -c '
import json, sys
config = json.load(sys.stdin)
for service, key, previous in (("db", "postgres_data", sys.argv[1]), ("redis", "redis_data", sys.argv[2])):
    if previous and config["volumes"][key]["name"] != previous:
        sys.exit("Refusing deployment: " + service + " persistent volume name changed.")
' "$postgres_volume" "$redis_volume"

# Build first: a build failure leaves the currently running containers serving.
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d --remove-orphans
# Nginx resolves backend DNS at startup, so refresh it after backend recreation.
docker compose -f docker-compose.yml up -d --no-deps --force-recreate frontend
docker compose -f docker-compose.yml ps
for url in http://localhost/ http://localhost/api/v1/health; do
  curl --fail --silent --show-error --retry 12 --retry-all-errors \
    --retry-delay 5 --retry-max-time 180 --max-time 10 "$url" > /dev/null
done

if [ "$previous_sha" != "$deploy_sha" ]; then
  printf '%s\n' "$previous_sha" > "$(git rev-parse --git-path ec2-deploy.previous)"
fi
printf '%s\n' "$deploy_sha" > "$(git rev-parse --git-path ec2-deploy.current)"
echo "Deployment and frontend/API health checks succeeded for $deploy_sha."
