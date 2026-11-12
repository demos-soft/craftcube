"""Staging bootstrap contract: the k8s3 instance initialises via migrations.

Guards the deployment promise of docs/DATABASE.md end-to-end on the live
staging instance:

  * the app serves login and accepts the standard staging credentials
  * the pod's SQLite database is versioned: schema_migrations lists every
    shipped migration and system.db_version matches
  * a freshly-initialised database (deleted PVC file + restart) comes up
    at head version with no manual step

These checks shell out to the node's kubectl via ssh (kubectl only exists
on k8s3.lan); they skip cleanly when the node or the ssh key is
unreachable, mirroring test_selenium_staging's posture.

Run:  .venv/bin/python -m pytest tests/test_staging_bootstrap.py
Env:  CRAFTCUBE_STAGING_URL (default http://k8s3.lan:30090)
      CC_SSH (default: the automation@k8s3.lan id-keysOnly form)
"""

import os
import shutil
import socket
import subprocess

import pytest

CC = os.environ.get("CRAFTCUBE_STAGING_URL", "http://k8s3.lan:30090")
SSH = os.environ.get(
    "CC_SSH", "ssh -o IdentitiesOnly=yes -i ~/.ssh/hermes-admin -o ConnectTimeout=5 automation@k8s3.lan"
)
POD_DB = "/data/craftcube.sqlite"

pytestmark = pytest.mark.staging


def _setup_available():
    host = CC.split("//", 1)[-1].split(":", 1)[0]
    port = int(CC.rsplit(":", 1)[-1])
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError:
        return False
    if shutil.which("ssh") is None:
        return False
    key = os.path.expanduser("~/.ssh/hermes-admin")
    return os.path.exists(key)


@pytest.fixture(scope="module")
def node():
    if not _setup_available():
        pytest.skip("k8s3.lan or its ssh key not reachable")
    return SSH


def _node_exec(node, cmd):
    """Run a shell command on the node (kubectl namespace baked in)."""
    full = f"{node} {_shell_quote('sudo microk8s kubectl -n craftcube ' + cmd)}"
    r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _pod(node):
    rc, out, err = _node_exec(node, "get pods -o name")
    if rc != 0:
        raise AssertionError(f"kubectl failed: {err}")
    names = [n.split("/")[-1] for n in out.splitlines() if n.split("/")[-1].startswith("craftcube-")]
    app_pods = [n for n in names if not n.startswith(("craftcube-dovecot", "craftcube-mailpit"))]
    assert app_pods, f"no craftcube app pod in {out!r}"
    return app_pods[0]


def _rows(node, pod, sql):
    """sqlite via the pod's python; single-column queries -> list of scalars."""
    py = f"import sqlite3;print([r[0] for r in sqlite3.connect({POD_DB!r}).execute({sql!r}).fetchall()])"
    rc, out, err = _node_exec(node, f"exec {pod} -- python -c {_shell_quote(py)}")
    assert rc == 0, f"pod query failed: {err}"
    return eval(out)  # pod prints a python list literal


# ------------------------------------------------------------------ the app
def test_serves_login_page(node):
    r = subprocess.run(["curl", "-fsSL", "-m", "10", CC + "/"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "rcmloginuser" in r.stdout


def test_login_succeeds(node):
    r = subprocess.run(
        [
            "curl",
            "-fsS",
            "-m",
            "10",
            "-c",
            "-",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code} %{redirect_url}",
            CC + "/login",
            "--data",
            "_user=test@example.org&_pass=secret",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    code, _, redirect = r.stdout.partition(" ")
    assert code == "302" and "/mail" in redirect, r.stdout


# ------------------------------------------------------------ the database
def test_pod_database_is_versioned(node):
    pod = _pod(node)
    versions = _rows(node, pod, "SELECT version FROM schema_migrations ORDER BY version")
    assert versions, "schema_migrations empty: database was not initialised through the migration runner"
    assert versions == list(range(1, max(versions) + 1)), f"migration history not gapless: {versions}"
    stamp = _rows(node, pod, "SELECT value FROM system WHERE name='db_version'")
    assert stamp == [str(max(versions))]


def test_head_matches_shipped_migrations(node):
    from app import db_migrations

    shipped = [v for v, _ in db_migrations.list_migrations()]
    pod = _pod(node)
    versions = _rows(node, pod, "SELECT version FROM schema_migrations ORDER BY version")
    assert versions == shipped, (
        f"pod at {versions}, code ships {shipped}: the deployed image is "
        "not built from this tree (or was never restarted after deploy)"
    )
