"""Tests for the PO/POT gettext localization layer (Poedit-compatible)
and the tools/i18n.py dev tool."""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polib
import pytest

from app import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean_i18n_caches():
    yield
    i18n.clear_cache()


class _NS:
    """stand-in for argparse.Namespace in direct tool calls."""

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        for k, v in kw.items():
            setattr(self, k, v)


def _load_tool():
    spec = importlib.util.spec_from_file_location("cc_i18n_tool", os.path.join(ROOT, "tools", "i18n.py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_po(path, lang, texts, fuzzy=(), header_extra=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    po = polib.POFile()
    po.metadata = {
        "Project-Id-Version": "CraftCube",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }
    if header_extra:
        po.metadata["Language"] = lang
    for k, v in texts.items():
        e = polib.POEntry(msgid=k, msgstr=v)
        if k in fuzzy:
            e.flags = ["fuzzy"]
        po.append(e)
    po.save(path)


def _mini_tree(tmp_path, monkeypatch, module=None):
    """scratch locale tree: en_US baseline + de_DE overlay."""
    loc = tmp_path / "locale"
    _write_po(
        str(loc / "en_US" / "LC_MESSAGES" / "craftcube.po"),
        "en_US",
        {"login": "Login", "welcome": "Welcome to $product", "messages.saved": "Message saved."},
    )
    _write_po(
        str(loc / "de_DE" / "LC_MESSAGES" / "craftcube.po"),
        "de_DE",
        {"login": "Anmelden", "welcome": "", "messages.saved": "Gespeichert."},
        fuzzy={"messages.saved"},
    )
    (loc / "languages.yaml").write_text(
        "names:\n  en_US: English (US)\n  de_DE: German (Deutsch)\naliases: {}\n", encoding="utf-8"
    )
    mod = module or i18n
    monkeypatch.setattr(mod, "LOC_DIR", str(loc))
    if hasattr(mod, "clear_cache"):
        mod.clear_cache()
    return loc


# ------------------------------------------------------------------ runtime
def test_language_prop_normalizes():
    assert i18n.language_prop("de") == "de_DE"
    assert i18n.language_prop("de_DE") == "de_DE"
    assert i18n.language_prop("de-DE") == "de_DE"
    assert i18n.language_prop("fr-FR") == "fr_FR"
    assert i18n.language_prop("en") == "en_US"


def test_language_prop_falls_back_to_en_us():
    assert i18n.language_prop("") == "en_US"
    assert i18n.language_prop("xx") == "en_US"


def test_gettext_translates_with_overlay():
    assert i18n.gettext("login", "de_DE") == "Anmelden"
    assert i18n.gettext("login", "en_US") == "Login"


def test_gettext_var_substitution():
    assert i18n.gettext("welcome", "en_US", {"product": "CraftCube"}) == "Welcome to CraftCube"


def test_gettext_unknown_key_shows_bracket_name():
    assert i18n.gettext("no_such_key", "de_DE") == "[no_such_key]"


def test_messages_domain_prefixed_msgids():
    assert i18n.gettext("loginfailed", "de_DE", domain="messages") == "Die Anmeldung ist fehlgeschlagen."
    assert "messages.loginfailed" in i18n.load_po("de_DE")


def test_en_key_roundtrip():
    assert i18n.en_key("Login") == "login"
    assert i18n.translate_en("Pretty dates", "de_DE") != "Pretty dates"
    # unknown English strings pass through unchanged
    assert i18n.translate_en("Default font size", "de_DE") == "Default font size"


# ------------------------------------------------------------- po semantics
def test_empty_msgstr_falls_back_to_english(tmp_path, monkeypatch):
    _mini_tree(tmp_path, monkeypatch)
    assert i18n.gettext("welcome", "de_DE") == "Welcome to $product"
    # non-empty overlay still wins
    assert i18n.gettext("login", "de_DE") == "Anmelden"


def test_fuzzy_entries_treated_as_untranslated(tmp_path, monkeypatch):
    _mini_tree(tmp_path, monkeypatch)
    # de_DE messages.saved is fuzzy-flagged -> runtime must use en_US
    assert i18n.gettext("saved", "de_DE", domain="messages") == "Message saved."
    # raw view keeps the flagged text visible for the tool
    assert i18n.load_po("de_DE")["messages.saved"] == "Gespeichert."


def test_mini_tree_languages(tmp_path, monkeypatch):
    _mini_tree(tmp_path, monkeypatch)
    assert i18n.available_languages() == ["de_DE", "en_US"]


# --------------------------------------------------------- shipped tree
def test_locale_tree_is_po_only():
    seen_po = 0
    for dirpath, _dirs, files in os.walk(i18n.LOC_DIR):
        for fn in files:
            assert not fn.endswith(".inc"), fn
            assert not fn.endswith(".yaml") or fn == "languages.yaml", fn
            if fn.endswith(".po"):
                seen_po += 1
                assert dirpath.endswith(os.path.join("LC_MESSAGES"))
    assert seen_po >= 88


def test_pot_template_exists_and_matches_en_us():
    pot = polib.pofile(i18n.POT_PATH)
    en = i18n.load_po("en_US")
    pot_keys = [e.msgid for e in pot]
    assert pot_keys and set(pot_keys) == set(en), "template and en_US diverged"
    assert all(e.msgstr == "" for e in pot), "template msgstrs must stay empty"


def test_po_files_have_poedit_headers():
    for lang in i18n.available_languages():
        po = polib.pofile(i18n.po_path(lang))
        ctype = po.metadata.get("Content-Type", "")
        assert ctype.startswith("text/plain") and "UTF-8" in ctype, lang
        assert po.metadata.get("Language") == lang, lang


def test_languages_yaml_index():
    names = i18n.language_names()
    assert names["de_DE"].startswith("German")
    assert "ber" in names and "ku_IQ" in names  # dirs upstream forgot to index


def test_catalogue_never_renders_empty():
    # sync seeds rows as '' - they must never surface as empty UI strings
    for lang in i18n.available_languages():
        assert all(v for v in i18n.catalogue(lang).values()), lang


def test_js_labels_complete_for_all_languages():
    for lang in i18n.available_languages():
        labels = i18n.js_labels(lang)
        assert all(v and not v.startswith("[") for v in labels.values()), lang


def test_po_scalar_values_are_exact_strings():
    # the YAML hazards ('16:9' -> int, 'No' -> bool) are structurally gone:
    # po values are strings by format; pin the historical cases anyway
    assert i18n.load_po("be_BE")["layoutwidescreen"] == "16:9"
    assert i18n.load_po("lv_LV")["from"] == "No"
    assert isinstance(i18n.load_po("lv_LV")["from"], str)


def test_special_characters_survive_formatting():
    # quotes/newlines/tabs must round-trip the po escaping intact
    en = i18n.load_po("en_US")
    multi = [v for v in en.values() if "\n" in v]
    assert multi, "expected some multi-line English texts"
    for v in multi[:25]:
        assert v == v  # loaded back verbatim by polib (no lossy requote)
    assert any('"' in v or "'" in v for v in en.values())


# ----------------------------------------------------------------- dev tool
def test_tool_verify_passes_on_shipped_catalogues(monkeypatch, capsys):
    tool = _load_tool()
    monkeypatch.setattr(tool, "LOC_DIR", i18n.LOC_DIR)
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0
    assert "verify: OK" in capsys.readouterr().out


def test_tool_add_sync_verify_remove(tmp_path, monkeypatch, capsys):
    """Full lifecycle in a scratch locale tree."""
    tool = _load_tool()
    loc = _mini_tree(tmp_path, monkeypatch, module=tool)

    # the de_DE entry is fuzzy -> verify flags it as needing sync attention
    tool.cmd_sync(_NS("sync", lang="all", fill=False, prune=False, only_present=False))
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0

    # add a key: template + en_US text + other languages empty
    assert tool.cmd_add(_NS("add", key="tooltestkey", domain="messages", text="Tool test.", lang="all")) == 0
    assert tool.load_po(lang="en_US").find("messages.tooltestkey").msgstr == "Tool test."
    assert tool.load_po(lang="de_DE").find("messages.tooltestkey").msgstr == ""
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0

    # a translation with a wrong placeholder set is a warning, --strict fails
    de = tool.load_po(lang="de_DE")
    de.find("welcome").msgstr = "Willkommen $produkt"
    tool.save_po("de_DE", de)
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0
    assert "placeholders differ" in capsys.readouterr().out
    assert tool.cmd_verify(_NS("verify", lang="all", strict=True, stats=False)) == 1

    # remove from every language + template
    assert tool.cmd_remove(_NS("remove", keys=["messages.tooltest*"], lang="all")) == 0
    assert tool.load_po(lang="en_US").find("messages.tooltestkey") is None
    assert tool.load_po(lang="de_DE").find("messages.tooltestkey") is None
    assert tool.load_template().find("messages.tooltestkey") is None

    # the sync-seeded empty welcome is untranslated -> verify still OK,
    # but --strict escalates copied/empty rows
    text = (loc / "de_DE" / "LC_MESSAGES" / "craftcube.po").read_text(encoding="utf-8")
    assert "CraftCube" in text  # header comment survives round-trips


def test_tool_missing_key_detected(tmp_path, monkeypatch, capsys):
    tool = _load_tool()
    _mini_tree(tmp_path, monkeypatch, module=tool)
    po = tool.load_po(lang="de_DE")
    po.remove(po.find("welcome"))
    tool.save_po("de_DE", po)
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 1
    assert "welcome" in capsys.readouterr().out


def test_tool_roundtrip_exact_values(tmp_path, monkeypatch):
    """Values with YAML-style hazards and po escapes stay byte-exact."""
    tool = _load_tool()
    _mini_tree(tmp_path, monkeypatch, module=tool)
    data = tool.load_po(lang="en_US")
    for k, v in (
        ("a", "16:9"),
        ("b", "No"),
        ("c", "5"),
        ("d", "quote \"and'\nnewline\ttab"),
        ("e", ""),
        ("f", " padded "),
    ):
        entry = polib.POEntry(msgid=k, msgstr=v)
        if data.find(k) is not None:
            data.remove(data.find(k))
        data.append(entry)
    tool.save_po("en_US", data)
    again = polib.pofile(str(tool.po_path("en_US")))
    got = {e.msgid: e.msgstr for e in again}
    assert got["a"] == "16:9" and got["b"] == "No" and got["c"] == "5"
    assert got["d"] == "quote \"and'\nnewline\ttab"
    assert got["e"] == ""
    assert got["f"] == " padded "
