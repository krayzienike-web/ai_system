#!/bin/sh
# The database roles of the demo stand (deploy/compose.yml): passwords from the environment, none in the image.
# franchise_owner owns the schema and runs migrations; franchise_app is what the API uses, under row-level security.
set -eu
psql -v ON_ERROR_STOP=1 --username postgres <<SQL
CREATE ROLE franchise_owner LOGIN PASSWORD '${OWNER_DB_PASSWORD}';
CREATE ROLE franchise_app LOGIN PASSWORD '${APP_DB_PASSWORD}' NOBYPASSRLS;
CREATE DATABASE franchise OWNER franchise_owner;
SQL
