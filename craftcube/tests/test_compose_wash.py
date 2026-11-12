"""Byte-parity tests for app.compose_wash against live captures from the
reference Roundcube 1.7.5 pod on k8s3 (k8s3.lan:30091), plus the
compose_header_value() reply-recipient rules from
program/include/rcmail_sendmail.php:1057-1145."""

import email

from app.compose_wash import compose_wash_html


def _wash(raw, container="replybody1", prefix="v1"):
    return compose_wash_html(raw, container_id=container, css_prefix=prefix)


class TestComposeWash:
    def test_fragment_links_style_cid(self):
        # fixture FIX-1: no <body>, style block, class/id, http + mailto
        # links, unresolved cid: image — reference textarea byte-for-byte
        raw = ('<div style="color:blue">Blue</div><style>h1{color:red} '
               '.mycls{color:blue} #theid{color:green}</style>'
               '<h1 class="mycls" id="theid">Hi</h1><p>'
               '<a href="https://x.org">lnk</a> '
               '<a href="mailto:a@b.org">m</a><br><img src="cid:img1">x</p>\r\n')
        want = ('<div id="replybody1"><div style="color: blue">Blue</div>'
                '<style type="text/css">#replybody1 h1{ color: red; } '
                '#replybody1 .v1mycls{ color: blue; } '
                '#replybody1 #v1theid{ color: green; }</style>'
                '<h1 class="v1mycls" id="v1theid">Hi</h1><p>'
                '<a href="https://x.org" target="_blank" rel="noopener noreferrer">lnk</a> '
                '<a href="mailto:a@b.org" '
                'onclick="return rcmail.command(\'compose\',\'a@b.org\',this)" '
                'rel="noreferrer">m</a><br /><img />x</p></div>')
        assert _wash(raw) == want

    def test_body_attrs_promoted(self):
        # fixture FIX-2: body id wins over container id (prefixed),
        # bgcolor/text fold into style; trailing NL after </html> vanishes
        raw = ('<html><head></head><body bgcolor="#AABBCC" text=white '
               'id="bid"><p>doc body</p></body></html>\r\n')
        want = ('<div id="v1bid" style="background-color: #AABBCC; color: white">'
                '<p>doc body</p></div>')
        assert _wash(raw) == want

    def test_body_style_only(self):
        # fixture PAR-D host wrapper: body style kept on the container,
        # newlines inside body preserved, self-closing <meta/> must not
        # swallow the rest of the document
        raw = ('<html><head><meta http-equiv="Content-Type" '
               'content="text/html; charset=UTF-8" /></head>'
               '<body style="font-size: 10pt; font-family: Verdana,Geneva,sans-serif">\n'
               '<h1>Hü</h1><p>some</p>\n</body></html>')
        want = ('<div id="replybody1" style="font-size: 10pt; '
                'font-family: Verdana,Geneva,sans-serif">\n'
                '<h1>Hü</h1><p>some</p>\n</div>')
        assert _wash(raw) == want

    def test_draft_rewash_double_prefix(self):
        # fixture FIX-6: opening an already-prefixed draft (mode draft:
        # no container id, prefix v1) — reference re-prefixes ids,
        # classes and CSS selectors and wraps in a bare body div
        raw = ('<div id="replybody1"><div style="color: blue">Blue</div>'
               '<style type="text/css">#replybody1 h1{ color: red; } '
               '#replybody1 .v1mycls{ color: blue; }</style>'
               '<h1 class="v1mycls">Hi</h1><p>draft &amp; text</p></div>')
        want = ('<div><div id="v1replybody1"><div style="color: blue">Blue</div>'
                '<style type="text/css">#v1replybody1 h1{ color: red; } '
                '#v1replybody1 .v1v1mycls{ color: blue; }</style>'
                '<h1 class="v1v1mycls">Hi</h1><p>draft &amp; text</p></div></div>')
        assert compose_wash_html(raw, container_id=None, css_prefix="v1") == want

    def test_mailto_with_name_and_query(self):
        out = _wash('<a href="mailto:Ann &lt;ann@example.org&gt;?subject=hi%20there">m</a>')
        assert "href=\"mailto:ann@example.org\"" in out
        assert ("onclick=\"return rcmail.command('compose','Ann &lt;ann@example.org&gt;"
                "?subject=hi there',this)\"") in out

    def test_fragment_href_no_newwindow(self):
        out = _wash('<a href="#sec">x</a>')
        assert 'target' not in out and 'rel' not in out


def _msg(headers):
    lines = [f"{k}: {v}" for k, v in headers.items()]
    return email.message_from_string("\n".join(lines) + "\n\nbody\n")


def _recip(headers, mode, ident="test@example.org"):
    from app.views import _reply_recipients
    return _reply_recipients(_msg(headers), mode, ident)


class TestReplyRecipients:
    def test_plain_reply_prefers_reply_to(self):
        to, cc = _recip({"From": "Bob <bob@example.org>",
                         "Reply-To": "rb@example.org", "To": "test@example.org"}, "reply")
        assert (to, cc) == ("rb@example.org", "")

    def test_self_reply_swaps_to(self):
        to, _ = _recip({"From": "test@example.org", "To": "alice@example.org",
                        "Cc": "carol@example.org"}, "reply")
        assert to == "alice@example.org"

    def test_replyall_to_cc_split(self):
        # reference: To stays the sender (self kept in To), Cc = To+Cc
        # minus the self address already listed in To
        to, cc = _recip({"From": "test@example.org", "To": "test@example.org",
                         "Cc": "bob@example.org"}, "replyall")
        assert (to, cc) == ("test@example.org", "bob@example.org")

    def test_replyall_followup_to(self):
        to, cc = _recip({"From": "bob@example.org", "To": "test@example.org",
                         "Cc": "dave@example.org",
                         "Mail-Followup-To": "list@example.org, bob@example.org"}, "replyall")
        assert to == "list@example.org, bob@example.org"
        # self is dropped from Cc (compose_header_value: cc skips the
        # identity address in MODE_REPLY), verified vs reference uid 43
        assert cc == "dave@example.org"

    def test_replylist_followup_then_list_post(self):
        to, cc = _recip({"From": "a@l.org", "To": "t@x.org",
                         "Mail-Followup-To": "f@l.org",
                         "List-Post": "<mailto:team@l.org>"}, "replylist")
        assert (to, cc) == ("f@l.org", "")
        to, _ = _recip({"From": "a@l.org", "To": "t@x.org",
                        "List-Post": "<mailto:team@l.org>"}, "replylist")
        assert to == "team@l.org"

    def test_mail_reply_to_beats_reply_to(self):
        to, _ = _recip({"From": "bob@example.org", "To": "test@example.org",
                        "Reply-To": "rt@example.org",
                        "Mail-Reply-To": "mrt@example.org"}, "reply")
        assert to == "mrt@example.org"

    def test_cc_dedupe_across_fields(self):
        to, cc = _recip({"From": "bob@example.org", "To": "carol@example.org, bob@example.org",
                         "Cc": "dave@example.org, carol@example.org"}, "replyall")
        assert to == "bob@example.org"
        assert cc == "carol@example.org, dave@example.org"
