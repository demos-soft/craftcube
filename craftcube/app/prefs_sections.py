"""Preference section specs mirroring the reference (Elastic) settings UI.

Each section: label + blocks; each field: type ('select'|'checkbox'|'text'),
form field name and id exactly like the reference (_x / rcmfd_x), title text,
option list and current value. PREF_MAP lists every savable field.
"""
from . import prefs_data as D

DEFAULTS = {
    "language": "en_US", "timezone": "auto", "time_format": "H:i",
    "date_format": "Y-m-d", "pretty_date": 1, "display_next": 1,
    "refresh_interval": "1", "standard_windows": 0,
    "mail_read_time": "0", "autoexpand_threads": "0", "mail_pagesize": "50",
    "check_all_folders": 0,
    "message_extwin": 0, "message_show_email": 0, "prefer_html": 1,
    "show_images": "0", "mdn_requests": "0", "inline_images": 1,
    "default_charset": "ISO-8859-1",
    "compose_extwin": 0, "htmleditor": "0", "draft_autosave": "300",
    "mdn_default": 0, "dsn_default": 0, "reply_same_folder": 0,
    "reply_mode": "0", "forward_attachment": "0",
    "default_font": "Verdana", "default_font_size": "10pt",
    "enable_autolink": 1, "keep_formatting_default": 0,
    "reply_all_mode": "0", "show_sig": "1", "sig_below": 0,
    "strip_existing_sig": 1, "sig_separator": 1,
    "spellcheck_before_send": 0, "spellcheck_ignore_syms": 0,
    "spellcheck_ignore_nums": 0, "spellcheck_ignore_caps": 0,
    "mime_param_folding": "1", "force_7bit": 0, "compose_save_localstorage": 1,
    "addressbook_name_listing": "0", "addressbook_sort_col": "surname",
    "addressbook_pagesize": "50", "contact_form_mode": "private",
    "autocomplete_single": 0, "collected_recipients": "1",
    "collected_senders": "2",
    "show_real_foldernames": 0, "drafts_mbox": "", "sent_mbox": "",
    # reference default values: every special folder starts as '' / '---'
    # (defaults.inc.php); resolution happens via SPECIAL-USE flags at runtime
    "junk_mbox": "", "trash_mbox": "", "archive_mbox": "", "archive_type": "",
    # reference default is true (defaults.inc.php:1431)
    "read_when_deleted": 1, "flag_for_deletion": 0, "skip_deleted": 0,
    "delete_junk": 0, "read_on_archive": 0,
    "logout_purge": "never", "logout_expunge": 0,
    "mailvelope_main_keyring": 0,
}

# checkbox fields (saved as 0/1). Listed explicitly: the reference default of
# a switch (config/defaults.inc.php) is unrelated to whether it is a checkbox.
CHECKBOXES = [
    "pretty_date", "display_next", "standard_windows", "check_all_folders",
    "message_extwin", "message_show_email", "prefer_html", "inline_images",
    "compose_extwin", "mdn_default", "dsn_default", "reply_same_folder",
    "enable_autolink", "keep_formatting_default",
    "sig_below", "strip_existing_sig", "sig_separator",
    "spellcheck_before_send", "spellcheck_ignore_syms", "spellcheck_ignore_nums",
    "spellcheck_ignore_caps", "force_7bit", "compose_save_localstorage",
    "autocomplete_single", "read_when_deleted", "flag_for_deletion",
    "skip_deleted", "delete_junk", "read_on_archive", "logout_expunge",
    "mailvelope_main_keyring", "show_real_foldernames",
]
# selects: pref key -> option list name in prefs_data / special
SELECTS = {
    "language": "LANGUAGES", "timezone": "TIMEZONES",
    "time_format": "TIME_FORMAT", "date_format": "DATE_FORMAT",
    "refresh_interval": "REFRESH_INTERVAL",
    "mail_read_time": "MAIL_READ_TIME", "autoexpand_threads": "AUTOEXPAND_THREADS",
    "show_images": "SHOW_IMAGES", "mdn_requests": "MDN_REQUESTS",
    "default_charset": "CHARSETS",
    "htmleditor": "HTMLEDITOR", "draft_autosave": "DRAFT_AUTOSAVE",
    "reply_mode": "REPLY_MODE", "forward_attachment": "FORWARD_ATTACHMENT",
    "default_font": "FONTS", "default_font_size": "FONT_SIZES",
    "reply_all_mode": "REPLY_ALL_MODE", "show_sig": "SHOW_SIG",
    "mime_param_folding": "MIME_PARAM_FOLDING",
    "addressbook_name_listing": "ADDRESSBOOK_NAME_LISTING",
    "addressbook_sort_col": "ADDRESSBOOK_SORT_COL",
    "contact_form_mode": "CONTACT_FORM_MODE",
    "collected_recipients": "COLLECTED_RECIPIENTS",
    "collected_senders": "COLLECTED_SENDERS",
    "logout_purge": "LOGOUT_PURGE", "archive_type": "ARCHIVE_TYPE",
}
TEXTS = {"mail_pagesize": 5, "addressbook_pagesize": 5}
FOLDERS = ["drafts", "sent", "junk", "trash", "archive"]

SECTION_LABELS = [
    ("general", "User Interface"), ("mailbox", "Mailbox View"),
    ("mailview", "Displaying Messages"), ("compose", "Composing Messages"),
    ("addressbook", "Contacts"), ("folders", "Special Folders"),
    ("server", "Server Settings"), ("encryption", "Encryption"),
]


def _id(key):
    """field ids exactly as the reference sets $field_id (incl. its quirks:
    'rcmfdcompose_extwin' without underscore, bare 'show_real_foldernames',
    plugin ids 'ff_*' and special-folder ids '<name>_mbox')."""
    return ID_OVERRIDES.get(key, "rcmfd_" + key)


# rcmail_action_settings_index::user_prefs() $field_id values that differ
# from the default rcmfd_<pref> pattern:
ID_OVERRIDES = {
    "language": "rcmfd_lang",
    "pretty_date": "rcmfd_prettydate",
    "display_next": "rcmfd_displaynext",
    "prefer_html": "rcmfd_htmlmsg",
    "compose_extwin": "rcmfdcompose_extwin",
    "draft_autosave": "rcmfd_autosave",
    "mime_param_folding": "rcmfd_param_folding",
    "show_real_foldernames": "show_real_foldernames",
    "drafts_mbox": "_drafts_mbox",
    "sent_mbox": "_sent_mbox",
    "junk_mbox": "_junk_mbox",
    "trash_mbox": "_trash_mbox",
    "archive_mbox": "_archive_mbox",
    "archive_type": "ff_archive_type",
    "read_when_deleted": "rcmfd_read_deleted",
    "read_on_archive": "ff_read_on_archive",
}


def _sel(key, title, prefs, attrs=""):
    opts = getattr(D, SELECTS[key])
    val = str(prefs.get(key, DEFAULTS.get(key, "")))
    return {"type": "select", "key": key, "name": "_" + key,
            "id": _id(key), "title": title, "options": opts,
            "value": val, "attrs": attrs}


def _cb(key, title, prefs, hint=None, onchange=""):
    row = {"type": "checkbox", "key": key, "name": "_" + key,
           "id": _id(key), "title": title,
           "checked": bool(prefs.get(key, DEFAULTS.get(key, 0)))}
    if hint:
        row["hint"] = hint
    if onchange:
        row["attrs"] = f'onchange="{onchange}"'
    return row


def _mailview_main(p):
    # settings/index.php:557-616 — prefer_html is coupled to show_images:
    # the checkbox toggles the select's disabled state (and resets it to 0)
    # client-side, and the initial state mirrors PHP empty(prefer_html).
    prefer = str(p.get("prefer_html", DEFAULTS["prefer_html"])) not in (
        "", "0", "None", "False")
    show = _sel("show_images", "Allow remote resources (images, styles)", p)
    if not prefer:
        show["value"] = "0"
        show["attrs"] = 'disabled="disabled"'
    return [
        _cb("message_extwin", "Open message in a new window", p),
        _cb("message_show_email", "Show email address with display name", p),
        _cb("prefer_html", "Display HTML", p,
            onchange="$('#rcmfd_show_images').prop('disabled', !this.checked)"
                     ".val(0)"),
        show,
        _sel("mdn_requests", "On request for return receipt", p),
        _cb("inline_images", "Display attached images below the message", p),
    ]


def _txt(key, title, prefs):
    return {"type": "text", "key": key, "name": "_" + key,
            "id": _id(key), "title": title,
            "value": str(prefs.get(key, DEFAULTS[key])),
            "size": TEXTS[key]}


def _folder_tree(folders):
    """Order folders the way the reference folder_selector does: folder tree
    flattened depth-first (parent immediately followed by its children),
    INBOX first, siblings alphabetically (case-insensitive)."""
    tree = {}
    for f in folders:
        node = tree
        for part in f.split("/"):
            node = node.setdefault(part + "/", {})
    def emit(prefix, node, out):
        for name in sorted(node, key=lambda k: (k != "INBOX/", k.lower())):
            out.append(prefix + name.rstrip("/"))
            emit(prefix + name, node[name], out)
    out = []
    emit("", tree, out)
    return out


def _folder(key, title, prefs, folders):
    # rcmail_action::folder_selector(noselection '---', folder_filter mail,
    # folder_rights w) over SUBSCRIBED folders; INBOX implicitly included.
    # All selectors but _sent_mbox carry the "no INBOX as special" guard
    # (index.php #1486114, #1488279, #1489219).
    opts = [("", "---")] + [(f, f) for f in _folder_tree(folders)]
    onchange = ("if ($(this).val() == 'INBOX') $(this).val('')"
                if key != "sent" else "")
    pk = key + "_mbox"
    return {"type": "select", "key": pk, "name": "_" + pk,
            "id": _id(pk), "title": title, "options": opts,
            "value": str(prefs.get(pk, DEFAULTS.get(pk, ""))),
            "attrs": (("onchange=\"" + onchange + "\"") if onchange else "")}


def sections(prefs, folders):
    """Return {key: {label, blocks:[(class, legend, [fields])]}}."""
    p = prefs
    return {
        "general": {"label": "User Interface", "blocks": [
            ("main", "Main Options", [
                _sel("language", "Language", p),
                _sel("timezone", "Time zone", p),
                _sel("time_format", "Time format", p),
                _sel("date_format", "Date format", p),
                _cb("pretty_date", "Pretty dates", p),
                _cb("display_next", "Display next list entry after delete/move", p),
                _sel("refresh_interval", "Refresh (check for new messages, etc.)", p),
            ]),
            ("browser", "Browser Options", [
                _cb("standard_windows", "Handle popups as standard windows", p),
                {"type": "mailto", "name": "_mailto_handler", "id": "mailtoprotohandler",
                 "title": "Register protocol handler for mailto: links"},
            ]),
        ]},
        "mailbox": {"label": "Mailbox View", "blocks": [
            ("main", "Main Options", [
                _sel("mail_read_time", "Mark messages as read", p),
                _sel("autoexpand_threads", "Expand message threads", p),
                _txt("mail_pagesize", "Rows per page", p),
            ]),
            ("new_message", "New Message", [
                _cb("check_all_folders", "Check all folders for new messages", p),
            ]),
        ]},
        "mailview": {"label": "Displaying Messages", "blocks": [
            ("main", "Main Options", _mailview_main(p)),
            ("advanced", "Advanced options", [
                _sel("default_charset", "Default Character Set", p),
            ]),
        ]},
        "compose": {"label": "Composing Messages", "blocks": [
            ("main", "Main Options", [
                _cb("compose_extwin", "Compose in a new window", p),
                _sel("htmleditor", "Compose HTML messages", p),
                _sel("draft_autosave", "Automatically save draft", p),
                _cb("mdn_default", "Always request a return receipt", p),
                _cb("dsn_default", "Always request a delivery status notification", p),
                _cb("reply_same_folder", "Place replies in the folder of the message being replied to", p),
                _sel("reply_mode", "When replying", p),
                _sel("forward_attachment", "Messages forwarding", p),
                {"type": "fontgroup", "title": "Default font of HTML message",
                 "fields": [_sel("default_font", "Default font of HTML message", p),
                            _sel("default_font_size", "Default font size", p)]},
                _sel("reply_all_mode", "Default action of [Reply all] button", p),
            ]),
            ("editor", "Editor Options", [
                _cb("enable_autolink", "Automatically convert valid URLs into hyperlinks", p),
                _cb("keep_formatting_default", "Always keep original text formatting", p),
            ]),
            ("sig", "Signature Options", [
                _sel("show_sig", "Automatically add signature", p),
                _cb("sig_below", "Place signature below the quoted message", p),
                _cb("strip_existing_sig", "When replying remove original signature from message", p),
                _cb("sig_separator", "Force standard separator in signatures", p),
            ]),
            ("spellcheck", "Spellcheck Options", [
                _cb("spellcheck_before_send", "Check spelling before sending a message", p),
                _cb("spellcheck_ignore_syms", "Ignore words with symbols", p),
                _cb("spellcheck_ignore_nums", "Ignore words with numbers", p),
                _cb("spellcheck_ignore_caps", "Ignore words with all letters capitalized", p),
            ]),
            ("advanced", "Advanced options", [
                _sel("mime_param_folding", "Attachment names", p),
                _cb("force_7bit", "Use MIME encoding for 8-bit characters", p),
                _cb("compose_save_localstorage", "Save in the browser's local storage (temporarily)", p),
            ]),
        ]},
        "addressbook": {"label": "Contacts", "blocks": [
            ("main", "Main Options", [
                {"type": "select", "key": "default_addressbook",
                 "name": "_default_addressbook", "id": "rcmfd_default_addressbook",
                 "title": "Default address book",
                 "options": [("0", "Personal Addresses")],
                 "value": str(p.get("default_addressbook", ""))},
                _sel("addressbook_name_listing", "List contacts as", p),
                _sel("addressbook_sort_col", "Sorting column", p),
                _txt("addressbook_pagesize", "Rows per page", p),
                _sel("contact_form_mode", "Contact form mode", p),
                _cb("autocomplete_single", "Skip alternative email addresses in autocompletion", p),
            ]),
            ("collected", "Collected addresses", [
                _sel("collected_recipients", "Store outgoing email recipients in", p),
                _sel("collected_senders", "Store trusted senders in", p),
            ]),
        ]},
        "folders": {"label": "Special Folders", "blocks": [
            ("main", "Main Options", [
                _cb("show_real_foldernames", "Show real names for special folders", p),
                _folder("drafts", "Drafts", p, folders),
                _folder("sent", "Sent", p, folders),
                _folder("junk", "Junk", p, folders),
                _folder("trash", "Trash", p, folders),
                _folder("archive", "Archive", p, folders),
                _sel("archive_type", "Divide archive by", p),
            ]),
        ]},
        "server": {"label": "Server Settings", "blocks": [
            ("main", "Main Options", [
                _cb("read_when_deleted", "Mark the message as read on delete", p),
                _cb("flag_for_deletion", "Flag the message for deletion instead of delete", p),
                _cb("skip_deleted", "Do not show deleted messages", p),
                _cb("delete_junk", "Directly delete messages in Junk", p),
            ]),
            ("maintenance", "Maintenance", [
                _sel("logout_purge", "Clear Trash on logout", p),
                _cb("logout_expunge", "Compact Inbox on logout", p),
            ]),
        ]},
        "encryption": {"label": "Encryption", "blocks": [
            ("mailvelope", "Mailvelope options", [
                _cb("mailvelope_main_keyring", "Use Mailvelope main keyring", p),
            ]),
        ]},
    }


def section_field_names(section):
    """All _field names rendered by a section (checkboxes included)."""
    spec = sections({}, [])
    names = []
    for _cls, _leg, fields in spec.get(section, {"blocks": []})["blocks"]:
        for f in fields:
            if f["type"] == "fontgroup":
                names.extend(sub["name"] for sub in f["fields"])
            else:
                names.append(f["name"])
    return [n for n in names if n]


def apply_form(prefs, form):
    """Apply a posted prefs form to the prefs dict (Roundcube field names)."""
    for name in form:
        if not name.startswith("_") or name in ("_task", "_action", "_section",
                                                "_token", "_framed"):
            continue
        key = name[1:]
        if key.endswith("_mbox") and key[:-5] in FOLDERS:
            # Roundcube stores the full key (trash_mbox), verified live via
            # the reference DB (archive_mbox => 'Archive'); do NOT strip it
            prefs[key] = form[name].strip()
        elif key in CHECKBOXES:
            prefs[key] = 1 if form[name] == "1" else 0
        elif key in SELECTS or key in TEXTS \
                or key == "default_addressbook":
            prefs[key] = form[name].strip()
    # unchecked boxes are omitted by the browser: clear the section's boxes
    section = form.get("_section", "")
    for name in section_field_names(section):
        key = name[1:]
        if name.startswith("_") and key not in ("default_addressbook",) \
                and key in CHECKBOXES and name not in form:
            prefs[key] = 0
    return prefs
