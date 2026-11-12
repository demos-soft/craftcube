"""Language switch application regressions (user-reported: 'Language switch does not apply')."""
import pytest


@pytest.fixture(autouse=True)
def _no_imap(monkeypatch):
    # section forms and the sidebar enumerate IMAP folders; not the subject here
    from app import views
    monkeypatch.setattr(views, "folders_for_menu", lambda: [])


class TestLanguageSwitchApplies:
    def _post_general(self, client, lang):
        return client.post("/settings/preferences/general?_framed=1",
                           data={"_section": "general", "_language": lang})

    def test_language_select_persists(self, client):
        from app import prefs_sections
        out = prefs_sections.apply_form({"language": "en_US"},
                                        {"_language": "de_DE", "_section": "general"})
        assert out["language"] == "de_DE"

    def test_language_change_reloads_window_like_rc(self, client):
        # prefs_save.php: language change => output->command('reload', 500);
        # the reference reloads the whole window so all chrome re-renders
        r = self._post_general(client, "de_DE")
        assert r.status_code == 200  # inline reload page, not a silent redirect
        body = r.get_data(as_text=True)
        assert "location.reload" in body and "500" in body
        # persisted: the framed form now selects de_DE
        h = client.get("/settings/preferences/general?_framed=1").get_data(as_text=True)
        assert 'value="de_DE" selected="selected"' in h
        # and the UI chrome follows on the next page load
        h = client.get("/settings").get_data(as_text=True)
        assert "Einstellungen" in h or "Kontakte" in h

    def test_same_language_keeps_plain_redirect(self, client):
        self._post_general(client, "en_US")
        r = self._post_general(client, "en_US")
        assert r.status_code == 302  # no reload page without an actual change

    def test_framed_save_button_is_wired(self, client):
        # the Save button renders OUTSIDE the <form> (.formbuttons sibling,
        # like the reference); without form="form" it is a dead button in the
        # real browser UI (user-reported: language switch does not apply)
        h = client.get("/settings/preferences/general?_framed=1").get_data(as_text=True)
        assert 'id="form"' in h
        assert 'form="form"' in h

    def test_pages_declare_current_language(self, client):
        # html lang must follow the language preference (RC sets it from locale)
        self._post_general(client, "de_DE")
        for url in ("/settings", "/settings/preferences/general?_framed=1"):
            h = client.get(url).get_data(as_text=True)
            assert 'lang="de"' in h, url

    def test_mailvelope_warning_banner_is_elastic_alert(self, client):
        # the reference renders the extension-missing notice as an elastic
        # 'alert alert-warning' banner with an icon column, shown without
        # jQuery (CraftCube has no $; a $() call left the banner invisible)
        h = client.get("/settings/preferences/encryption?_framed=1").get_data(as_text=True)
        assert 'id="mailvelope-warning"' in h
        assert 'class="boxwarning ui alert alert-warning"' in h
        assert '<i class="icon"></i>' in h
        assert "$('#mailvelope-warning')" not in h
        assert "document.getElementById('mailvelope-warning')" in h
