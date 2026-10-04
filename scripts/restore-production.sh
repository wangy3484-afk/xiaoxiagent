#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# < 2 || $# > 3 )); then
  echo "Usage: $0 ENV_FILE BACKUP_DIRECTORY [COMPOSE_PROJECT]" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$(realpath "$1")"
backup_dir="$(realpath "$2")"
project="${3:-ops-strategy-agent-prod}"
compose=(docker compose -p "$project" --env-file "$env_file" -f "$repo_root/compose.production.yaml")

if [[ ! -f "$backup_dir/COMPLETE" ]]; then
  echo "Backup is incomplete: $backup_dir" >&2
  exit 2
fi
(cd "$backup_dir" && sha256sum --check --status SHA256SUMS)

# Restoration is deliberately restricted to an empty destination.
"${compose[@]}" up -d --wait postgres redis >&2
public_tables="$("${compose[@]}" exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname = '\''public'\''"')"
if [[ "$public_tables" != "0" ]]; then
  echo "Destination database is not empty; restore refused" >&2
  exit 2
fi

artifact_probe="$("${compose[@]}" run --rm --no-deps -T --entrypoint sh api \
  -c 'find /app/artifacts -mindepth 1 -print -quit')"
if [[ -n "$artifact_probe" ]]; then
  echo "Destination artifact volume is not empty; restore refused" >&2
  exit 2
fi

"${compose[@]}" exec -T postgres sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl' \
  < "$backup_dir/postgres.dump"
"${compose[@]}" run --rm --no-deps -T --entrypoint tar api \
  -C /app/artifacts -xf - < "$backup_dir/artifacts.tar"

restored_inventory="$("${compose[@]}" run --rm --no-deps -T --entrypoint python api \
  -m ops_agent.persistence.backup_validation)"
if [[ "$restored_inventory" != "$(< "$backup_dir/inventory.json")" ]]; then
  echo "Restored database or exported files differ from backup inventory" >&2
  exit 1
fi

"${compose[@]}" up -d >&2
echo "Restore complete: $project" >&2
