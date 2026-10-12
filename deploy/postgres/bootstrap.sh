#!/bin/sh
# Fresh Project 2 databases; safe to rerun without deleting data.
set -eu

: "${POSTGRES_USER:?}"
: "${MEDIA_MIGRATION_PASSWORD:?}"
: "${MEDIA_RUNTIME_PASSWORD:?}"
: "${PROCESSING_MIGRATION_PASSWORD:?}"
: "${PROCESSING_RUNTIME_PASSWORD:?}"

for service in media processing; do
    case "$service" in
        media)
            migration_password=$MEDIA_MIGRATION_PASSWORD
            runtime_password=$MEDIA_RUNTIME_PASSWORD
            ;;
        processing)
            migration_password=$PROCESSING_MIGRATION_PASSWORD
            runtime_password=$PROCESSING_RUNTIME_PASSWORD
            ;;
    esac
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
        -v database="${service}_db" \
        -v migrator="${service}_migrator" -v runtime="${service}_runtime" \
        -v migration_password="$migration_password" -v runtime_password="$runtime_password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'migrator')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'migrator') \gexec
SELECT format('CREATE ROLE %I LOGIN', :'runtime')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'runtime') \gexec
ALTER ROLE :"migrator" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    PASSWORD :'migration_password';
ALTER ROLE :"runtime" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    PASSWORD :'runtime_password';
SELECT format('CREATE DATABASE %I OWNER %I', :'database', :'migrator')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'database') \gexec
REVOKE ALL ON DATABASE :"database" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database" TO :"migrator", :"runtime";
SQL

    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${service}_db" \
        -v migrator="${service}_migrator" -v runtime="${service}_runtime" <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO :"migrator";
GRANT USAGE ON SCHEMA public TO :"runtime";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"runtime";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"runtime";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"runtime";
SQL
done
