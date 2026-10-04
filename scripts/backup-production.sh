#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# < 2 || $# > 3 )); then
  echo "Usage: $0 ENV_FILE BACKUP_DIRECTORY [COMPOSE_PROJECT]" >&2
  exit 2
fi

umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$(realpath "$1")"
backup_dir="$2"
project="${3:-ops-strategy-agent-prod}"
compose=(docker compose -p "$project" --env-file "$env_file" -f "$repo_root/compose.production.yaml")

if [[ -e "$backup_dir" ]]; then
  echo "Backup destination already exists: $backup_dir" >&2
  exit 2
fi
mkdir -p "$(dirname "$backup_dir")"
mkdir -m 700 "$backup_dir"

stopped=0
resume_services() {
  if (( stopped )); then
    "${compose[@]}" start api worker web proxy >&2
  fi
}
trap resume_services EXIT

# A short maintenance window makes the database dump and artifact archive one snapshot.
"${compose[@]}" stop proxy web api worker >&2
stopped=1

"${compose[@]}" exec -T postgres sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
  > "$backup_dir/postgres.dump"
"${compose[@]}" run --rm --no-deps -T --entrypoint tar api \
  -C /app/artifacts -cf - . > "$backup_dir/artifacts.tar"
"${compose[@]}" run --rm --no-deps -T --entrypoint python api \
  -m ops_agent.persistence.backup_validation > "$backup_dir/inventory.json"

(cd "$backup_dir" && sha256sum postgres.dump artifacts.tar inventory.json > SHA256SUMS)
printf 'complete\n' > "$backup_dir/COMPLETE"
echo "Backup complete: $backup_dir" >&2
