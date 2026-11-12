"""Settings > Folders manager regressions (user-reported: 'Settings/folders
does not work as the same view in roundcube'). The reference manager is a
two-pane view: an iconized treelist (#layout-list) with folder properties
loaded into #preferences-frame (folder_edit.php) — not an inline editor."""
import re

import pytest


@pytest.fixture(autouse=True)
def _no_imap(monkeypatch):
    from app import views
    monkeypatch.setattr(views, "folders_for_menu", lambda: [])


FOLDERS = [
    {"name": "INBOX", "special": "", "subscribed": True},
    {"name": "Drafts", "special": "drafts", "subscribed": True},
    {"name": "INBOX/Drafts", "special": "", "subscribed": True},
    {"name": "Trash", "special": "trash", "subscribed": True},
    {"name": "Zoo", "special": "", "subscribed": False},
]
COUNTS = {"INBOX": 4, "Drafts": 0, "INBOX/Drafts": 2, "Trash": 35, "Zoo": 0}


class FakeImap:
    @staticmethod
    def status_size(name):
        return COUNTS.get(name, 0), 1024 if name == "INBOX" else None


class FakeBox:
    folders = staticmethod(lambda: [dict(f) for f in FOLDERS])
    imap = FakeImap()


def _patch_box(monkeypatch):
    from app import views
    monkeypatch.setattr(views, "imap_box", lambda *a, **k: FakeBox())


class TestFolderListPane:
    def test_manager_is_treelist_with_toolbar_and_frame(self, client, monkeypatch):
        _patch_box(monkeypatch)
        h = client.get("/settings/folders").get_data(as_text=True)
        # reference list pane: iconized treelist inside #layout-list and an
        # always-present content frame; toolbar is an iconized menu
        assert 'id="layout-list"' in h
        assert "treelist listing folderlist iconized" in h
        assert "notree" not in h
        assert 'id="folderstoolbar"' in h
        assert 'class="create"' in h
        assert 'class="delete disabled"' in h
        assert 'class="purge disabled"' in h
        assert 'id="preferences-frame"' in h
        # rows carry selection metadata for the toolbar state machine
        assert 'data-folder="INBOX/Drafts"' in h
        assert 'data-messages="2"' in h
        assert "data-framed-href" in h
        # delete protection is config-based (no *_mbox prefs set here):
        # only INBOX is protected, a folder merely named Drafts is not
        m = re.search(r'<li[^>]*data-folder="INBOX"[^>]*>', h)
        assert m and 'data-protected="1"' in m.group(0)
        m = re.search(r'<li[^>]*data-folder="Drafts"[^>]*>', h)
        assert m and 'data-protected=""' in m.group(0)

    def test_tree_nests_children_and_orders_inbox_first(self, client, monkeypatch):
        _patch_box(monkeypatch)
        h = client.get("/settings/folders").get_data(as_text=True)
        import re
        # children live in a <ul role="group"> inside the parent li
        m = re.search(r'<li[^>]*data-folder="INBOX".*?</li>', h, re.S)
        assert m and 'data-folder="INBOX/Drafts"' in m.group(0)
        order = re.findall(r'data-folder="([^"]+)"', h)
        assert order[0] == "INBOX"

    def test_no_inline_editor_on_list_page(self, client, monkeypatch):
        _patch_box(monkeypatch)
        # a deep-link must load the framed editor into the iframe, not
        # switch the list page to an inline form (the old CraftCube shape)
        h = client.get("/settings/folders?_edit=INBOX").get_data(as_text=True)
        assert 'name="_act"' not in h
        assert "_edit=INBOX" in h and "_framed=1" in h
        assert "subscription-table" in h

    def test_dead_deep_link_is_dropped(self, client, monkeypatch):
        _patch_box(monkeypatch)
        h = client.get("/settings/folders?_edit=Nope").get_data(as_text=True)
        assert "_edit=Nope" not in h


class TestFolderEditFrame:
    def test_inbox_editor_shape(self, client, monkeypatch):
        _patch_box(monkeypatch)
        h = client.get("/settings/folders?_edit=INBOX&_framed=1").get_data(as_text=True)
        assert '<body class="task-settings action-folder-edit">' in h
        assert "Folder properties" in h
        # INBOX: plaintext localized name, hidden parent, no name input
        assert "form-control-plaintext" in h
        assert 'name="name"' not in h
        # the three reference fieldsets
        assert "<legend>Location</legend>" in h
        assert "<legend>Settings</legend>" in h
        assert "<legend>Information</legend>" in h
        # Information block comes from IMAP STATUS (MESSAGES SIZE)
        assert ">4<" in h and "1 KB" in h
        # List view mode defaults to List (folder_edit.php:198)
        assert '<option value="list" selected="selected">' in h

    def test_new_folder_editor_shape(self, client, monkeypatch):
        _patch_box(monkeypatch)
        h = client.get("/settings/folders?_edit=new&_framed=1").get_data(as_text=True)
        assert '_act" value="create"' in h
        assert "<legend>Information</legend>" not in h
        assert 'name="name" id="_name"' in h
        # top-level parent option like the reference
        assert '<option value="">---</option>' in h

    def test_nested_folder_parent_selected(self, client, monkeypatch):
        _patch_box(monkeypatch)
        h = client.get(
            "/settings/folders?_edit=INBOX/Drafts&_framed=1").get_data(as_text=True)
        assert '_act" value="rename"' in h
        assert 'name="folder" value="INBOX/Drafts"' in h
        assert 'value="INBOX" selected="selected"' in h
        # the folder's own name pre-fills the name field
        assert 'id="_name" size="30" class="form-control" value="Drafts"' in h

    def test_framed_redirect_is_html_not_xml(self, client, monkeypatch):
        # a redirect to the editor must keep _framed so the iframe can
        # render the HTML editor (XHTML redirects killed language saves)
        _patch_box(monkeypatch)

        class WritableImap(FakeImap):
            @staticmethod
            def create_folder(name):
                COUNTS[name] = 0
                FOLDERS.append({"name": name, "special": "",
                                "subscribed": True})

            @staticmethod
            def subscribe(name):
                pass

        monkeypatch.setattr(FakeBox, "imap", WritableImap())
        r = client.post("/settings/folders", data={
            "_act": "create", "name": "Fresh", "parent": "",
            "viewmode": "list", "_framed": "1"})
        assert r.status_code == 302
        assert "_framed=1" in r.headers["Location"]
        assert "_saved=1" in r.headers["Location"]
        r2 = client.get(r.headers["Location"])
        assert r2.status_code == 200
        assert r2.mimetype == "text/html"
        assert "Folder properties" in r2.get_data(as_text=True)
