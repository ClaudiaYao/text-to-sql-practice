-- The rsundqvist/sakila-preload image only ships the `postgres` superuser.
-- This creates the read-only `sakila` login that backend/.env expects. Run once per fresh container:
--   docker exec -i $(docker compose ps -q sakila-db) psql -U postgres -d sakila < backend/scripts/create_readonly_role.sql
-- Local development password only — change it for anything shared.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sakila') THEN
    CREATE ROLE sakila LOGIN PASSWORD 'p_ssW0rd';
  END IF;
END $$;

GRANT CONNECT ON DATABASE sakila TO sakila;
GRANT USAGE ON SCHEMA public TO sakila;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sakila;
ALTER ROLE sakila SET default_transaction_read_only = on;
