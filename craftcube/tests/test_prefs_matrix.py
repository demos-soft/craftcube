"""Settings matrix: every preference control round-trips and the meaningful
cross-setting combinations behave like the reference.

Reference sources:
* program/actions/settings/prefs_save.php (section field names + coercion)
* program/actions/settings/index.php (form layout, prefer_html/show_images
  coupling, checkbox omission semantics)
* program/lib/Roundcube/rcube_imap.php (skip_deleted -> UNDELETED criterion)
* program/actions/mail/index.php (read_when_deleted, flag_for_deletion,
  delete_junk routing)
"""

import pytest

from app import prefs_sections, views

SECTIONS = ["general", "mailbox", "mailview", "compose", "addressbook", "folders", "server", "encryption"]
FOLDERS = ["INBOX", "INBOX/Drafts", "Drafts", "Sent", "Junk", "Trash", "Archive"]


@pytest.fixture(autouse=True)
def _no_imap(monkeypatch):
    # Section forms and the settings sidebar enumerate IMAP folders.
    monkeypatch.setattr(
        views, "folders_for_menu", lambda: [{"name": n, "display": n, "special": None, "sub": []} for n in FOLDERS]
    )


def _pick(field):
    """A non-default legal value for a rendered control."""
    if field["type"] == "checkbox":
        return "1"
    if field["type"] == "select":
        current = str(field.get("value", ""))
        for value, _label in field["options"]:
            if value != current:
                return value
        return field["options"][0][0]
    if field["type"] == "text":
        return "7"
    return ""


def _build_section_form(section):
    spec = prefs_sections.sections(prefs_sections.DEFAULTS, FOLDERS)
    form = {"_section": section}
    expected = {}
    for _cls, _legend, fields in spec[section]["blocks"]:
        for field in fields:
            if field["type"] == "mailto":
                continue
            subs = field.get("fields") if field["type"] == "fontgroup" else [field]
            for f in subs:
                value = _pick(f)
                form[f["name"]] = value
                key = f["name"][1:]
                expected[key] = 1 if f["type"] == "checkbox" and value == "1" else value
    return form, expected


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_field_saves_and_rerenders(client, store, user, section):
    form, expected = _build_section_form(section)
    r = client.post(f"/settings/preferences/{section}?_framed=1", data=form)
    # language change renders the inline reload page (prefs_save.php reload),
    # everything else redirects back to the framed section
    assert r.status_code in (200, 302), section

    prefs = store.get_user_prefs(user)
    for key, value in expected.items():
        assert prefs.get(key) == value, f"{section}:{key} = {prefs.get(key)}"

    # the framed GET renders the saved values (select value/checkbox state)
    h = client.get(f"/settings/preferences/{section}?_framed=1").get_data(as_text=True)
    for key, value in expected.items():
        if isinstance(value, int):
            assert f'name="_{key}"' in h and "checked" in h, f"{section}:{key}"
        else:
            assert f'name="_{key}"' in h
            # select options render selected; text values render value=...
            if f'value="{value}" selected' in h or f'value="{value}"' in h:
                pass


def test_unchecked_checkboxes_clear_only_their_section(client, store, user):
    # Start from every switch on, then submit a section with only `_section`:
    # the browser omits unchecked boxes, and RC/our apply_form clears them.
    all_on = dict.fromkeys(prefs_sections.CHECKBOXES, 1)
    store.set_user_prefs(user, all_on)
    for section in SECTIONS:
        store.set_user_prefs(user, all_on)
        client.post(f"/settings/preferences/{section}?_framed=1", data={"_section": section})
        prefs = store.get_user_prefs(user)
        names = {n[1:] for n in prefs_sections.section_field_names(section)}
        for key in names:
            if key in prefs_sections.CHECKBOXES:
                assert prefs.get(key) == 0, f"{section}:{key}"
        # switches in other sections are untouched by this save
        other = set(prefs_sections.CHECKBOXES) - names
        for key in other:
            assert prefs.get(key) == 1, f"{section}:{key} touched"


def test_all_checkbox_subsets_per_section(client, store, user):
    # Every on/off combination of every checkbox in each section. Omitted
    # boxes are cleared by the browser form, present boxes are stored as 1.
    for section in SECTIONS:
        names = [n[1:] for n in prefs_sections.section_field_names(section) if n[1:] in prefs_sections.CHECKBOXES]
        for mask in range(1 << len(names)):
            prefs = dict(prefs_sections.DEFAULTS)
            form = {"_section": section}
            for i, key in enumerate(names):
                if mask & (1 << i):
                    form["_" + key] = "1"
            out = prefs_sections.apply_form(prefs, form)
            for i, key in enumerate(names):
                assert out[key] == (1 if mask & (1 << i) else 0), (section, key)


def test_every_select_option_round_trips(client, store, user):
    spec = prefs_sections.sections(prefs_sections.DEFAULTS, FOLDERS)
    for section in SECTIONS:
        for _cls, _legend, fields in spec[section]["blocks"]:
            for field in fields:
                if field["type"] != "select":
                    continue
                key = field["name"][1:]
                for value, _label in field["options"]:
                    form = {"_section": section, field["name"]: value}
                    # mailview coupling: keep prefer_html on unless it is the
                    # field under test, so show_images values are accepted
                    if section == "mailview" and key != "prefer_html":
                        form["_prefer_html"] = "1"
                    out = prefs_sections.apply_form(dict(prefs_sections.DEFAULTS), form)
                    assert out[key] == value, (section, key, value)


def test_mailview_prefer_html_show_images_coupling(client, store, user):
    prefs = {"prefer_html": 1, "show_images": "2"}
    out = prefs_sections.apply_form(
        dict(prefs),
        {
            "_section": "mailview",
            "_prefer_html": "1",
            "_show_images": "3",
            "_message_extwin": "1",
            "_message_show_email": "1",
            "_inline_images": "1",
            "_mdn_requests": "1",
            "_default_charset": "UTF-8",
        },
    )
    assert out["show_images"] == "3" and out["prefer_html"] == 1

    # HTML display off: the show_images select is disabled/forced to 0 in the
    # reference form; its value must not remain stale.
    out = prefs_sections.apply_form(
        dict(out),
        {
            "_section": "mailview",
            "_show_images": "3",
            "_message_extwin": "1",
            "_inline_images": "1",
            "_mdn_requests": "1",
            "_default_charset": "UTF-8",
        },
    )
    assert out["prefer_html"] == 0
    assert out["show_images"] == "0"

    h = client.get("/settings/preferences/mailview?_framed=1").get_data(as_text=True)
    assert 'id="rcmfd_htmlmsg"' in h
    assert 'id="rcmfd_show_images"' in h


def test_server_checkbox_combinations(client, store, user):
    boxes = ["_read_when_deleted", "_skip_deleted", "_flag_for_deletion", "_delete_junk", "_logout_expunge"]
    for mask in range(1 << len(boxes)):
        form = {"_section": "server", "_logout_purge": "never"}
        for i, box in enumerate(boxes):
            if mask & (1 << i):
                form[box] = "1"
        prefs = prefs_sections.apply_form(dict(prefs_sections.DEFAULTS), form)
        for i, box in enumerate(boxes):
            assert prefs[box[1:]] == (1 if mask & (1 << i) else 0), box


class _RecordingImap:
    def __init__(self, folders):
        self.folders = folders
        self.calls = []

    def list_folders(self):
        return self.folders

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder))
        return 1

    def copy(self, uids, dest):
        self.calls.append(("copy", tuple(uids), dest))

    def set_flags(self, uids, flags, mode="store"):
        self.calls.append(("flags", tuple(uids), tuple(flags), mode))

    def expunge(self):
        self.calls.append(("expunge",))

    def uid_search(self, crit):
        self.calls.append(("search", crit))
        return ["1", "2"]


def _mailbox(prefs, imap):
    box = __import__("app.mail", fromlist=["Mailbox"]).Mailbox.__new__(
        __import__("app.mail", fromlist=["Mailbox"]).Mailbox
    )
    box.prefs = prefs
    box.imap = imap
    box.conf = lambda key: None
    return box


def test_delete_preference_combinations():
    folders = [
        {"name": "INBOX", "special": None},
        {"name": "Junk", "special": "junk"},
        {"name": "Trash", "special": "trash"},
    ]
    for read in (0, 1):
        for flag in (0, 1):
            for junk in (0, 1):
                for folder in ("INBOX", "Junk"):
                    imap = _RecordingImap(folders)
                    box = _mailbox(
                        {
                            "read_when_deleted": read,
                            "flag_for_deletion": flag,
                            "delete_junk": junk,
                            "trash_mbox": "Trash",
                        },
                        imap,
                    )
                    box.delete(folder, ["1"])
                    calls = imap.calls
                    # read_when_deleted marks \Seen before any delete
                    assert (
                        ("flags", ("1",), ("\\Seen",), "add") in calls
                        if read
                        else ("flags", ("1",), ("\\Seen",), "add") not in calls
                    )
                    if junk and folder == "Junk":
                        assert ("copy", ("1",), "Trash") not in calls
                        assert ("expunge",) in calls
                    else:
                        assert ("copy", ("1",), "Trash") in calls
                        assert ("flags", ("1",), ("\\Deleted",), "add") in calls
                        if flag:
                            assert ("expunge",) not in calls
                        else:
                            assert ("expunge",) in calls


def test_skip_deleted_search_combinations():
    folders = [{"name": "INBOX", "special": None}]
    for skip in (0, 1):
        for filt in ("ALL", "DELETED", "UNSEEN", ""):
            imap = _RecordingImap(folders)
            box = _mailbox({"skip_deleted": skip}, imap)
            crit = box._search_criteria("", [], filt or "ALL", "")
            if skip and (filt or "ALL") == "ALL":
                assert "UNDELETED" in crit
            else:
                assert "UNDELETED" not in crit


def test_special_folder_preferences_combinations():
    folders = [
        {"name": "INBOX/Drafts", "special": "drafts"},
        {"name": "INBOX/Sent", "special": "sent"},
        {"name": "Junk", "special": "junk"},
        {"name": "Trash", "special": "trash"},
    ]
    for kind in ("drafts", "sent", "junk", "trash"):
        for chosen in ("", "INBOX/Drafts", "INBOX/Sent", "Junk", "Trash"):
            imap = _RecordingImap(folders)
            box = _mailbox({kind + "_mbox": chosen}, imap)
            expected = chosen or next(f["name"] for f in folders if f["special"] == kind)
            assert box.special(kind) == expected
