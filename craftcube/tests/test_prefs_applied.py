"""Application-level preference checks: the saved value actually drives the
mail/addressbook/message routes, not just the settings form."""

import email.message
import re
from datetime import datetime

import pytest

from app import mail, spellchecker, util, views


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


class RecentBox:
    def __init__(self):
        self.prefs = {}
        self.status_calls = []

    def folders(self, subscribed_only=False):
        return [{"name": n} for n in ("INBOX", "Sent", "Junk")]

    class Imap:
        def __init__(self, outer):
            self.outer = outer

        def status(self, name):
            self.outer.status_calls.append(name)
            return (3, 1)

    @property
    def imap(self):
        return RecentBox.Imap(self)

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_check_all_folders_controls_check_recent(client, store, user, monkeypatch):
    box = RecentBox()
    monkeypatch.setattr(views, "imap_box", lambda *a, **k: box)
    monkeypatch.setattr(views, "folders_for_menu", lambda *a, **k: [])

    store.set_user_prefs(user, {"check_all_folders": 0})
    box.prefs = {"check_all_folders": 0}
    box.status_calls = []
    r = client.get("/mail/check-recent?_mbox=Sent")
    assert r.status_code == 200
    assert box.status_calls == ["Sent"], box.status_calls

    store.set_user_prefs(user, {"check_all_folders": 1})
    box.prefs = {"check_all_folders": 1}
    box.status_calls = []
    client.get("/mail/check-recent?_mbox=Sent")
    assert set(box.status_calls) == {"INBOX", "Sent", "Junk"}


def test_autocomplete_single_limits_multiple_addresses(client, store, user):
    ext = {
        "firstname": "Grace",
        "surname": "Hopper",
        "emails": [("home", "grace@navy.example"), ("work", "ghopper@navy.example")],
    }
    store.contact_save(
        user,
        {
            "name": "Grace Hopper",
            "email": "grace@navy.example, ghopper@navy.example",
            "firstname": "Grace",
            "surname": "Hopper",
            "vcard": util.vcard_encode(ext),
        },
    )

    store.set_user_prefs(user, {"autocomplete_single": 0})
    r = client.get("/mail/autocomplete?_search=grace&_reqid=x")
    text = r.get_data(as_text=True)
    assert text.count("ghopper@navy.example") == 2

    store.set_user_prefs(user, {"autocomplete_single": 1})
    r = client.get("/mail/autocomplete?_search=grace&_reqid=x")
    text = r.get_data(as_text=True)
    assert text.count("ghopper@navy.example") == 0


def test_enable_autolink_disables_editor_plugin(app):
    with app.test_request_context("/"):
        off = views.editor_config("", {"enable_autolink": 0})
        assert "autolink" in off["disabled_plugins"]
        on = views.editor_config("", {"enable_autolink": 1})
        assert "autolink" not in on["disabled_plugins"]


def test_keep_formatting_default_seeds_compose_checkbox(client, store, user, make_box):
    store.set_user_prefs(user, {"keep_formatting_default": 1})
    make_box.prefs = dict(store.get_user_prefs(user))
    html = client.get("/compose").get_data(as_text=True)
    m = re.search(r'id="compose-keep-formatting"[^>]*', html)
    assert m and "checked" in m.group(0)

    store.set_user_prefs(user, {"keep_formatting_default": 0})
    make_box.prefs = dict(store.get_user_prefs(user))
    html = client.get("/compose").get_data(as_text=True)
    m = re.search(r'id="compose-keep-formatting"[^>]*', html)
    assert m and "checked" not in m.group(0)


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

class _ArchiveImap:
    def __init__(self):
        self.copies = []
        self.created = []
        self.flags = []

    def list_folders(self, subscribed_only=False):
        return [{"name": "Archive", "special": "archive"}]

    def fetch_envelopes(self, uids):
        return [{"date": datetime(2026, 11, 15)}]

    def create_folder(self, name, subscribe=True):
        self.created.append(name)

    def select(self, folder, readonly=False):
        pass

    def copy(self, uids, target):
        self.copies.append((list(uids), target))

    def set_flags(self, uids, flags, mode):
        self.flags.append((list(uids), list(flags), mode))

    def expunge(self):
        pass


def test_archive_type_applied():
    cases = {
        "": "Archive",
        "year": "Archive/2026",
        "month": "Archive/2026/11",
        "tbmonth": "Archive/2026/2026-11",
    }
    for atype, expected in cases.items():
        imap = _ArchiveImap()
        box = mail.Mailbox(imap, {}, "unit@example.org")
        box.prefs = {"archive_type": atype, "read_on_archive": 1}
        target = box.archive("INBOX", [10])
        assert target == expected, (atype, target)
        assert imap.copies[-1][1] == expected
        assert any(chr(92) + "Seen" in f[1] for f in imap.flags), (atype, imap.flags)
        assert any(chr(92) + "Deleted" in f[1] for f in imap.flags), (atype, imap.flags)

def test_spellcheck_prefs_control_send(client, store, user, make_box, monkeypatch):
    seen = []
    monkeypatch.setattr(spellchecker, "check",
                        lambda text, lang, ignore=None: seen.append(ignore) or {})

    form = {"_action": "send", "_to": "a@example.org", "_subject": "S",
            "_body": "hello", "_is_html": "0"}

    store.set_user_prefs(user, {"spellcheck_before_send": 0})
    make_box.prefs = dict(store.get_user_prefs(user))
    client.post("/compose", data=form)
    assert not seen

    store.set_user_prefs(user, {
        "spellcheck_before_send": 1,
        "spellcheck_ignore_syms": 1,
        "spellcheck_ignore_nums": 1,
        "spellcheck_ignore_caps": 1,
    })
    make_box.prefs = dict(store.get_user_prefs(user))
    client.post("/compose", data=form)
    assert seen[-1] == {"syms": True, "nums": True, "caps": True}, seen[-1]

def test_mail_read_time_controls_preview_marking(client, store, user, make_box):
    cases = [("0", False), ("5", True), ("-1", True)]
    for rt, noseen in cases:
        store.set_user_prefs(user, {"mail_read_time": rt})
        make_box.prefs = dict(store.get_user_prefs(user))
        html = client.get("/mail?_mbox=INBOX&_uid=10").get_data(as_text=True)
        assert f'data-read-time="{rt}"' in html, rt
        assert ("_noseen=1" in html) == noseen, rt

def test_show_real_foldernames_controls_folder_label(app):
    with app.test_request_context("/"):
        assert views.folder_label("INBOX/Drafts", {"show_real_foldernames": 1}) == "INBOX/Drafts"
        assert views.folder_label("INBOX/Drafts", {"show_real_foldernames": 0}) == "Drafts"


def test_addressbook_name_listing_and_sort_col(client, store, user):
    for first, last, addr in [("Alice", "Smith", "alice@example.org"),
                              ("Bob", "Adams", "bob@example.org")]:
        store.contact_save(user, {
            "name": f"{first} {last}", "email": addr,
            "firstname": first, "surname": last, "vcard": "",
        })

    cases = {
        "1": ("Alice Smith", "Bob Adams"),
        "2": ("Smith Alice", "Adams Bob"),
        "3": ("Smith, Alice", "Adams, Bob"),
    }
    for mode, expected in cases.items():
        store.set_user_prefs(user, {"addressbook_name_listing": mode})
        h = client.get("/contacts?_dialog=1").get_data(as_text=True)
        assert expected[0] in h and expected[1] in h, mode

    # sorting column: surname puts Adams before Smith
    store.set_user_prefs(user, {"addressbook_sort_col": "surname",
                                "addressbook_name_listing": "0"})
    h = client.get("/contacts?_dialog=1").get_data(as_text=True)
    assert h.index("Adams") < h.index("Smith")
    store.set_user_prefs(user, {"addressbook_sort_col": "firstname",
                                "addressbook_name_listing": "0"})
    h = client.get("/contacts?_dialog=1").get_data(as_text=True)
    assert h.index("Alice") < h.index("Bob")

def test_layout_and_compose_prefs_attributes(client, store, user, make_box):
    store.set_user_prefs(user, {
        "autoexpand_threads": "2",
        "standard_windows": 1,
        "compose_extwin": 1,
        "refresh_interval": "5",
        "draft_autosave": "60",
    })
    make_box.prefs = dict(store.get_user_prefs(user))

    mail = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
    assert 'data-autoexpand-threads="2"' in mail
    assert 'data-standard-windows="1"' in mail
    assert 'data-compose-extwin="1"' in mail
    assert 'data-refresh-interval="5"' in mail

    compose = client.get("/compose").get_data(as_text=True)
    assert "draft_autosave: 60" in compose
