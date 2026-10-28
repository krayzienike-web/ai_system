#!/bin/sh
# The database roles of the demo stand (deploy/compose.yml): passwords from the environment, none in the image.
# franchise_owner owns the schema and runs migrations; franchise_app is what the API uses, under row-level security.
# Passwords go in as psql variables (:'name' quotes them), so any character is safe.
set -eu
psql -v ON_ERROR_STOP=1 --username postgres \
  -v owner_pw="$OWNER_DB_PASSWORD" -v app_pw="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE franchise_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE franchise_app LOGIN PASSWORD :'app_pw' NOBYPASSRLS;
CREATE DATABASE franchise OWNER franchise_owner;
SQL
