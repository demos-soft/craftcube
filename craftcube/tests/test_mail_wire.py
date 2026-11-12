"""Wire-format parity tests: expected values captured from the reference
Roundcube 1.7.5 (PEAR Mail_mime / rcmail_sendmail) running on k8s3 staging
(php oracle scripts + raw Sent-folder captures, 2026-11-03)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.mail import (
    build_message,
    encode_header_value,
    wire_bytes,
)


def _b(msg):
    return wire_bytes(msg).decode("utf-8")


class TestEncodeHeaderValue:
    # Mail_mimePart::encodeHeader() oracle
    def test_structured_phrase(self):
        assert encode_header_value(
            "From", "Ünicode Name <test@example.org>") == \
            "=?UTF-8?Q?=C3=9Cnicode_Name?= <test@example.org>"

    def test_unstructured_encodes_addr_like(self):
        assert encode_header_value(
            "Subject", "Ünicode Name <test@example.org>") == \
            "=?UTF-8?Q?=C3=9Cnicode_Name_=3Ctest=40example=2Eorg=3E?="

    def test_subject_whole_word(self):
        assert encode_header_value("Subject", "Ünïcode — PAR-B") == \
            "=?UTF-8?Q?=C3=9Cn=C3=AFcode_=E2=80=94_PAR-B?="

    def test_ascii_dots_quoted(self):
        assert encode_header_value("From", "J. Q. Public <j@example.org>") == \
            '"J. Q. Public" <j@example.org>'

    def test_long_subject_fold(self):
        got = encode_header_value("Subject", "wörld " * 20)
        want = ("=?UTF-8?Q?w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld?=\r\n"
                " =?UTF-8?Q?_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6?=\r\n"
                " =?UTF-8?Q?rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w?=\r\n"
                " =?UTF-8?Q?=C3=B6rld_w=C3=B6rld_w=C3=B6rld_w=C3=B6rld_?=")
        assert got == want

    def test_multi_recipients_fold(self):
        got = encode_header_value(
            "To", "Ünicode A <a@x.org>, Ünicode B <b@x.org>, plain@y.org")
        want = ("=?UTF-8?Q?=C3=9Cnicode_A?= <a@x.org>, "
                "=?UTF-8?Q?=C3=9Cnicode_B?=\r\n <b@x.org>, plain@y.org")
        assert got == want

    def test_ascii_passthrough(self):
        assert encode_header_value("To", "a@x.org, B <b@y.org>") == "a@x.org, B <b@y.org>"


class TestBuildMessage:
    def test_plain_ascii_single_part(self):
        raw = _b(build_message("t@e.org", "", ["a@x.org"], [], [], "S", "body"))
        assert "Content-Type: text/plain; charset=US-ASCII;\r\n format=flowed\r\n" in raw
        assert "Content-Transfer-Encoding: 7bit\r\n" in raw
        assert "X-Sender: t@e.org" in raw
        assert raw.endswith("body")

    def test_nonascii_plain_8bit_utf8(self):
        raw = _b(build_message("t@e.org", "", ["a@x.org"], [], [], "S", "Grüße"))
        assert "Content-Type: text/plain; charset=UTF-8;\r\n format=flowed\r\n" in raw
        assert "Content-Transfer-Encoding: 8bit\r\n" in raw

    def test_html_alternative_layout(self):
        raw = _b(build_message("t@e.org", "", ["a@x.org"], [], [], "S",
                               "<p>Hü</p>", html=True))
        assert "Content-Type: multipart/alternative;\r\n boundary=\"=_" in raw
        i_plain = raw.index("Content-Type: text/plain")
        i_html = raw.index("Content-Type: text/html; charset=UTF-8")
        assert i_plain < i_html  # plain alternative first
        assert "body style=3D'font-size: 10pt; font-family: Verdana,Gen=" in raw  # QP-wrapped host
        assert "Content-Transfer-Encoding: quoted-printable\r\nContent-Type: text/html; charset=UTF-8" in raw

    def test_attachment_part_headers(self):
        # Mail_mime real output: CTE first, atom name/filename, size, base64
        data = b"attach parity line1\nline2\n"
        raw = _b(build_message("t@e.org", "", ["t@e.org"], [], [], "S",
                               "see attached", attachments=[("att.txt", "text/plain", data)]))
        import re as _re
        boundary = _re.search(r'boundary="([^"]+)"', raw).group(1)
        idx = raw.index("--" + boundary, raw.index("--" + boundary) + 1)
        part = raw[idx + len(boundary) + 4:]
        assert part.startswith("Content-Transfer-Encoding: base64\r\n"
                               "Content-Type: text/plain;\r\n name=att.txt\r\n"
                               "Content-Disposition: attachment;\r\n filename=att.txt;\r\n"
                               " size=26\r\n\r\nYXR0YWNoIHBhcml0eSBsaW5lMQpsaW5lMgo=\r\n")

    def test_body_append_newline_in_mixed(self):
        raw = _b(build_message("t@e.org", "", [], [], [], "S", "see attached",
                               attachments=[("a.bin", None, b"x")]))
        assert "see attached\r\n\r\n--=_" in raw
