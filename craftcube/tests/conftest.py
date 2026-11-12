"""Shared fixtures: an app instance on a temp DB, isolated from IMAP."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "DB_PATH": str(tmp_path / "test.sqlite"),
        "SECRET_KEY": "test-secret",
        # nothing in these tests talks to a real server
        "IMAP_HOST": "127.0.0.1",
        "IMAP_PORT": 1,
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": 1,
    })
    yield application


@pytest.fixture()
def store(app):
    return app.store


@pytest.fixture()
def user(store):
    from app.auth import hash_password
    return store.create_user("unit@example.org", hash_password("secret"))


@pytest.fixture()
def client(app, user):
    """Logged-in client: session keys mirror what POST /login sets."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = user
        sess["username"] = "unit@example.org"
        sess["imap_password"] = "secret"
    return c


@pytest.fixture()
def anon_client(app):
    return app.test_client()
