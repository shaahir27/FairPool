-- Extensions required by the initial migration: citext for case-insensitive
-- email and account keys, pg_trgm for the Postgres search fallback.
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
