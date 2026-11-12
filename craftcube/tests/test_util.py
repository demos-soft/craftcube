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
    def test_encode_escapes(self):
        f = {"name": "Jane, Doe", "firstname": "Jane", "surname": "Doe",
             "emails": [("work", "j@d.org")], "phones": [], "addresses": []}
        v = util.vcard_encode(f)
        assert "FN:Jane\\, Doe" in v
        assert "EMAIL;TYPE=work:j@d.org" in v

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
