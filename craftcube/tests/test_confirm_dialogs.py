"""Confirmation-dialog fidelity tests.

The reference (program/js/app.js) shows every destructive confirmation
through confirm_dialog() -> a styled 'Are you sure...' dialog
(confirmationtitle), and delete_message() never confirms at all when a
trash mailbox is defined (silent move-to-trash).  Native window.confirm()
broke that look (and blocks automation), so it must not reappear.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
JS = APP / "static" / "craftcube.js"
TEMPLATES = APP / "templates"


def _code_lines(text):
    """Lines that are actual code (strip // and /* comment lines)."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        # drop trailing // comments
        if "//" in s:
            s = s.split("//", 1)[0]
        yield s


def test_no_native_confirm_in_craftcube_js():
    offenders = []
    for line in _code_lines(JS.read_text()):
        for m in re.finditer(r"confirm\(", line):
            prefix = line[:m.start()]
            if prefix.endswith("cc_confirm_dialog(") or prefix.endswith("."):
                continue
            if re.search(r"cc_confirm_dialog$", prefix):
                continue
            # cc_confirm_dialog( itself is fine
            if re.search(r"cc_confirm_dialog\($", prefix):
                continue
            if "cc_confirm_dialog(" in line:
                continue
            offenders.append(line)
    assert not offenders, f"native confirm() found in craftcube.js: {offenders}"


def test_no_native_confirm_in_templates():
    offenders = []
    for tpl in sorted(TEMPLATES.rglob("*.html")):
        for line in _code_lines(tpl.read_text()):
            if re.search(r"(?<!cc_)\bconfirm\(", line):
                offenders.append(f"{tpl.name}: {line.strip()}")
    assert not offenders, f"native confirm() found in templates: {offenders}"


def test_confirm_dialog_port():
    js = JS.read_text()
    assert "window.cc_confirm_dialog" in js
    # title is the reference 'confirmationtitle' label ("Are you sure...")
    start = js.index("window.cc_confirm_dialog")
    body = js[start:start + 900]
    assert "cc_get_label('confirmationtitle')" in body
    # reference show_popup_dialog default width (dialog measures 502 incl. border)
    assert "width: 500" in body
    # action button carries the command class + btn-danger (reference:
    # 'mainaction delete btn btn-primary btn-danger'), plus a Cancel button
    assert "mainaction " in body and "btn-danger" in body
    assert "cc_get_label('cancel')" in body


def test_toolbar_delete_has_no_confirmation():
    """RC delete_message() with a trash defined is a silent move — the
    toolbar/message handlers must not gate it on any confirm."""
    js = JS.read_text()
    start = js.index("cmd === 'delete'")
    window = js[start:start + 700]
    assert "cc_confirm_dialog" not in window
    assert "confirm(" not in window


def test_empty_folder_still_confirms_via_styled_dialog():
    js = JS.read_text()
    start = js.index("cmd === 'empty'")
    window = js[start:start + 400]
    assert "cc_confirm_dialog(" in window
    assert "purgefolderconfirm" in window
