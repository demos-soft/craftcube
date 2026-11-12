# Database schema: initialization and migrations

CraftCube keeps its metadata (users, contacts, contact lists, identities,
sessions, ...) in SQLite. Mail itself lives on the IMAP server; only this
small database is stored locally (`CRAFTCUBE_DB`, default
`./data/craftcube.sqlite`).

The schema is **versioned** and ships as plain SQL files:

```
craftcube/
  sql/migrations/
    0001_initial.sql          # baseline: all core tables (schema_version 1)
    0002_contact_photo.sql    # ALTER TABLE contacts ADD COLUMN photo
    ...                       # future migrations: strictly sequential numbers
  app/db_migrations.py        # the migration runner (used by app + tools)
  tools/db.py                 # command-line helper: status / apply / new
```

## How versioning works

* The **schema version** is the highest migration number applied. Every
  applied file is recorded in the `schema_migrations` table
  (`version`, `name`, `applied_at`), and the same number is kept in
  Roundcube's `system` table under `db_version` for anyone inspecting the
  database with plain `sqlite3`.
* **A fresh instance needs no manual setup.** On startup the application
  opens the database and applies every outstanding migration inside its
  normal boot path, so a new deployment (Docker, k8s, bare `run.py`) just
  works — point `CRAFTCUBE_DB` at a path and start the app.
* **Existing databases are upgraded the same way**: rolling out a new
  build applies the new migration files automatically at first start.
* Databases created **before versioning existed** are detected: migration
  files whose objects are already present are *stamped* as applied instead
  of being re-executed (the predicates live in `BOOTSTRAP_CHECKS` in
  `app/db_migrations.py`).
* If the database is **newer than the code** (a rollback of an app deploy),
  startup aborts loudly rather than corrupting the newer schema.
* Each migration is **atomic**: all its statements plus the bookkeeping row
  commit in one transaction; a failure leaves the version unchanged.

## Checking / upgrading manually

```console
$ cd craftcube
$ .venv/bin/python tools/db.py status          # current/head + applied/pending
$ .venv/bin/python tools/db.py apply           # apply pending migrations
$ .venv/bin/python tools/db.py version         # just the number
$ .venv/bin/python tools/db.py --db /path/to/craftcube.sqlite status
```

`tools/db.py status` exits non-zero while migrations are pending, so it can
gate a deploy.

## Adding a migration

1. Scaffold the next file (the tool picks the number for you):

   ```console
   $ .venv/bin/python tools/db.py new add_folder_cache
   created .../sql/migrations/0003_add_folder_cache.sql
   ```

2. Edit the file. Rules:
   * Numbers are **strictly sequential** (`0001`, `0002`, `0003`, ...);
     gaps or duplicates are rejected by the runner and the test suite.
   * Statements run in **one transaction** per file — SQLite supports
     transactional DDL, so a half-applied migration cannot survive.
   * Migration files are **immutable once committed**. If you ship a bug,
     fix it in the next number; never edit a file that may already be
     applied somewhere (the runner has no checksums — discipline is the
     contract, mirroring Roundcube's `SQL/*.sqlite*.sql` history files).
3. If older, pre-versioning databases might already contain the new
   objects, add a predicate to `BOOTSTRAP_CHECKS`
   (`app/db_migrations.py`) so the migration is stamped rather than
   replayed there. For normal databases added after versioning this is not
   needed — their version history is exact.
4. Extend `tests/test_db_migrations.py` if the migration changes
   behaviour tests care about, then verify:

   ```console
   $ .venv/bin/python -m pytest tests/test_db_migrations.py -q
   $ .venv/bin/python tools/db.py --db data/craftcube.sqlite apply
   ```

5. Commit the `.sql` file together with the code that uses the new schema.
   Deploying the app is enough — no separate migration step is required.

## Reference layout (Roundcube)

The baseline mirrors `roundcubemail/SQL/sqlite.initial.sql` restricted to
the tables this app implements (`users`, `contacts`, `contactgroups`,
`contactgroupmembers`, `identities`, `searches`, `session`,
`collected_addresses`, `responses`) plus the two bookkeeping tables
(`schema_migrations`, `system`).
