#!/bin/sh
# Run inside this stack's PostgreSQL container; no credentials on command lines.
set -eu
export PGHOST=127.0.0.1 PGCONNECT_TIMEOUT=5
check_service() (
    service=$1
    migration_password=$2
    runtime_password=$3
    opposite=$4
    table="infra_smoke_$$"
    denied="infra_denied_$$"
    export PGDATABASE="${service}_db"
    cleanup() {
        PGPASSWORD=$migration_password psql -X -v ON_ERROR_STOP=1 -U "${service}_migrator" \
            -c "DROP TABLE IF EXISTS public.$table, public.$denied" >/dev/null
    }
    trap cleanup EXIT
    PGPASSWORD=$migration_password psql -X -v ON_ERROR_STOP=1 -U "${service}_migrator" \
        -c "CREATE TABLE public.$table (id integer PRIMARY KEY)" >/dev/null
    PGPASSWORD=$runtime_password psql -X -v ON_ERROR_STOP=1 -U "${service}_runtime" \
        -c "INSERT INTO public.$table VALUES (1); SELECT * FROM public.$table; DELETE FROM public.$table" >/dev/null
    if PGPASSWORD=$runtime_password psql -X -v ON_ERROR_STOP=1 -U "${service}_runtime" \
        -c "CREATE TABLE public.$denied (id integer)" >/dev/null 2>&1; then
        echo "Runtime role unexpectedly allowed DDL" >&2; exit 1
    fi
    for role in runtime migrator; do
        case "$role" in
            runtime) password=$runtime_password ;;
            migrator) password=$migration_password ;;
        esac
        if PGPASSWORD=$password psql -X -v ON_ERROR_STOP=1 -U "${service}_$role" \
            -d "${opposite}_db" -c 'SELECT 1' >/dev/null 2>&1; then
            echo "Role unexpectedly connected to opposite database" >&2; exit 1
        fi
    done
)
check_service media "$MEDIA_MIGRATION_PASSWORD" "$MEDIA_RUNTIME_PASSWORD" processing
check_service processing "$PROCESSING_MIGRATION_PASSWORD" "$PROCESSING_RUNTIME_PASSWORD" media
echo "Both database owners/runtime grants and cross-database/DDL denials passed."
