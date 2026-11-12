-- CraftCube schema migration 0002: contact photos.
-- The reference RC contacts table carries a photo blob; older CraftCube
-- databases were patched with an untracked ad-hoc ALTER, which this
-- migration formalises. Kept IF-style guarded (sqlite3 CLI rejects
-- "ADD COLUMN IF NOT EXISTS", so the runner's precondition hook in
-- app/db_migrations.py skips this file when the column already exists).

ALTER TABLE contacts ADD COLUMN photo blob DEFAULT NULL;
