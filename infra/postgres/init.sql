-- Local/CI database roles. Passwords here are for development only.
-- franchise_owner owns the schema and runs migrations; franchise_app is what the API uses
-- and is subject to row-level security (no BYPASSRLS, not an owner).
CREATE ROLE franchise_owner LOGIN PASSWORD 'owner';
CREATE ROLE franchise_app LOGIN PASSWORD 'app' NOBYPASSRLS;
CREATE DATABASE franchise OWNER franchise_owner;
CREATE DATABASE franchise_test OWNER franchise_owner;
