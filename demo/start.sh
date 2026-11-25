#!/bin/sh
set -eu

if [ -n "${DATABASE_URL:-}" ]; then
    case "$DATABASE_URL" in
        postgres://*) export DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgres://}" ;;
        postgresql://*) export DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql://}" ;;
    esac
fi

alembic upgrade head

export RESEARCHHUB_FIXTURE_PASSWORD="${RESEARCHHUB_DEMO_PASSWORD:-synthetic-public-demo-only}"
export RESEARCHHUB_STORAGE="${RESEARCHHUB_STORAGE:-/tmp/researchhub-artifacts}"
mkdir -p "$RESEARCHHUB_STORAGE"

if python - <<'PY'
from sqlalchemy import select
from researchhub.db import connect
from researchhub.models import users

with connect().begin() as connection:
    raise SystemExit(0 if connection.execute(select(users.c.id).limit(1)).first() is None else 1)
PY
then
    python seed_browser_fixture.py
fi

nginx
python -m uvicorn researchhub.api:app --host 127.0.0.1 --port 8000 &
api_pid=$!
python -m researchhub.worker &
worker_pid=$!
python -m researchhub.scheduler &
scheduler_pid=$!

cleanup() {
    kill "$api_pid" "$worker_pid" "$scheduler_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$api_pid"
