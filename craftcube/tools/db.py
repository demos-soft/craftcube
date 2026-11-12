#!/usr/bin/env python3
"""CraftCube database maintenance tool (development / ops use).

The schema lives in craftcube/sql/migrations/NNNN_name.sql; schema_version
equals the highest applied number. The web app applies outstanding
migrations automatically at startup — this tool is for inspecting the
state and for upgrading a database before/at a deploy.

Commands
  status                show current/head version and pending migrations
  apply                 apply all pending migrations
  new NAME              scaffold the next migration file (0003_NAME.sql)
  version               print just the current schema version

The database is the configured one (CRAFTCUBE_DB, default
./data/craftcube.sqlite); override with --db PATH.

Examples
  python tools/db.py status
  python tools/db.py new add_folder_cache
  python tools/db.py apply --db /var/lib/craftcube/craftcube.sqlite
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import db_migrations  # noqa: E402

DEFAULT_DB = os.environ.get("CRAFTCUBE_DB", os.path.join(_ROOT, "data", "craftcube.sqlite"))


def _cmd_status(args):
    st = db_migrations.status(args.db)
    print(f"database: {args.db}")
    print(f"schema version: {st['current']} (head: {st['head']})")
    if st["applied"]:
        print("applied:")
        for version, name, when in st["applied"]:
            print(f"  {version:04d}  {name:<36} {when}")
    else:
        print("applied: (none - fresh database)")
    if st["pending"]:
        print("pending:")
        for version, name in st["pending"]:
            print(f"  {version:04d}  {name}")
        print("run: python tools/db.py apply")
        return 1
    print("pending: (none - up to date)")
    return 0


def _cmd_apply(args):
    if not os.path.exists(args.db):
        print(
            f"error: database {args.db} does not exist (it is created automatically on first app start)",
            file=sys.stderr,
        )
        return 2
    applied = db_migrations.apply(args.db)
    if not applied:
        print("already up to date")
    for version, name in applied:
        print(f"applied {version:04d} {name}")
    print(f"schema version: {db_migrations.status(args.db)['current']}")
    return 0


def _cmd_new(args):
    name = args.name.lower().replace("-", "_")
    if not name.replace("_", "").isalnum():
        print("error: migration name must be alphanumeric/underscore", file=sys.stderr)
        return 2
    files = db_migrations.list_migrations()
    nxt = (files[-1][0] + 1) if files else 1
    path = os.path.join(db_migrations.SQL_DIR, f"{nxt:04d}_{name}.sql")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"""-- CraftCube schema migration {nxt:04d}: {args.name}.
-- TODO: describe what this migration changes.
-- Notes: statements run in ONE transaction per file; SQLite supports
-- transactional DDL. If an object may already exist in pre-versioning
-- databases, add a BOOTSTRAP_CHECKS predicate in app/db_migrations.py so
-- the migration is stamped instead of re-executed. Never edit shipped
-- migrations (docs/DATABASE.md).

""")
    print("created", path)
    return 0


def _cmd_version(args):
    print(db_migrations.status(args.db)["current"])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="db.py",
        description="CraftCube database maintenance (schema migrations)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="current/head/pending versions")
    sub.add_parser("apply", help="apply pending migrations")
    p_new = sub.add_parser("new", help="scaffold the next migration file")
    p_new.add_argument("name")
    sub.add_parser("version", help="print the current schema version")
    args = ap.parse_args(argv)
    return {"status": _cmd_status, "apply": _cmd_apply, "new": _cmd_new, "version": _cmd_version}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
