#!/usr/bin/env bash
# Verify / Tests: prove the Alembic migrations apply cleanly to an EMPTY PostgreSQL database and that
# there is exactly one head. Runs inside CodeBuild (Amazon Linux 2023) as root; PostgreSQL itself
# runs as the unprivileged `postgres` user and listens on localhost only. SYNTHETIC database only.
set -euo pipefail

initdb_bin="$(command -v initdb || ls /usr/bin/initdb /usr/lib64/pgsql*/bin/initdb /usr/pgsql-*/bin/initdb 2>/dev/null | head -n 1 || true)"
if [[ -z "${initdb_bin}" ]]; then
  echo "initdb not found (is postgresql-server installed?)" >&2
  exit 1
fi
pg_bin="$(dirname "${initdb_bin}")"
data_dir="$(mktemp -d /tmp/pgdata.XXXXXX)"
chown postgres:postgres "${data_dir}"

runuser -u postgres -- "${pg_bin}/initdb" -D "${data_dir}" -A trust -U postgres >/dev/null
runuser -u postgres -- "${pg_bin}/pg_ctl" -D "${data_dir}" -l "${data_dir}/server.log" \
  -o "-c listen_addresses=localhost -k ${data_dir}" -w start
trap 'runuser -u postgres -- "${pg_bin}/pg_ctl" -D "${data_dir}" -m fast stop >/dev/null || true' EXIT

"${pg_bin}/psql" -h localhost -U postgres -v ON_ERROR_STOP=1 -q \
  -c "CREATE ROLE ora LOGIN PASSWORD 'ora';" \
  -c "CREATE DATABASE ora OWNER ora;"

cd "${CODEBUILD_SRC_DIR:-.}/backend"
heads="$(python -m alembic heads | grep -c '(head)' || true)"
if [[ "${heads}" -ne 1 ]]; then
  echo "Expected exactly 1 Alembic head, found ${heads}:" >&2
  python -m alembic heads >&2
  exit 1
fi

export ORA_DATABASE_URL="postgresql+psycopg://ora:ora@localhost:5432/ora"
python -m alembic upgrade head
echo "Migrations applied cleanly to an empty PostgreSQL: $(python -m alembic current 2>/dev/null | tail -n 1)"
