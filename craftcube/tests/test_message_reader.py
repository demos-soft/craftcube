"""Standalone reader (/message) parity with reference ?_action=show.

Reference (verified live on staging): the plain message URL renders a
dedicated reader page — no sidebar/list columns — and the header toolbar
carries Print (main toolbar, absent from the More menu) plus prev/next
navigation ('prev'/'next' classes) wired to the folder list order.
"""
import re

import pytest

from app import views


class FakeBox:
    def __init__(self, uids):
        self.uids = uids
        self.prefs = {}

    def message_list(self, folder, **kw):
        return {"uids": list(self.uids), "count": len(self.uids),
                "items": [], "page": 1, "pages": 1,
                "total": len(self.uids), "first": 1, "last": len(self.uids)}

    def raw_message(self, folder, uid):
        return b""

    def __getattr__(self, name):
        # tolerate any other shell-side mailbox queries with no-op callables
        return lambda *a, **k: None


def _addr(name="Alice Example", email="alice@example.org"):
    return {"name": name, "email": email, "string": f"{name} <{email}>"}


@pytest.fixture()
def reader_ctx(monkeypatch):
    ctx = {
        "uid": "55", "folder": "INBOX",
        "subject": "Welcome to CraftCube staging", "subject_title": "x",
        "from": _addr(), "sender": _addr(),
        "from_addr": [("Alice Example", "alice@example.org")], "has_from": True,
        "to": [], "to_addr": [("Bob", "bob@example.org")],
        "cc_addr": [], "replyto_addr": [],
        "date": __import__("datetime").datetime(
            2026, 11, 3, 10, 24, tzinfo=__import__("datetime").timezone.utc),
        "date_short": "Nov 3",
        "parts": [("plain", "Hello!\n\nThis is a plain-text message.\n-- Alice")],
        "image_attachments": [],
        "attachments": [], "adr_links": {}, "a": "",
        "mdn": None, "photo_src": None, "remote_blocked": False,
        "optional_format": "html", "framed": False, "extwin": False,
        "print": False, "tb_active": True, "action": "show",
        "msg": {"message_id": "m1"},
    }
    monkeypatch.setattr(views, "imap_box", lambda *a, **k: FakeBox(["56", "55", "54"]))
    monkeypatch.setattr(views, "build_message_ctx", lambda box, folder, uid, **kw: dict(ctx, uid=uid))
    monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])
    return ctx


class TestReaderPage:
    def test_renders_reader_not_shell(self, client, reader_ctx):
        r = client.get("/message?_mbox=INBOX&_uid=55")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        # dedicated reader: no folder sidebar, no message list column
        assert 'id="layout-list"' not in html
        assert 'id="messagelist"' not in html
        assert 'id="mailboxlist"' not in html

    def test_plain_part_nl2br(self, client, reader_ctx):
        # reference (verified live): the plain part renders as
        # <div class="message-part" id="message-partN"><div class="pre">…<br>
        # newlines converted to <br> (white-space CSS is 'normal')
        html = client.get("/message?_mbox=INBOX&_uid=55").get_data(as_text=True)
        assert 'id="message-part1"' in html
        assert '<div class="pre">Hello!<br>' in html

    def test_print_in_main_toolbar_only(self, client, reader_ctx):
        html = client.get("/message?_mbox=INBOX&_uid=55").get_data(as_text=True)
        assert 'id="tb-print-message"' in html
        assert "_print=1" in html
        # reference reader: no Print entry in the More menu anymore
        assert 'id="tb-print"' not in html

    def test_prev_next_navigation(self, client, reader_ctx):
        # FakeBox order ["56","55","54"] = date-desc listing; 55 is mid-list
        html = client.get("/message?_mbox=INBOX&_uid=55").get_data(as_text=True)
        assert 'class="prev"' in html and "_uid=56" in html   # row above = newer
        assert 'class="next"' in html and "_uid=54" in html

    def test_prev_disabled_at_top_boundary(self, client, reader_ctx):
        html = client.get("/message?_mbox=INBOX&_uid=56").get_data(as_text=True)
        assert 'class="prev disabled"' in html
        assert 'class="next"' in html

    def test_list_toolbar_has_no_reader_buttons(self, client, reader_ctx):
        # the shell list toolbar must stay exactly like the reference list
        # view: no print/prev/next in the header
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="tb-print-message"' not in html
        assert 'class="prev"' not in html and 'class="next"' not in html

    def test_list_toolbar_thread_button(self, client, reader_ctx):
        # reference #toolbar-list-menu is always Select | Threads | Options
        # (verified live: Threads stays rendered, disabled, even with the
        # preview pane open)
        for url in ("/mail?_mbox=INBOX", "/mail?_mbox=INBOX&_uid=55"):
            html = client.get(url).get_data(as_text=True)
            m = html[html.index('id="toolbar-list-menu"'):]
            order = re.findall(r'class="(select|threads|options)', m)
            assert order[:3] == ["select", "threads", "options"], url
