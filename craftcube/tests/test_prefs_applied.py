"""Application-level preference checks: the saved value actually drives the
mail/addressbook/message routes, not just the settings form."""

import email.message

import pytest

from app import views


class FakeBox:
    def __init__(self, prefs=None):
        self.prefs = dict(prefs or {})
        self.calls = []

    def message_list(self, folder, page=1, page_size=20, **kw):
        self.calls.append((folder, page, page_size))
        return {"items": [], "page": 1, "pages": 1, "total": 0, "first": 0, "last": 0, "uids": []}

    def quota_usage(self):
        return (0, 0)

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture()
def make_box(monkeypatch, store, user):
    box = FakeBox()

    def factory():
        box.prefs = dict(store.get_user_prefs(user))
        box.calls.clear()
        return box

    monkeypatch.setattr(views, "imap_box", factory)
    monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])
    return box


def test_mail_pagesize_controls_listing(client, store, user, make_box):
    for size in ("2", "10", "43", "50"):
        store.set_user_prefs(user, {"mail_pagesize": size})
        make_box.prefs = {"mail_pagesize": size}
        client.get("/mail?_mbox=INBOX")
        assert make_box.calls[-1][2] == int(size), size


def test_addressbook_pagesize_controls_contact_list(client, store, user):
    # 5 contacts, page size 2 => 3 pages and "more"; page size 50 => 1 page
    for i in range(5):
        store.contact_save(
            user,
            {
                "name": f"Person {i}",
                "email": f"p{i}@example.org",
                "firstname": "",
                "surname": "",
                "vcard": "",
            },
        )
    store.set_user_prefs(user, {"addressbook_pagesize": "2"})
    h = client.get("/contacts?_dialog=1").get_data(as_text=True)
    assert h.count('class="contact"') == 2
    assert 'class="nextpage disabled"' not in h
    store.set_user_prefs(user, {"addressbook_pagesize": "50"})
    h = client.get("/contacts?_dialog=1").get_data(as_text=True)
    assert h.count('class="contact"') == 5
    assert 'class="nextpage disabled"' in h


def _alternative_message():
    msg = email.message.EmailMessage()
    msg["Subject"] = "Alternative"
    msg["From"] = "Alice <alice@example.org>"
    msg["To"] = "Bob <bob@example.org>"
    msg["Date"] = "Wed, 11 Nov 2026 10:00:00 +0000"
    msg.set_type("multipart/alternative")
    msg.add_alternative("Plain body\n", subtype="plain")
    msg.add_alternative("<p>HTML body</p>", subtype="html")
    return msg


class MessageBox:
    def __init__(self, msg):
        self.msg = msg
        self.prefs = {}
        self.calls = []

    def get_message(self, folder, uid, mark_seen=False):
        return self.msg

    def _is_seen(self, folder, uid):
        return True

    def set_flags(self, folder, uids, flags, mode="add"):
        self.calls.append(("flags", tuple(uids), tuple(flags), mode))

    def raw_message(self, folder, uid):
        return self.msg

    def message_list(self, folder, **kw):
        return {"uids": [], "items": [], "page": 1, "pages": 1, "total": 0, "first": 0, "last": 0}

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture()
def message_box(monkeypatch, store):
    msg = _alternative_message()
    box = MessageBox(msg)

    def factory():
        box.prefs = {}
        return box

    monkeypatch.setattr(views, "imap_box", factory)
    monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])
    return box


def test_prefer_html_selects_alternative_part(client, store, user, message_box):
    store.set_user_prefs(user, {"prefer_html": 1})
    h = client.get("/message?_mbox=INBOX&_uid=1&_framed=1").get_data(as_text=True)
    assert "HTML body" in h
    assert "message-htmlpart" in h
    assert 'class="plain"' in h  # toggle offered because an HTML part exists

    store.set_user_prefs(user, {"prefer_html": 0})
    h = client.get("/message?_mbox=INBOX&_uid=1&_framed=1").get_data(as_text=True)
    assert "Plain body" in h
    assert "HTML body" not in h
    assert 'class="html"' in h


def test_compose_html_mode_table():
    # compose_editor_mode(): htmleditor x mode x prefer_html combinations
    html_msg = _alternative_message()
    plain_msg = email.message.EmailMessage()
    plain_msg.set_content("plain only")
    html_plain_msg = email.message.EmailMessage()
    html_plain_msg.set_content("<p>html only</p>", subtype="html")
    for htmleditor in range(5):
        for prefer_html in (0, 1):
            prefs = {"htmleditor": str(htmleditor), "prefer_html": prefer_html}
            for mode in ("reply", "replyall", "replylist", "forward", "forward-attachment", "draft", "edit", "new"):
                for source in (html_msg, plain_msg, html_plain_msg, None):
                    got = views.compose_html_mode(mode, source, prefs)
                    msg_html = prefer_html and source is not None and views._msg_has_html(source)
                    if mode in ("draft", "edit"):
                        expected = msg_html
                    elif mode in ("reply", "replyall", "replylist"):
                        expected = htmleditor == 1 or (htmleditor >= 2 and msg_html)
                    elif mode in ("forward", "forward-attachment"):
                        expected = htmleditor in (1, 4) or (htmleditor == 3 and msg_html)
                    else:
                        expected = htmleditor in (1, 4)
                    assert got == expected, (htmleditor, prefer_html, mode, source is not None, got, expected)


def test_message_format_override_wins_over_prefer_html(client, store, user, message_box):
    store.set_user_prefs(user, {"prefer_html": 0})
    h = client.get("/message?_mbox=INBOX&_uid=1&_framed=1&_format=html").get_data(as_text=True)
    assert "HTML body" in h and "Plain body" not in h
    h = client.get("/message?_mbox=INBOX&_uid=1&_framed=1&_format=text").get_data(as_text=True)
    assert "Plain body" in h and "HTML body" not in h


def test_display_next_after_delete(client, store, user, make_box):
    box = FakeBox({"display_next": 1})
    # the list order (newest first) has the deleted uid followed by a survivor
    box.message_list = lambda folder, **kw: {
        "uids": ["3", "2", "1"],
        "items": [],
        "page": 1,
        "pages": 1,
        "total": 3,
        "first": 1,
        "last": 3,
    }
    box.delete = lambda folder, uids: None
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(views, "imap_box", lambda *a, **k: box)
    monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])
    r = client.post("/mail/act", data={"_mbox": "INBOX", "_act": "delete", "_uids[]": ["3"], "_return_uid": "3"})
    assert r.status_code == 302
    assert "_uid=2" in r.headers["Location"]
    monkeypatch.undo()
