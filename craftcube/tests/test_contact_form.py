"""Contact edit form parity with Roundcube 1.7.5 elastic contactedit.

Contract sources: program/actions/contacts/index.php render_contact_form()
(head rows render hidden+menu-listed when empty; email/phone/address groups
render one blank row when empty, value rows otherwise; website/IM groups
render only when the record has values; gender/birthday are 'visible'
coltypes and always render; the notes add-field menu renders hidden) and
program/js/app.js insert_edit_field/delete_edit_field.
"""
import io
import re

import pytest

from app import util
from app.views import _compose_display_name, _contact_head_props, folders_for_menu


@pytest.fixture(autouse=True)
def _no_imap(monkeypatch):
    # the sidebar menu renders IMAP folders; not what these tests are about
    from app import views
    monkeypatch.setattr(views, "folders_for_menu", lambda: [])
    yield


def _cid(rv):
    return int(re.search(r"/contact/(\d+)", rv.headers["Location"]).group(1))


def _head_menu(html):
    m = re.search(r'class="addfieldmenu custom-select" rel="head">(.*?)</select>',
                  html, re.S)
    assert m, "addfieldmenu rel=head missing"
    return re.findall(r'<option value="([^"]*)"', m.group(1))


class TestComposeDisplayName:
    def test_name_parts_order(self):
        ext = {"prefix": "Right", "firstname": "Ada", "middlename": "King",
               "surname": "Lovelace", "suffix": "Hon", "emails": []}
        # array_intersect_key() preserves record order (CONTACT_COLTYPES:
        # firstname, surname, then middlename/prefix/suffix) -- verified by
        # two live RC saves: "Ada Lovelace King Right Hon" and
        # "Grace Hopper Murray Right RADM"
        assert _compose_display_name(ext) == "Ada Lovelace King Right Hon"

    def test_email_fallback_split(self):
        # local part split on . - _ with PHP ucfirst of both halves
        ext = {"emails": [("", "ada.lovelace@analytical.example")]}
        assert _compose_display_name(ext) == "Ada Lovelace"
        assert _compose_display_name(ext, full_email=True) == "ada.lovelace@analytical.example"

    def test_email_fallback_plain(self):
        ext = {"emails": [("", "bob@x.org")]}
        assert _compose_display_name(ext) == "Bob"
        assert _compose_display_name(ext, full_email=True) == "bob@x.org"

    def test_head_props_hide_composed_name(self):
        # save.php stored the composed name; the edit form hides the row
        # and offers 'name' in the head menu (index.php:886-890)
        ext = {"name": "Ada Lovelace", "firstname": "Ada", "surname": "Lovelace",
               "prefix": "", "middlename": "", "suffix": "", "emails": []}
        _contact_head_props(ext)
        assert ext["name_explicit"] is False
        ext["name"] = "The Countess"
        _contact_head_props(ext)
        assert ext["name_explicit"] is True


class TestNewContactForm:
    def test_head_rows_and_menu(self, client):
        html = client.get("/contact/new").get_data(as_text=True)
        # empty head rows render hidden
        for ff in ("prefix", "middlename", "suffix", "name", "nickname",
                   "organization", "department", "jobtitle"):
            m = re.search(r'<div class="[^"]*"[^>]*><label for="ff_%s">' % ff, html)
            assert m and 'style="display:none"' in m.group(0), f"{ff} row should be hidden"
        # firstname/surname always visible
        for ff in ("firstname", "surname"):
            m = re.search(r'<div class="[^"]*"[^>]*><label for="ff_%s">' % ff, html)
            assert m and 'style="display:none"' not in m.group(0), f"{ff} row should be visible"
        assert _head_menu(html) == ["", "prefix", "middlename", "suffix", "name",
                                    "nickname", "organization", "department",
                                    "jobtitle"]

    def test_group_menus_and_sections(self, client):
        html = client.get("/contact/new").get_data(as_text=True)
        # one blank row each for the always-visible multi groups
        for kind in ("email", "phone"):
            rows = re.findall(r'contactcontroller%s".*?</fieldset>' % kind,
                              html.split("<template")[0], re.S)
            assert len(rows) == 1 and rows[0].count("<div class=" + chr(34) + "row") == 1
        # website/IM groups do not render when empty, only as menu options
        sec = html.split('id="contactsectioncontact"')[1].split("</div>\n    </fieldset>")[0]
        assert "contactcontrolleremail" in sec and "contactcontrolleraddress" in sec
        assert "contactcontrollerwebsite" not in sec
        assert "contactcontrollerim" not in sec
        menu = re.search(r'rel="contact"[^>]*>(.*?)</select>', html, re.S).group(1)
        assert re.findall(r'<option value="([^"]*)"', menu) == [
            "", "email", "phone", "address", "website", "im"]
        # personal: gender + birthday render always, others as menu options
        assert 'class="contactfieldgroup contactcontrollergender"' in sec + html
        assert 'contactcontrollergender' in html
        assert 'contactcontrollerbirthday' in html
        pm = re.search(r'rel="personal"[^>]*>(.*?)</select>', html, re.S).group(1)
        assert re.findall(r'<option value="([^"]*)"', pm) == [
            "", "maidenname", "anniversary", "manager", "assistant", "spouse"]
        # notes menu renders with no options and hidden (elastic contract)
        nm = re.search(r'<select class="addfieldmenu custom-select" rel="notes"[^>]*>', html)
        assert nm and 'style="display:none"' in nm.group(0)

    def test_save_generates_display_name_and_v3_vcard(self, client, store, user):
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Grace", "_surname": "Hopper",
            "_subtype_email[]": "work", "_email[]": "grace@navy.example",
            "_website[]": "https://hopper.example.org",
            "_subtype_website[]": "homepage",
            "_im[]": "ghopper", "_subtype_im[]": "jabber",
            "_maidenname": "Bachman", "_gender": "female",
            "_notes": "compiler pioneer",
        }, follow_redirects=False)
        cid = _cid(rv)
        row = store.contact(user, cid)
        assert row["name"] == "Grace Hopper"  # composed at save (save.php:287)
        vcard = row["vcard"]
        assert vcard.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
        assert "X-MAIDENNAME:Bachman\r\n" in vcard
        assert "URL;TYPE=homepage:https://hopper.example.org\r\n" in vcard
        assert "X-JABBER:ghopper\r\n" in vcard
        assert "X-GENDER:female\r\n" in vcard

    def test_name_reset_when_equal_to_email(self, client, store, user):
        rv = client.post("/contact/new", data={
            "_cid": "", "_email[]": "solo@x.org", "_subtype_email[]": "work",
        })
        assert rv.status_code == 302
        row = store.contact(user, _cid(rv))
        # save.php:290-292 resets the composed-equals-email name...
        assert row["name"] == ""
        # ...but export() falls back to the email for FN
        assert "FN:solo@x.org\r\n" in row["vcard"]

    def test_body_class_matches_reference_action(self, client, store):
        # RC task-settings/addressbook body classes: edit -> action-edit,
        # add -> action-add (visible to CSS selectors in the elastic port)
        import re as _re
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Body", "_surname": "Class",
            "_email[]": "b@c.example", "_subtype_email[]": "work",
        })
        m = _re.search(r"/contact/(\d+)", rv.headers["Location"])
        cid = m.group(1)
        html = client.get(f"/contact/edit/{cid}?_framed=1").get_data(as_text=True)
        assert 'class="task-addressbook action-edit"' in html
        html = client.get("/contact/new?_framed=1").get_data(as_text=True)
        assert 'class="task-addressbook action-add"' in html

    def test_framed_editor_is_bare_like_reference(self, client, store):
        # reference edit-contact frame (_level=2) renders bare: html.iframe,
        # h1.voice, form#contact-details.formcontent, sibling .formbuttons —
        # and NO app shell (menu/logo/#layout-content/header)
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Bare", "_surname": "Page",
            "_email[]": "bare@p.example", "_subtype_email[]": "work",
        }, follow_redirects=False)
        cid = _cid(rv)
        html = client.get(f"/contact/edit/{cid}?_framed=1").get_data(as_text=True)
        assert 'class="iframe"' in html
        assert '<h1 class="voice">Edit contact</h1>' in html
        assert 'id="contact-details" class="formcontent"' in html
        assert '<div class="formbuttons">' in html
        for shell in ('id="taskmenu"', 'id="logo"', 'id="layout-content"',
                      'back-content-button', 'includes/menu'):
            assert shell not in html, shell
        assert 'id="contacttabs"' in html
        # standalone (non-framed) keeps the full shell
        full = client.get(f"/contact/edit/{cid}").get_data(as_text=True)
        assert 'id="layout-content"' in full and 'class="iframe"' not in full

    def test_photo_widget_and_save_dirty_state(self, client, store, user):
        # elastic image_upload_input: hidden smart-upload form + hidden
        # marker inputs only (no visible native file input), Save starts
        # disabled until the form changes (rcmail check_stack)
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Photo", "_surname": "Widget",
            "_email[]": "pw@p.example", "_subtype_email[]": "work",
        }, follow_redirects=False)
        cid = _cid(rv)
        html = client.get(f"/contact/edit/{cid}?_framed=1").get_data(as_text=True)
        assert 'id="upload-formFrm"' in html
        assert 'name="_upload" value="1"' in html
        assert 'id="contactpic" class="image-upload" data-placeholder=' in html
        assert 'id="ff_photo_file"' in html and 'id="ff_photo"' in html
        for tag in [t for t in html.split("<input") if 'type="file"' in t]:
            assert "smart-upload" in tag, tag[:120]
        assert 'value="Save" disabled' in html
        # upload-form posts replace the photo only, fields stay (RC
        # rcmail.command('upload-photo'))
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080600"
            "00001f15c4890000000a49444154789c63000100000500010d0a2db4"
            "0000000049454e44ae426082")
        rv = client.post(f"/contact/edit/{cid}?_framed=1", data={
            "_upload": "1", "_cid": str(cid),
            "_photo": (io.BytesIO(png), "p.png"),
        }, content_type="multipart/form-data", follow_redirects=False)
        assert rv.status_code == 302 and f"/contact/edit/{cid}" in rv.headers["Location"]
        assert store.contact_photo(user, cid) == png
        row = store.contact(user, cid)
        assert row["firstname"] == "Photo" and row["email"] == "pw@p.example"
        # the editor now renders with a photo: marker '' and photo <img>
        html = client.get(f"/contact/edit/{cid}?_framed=1").get_data(as_text=True)
        assert 'name="_photo" id="ff_photo" value=""' in html
        assert f"/contact/{cid}/photo" in html
        # '-del-' marker on the main save deletes (save.php:62-72)
        client.post(f"/contact/edit/{cid}", data={
            "_cid": str(cid), "_firstname": "Photo", "_surname": "Widget",
            "_email[]": "pw@p.example", "_subtype_email[]": "work",
            "_photo": "-del-",
        }, follow_redirects=False)
        assert store.contact_photo(user, cid) is None
        # validation re-render (nonamewarning) replays with Save enabled
        bad = client.post("/contact/new", data={"_cid": "", "_photo": "-del-"})
        bad_html = bad.get_data(as_text=True)
        assert "value=\"Save\"" in bad_html and "value=\"Save\" disabled" not in bad_html

    def test_edit_shows_value_rows_and_no_present_options(self, client, store):
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Alan", "_surname": "Turing",
            "_nickname": "Al", "_email[]": "a@turing.example",
            "_subtype_email[]": "work", "_manager": "Max",
        }, follow_redirects=False)
        cid = _cid(rv)
        html = client.get(f"/contact/edit/{cid}").get_data(as_text=True)
        # nickname has a value -> row visible, absent from head menu
        m = re.search(r'<div class="nickname row"[^>]*>', html)
        assert m and 'style="display:none"' not in m.group(0)
        assert "nickname" not in _head_menu(html)
        # manager renders as a personal fieldset and drops from the menu
        assert 'contactcontrollermanager' in html
        pm = re.search(r'rel="personal"[^>]*>(.*?)</select>', html, re.S).group(1)
        assert "manager" not in re.findall(r'<option value="([^"]*)"', pm)
        # display name equals composed -> hidden with 'name' option
        m = re.search(r'<div class="displayname row"[^>]*>', html)
        assert 'style="display:none"' in m.group(0)
        assert "name" in _head_menu(html)

    def test_save_full_post_matches_reference_vcard(self, client, store, user):
        # same record as the reference staging DB contact, via the form
        rv = client.post("/contact/new", data={
            "_cid": "", "_prefix": "Right", "_firstname": "Ada",
            "_middlename": "King", "_surname": "Lovelace", "_suffix": "Hon",
            "_name": "Ada Lovelace King Right Hon", "_nickname": "countess",
            "_organization": "Analytical Engine Ltd", "_department": "Engines",
            "_jobtitle": "Chief Programmer", "_gender": "female",
            "_birthday": "1815-12-10",
            "_subtype_email[]": ["work", "home"],
            "_email[]": ["ada@example.org", "ada.lovelace@analytical.example"],
            "_subtype_phone[]": ["home", "mobile"],
            "_phone[]": ["+44 20 7946 0000", "+44 7700 900000"],
            "_subtype_address[]": ["work"], "_street[]": ["12 Byron Row"],
            "_locality[]": ["London"], "_zipcode[]": ["SW1"],
            "_region[]": [""], "_country[]": ["United Kingdom"],
            "_notes": "first programmer; enbows arrows",
        }, follow_redirects=False)
        cid = _cid(rv)
        row = store.contact(user, cid)
        expected = util.vcard_encode(util.vcard_parse(
            "BEGIN:VCARD\r\nVERSION:3.0\r\n"
            "N:Lovelace;Ada;King;Right;Hon\r\n"
            "FN:Ada Lovelace King Right Hon\r\n"
            "EMAIL;TYPE=work:ada@example.org\r\n"
            "EMAIL;TYPE=home:ada.lovelace@analytical.example\r\n"
            "NICKNAME:countess\r\nTITLE:Chief Programmer\r\n"
            "ORG:Analytical Engine Ltd\r\nX-DEPARTMENT:Engines\r\n"
            "X-GENDER:female\r\nTEL;TYPE=home:+44 20 7946 0000\r\n"
            "TEL;TYPE=cell:+44 7700 900000\r\n"
            "ADR;TYPE=work:;;12 Byron Row;London;;SW1;United Kingdom\r\n"
            "BDAY;VALUE=date:1815-12-10\r\n"
            "NOTE:first programmer\\; enbows arrows\r\nEND:VCARD\r\n"))
        assert row["vcard"] == expected


class TestVcardTypeMaps:
    # rcube_vcard $typemap/$phonetypemap/$addresstypemap both directions

    def test_phone_form_subtype_to_stored_type(self):
        # verified against a LIVE Roundcube 1.7.5 save (contact 6):
        # mobile->CELL via phonetypemap; everything else stored verbatim
        # because set()'s array_flip($typemap) lookup is keyed by $type_uc
        # while the flip's keys are lowercase -> never matches.
        assert util.rc_stored_type("TEL", "mobile") == "cell"
        assert util.rc_stored_type("TEL", "home") == "home"
        assert util.rc_stored_type("TEL", "workfax") == "workfax"
        assert util.rc_stored_type("TEL", "homefax") == "homefax"
        assert util.rc_stored_type("TEL", "other") == "other"
        assert util.rc_stored_type("EMAIL", "other") == "other"
        assert util.rc_stored_type("EMAIL", "work") == "work"

    def test_stored_type_to_form_subtype(self):
        assert util.rc_subtype("TEL", "cell") == "mobile"
        assert util.rc_subtype("TEL", "work,fax") == "workfax"
        assert util.rc_subtype("TEL", "fax") == "homefax"
        assert util.rc_subtype("EMAIL", "internet,work") == "work"
        assert util.rc_subtype("TEL", "") == ""

    def test_export_drops_other_and_internet(self):
        # rcube_vcard::export(): "TYPE=OTHER is non-standard, TYPE=INTERNET is
        # redundant, remove these"
        assert util._vc_typ("other") == ""
        assert util._vc_typ("other,fax") == ";TYPE=fax"
        f = {"name": "X", "firstname": "X", "surname": "",
             "emails": [("other", "x@y.z")], "phones": [], "addresses": []}
        v = util.vcard_encode(f)
        assert "EMAIL:x@y.z\r\n" in v

    def test_stored_cell_roundtrips_as_mobile(self):
        raw = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:;;;;\r\nFN:T T\r\n"
               "TEL;TYPE=cell:123\r\nEND:VCARD\r\n")
        ext = util.vcard_parse(raw)
        assert ext["phones"] == [("mobile", "123")]
        assert util.vcard_export(ext) == raw

    def test_form_post_mobile_stores_cell(self, client, store, user):
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Mob", "_surname": "Ile",
            "_subtype_phone[]": "mobile", "_phone[]": "+49 170 000000",
            "_subtype_im[]": "jabber", "_im[]": "mobster",
        })
        assert rv.status_code == 302
        cid = _cid(rv)
        row = store.contact(user, cid)
        assert "TEL;TYPE=cell:+49 170 000000\r\n" in row["vcard"]
        assert "X-JABBER:mobster\r\n" in row["vcard"]
        # the edit form shows the form-level subtype back
        html = client.get(f"/contact/edit/{cid}").get_data(as_text=True)
        m = re.search(r'name="_subtype_phone\[\]"[^>]*>(.*?)</select>', html, re.S)
        assert re.search(r'<option value="mobile"[^>]*selected', m.group(1))


class TestGroupRowOrder:
    # contact_field_values(): rows emitted in coltype subtype order

    def test_email_rows_sorted_by_subtype(self, client, store, user):
        from app import views as v
        ext = {"emails": [("work", "w@x.y"), ("home", "h@x.y"), ("zz", "z@x.y")],
               "phones": [("homefax", "1"), ("mobile", "2")],
               "websites": [("other", "o"), ("homepage", "p")],
               "name": "", "firstname": "", "surname": ""}
        v._contact_head_props(ext)
        assert [t for t, _ in ext["emails"]] == ["home", "work", "zz"]
        assert [t for t, _ in ext["phones"]] == ["mobile", "homefax"]
        assert [t for t, _ in ext["websites"]] == ["homepage", "other"]

    def test_edit_form_shows_home_email_first(self, client, store, user):
        rv = client.post("/contact/new", data={
            "_cid": "", "_firstname": "Ord", "_surname": "Ered",
            "_subtype_email[]": ["work", "home"],
            "_email[]": ["w@x.y", "h@x.y"],
        })
        cid = _cid(rv)
        html = client.get(f"/contact/edit/{cid}").get_data(as_text=True)
        html = html.split("<template")[0]  # drop inert JS row-templates
        subs = re.findall(r'name="_subtype_email\[\]"[^>]*>(.*?)</select>', html, re.S)
        order = [re.search(r'<option value="([^"]*)"[^>]*selected', m).group(1)
                 for m in subs]
        assert order == ["home", "work"]


class TestContactShow:
    # contacts/show framed page: RC locale subtype labels, RC personal
    # row order, no Address-Book source row (reference omits it entirely)

    def _grace(self, client):
        rv = client.post("/contact/new", data={
            "_cid": "", "_prefix": "Right", "_firstname": "Grace",
            "_middlename": "Murray", "_surname": "Hopper", "_suffix": "RADM",
            "_nickname": "amazing grace", "_organization": "Navy",
            "_subtype_email[]": ["home", "work"],
            "_email[]": ["gmhopper@cobol.example", "grace@navy.example"],
            "_subtype_phone[]": ["mobile", "homefax"],
            "_phone[]": ["+1 555 0100", "+1 555 0111"],
            "_subtype_website[]": ["homepage", "other"],
            "_website[]": ["https://grace.example.org", "https://alt.example.net"],
            "_gender": "female", "_birthday": "1906-12-09",
            "_maidenname": "Bachman", "_anniversary": "1930-08-15",
            "_manager": "Boss", "_assistant": "Helper", "_spouse": "Amaral",
            "_notes": "compiler pioneer",
        })
        return _cid(rv)

    def test_subtype_labels(self, client):
        cid = self._grace(client)
        html = client.get(f"/contact/{cid}").get_data(as_text=True)
        labels = re.findall(r'class="contactfieldlabel label">([^<]*)<', html)
        assert "Mobile" in labels      # stored cell -> form mobile -> label
        assert "Home Fax" in labels    # not 'Fax'/'Homefax'
        assert "Home Page" in labels   # not 'Homepage'

    def test_no_source_row(self, client):
        cid = self._grace(client)
        html = client.get(f"/contact/{cid}").get_data(as_text=True)
        assert "Address Book:" not in html
        assert 'class="source row"' not in html

    def test_personal_row_order(self, client):
        cid = self._grace(client)
        html = client.get(f"/contact/{cid}").get_data(as_text=True)
        order = [l for l in re.findall(r'class="contactfieldlabel label">([^<]*)<', html)
                 if l in ("Gender", "Maiden Name", "Birthday", "Anniversary",
                          "Manager", "Assistant", "Spouse")]
        assert order == ["Gender", "Maiden Name", "Birthday", "Anniversary",
                         "Manager", "Assistant", "Spouse"]


class TestDirectoryTree:
    # elastic #directorylist: sources-with-groups render the expand/collapse
    # caret (div.treetoggle) and aria tree states

    def test_caret_rendered_for_source_with_groups(self, client, store, user):
        store.contactgroup_save(user, "Mathematicians")
        html = client.get("/contacts").get_data(as_text=True)
        assert '<div class="treetoggle expanded">' in html
        m = re.search(r'<li class="addressbook selected"[^>]*>', html)
        assert 'aria-expanded="true"' in m.group(0)
        assert 'aria-selected="true"' in m.group(0)
        m = re.search(r'<li class="contactgroup[^"]*"[^>]*>', html)
        assert 'role="treeitem"' in m.group(0) and 'aria-level="2"' in m.group(0)

    def test_no_caret_without_groups(self, client):
        html = client.get("/contacts").get_data(as_text=True)
        assert 'class="treetoggle' not in html
        assert 'class="addressbook selected"' in html


class TestSettingsFrameEditors:
    # RC loads edit-identity/edit-response as a bare propform page into
    # #preferences-frame: html.iframe, no task rail/sidebar/back button,
    # RC labels (Display Name / Email / Set default; Name / Response Text),
    # Save-only formbuttons

    @staticmethod
    def _mk_identity(store, user):
        return store.identity_save(user, {
            "name": "Unit User", "organization": "", "email": "unit@example.org",
            "reply_to": "", "bcc": "", "signature": "", "html_signature": 0,
            "standard": 1})

    def test_identity_edit_framed(self, client, store, user):
        iid = self._mk_identity(store, user)
        html = client.get(f"/settings/identity/edit/{iid}?_framed=1").get_data(as_text=True)
        assert '<html lang="en" class="iframe">' in html
        assert 'action-edit-identity' in html
        assert 'id="rcmfd_name"' in html
        assert "Display Name" in html and "Set default" in html
        assert "Encryption" in html and "identityImageUpload" in html
        # legacy inline-editor artifacts must not appear
        assert "E-mail" not in html and "Set as default" not in html
        assert "back-content-button" not in html and ">Cancel<" not in html
        assert "Application tasks" not in html  # no task rail

    def test_identity_new_framed_title(self, client):
        html = client.get("/settings/identity/new?_framed=1").get_data(as_text=True)
        assert '<h1 class="voice">New identity</h1>' in html

    def test_response_editor_framed(self, client, store, user):
        rid = store.response_save(user, "Sig", "Hello", html=0)
        html = client.get(f"/settings/response/edit/{rid}?_framed=1").get_data(as_text=True)
        assert '<html lang="en" class="iframe">' in html
        assert "action-edit-response" in html
        assert 'id="ffname"' in html and 'id="fftext"' in html
        assert ">Name<" in html and "Response Text" in html
        assert "back-content-button" not in html and ">Cancel<" not in html
        html_new = client.get("/settings/response/new?_framed=1").get_data(as_text=True)
        assert '<h1 class="voice">Add response</h1>' in html_new

    def test_identity_save_keeps_record_open(self, client, store, user):
        iid = self._mk_identity(store, user)
        rv = client.post(f"/settings/identity/edit/{iid}?_framed=1", data={
            "_iid": str(iid), "_name": "Renamed", "_email": "unit@example.org",
        })
        assert rv.status_code == 302
        assert f"/settings/identity/edit/{iid}" in rv.headers["Location"]
        assert "_framed=1" in rv.headers["Location"]
        # app.js update_identity_row(id, name): parent syncs the row text
        assert "_saved=update" in rv.headers["Location"]

    def test_new_records_redirect_with_saved_insert(self, client, store, user):
        # app.js update_*_row(id, name, add=true): insert+select in parent
        self._mk_identity(store, user)  # a baseline identity exists
        rv = client.post("/settings/identity/new?_framed=1", data={
            "_iid": "", "_name": "Fresh", "_email": "fresh@example.org",
        })
        assert rv.status_code == 302
        assert "_saved=insert" in rv.headers["Location"]
        rv = client.post("/settings/response/new?_framed=1", data={
            "_id": "", "_name": "Fresh sig", "_text": "Bye", "_is_html": "0",
        })
        assert rv.status_code == 302
        assert "_saved=insert" in rv.headers["Location"]
        new_rid = rv.headers["Location"].split("/edit/")[1].split("?")[0]
        assert store.response(user, int(new_rid))["name"] == "Fresh sig"

    def test_editors_form_has_id_for_orphan_save_button(self, client, store, user):
        # RC puts .formbuttons outside <form>; the clone relies on the
        # button's form="form" attribute, which needs form#form to exist
        iid = self._mk_identity(store, user)
        html = client.get(f"/settings/identity/edit/{iid}?_framed=1").get_data(as_text=True)
        assert '<form name="form" id="form"' in html
        assert 'form="form"' in html
        rid = store.response_save(user, "Sig", "Hello", html=0)
        html = client.get(f"/settings/response/edit/{rid}?_framed=1").get_data(as_text=True)
        assert '<form name="form" id="form"' in html
        assert 'form="form"' in html
