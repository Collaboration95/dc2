-- Run only with private pgpass and redirect into a 0600 roles.sql. Do not publish.
-- Restrict to the existing four owner identities; do not restore postgres/SSM roles.
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L;',
              rolname, rolpassword)
FROM pg_authid
WHERE rolname IN ('media_migrator', 'media_runtime', 'processing_migrator', 'processing_runtime')
ORDER BY rolname;
