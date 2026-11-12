"""Plain-text <-> HTML converters mirroring Roundcube's rcube_text2html /
rcube_html2text so the compose editor's html<->plain toggle converts content
exactly like the reference (?_task=utils&_action=text2html|html2text)."""

import re
from html import escape as _escape
from html import unescape

# rcube_text2html defaults ('wrap' => true, as used by the text2html action)
_NBSP = "\u00a0"
_SPACE = _NBSP  # 'space' default
_BREAK = "<br>\n"


def _convert_line(text, state):
    """rcube_text2html::convert_line() with wrap=true."""
    if text == "":
        return text
    if text == "-- ":
        return "--" + _SPACE

    # unified-diff detection keeps whole lines unwrappable
    if state.get("nowrap"):
        if text[0] not in (" ", "-", "+", "@"):
            state["nowrap"] = False
    else:
        if (text[0] == "-" and re.match(r"^--- \S+", text)) \
           or (text[0] == "+" and re.match(r"^\+\+\+ \S+", text)) \
           or (text[0] == "@" and re.match(r"^@@ [0-9 ,+-]+ @@", text)):
            state["nowrap"] = True

    # HTML_SPECIALCHARS translation table: & < > " ' (quotes ARE escaped;
    # '?' is unset from the table in PHP, so it stays literal)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace('"', "&quot;").replace("'", "&#039;")
    text = text.replace("\r", "").replace("\t", "    ")

    # wrap=true: always wrappable — protect runs of spaces with nbsp
    if not state["nowrap"]:
        out, pos, last = text, 0, -2
        while True:
            pos = text.find(" ", pos)
            if pos == -1:
                break
            if (pos == 0 or text[pos - 1] == " ") and pos - 1 != last:
                last = pos
                out = out[:pos] + _NBSP + out[pos + 1:]
            pos += 1
        return out

    if text != "" and re.search(r"[^a-zA-Z0-9_]", text):
        text = text.replace(" ", _SPACE)
        return '<span style="white-space:nowrap">' + text + "</span>"
    return text


class _LinkReplacer:
    """rcube_string_replacer + rcube_string_replacer_url/mail: tokenise URLs
    and e-mails, resolve them back as links at the end."""

    URL_RE = re.compile(
        r"(?:https?|ftps?|telnet|ssh|news?|sftp|irc):\/\/[^\s<>\"]+"
        r"[^\s<>\",.;:!?'`()]", re.I)
    MAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

    def __init__(self):
        self.tokens = []

    def _store(self, html):
        self.tokens.append(html)
        return f"\x00{len(self.tokens) - 1}\x01"

    def replace(self, text):
        # the reference protects URLs/addresses BEFORE html-escaping the lines
        # (replacer runs on raw text, resolve() re-inserts built <a> tags)
        pieces = []
        pos = 0
        while pos < len(text):
            m_url = self.URL_RE.search(text, pos)
            m_mail = self.MAIL_RE.search(text, pos)
            if not m_url and not m_mail:
                pieces.append(text[pos:])
                break
            if m_url and (not m_mail or m_url.start() <= m_mail.start()):
                url = m_url.group(0)
                html = (f'<a rel="noreferrer" target="_blank" href="{_escape(url, quote=True)}">'
                        f"{_escape(url, quote=False)}</a>")
                pieces.append(text[pos:m_url.start()])
                pieces.append(self._store(html))
                pos = m_url.end()
            else:
                addr = m_mail.group(0)
                html = f'<a href="mailto:{addr}">{addr}</a>'
                pieces.append(text[pos:m_mail.start()])
                pieces.append(self._store(html))
                pos = m_mail.end()
        return "".join(pieces)

    def resolve(self, text):
        def sub(m):
            return self.tokens[int(m.group(1))]
        # tokens survive line escaping (\x00, digits, \x01 are untouched)
        return re.sub("\x00(\\d+)\x01", sub, text)


def text2html(text):
    """rcube_text2html(text, False, {'wrap': True}).get_html()"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # (a) link/e-mail protection happens on the RAW text, before escaping:
    #     the reference resolves the <a> tokens after str_replace("\n", "<br>")
    replacer = _LinkReplacer()
    text = replacer.replace(text)

    # (b) split into lines and build the pre/sig/span wrapper — a faithful
    # port of rcube_text2html::converter()'s quote tracking, including its
    # quirk that merged lines leave the row as None (dropped on implode)
    lines = text.split("\n")
    state = {"nowrap": False}
    quote_level = 0
    last = None
    length = 0
    for n in range(len(lines)):
        line = lines[n]
        first = line[0] if line else ""
        m = re.match(r"^(>+ {0,1})+", line) if first == ">" else None
        if m:
            q = m.group(0).count(">")
            line = _convert_line(line[len(m.group(0)):], state)
            # PHP: $text[$n] = convert_line(...) happens BEFORE the q branches
            lines[n] = line
            _length = len(line.replace(" ", ""))
            if q > quote_level:
                if last is not None:
                    lines[last] += ("\n" if not length else "") + \
                        ("<blockquote>" * (q - quote_level)) + line
                    lines[n] = None
                else:
                    lines[n] = ("<blockquote>" * (q - quote_level)) + line
                    last = n
            elif q < quote_level:
                if last is not None:
                    lines[last] += ("\n" if not length else "") + \
                        ("</blockquote>" * (quote_level - q)) + line
                    lines[n] = None
                else:
                    last = n
            else:
                last = n
        else:
            line = _convert_line(line, state)
            lines[n] = line
            q = 0
            _length = len(line.replace(" ", ""))
            if quote_level > 0:
                if last is not None:
                    lines[last] += ("\n" if not length else "") + \
                        ("</blockquote>" * quote_level) + line
                    lines[n] = None
            else:
                last = n
        quote_level = q
        length = _length
    if quote_level > 0 and last is not None:
        lines[last] += "</blockquote>" * quote_level

    # PHP unset() removes the row so implode skips it entirely
    text = "\n".join(line for line in lines if line is not None)

    # (c) signature colorization: last standalone '--\u00a0\n' within
    # sig_max_lines(15) of the end wraps the tail in <span class="sig">
    sig_sep = "--" + _SPACE + "\n"
    sig_max_lines = 15
    sp = text.rfind(sig_sep)
    while sp != -1:
        if sp == 0 or text[sp - 1] == "\n":
            if text.count("\n", sp) < sig_max_lines:
                text = (text[:max(0, sp)] + '<span class="sig">' + text[sp:] + "</span>")
            break
        sp = text.rfind(sig_sep, 0, sp - 1)

    text = text.replace("\n", _BREAK)
    text = replacer.resolve(text)
    return '<div class="pre">' + text + "</div>"


# ---------------------------------------------------------------- html2text
# Faithful port of the container's rcube_html2text::_converter() pipeline
# (search/replace tables, callbacks, entity handling, blank-line collapse).

_H2T_SEARCH = [
    ("\r", ""),                                              # non-legal CR
    (r"\n*<?/?html>\n*", ""),                               # <html>
    (r"\n*<head[^>]*>.*?</head>\n*", ""),                   # <head>
    (r"\n*<script[^>]*>.*?</script>\n*", ""),               # <script>
    (r"\n*<style[^>]*>.*?</style>\n*", ""),                 # <style>
    (r"[\n\t]+", " "),                                      # newlines/tabs -> space
    (r"<p[^>]*>", "\n\n"),                                  # <p>
    (r"</p>[\s\n\t]*<div[^>]*>", "\n<div>"),              # </p> before <div>
    (r"<br[^>]*>[\s\n\t]*<div[^>]*>", "<div>"),            # <br> before <div>
    (r"<br[^>]*>\s*", "\n"),                                # <br>
    (r"<i[^>]*>(.*?)</i>", r"_\1_"),                         # <i>
    (r"<em[^>]*>(.*?)</em>", r"_\1_"),                       # <em>
    (r"(<ul[^>]*>|</ul>)", "\n\n"),                         # <ul>/</ul>
    (r"(<ol[^>]*>|</ol>)", "\n\n"),                         # <ol>/</ol>
    (r"<li[^>]*>(.*?)</li>", "\t* \\1\n"),                # <li>..</li>
    (r"<li[^>]*>", "\n\t* "),                               # <li>
    (r"<hr[^>]*>", "\n-------------------------\n"),        # <hr>
    (r"<div[^>]*>", "<div>\n"),                              # <div>
    (r"(<table[^>]*>|</table>)", "\n\n"),                   # <table>
    (r"(<tr[^>]*>|</tr>)", "\n"),                            # <tr>
    (r"<td[^>]*>(.*?)</td>", "\t\t\\1\n"),               # <td>..</td>
]

_H2T_ENT_SEARCH = [
    (r"&(nbsp|#160);", "\u00a0"),
    (r"&(quot|rdquo|ldquo|#8220|#8221|#147|#148);", '"'),
    (r"&(apos|rsquo|lsquo|#8216|#8217);", "'"),
    (r"&gt;", ">"),
    (r"&lt;", "<"),
    (r"&(copy|#169);", "(c)"),
    (r"&(trade|#8482|#153);", "(tm)"),
    (r"&(reg|#174);", "(R)"),
    (r"&(mdash|#151|#8212);", "--"),
    (r"&(ndash|minus|#8211|#8722);", "-"),
    (r"&(bull|#149|#8226);", "*"),
    (r"&(pound|#163);", "\u00a3"),
    (r"&(euro|#8364);", "EUR"),
    (r"&(amp|#38);", "|+|amp|+|"),
    (r"[ ]{2,}", " "),
]

_PRE_SEARCH = [(r"\n", "<br>"), (r"\t", "&nbsp;&nbsp;&nbsp;&nbsp;"),
               (r" ", "&nbsp;")]

LINKS_NONE, LINKS_END, LINKS_INLINE = 0, 1, 2


def _toupper(s):
    # strtoupper on text chunks, keeping HTML tags/entities untouched
    parts = re.split(r"(<[^>]*>)", s)
    return "".join(p if p.startswith("<") else p.upper() for p in parts)


def _handle_link(url, display, links_mode, width):
    if not url:
        return display
    if re.match(r"^(javascript:|mailto:|#)", url, re.I):
        return display
    if url == display:
        return display
    if links_mode == LINKS_NONE:
        # inner conversion of the (still-HTML) label, width 1024
        text = html2text(display, links=LINKS_NONE, width=1024, _inner=True)
        if not text and re.match(r"^[a-z][a-z0-9.+-]+://", url, re.I):
            return url
        return text
    if links_mode == LINKS_INLINE:
        return display + " &lt;" + url + "&gt;"
    return None  # LINKS_END handled by caller (needs list state)


def _blockquote_citation(m):
    line = m.group(2).lstrip()
    space = "" if line and line[0] == ">" else " "
    return m.group(1) + ">" + space + line


def _convert_blockquotes(text, links_mode, width, inner):
    level = 0
    offset = 0
    while True:
        start = text.lower().find("<blockquote", offset)
        if start == -1:
            break
        offset = start + 12
        while True:
            end = text.lower().find("</blockquote>", offset)
            nxt = text.lower().find("<blockquote", offset)
            if nxt != -1 and (end == -1 or nxt < end):
                offset = nxt + 12
                level += 1
            if end != -1 and level > 0:
                offset = end + 12
                level -= 1
            elif end != -1 and level == 0:
                taglen = text.find(">", start) - start
                body = text[start + taglen + 1:end].strip()
                # recursive _converter at width-2 (only when width > 0)
                body = _converter(body, links_mode,
                                  (width - 2) if width > 0 else width, inner)
                body = re.sub(r"((?:^|\n)>*)([^\n]*)",
                              _blockquote_citation, body.strip())
                body = "<pre>" + _escape_html(body) + "</pre>"
                text = text[:start] + body + "\n" + text[end + 13:]
                offset = 0
                break
            else:
                break
        # PHP resets offset to 0 after a match; scan again from scratch
        if offset == 0 and "<blockquote" not in text[offset:].lower():
            break
    return text


def _escape_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _replace_links(text, links_mode, width, link_list):
    def cb(m):
        url = m.group(3).replace(" ", "")
        url = unescape(url)
        display = m.group(5)
        if links_mode == LINKS_END:
            if url in link_list:
                index = link_list.index(url)
            else:
                index = len(link_list)
                link_list.append(url)
            return f"{display} [{index + 1}]"
        return _handle_link(url, display, links_mode, width)
    return re.sub(r"<a [^>]*href=([\"'])(.*?)\1[^>]*>(.*?)</a>",
                  lambda m: cb_type(m, links_mode, width, link_list),
                  text, flags=re.I | re.S)


def cb_type(m, links_mode, width, link_list):
    url = m.group(2).replace(" ", "")
    url = unescape(url)
    display = m.group(3)
    if links_mode == LINKS_END:
        if url in link_list:
            index = link_list.index(url)
        else:
            index = len(link_list)
            link_list.append(url)
        return f"{display} [{index + 1}]"
    return _handle_link(url, display, links_mode, width)


def _callback_passes(text, links_mode, width, link_list):
    # callback_search order: <a href>, <h1-6>, <th>
    text = _replace_links(text, links_mode, width, link_list)
    text = re.sub(r"<(h)[123456]( [^>]*)?>(.*?)</h[123456]>",
                  lambda m: _toupper("\n\n" + m.group(3) + "\n\n"),
                  text, flags=re.I | re.S)
    return re.sub(r"<(th)( [^>]*)?>(.*?)</th>",
                  lambda m: _toupper("\t\t" + m.group(3) + "\n"),
                  text, flags=re.I | re.S)


def _convert_pre(text, links_mode, width, link_list):
    while True:
        m = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.I | re.S)
        if not m:
            break
        content = m.group(1)
        content = _callback_passes(content, links_mode, width, link_list)
        content = content.replace("\n", "<br>")
        content = content.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
        content = content.replace(" ", "&nbsp;")
        repl = "<div><br>" + content + "<br></div>"
        text = text[:m.start()] + repl + text[m.end():]
    return text


def _converter(text, links_mode, width, inner):
    text = _convert_blockquotes(text, links_mode, width, inner)
    text = _convert_pre(text, links_mode, width, [])
    pos = text.lower().find("<body")
    if pos != -1:
        gt = text.find(">", pos)
        text = text[gt + 1:].lstrip()
    for pat, rep in _H2T_SEARCH:
        text = re.sub(pat, rep, text, flags=re.I)
    text = _callback_passes(text, links_mode, width, _converter.link_list)
    text = re.sub(r"<[^>]*>", "", text)          # strip_tags
    for pat, rep in _H2T_ENT_SEARCH:
        text = re.sub(pat, rep, text, flags=re.I)
    text = unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"&([a-zA-Z0-9]{2,6}|#[0-9]{2,4});", "", text)
    text = text.replace("|+|amp|+|", "&")
    text = re.sub(r"\n\s+\n", "\n\n", text)
    text = re.sub(r"[\n]{3,}", "\n\n", text)
    text = text.lstrip("\n")
    if width > 0:
        import textwrap
        # PHP wordwrap(break='"'\n"', cut=false): wrap words at `width`
        wrapped = []
        for para in text.split("\n"):
            wrapped.append("\n".join(textwrap.wrap(para, width)) if para else "")
        text = "\n".join(wrapped)
    return text


def html2text(html, links=False, width=75, _inner=False):
    """rcmail::html2text($html, ['links'=>..., 'width'=>...]) — the wrapper
    passes links as bool: false => LINKS_NONE, true => LINKS_DEFAULT(END);
    the editor's toggle calls it without params (links=false, width=0)."""
    links_mode = links if isinstance(links, int) else (LINKS_END if links else LINKS_NONE)
    _converter.link_list = []
    text = _converter(html, links_mode, width, _inner)
    if _converter.link_list:
        text += "\n\nLinks:\n------\n"
        for i, url in enumerate(_converter.link_list):
            text += f"[{i + 1}] {url}\n"
    return text.rstrip()
