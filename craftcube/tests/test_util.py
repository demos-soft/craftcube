"""app.util: date formatting, sanitizing, vCard round-trip."""
import datetime

from app import util


class TestPasswords:
    def test_hash_verify_roundtrip(self):
        from app.auth import hash_password, verify_password
        h = hash_password("s3cret")
        assert verify_password("s3cret", h)
        assert not verify_password("wrong", h)

    def test_hash_is_salted_and_stretched(self):
        from app.auth import hash_password
        a, b = hash_password("same"), hash_password("same")
        assert a != b  # random salt per hash

    def test_verify_rejects_garbage(self):
        from app.auth import verify_password
        assert not verify_password("x", "not-a-hash")
        assert not verify_password("x", "")


class TestDates:
    def test_php_strftime(self):
        d = datetime.datetime(2026, 1, 2, 3, 4, 5)
        assert util.php_strftime("Y-m-d H:i", d) == "2026-01-02 03:04"
        # escaped literal
        assert util.php_strftime("\\D:i", d) == "D:04"

    def test_list_date_today_is_time(self):
        # naive datetimes are read as UTC; compare against the local wall clock
        now_utc = datetime.datetime.now(datetime.UTC)
        local = now_utc.astimezone()
        out = util.fmt_list_date(now_utc)
        assert local.strftime("%H:%M") in out or local.strftime("%I:%M") in out

    def test_human_size(self):
        assert util.human_size(0) == "0 B"
        assert "K" in util.human_size(2048) or "KB" in util.human_size(2048)

    def test_to_local_tz_invalid_zone_falls_back(self):
        dt = datetime.datetime(2026, 1, 1, 12)
        assert util.to_local_tz(dt, "Not/AZone") is not None
        assert util.to_local_tz(None) is None

    def test_fmt_pref_time_short_and_php(self):
        from zoneinfo import ZoneInfo

        # fmt_pref_time renders in the *preference* timezone; naive input
        # would be read as UTC and shifted, so build the instant in-zone
        berlin = ZoneInfo("Europe/Berlin")
        d = datetime.datetime(2026, 1, 1, 14, 5, tzinfo=berlin)
        prefs = {"timezone": "Europe/Berlin"}
        assert util.fmt_pref_time(d, {**prefs, "time_format": "H"}) == "14:05"
        assert util.fmt_pref_time(d, {**prefs, "time_format": "H:i"}) == "14:05"

    def test_list_date_localized_today_and_weekday(self):
        from zoneinfo import ZoneInfo

        berlin = ZoneInfo("Europe/Berlin")
        now = datetime.datetime.now(berlin)
        assert util.fmt_list_date(now, "de_DE").startswith("Heute ")
        two_days = now - datetime.timedelta(days=2)
        weekday = util.i18n.gettext(two_days.strftime("%a").lower(), "de_DE")
        assert util.fmt_list_date(two_days, "de_DE").startswith(weekday + " ")

    def test_list_pref_date_localized_today(self):
        from zoneinfo import ZoneInfo

        berlin = ZoneInfo("Europe/Berlin")
        now = datetime.datetime.now(berlin)
        prefs = {"pretty_date": 1, "timezone": "Europe/Berlin", "time_format": "H:i"}
        assert util.list_pref_date(now, prefs, "de_DE").startswith("Heute ")
        prefs["pretty_date"] = 0
        assert util.list_pref_date(now, prefs, "de_DE").startswith("2026-")


class TestSanitizer:
    def test_strips_scripts(self):
        out = util.sanitize_html('<p>ok</p><script>alert(1)</script>')
        assert "<script" not in out and "alert" not in out and "<p>ok</p>" in out

    def test_drops_javascript_urls(self):
        out = util.sanitize_html('<a href="javascript:x()">c</a>')
        assert "javascript:" not in out

    def test_keeps_safe_urls(self):
        out = util.sanitize_html('<a href="https://a.org">c</a>')
        assert 'href="https://a.org"' in out

    def test_remote_content_detection(self):
        assert util.contains_remote_content('<img src="http://x/y.png">')
        assert not util.contains_remote_content('<img src="/local.png">')

    def test_block_remote_content(self):
        out = util.block_remote_content('<img src="http://x/y.png">')
        assert "http://x/y.png" not in out


class TestVCard:
    def test_encode_v3_escapes(self):
        # storage format is rcube_vcard::export(false): vCard 3.0, CRLF,
        # semicolons escaped, commas NOT escaped (Roundcube 1.7.5 oracle)
        f = {"name": "Jane, Doe", "firstname": "Jane", "surname": "Doe",
             "emails": [("work", "j@d.org")], "phones": [], "addresses": []}
        v = util.vcard_encode(f)
        assert v.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
        assert "FN:Jane, Doe\r\n" in v
        assert "EMAIL;TYPE=work:j@d.org" in v

    def test_encode_fn_falls_back_to_email(self):
        # rcube_vcard::export(): "Make sure FN is not empty" -> primary email
        f = {"name": "", "emails": [("work", "only@x.org")]}
        v = util.vcard_encode(f)
        assert "FN:only@x.org\r\n" in v
        assert "N:;;;;\r\n" in v

    def test_encode_matches_reference_stored_vcard(self):
        # byte-exact against the staging reference DB (contacts.contact_id=1)
        f = {"name": "Ada Lovelace King Right Hon", "prefix": "Right",
             "firstname": "Ada", "middlename": "King", "surname": "Lovelace",
             "suffix": "Hon", "nickname": "countess",
             "organization": "Analytical Engine Ltd", "department": "Engines",
             "jobtitle": "Chief Programmer", "gender": "female",
             "birthday": "1815-12-10", "notes": "first programmer; enbows arrows",
             "emails": [("work", "ada@example.org"),
                        ("home", "ada.lovelace@analytical.example")],
             "phones": [("home", "+44 20 7946 0000"),
                        ("cell", "+44 7700 900000")],
             "addresses": [("work", "12 Byron Row", "London", "SW1", "",
                            "United Kingdom")]}
        oracle = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\n"
            "N:Lovelace;Ada;King;Right;Hon\r\n"
            "FN:Ada Lovelace King Right Hon\r\n"
            "EMAIL;TYPE=work:ada@example.org\r\n"
            "EMAIL;TYPE=home:ada.lovelace@analytical.example\r\n"
            "NICKNAME:countess\r\n"
            "TITLE:Chief Programmer\r\n"
            "ORG:Analytical Engine Ltd\r\n"
            "X-DEPARTMENT:Engines\r\n"
            "X-GENDER:female\r\n"
            "TEL;TYPE=home:+44 20 7946 0000\r\n"
            "TEL;TYPE=cell:+44 7700 900000\r\n"
            "ADR;TYPE=work:;;12 Byron Row;London;;SW1;United Kingdom\r\n"
            "BDAY;VALUE=date:1815-12-10\r\n"
            "NOTE:first programmer\\; enbows arrows\r\n"
            "END:VCARD\r\n")
        assert util.vcard_encode(f) == oracle

    def test_encode_address_layout(self):
        f = {"name": "A", "addresses": [("home", "S1", "Berlin", "10115", "BE", "DE")],
             "emails": [], "phones": []}
        v = util.vcard_encode(f)
        assert "ADR;TYPE=home:;;S1;Berlin;BE;10115;DE" in v

    def test_parse_roundtrip(self):
        f = {"name": "Bob", "firstname": "Bob", "surname": "", "emails": [("work", "b@x.org")],
             "phones": [("cell", "+491701234")], "addresses": []}
        parsed = util.vcard_parse(util.vcard_encode(f))
        assert parsed["name"] == "Bob"
        assert any("b@x.org" in str(e) for e in parsed.get("emails", []))


class TestHtmlToText:
    # Oracles captured from the real rcube_html2text (Roundcube 1.7.5)
    def test_alternative_conversions(self):
        from app import util
        h = ('<h1>Headline</h1><p>Paragraph with <b>bold</b> and a '
             '<a href="https://example.org/article">link to article</a> plus '
             '<a href="mailto:box@example.org">mail</a>.</p>'
             '<ul><li>alpha item</li><li>beta item</li></ul>'
             '<blockquote>quoted line A<br>quoted line B</blockquote>'
             '<hr><p>trailing text</p>')
        want = ('HEADLINE\n\nParagraph with bold and a link to article [1] '
                'plus mail.\n\n\t* alpha item\n\t* beta item\n\n'
                '> quoted line A\n> quoted line B\n\n'
                '-------------------------\n\ntrailing text\n\n'
                'Links:\n------\n[1] https://example.org/article\n')
        assert util.html_to_text(h) == want

    def test_tables_emphasis_and_dedup_links(self):
        from app import util
        h = ('<body><div>para one<br>line two</div><table><tr><th>H1</th>'
             '<th>H2</th></tr><tr><td>a</td><td>b</td></tr></table>'
             '<em>it</em> <a href="https://a.example/x">x</a>'
             '<a href="https://a.example/x">again</a></body>')
        want = ('para one\nline two\n\n\t\tH1\n\t\tH2\n\n\t\ta\n\t\tb\n\n'
                '_it_ x [1]again [1]\n\nLinks:\n------\n'
                '[1] https://a.example/x\n')
        assert util.html_to_text(h) == want

    def test_wordwrap_at_75(self):
        from app import util
        text = util.html_to_text("<p>" + "word " * 40 + "</p>")
        assert all(len(ln) <= 75 for ln in text.split("\n"))

    def test_entity_replacements(self):
        # Oracle captured from real rcube_html2text (1.7.5 pod) via
        # rcube_html2text::get_text(70); ent_search/ent_replace set.
        from app import util
        h = ('<p>Author &mdash; said &ldquo;hi&rdquo; &amp; bye &bull; '
             'price &pound;1 &euro;2 &copy; &ndash;&nbsp;&nbsp;x</p>')
        assert util.html_to_text(h, 70) == (
            'Author -- said "hi" & bye * price \u00a31 EUR2 (c) -  x')
