#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${PAYER_APP_PASSWORD:?PAYER_APP_PASSWORD is required}"

PSQL="/Library/PostgreSQL/18/bin/psql"
"$PSQL" "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/sql/001_schema.sql
"$PSQL" "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/sql/002_grants.sql
"$PSQL" "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/sql/003_app_user.sql
"$PSQL" "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "ALTER ROLE payer_app WITH LOGIN PASSWORD '$PAYER_APP_PASSWORD'"
echo "applied schema to claimsai"
