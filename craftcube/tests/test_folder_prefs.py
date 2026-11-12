"""Special-folder settings regressions (user-reported: 'Folder settings do not work correctly')."""
import pytest

from app import prefs_sections


@pytest.fixture(autouse=True)
def _no_imap(monkeypatch):
    from app import views
    monkeypatch.setattr(views, "folders_for_menu", lambda: [])


class TestApplyFormKeys:
    def test_mbox_prefs_keep_full_rc_key(self):
        # Roundcube stores trash_mbox (verified in the reference DB);
        # stripping to 'trash' made the selection never persist or apply
        prefs = {}
        out = prefs_sections.apply_form(prefs, {
            "_trash_mbox": "Trash", "_drafts_mbox": "Drafts",
            "_sent_mbox": "", "_junk_mbox": "", "_archive_mbox": "",
            "_section": "folders"})
        assert out["trash_mbox"] == "Trash"
        assert out["drafts_mbox"] == "Drafts"
        assert "trash" not in out and "drafts" not in out


class TestFolderSelectorParity:
    FOLDERS = ["INBOX", "Drafts", "Sent", "INBOX/Drafts"]

    def _section(self, client, monkeypatch):
        from app import views
        monkeypatch.setattr(views, "folders_for_menu",
                            lambda: [{"name": f} for f in self.FOLDERS])
        return client.get("/settings/preferences/folders?_framed=1").get_data(as_text=True)

    def test_options_are_tree_ordered_like_rc(self, client, monkeypatch):
        # reference renders the subscribed folders as a flattened tree:
        # INBOX, INBOX/Drafts, Drafts, Sent (verified live against RC)
        import re
        h = self._section(client, monkeypatch)
        m = re.search(r"<select[^>]*name=\"_trash_mbox\".*?</select>", h, re.S)
        opts = re.findall(r"<option value=\"([^\"]*)\"", m.group(0))
        assert opts == ["", "INBOX", "INBOX/Drafts", "Drafts", "Sent"]

    def test_archive_rows_exist(self, client, monkeypatch):
        # the reference folders section ends with Archive + 'Divide
        # archive by'; 'Divide archive by' sits in its own
        # fieldset.archive with legend 'Archive' (elastic template)
        h = self._section(client, monkeypatch)
        assert 'name="_archive_mbox"' in h
        assert 'name="_archive_type"' in h
        assert "tbmonth" in h  # Thunderbird-compatible sub-option present
        assert '<fieldset class="archive">' in h
        assert '<legend>Archive</legend>' in h

    def test_defaults_are_full_keys_like_rc(self):
        # defaults.inc.php ships every special folder as '' (shown '---')
        for key in ("drafts_mbox", "sent_mbox", "junk_mbox", "trash_mbox",
                    "archive_mbox", "archive_type"):
            assert prefs_sections.DEFAULTS[key] == ""
        for short in ("drafts", "sent", "junk", "trash", "archive"):
            assert short not in prefs_sections.DEFAULTS

    def test_special_pref_lookup_uses_full_key(self):
        # regression: Mailbox.special() read the stripped short key, so a
        # saved trash_mbox never routed deletions to the Trash folder
        from app.mail import Mailbox
        box = Mailbox.__new__(Mailbox)
        box.prefs = {"trash_mbox": "Trash"}
        box.conf = lambda _k: "FALLBACK"
        box.imap = type("I", (), {"list_folders": lambda self: []})()
        assert Mailbox.special(box, "trash") == "Trash"

    def test_server_section_has_read_on_archive_row(self, client, monkeypatch):
        # the reference server section gains 'Mark the message as read on
        # archive' from the archive plugin, after 'Directly delete messages
        # in Junk' (verified row order in the reference DOM)
        from app import views
        monkeypatch.setattr(views, "folders_for_menu", lambda: [])
        h = client.get("/settings/preferences/server?_framed=1").get_data(as_text=True)
        assert 'name="_read_on_archive"' in h
        assert h.index("_delete_junk") < h.index("_read_on_archive")
        assert h.index("_read_on_archive") < h.index("Maintenance")
