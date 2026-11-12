"""Tests for the Roundcube-style localization layer."""
from app import i18n


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
    assert i18n.gettext("welcome", "en_US", {"product": "CraftCube"}) == \
        "Welcome to CraftCube"


def test_gettext_unknown_key_shows_bracket_name():
    assert i18n.gettext("no_such_key", "de_DE") == "[no_such_key]"


def test_messages_domain():
    assert i18n.gettext("loginfailed", "de_DE", domain="messages") == \
        "Die Anmeldung ist fehlgeschlagen."


def test_missing_translation_falls_back_to_english():
    # a language whose catalogue is (near-)empty still yields en_US texts
    texts = i18n.catalogue("en_GB")
    assert texts["login"] == "Login"


def test_en_key_roundtrip():
    assert i18n.en_key("Login") == "login"
    assert i18n.translate_en("Pretty dates", "de_DE") != "Pretty dates"
    # unknown English strings pass through unchanged
    assert i18n.translate_en("Default font size", "de_DE") == "Default font size"
