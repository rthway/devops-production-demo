#!/bin/sh
# Fail fast and loudly: without -e a failed migration would be followed by the
# server starting anyway, against a schema that is not what the code expects.
set -eu

log() { printf '{"event":"%s","level":"info","component":"entrypoint"}\n' "$1"; }

# Migrations are opt-in via RUN_MIGRATIONS. Default off, because with N
# replicas every pod would race to migrate the same database on every rollout.
# In Kubernetes the migration runs once as a Job (see k8s/migration-job.yaml);
# in docker compose it is convenient to let the single container do it.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    log "waiting_for_database"
    python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from app.core.config import get_settings

dsn = get_settings().database_url
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with create_engine(dsn).connect() as c:
            c.execute(text("SELECT 1"))
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("database did not become reachable within 60s", file=sys.stderr)
sys.exit(1)
PY
    log "running_migrations"
    alembic upgrade head
    log "migrations_complete"
fi

log "starting_application"
exec "$@"
