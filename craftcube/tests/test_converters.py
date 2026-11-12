"""Converter parity tests.

converters.py is a port of Roundcube's rcube_text2html / rcube_html2text
and was validated byte-exact against the running reference instance;
these cases lock in that behavior (including the quirky details that
were discovered while reaching parity)."""

from app.converters import html2text, text2html


class TestText2Html:
    def test_plain_paragraphs(self):
        assert text2html("Hello world") == '<div class="pre">Hello world</div>'

    def test_newlines_to_br(self):
        assert text2html("a\nb") == '<div class="pre">a<br>\nb</div>'

    def test_url_becomes_link_with_reference_rel(self):
        # the reference emits rel="noreferrer" only (NOT 'noreferrer noopener')
        out = text2html("Visit http://example.com now")
        assert ('<a rel="noreferrer" target="_blank" href="http://example.com">'
                'http://example.com</a>') in out

    def test_email_becomes_mailto(self):
        out = text2html("Mail me at a@b.com please")
        assert '<a href="mailto:a@b.com">a@b.com</a>' in out

    def test_quotes_become_blockquote(self):
        assert text2html("> quoted\n> more\nplain") == \
            '<div class="pre"><blockquote>quoted<br>\nmore</blockquote>plain</div>'

    def test_html_specialchars_escaped(self):
        # PHP HTML_SPECIALCHARS escapes quotes too: " -> &quot;  ' -> &#039;
        out = text2html('a & b < c > "d" \'e\'')
        assert "a &amp; b &lt; c &gt; &quot;d&quot; &#039;e&#039;" in out

    def test_signature_span(self):
        # a standalone '-- ' within 15 lines of the end wraps the tail
        out = text2html("-- \nsig here")
        assert '<span class="sig">' in out and "--\xa0" in out

    def test_empty_input(self):
        assert text2html("") == '<div class="pre"></div>'


class TestHtml2Text:
    def test_inline_markup_dropped(self):
        assert html2text("<p>Hi <b>there</b></p>", links=False, width=0) == "Hi there"

    def test_link_text_only_by_default(self):
        # reference action defaults: links disabled (LINKS_NONE)
        assert html2text('<p><a href="http://x.org">link</a></p>',
                         links=False, width=0) == "link"

    def test_links_end_numbered_list(self):
        html = ('<p><a href="http://a.org">A</a> and '
                '<a href="http://b.org">B</a> and '
                '<a href="http://a.org">A2</a></p>')
        out = html2text(html, links=True, width=0)
        assert "A [1]" in out and "B [2]" in out and "A2 [1]" in out
        assert "Links:\n------\n[1] http://a.org\n[2] http://b.org" in out

    def test_headings_uppercase_block(self):
        assert html2text("<h1>T</h1><p>body</p>", links=False, width=0) == "T\n\nbody"

    def test_list_items(self):
        assert html2text("<ul><li>a</li><li>b</li></ul>", links=False, width=0) == \
            "\t* a\n\t* b"

    def test_blockquote_prefix(self):
        assert html2text("<blockquote>quoted</blockquote>", links=False, width=0) == \
            "> quoted"

    def test_entities(self):
        assert html2text("&amp;&nbsp;&copy;", links=False, width=0) == "& (c)"

    def test_hr_line(self):
        assert html2text("<hr>", links=False, width=0).startswith("-----")
