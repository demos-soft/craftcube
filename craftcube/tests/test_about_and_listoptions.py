"""About dialog plugin metadata (rcube_plugin_api::get_info +
rcmail_action_settings_about::plugins_list port) and the mail list-options
dialog (ui.js menu_messagelist port)."""
from pathlib import Path

from app.plugins import get_api


def test_get_info_from_composer_metadata(app):
    with app.app_context():
        info = get_api().get_info("zipdownload")
    assert isinstance(info, dict)
    assert info["name"] == "zipdownload"
    assert info["version"] == "3.6"
    # composer SPDX id shortened like the reference does
    assert info["license"] == "GPL-3.0+"
    assert info["license_uri"] == "https://www.gnu.org/licenses/gpl.html"
    # php/ext-zip/plugin-installer deps are not bundled plugins
    assert info["require"] == []


def test_get_info_rejects_bad_names(app):
    with app.app_context():
        assert get_api().get_info("no_such_plugin") is False
        assert get_api().get_info("bad/../name") is False


def test_about_lists_active_plugins(client):
    resp = client.get("/about?_framed=1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "zipdownload" in html
    assert ">3.6<" in html
    assert "GPL-3.0+" in html
    assert "https://www.gnu.org/licenses/gpl.html" in html


def test_mail_options_link_opens_dialog_not_popup():
    tpl = (Path(__file__).resolve().parents[1]
           / "app" / "templates" / "mail.html").read_text()
    assert "return cc_listoptions_dialog(this, event)" in tpl
    assert 'data-popup="listoptions-menu"' not in tpl
    assert "cc_apply_list_options()" not in tpl
