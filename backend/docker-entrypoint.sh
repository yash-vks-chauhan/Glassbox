#!/bin/sh
# Bring the schema to head, then hand over to the server. Safe when several
# replicas start at once: migrations hold a Postgres advisory lock (see
# app/core/schema_lock.py), so the first one migrates and the rest find
# the database at head. Set GLASSBOX_SKIP_MIGRATIONS=1 to run them
# separately (e.g. as a one-off task before a deploy).
set -e
if [ "${GLASSBOX_SKIP_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
fi
exec "$@"
