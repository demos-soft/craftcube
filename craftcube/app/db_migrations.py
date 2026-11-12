"""Versioned SQL schema migrations.

The schema lives as numbered, immutable SQL files in ``sql/migrations/``
(the single source of truth; ``schema_version`` == highest applied number).
Applied files are recorded in ``schema_migrations``; the database itself
stamps the same fact into Roundcube's ``system`` table for humans probing
with plain sqlite3.

Runner contract
  * fresh database            -> every migration file is applied in order
  * pre-versioning database   -> files whose objects already exist are
    *stamped* as applied (check predicates below), never re-executed
  * every migration is transactional: SQL + bookkeeping row commit
    together, a failure leaves the version unchanged
  * a database ahead of the shipped files aborts loudly (no silent
    downgrade)

Adding a migration: see docs/DATABASE.md (tools/db.py new/apply/status).
"""

import itertools
import os
import re
import sqlite3
from datetime import datetime

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql", "migrations")

_TABLE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?([A-Za-z_][A-Za-z0-9_]*)", re.I)


# ------------------------------------------------------------- bootstrap checks
def _has_table(table):
    def check(conn):
        return (
            conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
        )

    check.__name__ = "has_table_" + table
    return check


def _has_column(table, column):
    def check(conn):
        return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))

    check.__name__ = f"has_column_{table}_{column}"
    return check


# version -> predicate meaning "this migration is ALREADY present in the
# schema" (used only to stamp databases created before versioning existed).
BOOTSTRAP_CHECKS = {
    1: _has_table("users"),
    2: _has_column("contacts", "photo"),
}


class MigrationError(RuntimeError):
    pass


def list_migrations(directory=None):
    """[(version, path)] sorted; enforces 4-digit, gapless, unique numbering."""
    directory = directory or SQL_DIR
    found = []
    for fn in sorted(os.listdir(directory)):
        if fn.endswith(".sql"):
            m = re.match(r"^(\d{4})_[A-Za-z0-9_]+\.sql$", fn)
            if not m:
                raise MigrationError(f"bad migration filename {fn!r} (want NNNN_name.sql)")
            found.append((int(m.group(1)), os.path.join(directory, fn)))
    found.sort()
    for (v1, _p1), (v2, _p2) in itertools.pairwise(found):
        if v2 != v1 + 1:
            raise MigrationError(f"migration numbering must be gapless and unique: jumped {v1:04d} -> {v2:04d}")
    if found and found[0][0] != 1:
        raise MigrationError("migrations must start at 0001")
    return found


def _ensure_meta(conn):
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version integer NOT NULL PRIMARY KEY,"
        "  name varchar(128) NOT NULL,"
        "  applied_at datetime NOT NULL);"
        "CREATE TABLE IF NOT EXISTS system ("
        "  name varchar(64) NOT NULL PRIMARY KEY,"
        "  value varchar(255) NOT NULL);"
    )


def current_version(conn):
    _ensure_meta(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def pending(conn, directory=None):
    """[(version, path)] not applied yet; bootstrap-present migrations are
    stamped rather than re-executed."""
    out = []
    for version, path in list_migrations(directory):
        if version <= current_version(conn):
            continue
        check = BOOTSTRAP_CHECKS.get(version)
        if check and check(conn):
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                (version, os.path.basename(path), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.execute("INSERT OR REPLACE INTO system(name, value) VALUES ('db_version', ?)", (str(version),))
            conn.commit()
            continue
        out.append((version, path))
    return out


def _statements(sql):
    """Split a migration script into complete statements. Uses SQLite's own
    completeness scanner, so quoted semicolons and -- comments are safe
    (and BEGIN ... END trigger bodies would stay intact)."""
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return out


def migrate(conn, directory=None):
    """Apply everything outstanding; returns [(version, name)] applied now.

    Each migration is atomic: statements and the bookkeeping row commit
    together (executescript() would pre-commit, so statements run one by
    one inside an explicit transaction).
    """
    _ensure_meta(conn)
    target = list_migrations(directory)
    if not target:
        return []
    head = current_version(conn)
    if head > target[-1][0]:
        raise MigrationError(
            f"database schema version {head} is newer than the migrations "
            f"shipped with this build ({target[-1][0]}) - refusing to run"
        )
    applied = []
    for version, path in pending(conn, directory):
        with open(path, encoding="utf-8") as fh:
            sql = fh.read()
        name = os.path.basename(path)
        conn.execute("BEGIN")
        try:
            for stmt in _statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                (version, name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.execute("INSERT OR REPLACE INTO system(name, value) VALUES ('db_version', ?)", (str(version),))
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationError(f"migration {name} failed: {exc}") from exc
        applied.append((version, name))
    return applied


# ------------------------------------------------------------------- CLI glue
def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=15)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def status(db_path, directory=None):
    conn = connect(db_path)
    try:
        pend = [(v, os.path.basename(p)) for v, p in pending(conn, directory)]
        cur = current_version(conn)
        rows = conn.execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY version").fetchall()
        head = (list_migrations(directory) or [(0, None)])[-1][0]
        return {"current": cur, "head": head, "pending": pend, "applied": [(r[0], r[1], r[2]) for r in rows]}
    finally:
        conn.close()


def apply(db_path, directory=None):
    conn = connect(db_path)
    try:
        return migrate(conn, directory)
    finally:
        conn.close()
