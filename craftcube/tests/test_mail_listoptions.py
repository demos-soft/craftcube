"""List-options persistence + list-context link carry.

Reference contract (skins/elastic/ui.js menu_messagelist + program/js/app.js
set_list_options/set_list_sorting + filter_mailbox): the dialog's Save is not
a one-shot URL rewrite — the chosen sort column/order becomes the session's
list state and the list mode is stored per folder, so opening a message,
paging, or clicking a column header keeps it. Craft is SSR: the equivalent
is persisting to user prefs on save and carrying the context in mail links.
"""
import base64
import html as html_lib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app import views

_NOW = datetime(2026, 11, 3, 10, 24, tzinfo=UTC)
ITEMS = [
    {
        "uid": str(100 - i), "subject": f"Msg {i}", "fromto": "Sender <s@example.org>",
        "folder": None, "date": _NOW, "size": (10 - i) * 100, "seen": True,
        "flagged": False, "replied": False, "forwarded": False, "deleted": False,
        "depth": 0, "ml": False,
    }
    for i in range(3)
]


class Box:
    """Recording fake of ImapBox for the /mail listing path."""

    def __init__(self):
        self.prefs = {}
        self.calls = []

    def message_list(self, folder, **kw):
        self.calls.append(dict(folder=folder, **kw))
        page = kw.get("page", 1)
        return {"items": ITEMS, "page": page, "pages": 3, "total": 30,
                "first": (page - 1) * 10 + 1, "last": (page - 1) * 10 + 3,
                "uids": [i["uid"] for i in ITEMS]}

    def quota_usage(self):
        return (0, 0)


@pytest.fixture()
def box(app, user, monkeypatch):
    b = Box()
    # imap_box() attaches the signed-in user's preferences to the box
    monkeypatch.setattr(
        views, "imap_box",
        lambda *a, **k: (setattr(b, "prefs", dict(app.store.get_user_prefs(user))) or b))
    monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])
    return b


def _hrefs(html, needle):
    out = []
    for chunk in html.split('href="')[1:]:
        href = html_lib.unescape(chunk.split('"', 1)[0])
        if needle in href:
            out.append(href)
    return out


class TestSaveOpts:
    def test_save_redirects_without_save_flag(self, client, box):
        r = client.get("/mail?_save_opts=1&_sort=size&_sort_order=ASC&_mode=list",
                       follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "_save_opts" not in loc
        q = parse_qs(urlparse(loc).query)
        assert q.get("_sort") == ["size"]
        assert q.get("_mode") == ["list"]

    def test_save_persists_prefs(self, client, app, user, box):
        client.get("/mail?_save_opts=1&_sort=size&_sort_order=ASC&_mode=list")
        prefs = app.store.get_user_prefs(user)
        assert prefs.get("message_sort_col") == "size"
        assert prefs.get("message_sort_order") == "asc"
        assert (prefs.get("folder_viewmodes") or {}).get("INBOX") == "list"

    def test_saved_prefs_are_the_new_defaults(self, client, app, user, box):
        app.store.set_user_pref(user, "message_sort_col", "size")
        app.store.set_user_pref(user, "message_sort_order", "asc")
        app.store.set_user_pref(user, "folder_viewmodes", {"INBOX": "list"})
        r = client.get("/mail")
        assert r.status_code == 200
        call = box.calls[-1]
        assert call["sort"] == "size"
        assert call["order"] == "asc"
        assert call["threads"] is False
        html = r.get_data(as_text=True)
        assert "size sorted asc" in html
        assert "thread-root" not in html

    def test_explicit_url_still_wins(self, client, app, user, box):
        app.store.set_user_pref(user, "message_sort_col", "size")
        client.get("/mail?_sort=date&_sort_order=asc&_mode=threads")
        call = box.calls[-1]
        assert call["sort"] == "date"
        assert call["order"] == "asc"
        assert call["threads"] is True

    def test_fromto_pref_stays_smart(self, client, app, user, box):
        # 'fromto' from the dialog keeps the smart Sent/Drafts->to mapping
        app.store.set_user_pref(user, "message_sort_col", "fromto")
        client.get("/mail")
        assert box.calls[-1]["sort"] in ("from", "to")


class TestContextCarry:
    def test_pagination_keeps_mode_and_filter(self, client, box):
        r = client.get("/mail?_mode=list&_filter=UNSEEN")
        html = r.get_data(as_text=True)
        page_links = _hrefs(html, "_page=2")
        assert page_links, "next-page link missing"
        for href in page_links:
            assert "_mode=list" in href
            assert "_filter=UNSEEN" in href
            assert "_sort" not in href  # arrival default must not leak in

    def test_header_sort_keeps_mode_and_filter(self, client, box):
        r = client.get("/mail?_mode=list&_filter=UNSEEN")
        html = r.get_data(as_text=True)
        links = _hrefs(html, "_sort=")
        assert links
        for href in links:
            assert "_mode=list" in href
            assert "_filter=UNSEEN" in href

    def test_search_terms_survive_paging(self, client, box):
        r = client.get("/mail?_q=hello&_mode=threads&_page=2")
        html = r.get_data(as_text=True)
        # earlier/first-page links must carry the term back
        assert any("_q=hello" in h and "_page=1" in h for h in _hrefs(html, "_page=1"))
        assert any("_mode=threads" in h for h in _hrefs(html, "_page=1"))

    def test_message_links_carry_back_state(self, client, box):
        r = client.get("/mail?_sort=size&_mode=list&_filter=UNSEEN")
        html = r.get_data(as_text=True)
        msg_links = _hrefs(html, "/message?")
        assert msg_links
        for href in msg_links:
            assert "_back" in parse_qs(urlparse(href).query), href
        def _dec(h):
            v = parse_qs(urlparse(h).query)["_back"][0]
            return base64.urlsafe_b64decode(
                v + "=" * (-len(v) % 4)).decode()

        backs = [_dec(h) for h in msg_links]
        assert all("_sort=size" in b and "_mode=list" in b
                   and "_filter=UNSEEN" in b for b in backs)


class TestBackLink:
    def _get(self, client, monkeypatch, back):
        class MsgBox(Box):
            def raw_message(self, folder, uid):
                return b""

            def __getattr__(self, name):
                return lambda *a, **k: None

        ctx = {
            "uid": "100", "folder": "INBOX", "subject": "S", "subject_title": "x",
            "from": None, "sender": None, "from_addr": [], "has_from": False,
            "to": [], "to_addr": [], "cc_addr": [], "replyto_addr": [],
            "date": _NOW, "date_short": "Nov 3", "parts": [],
            "image_attachments": [], "attachments": [], "adr_links": {}, "a": "",
            "mdn": None, "photo_src": None, "remote_blocked": False,
            "optional_format": None, "framed": False, "extwin": False,
            "print": False, "tb_active": True, "action": "show",
            "msg": {"message_id": "m1"},
        }
        b = MsgBox()
        monkeypatch.setattr(views, "imap_box", lambda *a, **k: b)
        monkeypatch.setattr(views, "build_message_ctx",
                            lambda box_, folder_, uid, **kw: ctx)
        monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])
        url = "/message?_mbox=INBOX&_uid=100"
        if back is not None:
            url += "&_back=" + back
        return client.get(url)

    def test_back_honours_safe_back_param(self, client, monkeypatch):
        from urllib.parse import quote

        r = self._get(client, monkeypatch, quote("/mail?_sort=size&_page=2", safe=""))
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'href="/mail?_sort=size&amp;_page=2"' in html

    def test_back_accepts_base64_param(self, client, monkeypatch):
        enc = base64.urlsafe_b64encode(
            b"/mail?_sort=size&_page=2").decode().rstrip("=")
        r = self._get(client, monkeypatch, enc)
        assert r.status_code == 200
        assert 'href="/mail?_sort=size&amp;_page=2"' in r.get_data(as_text=True)

    def test_back_rejects_absolute_urls(self, client, monkeypatch):
        from urllib.parse import quote

        r = self._get(client, monkeypatch, quote("https://evil.example/x", safe=""))
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "evil.example" not in html

    def test_back_defaults_without_param(self, client, monkeypatch):
        r = self._get(client, monkeypatch, None)
        assert r.status_code == 200
        assert 'href="/mail?_mbox=INBOX"' in r.get_data(as_text=True)
