"""Preview-pane + move-between-folders contract (reference elastic).

Reference behaviour (live-verified against Roundcube 1.7.5 on staging):
* single click on a row (desktop widescreen) previews the message in the
  third column via the framed message view; the watermark is the empty state
* More menu -> 'Move to...'/'Copy to...' popup lists the other folders
* dropping dragged rows on a sidebar folder opens #dragmessage-menu with
  Move/Copy (app.js show_dragmenu / drag_menu_action)
* server side: POST /mail/act _act=move|copy&_dest=<folder>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import views


class Box:
    """Recording fake of ImapBox (empty listing; move/copy calls logged)."""

    def __init__(self):
        self.prefs = {}
        self.calls = []

    def message_list(self, folder, **kw):
        return {"items": [], "page": 1, "pages": 1, "total": 0, "first": 0, "last": 0, "uids": []}

    def quota_usage(self):
        return (0, 0)

    def move(self, folder, uids, dest):
        self.calls.append(("move", folder, list(uids), dest))

    def copy(self, folder, uids, dest):
        self.calls.append(("copy", folder, list(uids), dest))

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture()
def box(monkeypatch):
    b = Box()
    monkeypatch.setattr(views, "imap_box", lambda *a, **k: b)
    monkeypatch.setattr(
        views,
        "folders_for_menu",
        lambda *a, **k: [
            {"name": "INBOX", "special": None, "unread": 0, "sub": []},
            {"name": "Drafts", "special": "drafts", "unread": 0, "sub": []},
            {"name": "Archive", "special": None, "unread": 0, "sub": []},
            {"name": "INBOX/Work", "special": None, "unread": 0, "sub": []},
        ],
    )
    return b


class TestPreviewPane:
    def test_third_column_frame_present(self, client, box):
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="messagecontframe"' in html
        # empty state is the watermark, exactly like env:blankpage in elastic
        assert "watermark" in html
        assert 'data-folder="INBOX"' in html

    def test_framed_message_is_a_bare_document(self, client, box, monkeypatch):
        # the preview URL the JS loads into the frame must render only the
        # message, no list shell
        ctx = {
            "uid": "100",
            "folder": "INBOX",
            "subject": "S",
            "subject_title": "x",
            "from": None,
            "sender": None,
            "from_addr": [],
            "has_from": False,
            "to": [],
            "to_addr": [],
            "cc_addr": [],
            "replyto_addr": [],
            "date": None,
            "date_short": "Nov 3",
            "parts": [],
            "image_attachments": [],
            "attachments": [],
            "adr_links": {},
            "a": "",
            "mdn": None,
            "photo_src": None,
            "remote_blocked": False,
            "optional_format": None,
            "framed": True,
            "extwin": False,
            "print": False,
            "tb_active": False,
            "action": "preview",
            "msg": {"message_id": "m1"},
        }
        monkeypatch.setattr(views, "build_message_ctx", lambda box_, folder_, uid, **kw: ctx)
        html = client.get("/message?_mbox=INBOX&_uid=100&_framed=1").get_data(as_text=True)
        assert "mailboxlist" not in html
        assert "messagelist" not in html

    def test_preview_wiring_in_page_js(self, client, box):
        # single click / keyboard focus move must drive the frame
        # (behavior asserted live in tests/test_selenium_staging.py)
        js_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "craftcube.js")
        with open(js_path, encoding="utf-8") as fh:
            js_src = fh.read()
        assert "previewRow" in js_src
        assert "&_framed=1" in js_src


class TestSearchForm:
    def test_exactly_one_hidden_mbox(self, client, box):
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        form = html.split('id="rcmqsearchform"', 1)[1].split("</form>", 1)[0]
        assert form.count('name="_mbox"') == 1


class TestMoveCopyMenu:
    def test_folder_selector_lists_all_folders_including_current(self, client, box):
        # reference entity_selector builds #folder-selector from mailboxes_list;
        # the current folder is included and clickable (move_messages then
        # no-ops), unlike an exclusion-only menu
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="folder-selector"' in html
        assert 'class="toolbarmenu menu listing folderlist"' in html
        assert 'data-dest="Archive"' in html
        assert 'data-dest="INBOX/Work"' in html
        assert 'data-dest="INBOX"' in html
        # current folder rendered active but the JS no-ops on it

    def test_folder_selector_classes_match_reference(self, client, box):
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        # special/folder classes drive the folderlist icons
        assert '<li class="inbox">' in html
        assert '<li class="drafts">' in html
        assert 'class="icon active"' in html
        # hierarchy indentation: nested INBOX/Work has one level -> 16px
        assert 'data-dest="INBOX/Work" style="padding-left: 16px"' in html
        # no heading: the reference selector is a bare popupmenu list
        assert "Move to folder" not in html
        assert "Copy to folder" not in html

    def test_dragmessage_menu_markup(self, client, box):
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="dragmessage-menu"' in html
        assert 'data-dragact="move"' in html
        assert 'data-dragact="copy"' in html
        assert 'id="rcmbtn142"' in html and 'id="rcmbtn143"' in html
        assert 'class="active"' in html

    def test_rows_draggable_and_drag_contract(self, client, box):
        # rows become draggable via JS at list init (kept out of the template
        # so the server markup stays reference-clean)
        js_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "craftcube.js")
        with open(js_path, encoding="utf-8") as fh:
            js_src = fh.read()
        assert "draggable = true" in js_src
        assert "dragmessage-menu" in js_src
        # reference app.js drag_end: SHIFT+drop opens the menu, plain drop moves
        assert "e.shiftKey" in js_src
        assert "act('move', dragUids, { _dest: name })" in js_src
        assert "current folder no-op" in js_src


class TestMessageMenuParity:
    def test_export_anchor_matches_reference(self, client, box):
        # reference message-menu: one download anchor with aria-haspopup,
        # no extra dropdown icon / with-sublist item
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="rcmbtn132"' in html
        assert 'aria-haspopup="true"' in html
        assert 'data-popup="zipdownload-menu"' in html
        menu = html.split('id="message-menu"', 1)[1].split("</div>", 1)[0]
        assert "button icon dropdown" not in menu
        assert "with-sublist" not in menu

    def test_zipdownload_menu_markup(self, client, box):
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="zipdownload-menu"' in html
        assert 'class="toolbarmenu menu"' in html
        assert 'class="download eml disabled"' in html
        assert 'id="rcmbtn101"' in html and 'id="rcmbtn103"' in html
        assert "Message Export Options Menu" in html

    def test_folder_actions_menu_matches_reference(self, client, box):
        html = client.get("/mail?_mbox=INBOX").get_data(as_text=True)
        assert 'id="aria-label-mailboxoptions-menu"' in html
        assert "Folder actions menu" in html
        assert 'class="expunge disabled"' in html
        assert 'class="purge disabled"' in html
        assert 'id="rcmbtn144"' in html and 'id="rcmbtn147"' in html

    def test_popup_anchors_are_decorated_like_reference(self, client, box):
        js_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "craftcube.js")
        with open(js_path, encoding="utf-8") as fh:
            js_src = fh.read()
        assert "#markmessage-menu li > a" in js_src
        assert "#mailboxoptions-menu li > a" in js_src
        assert "#listselect-menu li > a" in js_src
        assert "#threadselect-menu li > a" in js_src
        assert "el.setAttribute('tabindex', on ? '0' : '-1')" in js_src


class TestMoveCopyServer:
    def _post(self, client, act, dest="Archive", uids=("7",)):
        data = {"_mbox": "INBOX", "_act": act, "_dest": dest}
        return client.post("/mail/act", data={**data, **{"_uids[]": list(uids)}})

    def test_move_posts_to_dest(self, client, box):
        r = self._post(client, "move")
        assert r.status_code == 302
        assert ("move", "INBOX", [7], "Archive") in box.calls

    def test_copy_posts_to_dest(self, client, box):
        r = self._post(client, "copy", dest="INBOX/Work")
        assert r.status_code == 302
        # INBOX/Work reaches the mailbox verbatim (template passes full name)
        assert ("copy", "INBOX", [7], "INBOX/Work") in box.calls

    def test_move_redirect_back_to_folder(self, client, box):
        r = self._post(client, "move")
        assert "/mail" in r.headers["Location"]
        assert "_mbox=INBOX" in r.headers["Location"]
