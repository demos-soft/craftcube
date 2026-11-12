"""Database schema versioning + migration runner (sql/migrations, tools/db)."""

import os
import sqlite3

import pytest

from app import db_migrations

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

EXPECTED_TABLES = {
    "users",
    "contacts",
    "contactgroups",
    "contactgroupmembers",
    "identities",
    "searches",
    "session",
    "collected_addresses",
    "responses",
    "schema_migrations",
    "system",
}


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ------------------------------------------------------------- fresh database
def test_fresh_store_gets_full_versioned_schema(tmp_path):
    from app.store import Store

    db = str(tmp_path / "fresh.sqlite")
    store = Store(db)
    assert store.schema_version() == 2
    conn = sqlite3.connect(db)
    assert tables(conn) >= EXPECTED_TABLES
    cols = [r[1] for r in conn.execute("PRAGMA table_info(contacts)")]
    assert "photo" in cols  # migration 0002 ran
    ver = conn.execute("SELECT value FROM system WHERE name='db_version'")
    assert ver.fetchone()[0] == "2"  # Roundcube-style version stamp
    conn.close()


def test_reopening_store_is_a_no_op(tmp_path):
    from app.store import Store

    db = str(tmp_path / "twice.sqlite")
    Store(db)
    store2 = Store(db)  # must not re-run or fail
    assert store2.schema_version() == 2
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert n == 2
    conn.close()


# --------------------------------------------------- pre-versioning databases
def _make_legacy_db(path):
    """A database as created before schema versioning existed: migration
    0001 (which has no photo column), no schema_migrations table."""
    conn = sqlite3.connect(path)
    with open(os.path.join(ROOT, "sql", "migrations", "0001_initial.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    for stmt in db_migrations._statements(sql):
        conn.execute(stmt)
    conn.commit()
    conn.close()


def test_legacy_database_is_stamped_not_replayed(tmp_path):
    from app.store import Store

    db = str(tmp_path / "legacy.sqlite")
    _make_legacy_db(db)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(contacts)")]
    assert "photo" not in cols
    conn.close()

    store = Store(db)  # simulates deploying new code
    assert store.schema_version() == 2
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(contacts)")]
    assert "photo" in cols  # 0002 genuinely applied
    names = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    assert len(names) == 2  # 0001 was stamped, 0002 executed
    conn.close()


def test_legacy_db_with_photo_stamps_both(tmp_path):
    from app.store import Store

    db = str(tmp_path / "legacy2.sqlite")
    _make_legacy_db(db)
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE contacts ADD COLUMN photo blob DEFAULT NULL")
    conn.commit()
    conn.close()
    store = Store(db)
    assert store.schema_version() == 2
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(contacts)")]
    assert "photo" in cols  # stamped, not re-added
    conn.close()


# --------------------------------------------------------- runner behaviours
@pytest.fixture
def fixture_migrations(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001_alpha.sql").write_text("CREATE TABLE alpha (id integer PRIMARY KEY);\n")
    return str(d)


def test_sequential_apply(tmp_path, fixture_migrations):
    db = str(tmp_path / "x.sqlite")
    conn = sqlite3.connect(db)
    assert db_migrations.current_version(conn) == 0
    assert len(db_migrations.pending(conn, fixture_migrations)) == 1
    applied = db_migrations.migrate(conn, fixture_migrations)
    assert applied == [(1, "0001_alpha.sql")]
    assert db_migrations.current_version(conn) == 1
    applied2 = db_migrations.migrate(conn, fixture_migrations)
    assert applied2 == []
    conn.close()


def test_failed_migration_rolls_back(tmp_path, fixture_migrations):
    db = str(tmp_path / "x.sqlite")
    conn = sqlite3.connect(db)
    db_migrations.migrate(conn, fixture_migrations)
    # a failing 0002 must not advance the version nor keep its table
    (tmp_path / "migrations" / "0002_boom.sql").write_text(
        "CREATE TABLE boom (id integer);SELECT bad_col FROM nonexistent_table;"
    )
    with pytest.raises(db_migrations.MigrationError):
        db_migrations.migrate(conn, fixture_migrations)
    assert db_migrations.current_version(conn) == 1
    assert "boom" not in tables(conn)
    conn.close()


def test_database_ahead_of_code_refuses(tmp_path, fixture_migrations):
    db = str(tmp_path / "x.sqlite")
    conn = sqlite3.connect(db)
    db_migrations.migrate(conn, fixture_migrations)
    (tmp_path / "migrations" / "0002_next.sql").write_text("SELECT 1;")
    db_migrations.migrate(conn, fixture_migrations)
    # now version 2 while only 0001 remains on disk (rollback deploy)
    os.remove(tmp_path / "migrations" / "0002_next.sql")
    with pytest.raises(db_migrations.MigrationError, match="newer"):
        db_migrations.migrate(conn, fixture_migrations)
    conn.close()


def test_numbering_must_be_gapless(tmp_path, fixture_migrations):
    (tmp_path / "migrations" / "0005_far.sql").write_text("SELECT 1;")
    with pytest.raises(db_migrations.MigrationError, match="gapless"):
        db_migrations.list_migrations(fixture_migrations)


def test_bad_filename_rejected(tmp_path, fixture_migrations):
    (tmp_path / "migrations" / "notes.sql").write_text("SELECT 1;")
    with pytest.raises(db_migrations.MigrationError, match="filename"):
        db_migrations.list_migrations(fixture_migrations)


# ------------------------------------------------------------- shipped files
def test_shipped_migrations_are_valid():
    files = db_migrations.list_migrations()
    assert files, "sql/migrations must ship with the app"
    assert files[0][0] == 1
    for _v, path in files:
        with open(path, encoding="utf-8") as fh:
            assert db_migrations._statements(fh.read())


def test_statement_splitter_handles_quotes_and_comments():
    sql = "-- a ; comment\nCREATE TABLE t (x text DEFAULT 'a;b');\nCREATE INDEX i ON t(x);\n"
    stmts = db_migrations._statements(sql)
    assert len(stmts) == 2


# -------------------------------------------------------------------- CLI
def test_cli_status_and_new(tmp_path, capsys):
    sys_path_patch = os.path.join(ROOT, "tools", "db.py")
    import importlib.util

    spec = importlib.util.spec_from_file_location("cc_db_cli", sys_path_patch)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    db = str(tmp_path / "cli.sqlite")
    conn = sqlite3.connect(db)
    db_migrations.migrate(conn)  # real migration set
    conn.close()
    assert cli.main(["--db", db, "status"]) == 0
    out = capsys.readouterr().out
    assert "up to date" in out and "schema version:" in out
    assert cli.main(["--db", db, "version"]) == 0
    assert capsys.readouterr().out.strip() == "2"
