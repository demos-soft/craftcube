"""Tests for the YAML localization layer and the tools/i18n.py dev tool."""

import importlib.util
import os

import yaml

from app import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def test_messages_domain():
    assert i18n.gettext("loginfailed", "de_DE", domain="messages") == "Die Anmeldung ist fehlgeschlagen."


def test_missing_translation_falls_back_to_english():
    # a language whose catalogue is (near-)empty still yields en_US texts
    texts = i18n.catalogue("en_GB")
    assert texts["login"] == "Login"


def test_en_key_roundtrip():
    assert i18n.en_key("Login") == "login"
    assert i18n.translate_en("Pretty dates", "de_DE") != "Pretty dates"
    # unknown English strings pass through unchanged
    assert i18n.translate_en("Default font size", "de_DE") == "Default font size"


# ----------------------------------------------------------- YAML layer rules
def test_no_php_files_ship_in_locale():
    for _dirpath, _dirs, files in os.walk(i18n.LOC_DIR):
        for fn in files:
            assert not fn.endswith(".inc"), fn
            assert fn.endswith(".yaml") or fn == "COPYING", fn


def test_languages_yaml_index():
    names = i18n.language_names()
    assert names["de_DE"].startswith("German")
    assert "ber" in names and "ku_IQ" in names  # dirs upstream forgot to index


def test_empty_rows_fall_back_to_english():
    # sync seeds rows as '' - they must never surface as empty UI strings
    for lang in i18n.available_languages():
        assert all(v for v in i18n.catalogue(lang).values()), lang


def test_js_labels_complete_for_all_languages():
    for lang in i18n.available_languages():
        labels = i18n.js_labels(lang)
        assert all(v and not v.startswith("[") for v in labels.values()), lang


def test_yaml_scalar_typing_pitfalls():
    # sexagesimal '16:9' and YAML-1.1 bool 'No' must survive as strings
    assert i18n.gettext("layoutwidescreen", "be_BE") == "16:9"
    assert isinstance(i18n._load_domain("lv_LV", "labels")["from"], str)


def test_catalogue_values_are_strings():
    # raw rows may be empty (sync seeds, en_US overlay fills at runtime);
    # what must never happen is a non-string (YAML re-typed scalar)
    for lang in i18n.available_languages():
        for dom in i18n.DOMAINS:
            for k, v in i18n._load_domain(lang, dom).items():
                assert isinstance(v, str), (lang, dom, k, type(v).__name__)


# ----------------------------------------------------------------- dev tool
def test_tool_verify_passes_on_shipped_catalogues(monkeypatch, capsys):
    tool = _load_tool()
    monkeypatch.setattr(tool, "LOC", i18n.LOC_DIR)
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0
    assert "verify: OK" in capsys.readouterr().out


def test_tool_add_sync_verify_remove(tmp_path, monkeypatch, capsys):
    """Full lifecycle in a scratch locale tree."""
    tool = _load_tool()
    loc = tmp_path / "locale"
    for lang in ("en_US", "de_DE"):
        (loc / lang).mkdir(parents=True)
    (loc / "languages.yaml").write_text(
        "names:\n  en_US: English (US)\n  de_DE: German (Deutsch)\naliases: {}\n", encoding="utf-8"
    )
    (loc / "en_US" / "labels.yaml").write_text("login: Login\nwelcome: Welcome to $product\n", encoding="utf-8")
    (loc / "de_DE" / "labels.yaml").write_text("login: Anmelden\n", encoding="utf-8")
    monkeypatch.setattr(tool, "LOC", str(loc))

    # verify flags the missing key
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 1
    assert "missing key 'welcome'" in capsys.readouterr().out

    # sync seeds it empty (English fallback), verify then passes
    tool.cmd_sync(_NS("sync", lang="all", fill=False, prune=False, only_present=False))
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0

    # a translation with a wrong placeholder set is a warning, --strict fails
    de = tool.load_cat("de_DE", "labels")
    de["welcome"] = "Willkommen"
    tool.save_cat("de_DE", "labels", de)
    assert tool.cmd_verify(_NS("verify", lang="all", strict=False, stats=False)) == 0
    assert "placeholders differ" in capsys.readouterr().out
    assert tool.cmd_verify(_NS("verify", lang="all", strict=True, stats=False)) == 1

    # remove from every language, header comments survive round-trips
    assert tool.cmd_remove(_NS("remove", keys=["welcome"], lang="all")) == 0
    assert "welcome" not in tool.load_cat("en_US", "labels")
    assert "welcome" not in tool.load_cat("de_DE", "labels")
    text = (loc / "de_DE" / "labels.yaml").read_text(encoding="utf-8")
    assert text.startswith("# CraftCube catalogue")


def test_tool_quoting_roundtrip(tmp_path, monkeypatch):
    """Values YAML would re-type (16:9, No, 5, y, '') stay exact strings."""
    tool = _load_tool()
    loc = tmp_path / "locale"
    (loc / "en_US").mkdir(parents=True)
    monkeypatch.setattr(tool, "LOC", str(loc))
    data = tool.CommentedMap()
    for k, v in (("a", "16:9"), ("b", "No"), ("c", "5"), ("d", "y"), ("e", ""), ("f", " padded "), ("g", "plain text")):
        data[k] = v
    tool.save_cat("en_US", "labels", data)
    again = yaml.safe_load((loc / "en_US" / "labels.yaml").read_text(encoding="utf-8"))
    assert again == {"a": "16:9", "b": "No", "c": "5", "d": "y", "e": "", "f": " padded ", "g": "plain text"}
