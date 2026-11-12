"""Shared helpers: dates, sizes, HTML sanitizing, header parsing."""
import email
import email.utils
import html as _html
import math
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

from . import i18n

# ---------------------------------------------------------------- dates/sizes

def to_local(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone()

def fmt_date(dt):
    """Roundcube-ish list date: time today, 'd MMM' this year, 'd.M.yy' older."""
    if dt is None:
        return ""
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.year == now.year:
        return dt.strftime("%d %b")
    return dt.strftime("%d.%m.%y")

def fmt_list_date(dt, lang="en_US"):
    """Roundcube rcmail::format_date() default semantics: today shows
    '<localized today> <time>' (date_today=time_format), the last 7 days use
    date_short ('D H:i'), everything older date_long ('Y-m-d H:i')."""
    if dt is None:
        return ""
    dt = to_local(dt)
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return i18n.gettext("today", lang) + " " + dt.strftime("%H:%M")
    week_limit = (now - timedelta(days=6)).replace(hour=0, minute=0,
                                                   second=0, microsecond=0)
    if dt > week_limit:
        return i18n.gettext(dt.strftime("%a").lower(), lang) + " " + dt.strftime("%H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")

def fmt_summary_date(dt):
    if dt is None:
        return ""
    return to_local(dt).strftime("%Y-%m-%d %H:%M")


# HTML -> plain text: faithful port of rcube_html2text (Roundcube's HTML2Text
# fork) with LINKS_END and width 75 -- the defaults used by rcmail::html2text()
# on the print_body plain path (program/actions/mail/index.php). The replace
# arrays mirror rcube_html2text::$search/$replace 1:1.
_H2T_SEARCH = [
    (re.compile(r"\r"), ""),
    (re.compile(r"\n*</?html>\n*", re.I), ""),
    (re.compile(r"\n*<head[^>]*>.*?</head>\n*", re.I | re.S), ""),
    (re.compile(r"\n*<script[^>]*>.*?</script>\n*", re.I | re.S), ""),
    (re.compile(r"\n*<style[^>]*>.*?</style>\n*", re.I | re.S), ""),
    (re.compile(r"[\n\t]+"), " "),
    (re.compile(r"<p[^>]*>", re.I), "\n\n"),
    (re.compile(r"</p>[\s\n\t]*<div[^>]*>", re.I), "\n<div>"),
    (re.compile(r"<br[^>]*>[\s\n\t]*<div[^>]*>", re.I), "<div>"),
    (re.compile(r"<br[^>]*>\s*", re.I), "\n"),
    (re.compile(r"<i[^>]*>(.*?)</i>", re.I | re.S), r"_\1_"),
    (re.compile(r"<em[^>]*>(.*?)</em>", re.I | re.S), r"_\1_"),
    (re.compile(r"(<ul[^>]*>|</ul>)", re.I), "\n\n"),
    (re.compile(r"(<ol[^>]*>|</ol>)", re.I), "\n\n"),
    (re.compile(r"<li[^>]*>(.*?)</li>", re.I | re.S), "\\1", ),
    (re.compile(r"<li[^>]*>", re.I), "\n\t* "),
    (re.compile(r"<hr[^>]*>", re.I), "\n-------------------------\n"),
    (re.compile(r"<div[^>]*>", re.I), "<div>\n"),
    (re.compile(r"(<table[^>]*>|</table>)", re.I), "\n\n"),
    (re.compile(r"(<tr[^>]*>|</tr>)", re.I), "\n"),
    (re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S), "\\1"),
]
# the \t*\1 and \t\t\1 replacements need callables (backrefs with literal \t)
_H2T_SEARCH[14] = (_H2T_SEARCH[14][0], lambda m: "\t* " + m.group(1) + "\n")
_H2T_SEARCH[20] = (_H2T_SEARCH[20][0], lambda m: "\t\t" + m.group(1) + "\n")

_H2T_LINK_RX = re.compile(
    r'<(a) [^>]*href=("|\')(.*?)\2[^>]*>(.*?)</a>', re.I | re.S)
_H2T_H_RX = re.compile(r"<(h)[123456]( [^>]*)?>(.*?)</h[123456]>", re.I | re.S)
_H2T_TH_RX = re.compile(r"<(th)( [^>]*)?>(.*?)</th>", re.I | re.S)

# rcube_html2text::$ent_search / $ent_replace — applied to the tag-stripped
# text BEFORE generic entity decoding (so &mdash; becomes '--', not an
# em-dash, and &amp; is parked behind a marker until the very end).
_H2T_ENT = [
    (re.compile(r"&(nbsp|#160);", re.I), "\u00a0"),
    (re.compile(r"&(quot|rdquo|ldquo|#8220|#8221|#147|#148);", re.I), '"'),
    (re.compile(r"&(apos|rsquo|lsquo|#8216|#8217);", re.I), "'"),
    (re.compile(r"&gt;", re.I), ">"),
    (re.compile(r"&lt;", re.I), "<"),
    (re.compile(r"&(copy|#169);", re.I), "(c)"),
    (re.compile(r"&(trade|#8482|#153);", re.I), "(tm)"),
    (re.compile(r"&(reg|#174);", re.I), "(R)"),
    (re.compile(r"&(mdash|#151|#8212);", re.I), "--"),
    (re.compile(r"&(ndash|minus|#8211|#8722);", re.I), "-"),
    (re.compile(r"&(bull|#149|#8226);", re.I), "*"),
    (re.compile(r"&(pound|#163);", re.I), "\u00a3"),
    (re.compile(r"&(euro|#8364);", re.I), "EUR"),
    (re.compile(r"&(amp|#38);", re.I), "|+|amp|+|"),
    (re.compile(r"[ ]{2,}"), " "),
]


def _h2t_wordwrap(text, width):
    """PHP wordwrap() with break="\\n", cut_long_words=false."""
    if width <= 0:
        return text
    out = []
    for line in text.split("\n"):
        cur = ""
        for word in line.split(" "):
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= width:
                cur += " " + word
            else:
                out.append(cur)
                cur = word
        out.append(cur)
    return "\n".join(out)


def html_to_text(html, width=75):
    """Convert an HTML mail body to plain text exactly like rcube_html2text:
    h1-h6/<th> uppercased, <em>/<i> _underscored_, <li> bullets, 25-dash <hr>,
    URLs as inline ' [n]' markers plus a trailing 'Links:' list (LINKS_END),
    <blockquote> citation '> ' lines, PHP wordwrap at `width`."""
    links = []

    def _handle_link(url, display):
        url = _html.unescape(url.replace(" ", ""))
        if (not url or re.match(r"^(javascript:|mailto:|#)", url, re.I)
                or url == display):
            return display
        if url not in links:
            links.append(url)
        return f"{display} [{links.index(url) + 1}]"

    def _toupper(s):
        # uppercase the text between tags only (_toupper)
        return "".join(p.upper() if not p.startswith("<") else p
                       for p in re.split(r"(<[^>]*>)", s))

    def _callbacks(text):
        text = _H2T_LINK_RX.sub(
            lambda m: _handle_link(m.group(3), m.group(4)), text)
        text = _H2T_H_RX.sub(
            lambda m: _toupper("\n\n" + m.group(3) + "\n\n"), text)
        return _H2T_TH_RX.sub(
            lambda m: _toupper("\t\t" + m.group(3) + "\n"), text)

    def _cite_line(ln):
        # blockquote_citation_callback: run of '>' then ltrim, space unless
        # the remainder itself starts with '>'
        marks = re.match(r">*", ln).group(0)
        rest = ln[len(marks):].lstrip()
        space = "" if rest.startswith(">") else " "
        return marks + ">" + space + rest

    def _convert(text, w):
        # blockquotes: convert inner, quote it, insert as escaped <pre>
        # (RC decodes the inner once here; the outer pass decodes again)
        def _bq(bm):
            inner = _convert(bm.group(1).strip("\n"), max(w - 2, 0))
            inner = _html.unescape(inner)
            lines = inner.strip("\n").split("\n")
            quoted = "\n".join(_cite_line(ln) for ln in lines)
            return ("<pre>"
                    + _html.escape(quoted, quote=False).replace("\n", "<br>")
                    + "</pre>\n")
        text = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>", _bq, text,
                      flags=re.I | re.S)

        # _convert_pre: every <pre> (including the blockquote ones just
        # inserted) becomes <div><br>..<br></div> with whitespace protected
        def _protect_pre(pm):
            inner = _callbacks(pm.group(1))
            inner = inner.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
            inner = inner.replace(" ", "&nbsp;")
            inner = re.sub(r"\r?\n", "<br>", inner)
            return "<div><br>" + inner + "<br></div>"
        text = re.sub(r"<pre[^>]*>(.*?)</pre>", _protect_pre, text,
                      flags=re.I | re.S)

        # drop everything up to and including the <body...> tag
        i = text.lower().find("<body")
        if i >= 0:
            j = text.find(">", i)
            if j >= 0:
                text = text[j + 1:].lstrip()

        for rx, rep in _H2T_SEARCH:
            text = rx.sub(rep, text)
        text = _callbacks(text)
        text = re.sub(r"<[^>]+>", "", text)
        for rx, rep in _H2T_ENT:
            text = rx.sub(rep, text)
        text = _html.unescape(text)
        text = text.replace("\u00a0", " ")
        text = re.sub(r"&([a-zA-Z0-9]{2,6}|#[0-9]{2,4});", "", text)
        text = text.replace("|+|amp|+|", "&")
        text = re.sub(r"\n\s+\n", "\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.lstrip("\n")
        return _h2t_wordwrap(text, w)

    return _convert(html or "", width) + (
        "\n\nLinks:\n------\n"
        + "".join(f"[{i + 1}] {u}\n" for i, u in enumerate(links))
        if links else "")




# Preferred date/time formatting (settings > preferences) ---------------------

DATE_FORMATS = {
    "long": "%e %B %Y %H:%M",       # 9 January 2026 14:05
    "short": "%d.%m.%y %H:%M",      # 09.01.26 14:05
    "yyyy-mm-dd": "%Y-%m-%d %H:%M",
    "mm/dd/yyyy": "%m/%d/%Y %H:%M",
}

# PHP date() -> strftime() conversion for preference format strings
# (e.g. 'Y-m-d', 'd.m.Y', 'G:i', 'h:i A') as offered by the reference UI.
_PHP_TO_STRFTIME = {
    "Y": "%Y", "y": "%y", "m": "%m", "d": "%d", "j": "%-d", "n": "%-m",
    "H": "%H", "G": "%-H", "i": "%M", "s": "%S",
    "g": "%-I", "h": "%I", "a": "%p", "A": "%p",
    "D": "%a", "l": "%A", "M": "%b", "F": "%B",
}


def php_strftime(fmt, dt):
    """Render dt with a PHP-style format string (unknown chars kept literal)."""
    out = []
    i = 0
    while i < len(fmt):
        c = fmt[i]
        if c == "\\" and i + 1 < len(fmt):
            out.append(fmt[i + 1])
            i += 2
            continue
        out.append(_PHP_TO_STRFTIME.get(c, c))
        i += 1
    try:
        return dt.strftime("".join(out))
    except ValueError:
        return dt.strftime("%Y-%m-%d %H:%M")

def to_local_tz(dt, tzname=None):
    """Convert to local zone, or to the IANA zone named in prefs."""
    if dt is None:
        return None
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(ZoneInfo(tzname))
        except Exception:
            # unknown/invalid timezone pref -> local fallback
            return to_local(dt)
    return to_local(dt)

def fmt_pref_time(dt, prefs):
    if dt is None:
        return ""
    prefs = prefs or {}
    tf = prefs.get("time_format", "H:i")
    # reference stores PHP formats ('H:i'); legacy CraftCube used 'H'/'h'
    if ":" in tf:
        return php_strftime(tf, to_local_tz(dt, prefs.get("timezone")))
    return to_local_tz(dt, prefs.get("timezone")).strftime(
        "%H:%M" if tf == "H" else "%I:%M %p")

def fmt_pref_date(dt, prefs):
    """Message view date honouring date_format/time_format prefs.
    The reference renders the header date with an explicit date_long format
    (show.php: format_date($date, config['date_long'])), so pretty-date has
    no effect here — it only affects listing dates (format_date(null))."""
    if dt is None:
        return ""
    prefs = prefs or {}
    dt = to_local_tz(dt, prefs.get("timezone"))
    df = prefs.get("date_format", "Y-m-d")  # rc default (1.7: date_long='Y-m-d H:i')
    base = php_strftime(df, dt) if any(c in df for c in "Yydj") \
        else dt.strftime(DATE_FORMATS.get(df, "%Y-%m-%d"))
    return base + " " + fmt_pref_time(dt, prefs) \
        if any(c in df for c in "Yydj") and prefs.get("show_pref_time", 1) \
        else base

def list_pref_date(dt, prefs, lang="en_US"):
    """Message-list date honouring timezone + time/date format prefs,
    following rcmail::format_date(): localized Today / D H:i / date_long.
    With prettydate off the default format is plain date_long."""
    if dt is None:
        return ""
    prefs = prefs or {}
    dt = to_local_tz(dt, prefs.get("timezone"))
    now = to_local_tz(datetime.now(UTC), prefs.get("timezone"))
    tf = prefs.get("time_format", "H:i")
    tfmt = php_strftime(tf, dt) if ":" in tf else ("%H:%M" if tf == "H" else "%I:%M %p")
    df = prefs.get("date_format", "Y-m-d")
    if prefs.get("pretty_date", 1):
        if dt.date() == now.date():
            return i18n.gettext("today", lang) + " " + dt.strftime(tfmt)
        week_limit = (now - timedelta(days=6)).replace(hour=0, minute=0,
                                                       second=0, microsecond=0)
        if dt > week_limit:
            return i18n.gettext(dt.strftime("%a").lower(), lang) + " " + dt.strftime(tfmt)
    return php_strftime(df, dt) + " " + dt.strftime(tfmt)

def fmt_datetime(dt):
    if dt is None:
        return ""
    return dt.strftime("%a, %d %b %Y %H:%M %z")

def human_size(n):
    # mirrors rcube_html::show_message_size(): whole KB, one-decimal MB+,
    # half-way values away from zero like PHP round()
    if n is None:
        return ""
    n = float(n)
    if n > 1023:
        from decimal import ROUND_HALF_UP, Decimal
        power = int(math.log(n, 1024))
        if power > 1:
            value = str((Decimal(n) / Decimal(1024) ** power).quantize(Decimal("0.1"), ROUND_HALF_UP))
            if value.endswith(".0"):
                value = value[:-2]
        else:
            value = str((Decimal(n) / Decimal(1024)).quantize(Decimal(1), ROUND_HALF_UP))
        unit = ("KB", "MB", "GB", "TB", "PB")[min(power - 1, 4)]
        return f"{value} {unit}"
    return f"{int(n)} B"

# ---------------------------------------------------------------- mime text
# Ports of rcube_mime::wordwrap() and rcube_mime::format_flowed() (Roundcube
# 1.7.5) used when building sent messages (rcmail_sendmail::format_plain_body).

def wordwrap_rc(text, width=75, break_="\n", cut=False, wrap_quoted=True):
    """rcube_mime::wordwrap() — mb-aware wordwrap; PHP semantics kept
    deliberately: short lines pass through with their own separator, quoted
    ('>') lines are never wrapped unless wrap_quoted is False, long words
    overflow when cut=False."""
    text = text.replace("\r\n", "\n")
    result = []
    s = text
    while s:
        n = len(s)
        break_pos = s.find("\n")
        if wrap_quoted and s[0] == ">":
            if break_pos == n - 1 or break_pos == -1:
                sub, cut_len = s, None
            else:
                sub, cut_len = s[:break_pos], break_pos + 1
        elif break_pos != -1 and break_pos < width:
            if break_pos == n - 1:
                sub, cut_len = s, None
            else:
                sub, cut_len = s[:break_pos], break_pos + 1
        else:
            sub = s[:width] if width > 0 else s[:1]
            if break_pos == -1 and sub == s:
                cut_len = None
            else:
                next_char = s[width] if width < n else ""
                if next_char in (" ", "\n"):
                    after = s[width + 1] if width + 1 < n else ""
                    if after == "":
                        sub += next_char
                    cut_len = len(sub) + 1
                else:
                    space_pos = sub.rfind(" ")
                    if space_pos != -1:
                        sub = sub[:space_pos]
                        cut_len = space_pos + 1
                    elif cut is False:
                        space_pos = s.find(" ")
                        if space_pos != -1 and (break_pos == -1 or space_pos < break_pos):
                            sub = s[:space_pos]
                            cut_len = space_pos + 1
                        elif break_pos == -1:
                            sub, cut_len = s, None
                        else:
                            sub, cut_len = s[:break_pos], break_pos + 1
                    else:
                        cut_len = width
        result.append(sub)
        if cut_len is None:
            break
        s = s[cut_len:]
    return break_.join(result)


def format_flowed(text, length=72):
    """rcube_mime::format_flowed(): re-wrap to RFC 3676 flowed lines (soft
    break = trailing space before CRLF), space-stuff lines starting with
    'From', ' ' or '>'; the bare '-- ' signature delimiter passes through."""
    out = []
    for line in re.split(r"\r?\n", text):
        if line == "-- ":
            out.append(line)
            continue
        level = len(line) - len(line.lstrip(">"))
        if level:
            line = line[level:].rstrip(" ")
            if line[:1] == " ":
                line = line[1:]
            prefix = ">" * level + " "
            out.append(prefix + wordwrap_rc(line, length - level - 2, " \r\n" + prefix, False))
        elif line:
            wrapped = wordwrap_rc(line.rstrip(" "), length - 2, " \r\n", False)
            out.append(re.sub(r"(^|\r\n)(From| |>)", r"\1 \2", wrapped))
        else:
            out.append(line)
    return "\r\n".join(out)


def unfold_flowed(text, delsp=False):
    """rcube_mime::unfold_flowed($text, null, $delsp): join RFC 3676 flowed
    soft lines (previous line ending in a space, same quote level), undo
    space-stuffing; '-- ' signature lines never join. Faithful port incl.
    the raw-$text[$last] checks and unset() rows."""
    rows = re.split(r"\r?\n", text)
    last = -1
    q_level = 0
    for idx in range(len(rows)):
        line = rows[idx]
        q = len(line) - len(line.lstrip(">"))
        if q:
            line = line[q:]
            if line[:1] == " ":
                line = line[1:]
            prev = rows[last] if 0 <= last < len(rows) else None
            if (q == q_level and prev is not None and prev[-1:] == " "
                    and not re.match(r"^>+ {0,1}$", prev)):
                if delsp:
                    rows[last] = rows[last][:-1]
                rows[last] += line
                rows[idx] = None
            else:
                last = idx
        else:
            if line == "-- ":
                last = idx
            else:
                if line[:1] == " ":
                    line = line[1:]
                prev = rows[last] if 0 <= last < len(rows) else None
                last_len = len(prev) if prev is not None else 0
                if (last_len and line and not q_level
                        and prev is not None and prev != "-- "
                        and prev[-1] == " "):
                    if delsp:
                        rows[last] = rows[last][:-1]
                    rows[last] += line
                    rows[idx] = None
                else:
                    rows[idx] = line
                    last = idx
        q_level = q
    return "\r\n".join(r for r in rows if r is not None)


# ---------------------------------------------------------------- headers

def parse_header_date(msg, name="Date"):
    raw = msg.get(name)
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return to_local(dt) if dt else None
    except (ValueError, TypeError):
        return None

def header_addresses(msg, name):
    """[(name, email), ...] for a header line."""
    raw = msg.get(name)
    if not raw:
        return []
    out = []
    for disp, addr in email.utils.getaddresses([raw]):
        if addr:
            out.append((disp or addr, addr))
    return out

def format_address(name, addr):
    if name and name != addr:
        return f"{name} <{addr}>"
    return addr or ""

# ---------------------------------------------------------------- sanitize

_ALLOWED_TAGS = {
    "a", "abbr", "b", "big", "blockquote", "br", "caption", "center", "cite",
    "code", "col", "colgroup", "dd", "del", "dfn", "div", "dl", "dt", "em",
    "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins",
    "kbd", "li", "mark", "ol", "p", "pre", "q", "s", "samp", "small", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "tt", "u", "ul", "var", "wbr",
}
_DROP_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed"}
_ALLOWED_ATTR_RE = re.compile(
    r"^(href|src|alt|title|width|height|colspan|rowspan|align|valign|border|bgcolor|color|size|face|class|id|style)$")
_SAFE_URL_RE = re.compile(r"^\s*(https?:|mailto:|cid:|#|/)", re.I)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        parts = []
        for k, v in attrs:
            k = (k or "").lower()
            if not _ALLOWED_ATTR_RE.match(k):
                continue
            if k in ("href", "src") and not _SAFE_URL_RE.match(v or ""):
                continue
            parts.append(f'{k}="{_html.escape(v or "", quote=True)}"')
        self.out.append(f"<{tag}{' ' + ' '.join(parts) if parts else ''}>")

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr", "img", "wbr", "col"):
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(_html.escape(data))

def sanitize_html(raw):
    s = _Sanitizer()
    s.feed(raw or "")
    return "".join(s.out)

# ---------------------------------------------------------------- remote content

_REMOTE_SRC_RE = re.compile(r'\b(?:src|poster|background)\s*=\s*["\']https?://[^"\']*', re.I)
_KILL_REMOTE_RE = re.compile(r'\b(src|poster|background)\s*=\s*(["\'])https?://[^"\']*\2', re.I)

def contains_remote_content(safe_html):
    """True when sanitized markup would load resources from a remote server."""
    return bool(_REMOTE_SRC_RE.search(safe_html or ""))

def block_remote_content(safe_html):
    """Drop remote src/poster/background attributes (Elastic privacy blocking)."""
    return _KILL_REMOTE_RE.sub("", safe_html or "")

# ---------------------------------------------------------------- misc

def quotestr(s):
    """Quote an IMAP string."""
    return '"' + (s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'

def folder_display(name):
    return name.split("/")[-1] or name

def attachment_icon(content_type, filename):
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    if content_type and content_type.startswith("image/"):
        return "image"
    return {
        "pdf": "pdf", "zip": "zip", "gz": "zip", "tar": "zip", "7z": "zip",
        "rar": "zip", "doc": "doc", "docx": "doc", "xls": "xls", "xlsx": "xls",
        "ppt": "ppt", "pptx": "ppt", "txt": "txt", "md": "txt",
        "ics": "calendar", "vcf": "vcard",
    }.get(ext, "unknown")


# ---------------------------------------------------------------- vcards

_PHP_LATIN1 = dict(zip("äâàåáãæçéêëèïîìíñöôòøõóüûùúýÿ",
                       "aaaaaaaceeeeiiiinoooooouuuuyy", strict=True))
_PHP_LATIN2 = dict(zip("ąáâäćçčéęëěíîłľĺńňóôöŕřśšşťţůúűüźžżý",
                       "aaaaccceeeeiilllnnooorrsssttuuuuzzzy", strict=True))
_PHP_DIGRAPHS = {"ß": "ss", "ae": "a", "oe": "o", "ue": "u"}

_4BYTE_RE = re.compile("[\U00010000-\U0010FFFF]")
_TOK1_RE = re.compile(r"[\s;,\"'/+-]+")
_TOK2_RE = re.compile(r"(\d)[-.\s]+(\d)")


def tokenize_string(s, minlen=2):
    """Port of rcube_utils::tokenize_string() (PHP preg_replace order)."""
    if not isinstance(s, str):
        return []
    s = _TOK1_RE.sub(" ", s)
    s = _TOK2_RE.sub(r"\1\2", s)
    if minlen > 1:
        s = re.sub(rf"(^|\s+)\w{{1,{minlen - 1}}}(\s+|$)", " ", s)
    # PHP array_filter drops '0' tokens too
    return [t for t in s.split(" ") if t and t != "0"]


def normalize_string(s, as_array=False, minlen=2):
    """Port of rcube_utils::normalize_string(): tokenize, lowercase, fold
    ISO-8859-1/2 accents (map chosen exactly like PHP's charset probe)."""
    if isinstance(s, str):
        s = _4BYTE_RE.sub("?", s)
    tokens = tokenize_string(s, minlen)
    mapping = None
    try:
        (s or "").encode("iso8859_1")
        mapping = dict(_PHP_LATIN1)
    except (UnicodeEncodeError, AttributeError):
        try:
            (s or "").encode("iso8859_2")
            mapping = dict(_PHP_LATIN2)
        except (UnicodeEncodeError, AttributeError):
            mapping = None
    if mapping is not None:
        mapping.update(_PHP_DIGRAPHS)
        # PHP strtr(array): longest key wins at each position, no rescan
        keys = sorted(mapping, key=len, reverse=True)
        alt = re.compile("|".join(re.escape(k) for k in keys))
        mp = mapping

        def _fold(m):
            return mp[m.group(0)]
        tokens = [alt.sub(_fold, t.lower()) for t in tokens]
    else:
        tokens = [t.lower() for t in tokens]
    return tokens if as_array else " ".join(tokens)


# rcube_contacts::$fulltext_cols
_FULLTEXT_KEYS = ("name", "firstname", "surname", "middlename", "nickname",
                  "jobtitle", "organization", "department")


def contact_words(ext):
    """rcube_contacts::convert_save_data() words column content."""
    parts = []
    for key in _FULLTEXT_KEYS:
        v = ext.get(key) or ""
        if v and len(v.encode()) >= 3:
            parts.append(normalize_string(v))
    for _typ, val in ext.get("emails") or []:
        if val and len(val.encode()) >= 3:
            parts.append(normalize_string(val))
    for _typ, val in ext.get("phones") or []:
        if val and len(val.encode()) >= 3:
            parts.append(normalize_string(val))
    for addr in ext.get("addresses") or []:
        joined = " ".join(x for x in addr[1:] if x)
        if joined and len(joined.encode()) >= 3:
            parts.append(normalize_string(joined))
    notes = ext.get("notes") or ""
    if notes and len(notes.encode()) >= 3:
        parts.append(normalize_string(notes))
    words = " ".join(parts)
    return " ".join(dict.fromkeys(words.split(" ")))

# Elastic contactedit subtype selects (verified against 1.7.5 edit form)
CONTACT_EMAIL_TYPES = ["home", "work", "other"]
CONTACT_ADDRESS_TYPES = ["home", "work", "other"]
CONTACT_PHONE_TYPES = ["home", "home2", "work", "work2", "mobile", "main",
                       "homefax", "workfax", "car", "pager", "video",
                       "assistant", "other"]
CONTACT_TYPES = CONTACT_EMAIL_TYPES
# rcube_vcard $immap (rcube_vcard.php:69-77): extension tag -> service name
IM_SERVICE_TAGS = {"X-JABBER": "jabber", "X-ICQ": "icq", "X-MSN": "msn",
                   "X-AIM": "aim", "X-YAHOO": "yahoo", "X-SKYPE": "skype",
                   "X-SKYPE-USERNAME": "skype"}
IM_SERVICE_NAMES = {"jabber": "X-JABBER", "icq": "X-ICQ", "msn": "X-MSN",
                    "aim": "X-AIM", "yahoo": "X-YAHOO",
                    # RC's array_flip keeps the LAST duplicate tag (rcube_vcard.php:75-76)
                    "skype": "X-SKYPE-USERNAME"}
CONTACT_WEBSITE_TYPES = ["homepage", "work", "blog", "profile", "other"]
CONTACT_IM_TYPES = ["aim", "icq", "msn", "yahoo", "jabber", "skype"]

# rcube_vcard type maps (rcube_vcard.php:50-73). $typemap resolves a stored
# vCard TYPE (combined, uppercased, INTERNET/PREF stripped) to the internal
# subtype; the phone/address maps rewrite the form subtype on save.
RC_TYPEMAP = {
    "IPHONE": "mobile", "CELL": "mobile", "WORK,FAX": "workfax",
    "WORK,CELL": "other", "HOME,FAX": "homefax", "OTHER,FAX": "other",
    "FAX": "homefax",
}
RC_PHONETYPEMAP = {
    "HOME1": "HOME", "BUSINESS1": "WORK", "BUSINESS2": "WORK2",
    "BUSINESSFAX": "WORK,FAX", "MOBILE": "CELL",
}
RC_ADDRESSTYPEMAP = {"BUSINESS": "WORK"}
# array_flip($typemap) keyed by the uppercased subtype (rcube_vcard::set())
RC_TYPEMAP_FLIP = {v.upper(): k for k, v in RC_TYPEMAP.items()}


def rc_subtype(prop, raw_type):
    """rcube_vcard::get_assoc() subtype resolution for a stored TYPE
    (EMAIL/TEL/ADR/URL): combine TYPE parts (drop INTERNET/PREF), consult the
    typemap, else the first remaining part. An empty TYPE stays empty so the
    stored-vcard bytes are preserved on re-export (Roundcube drops TYPE=other
    and TYPE=internet on export); get_assoc's 'force other' only affects the
    edit-form display, not the serialized round-trip."""
    parts = [t.strip().lower() for t in (raw_type or "").split(",") if t.strip()]
    meaningful = [t for t in parts if t not in ("internet", "pref")]
    if not meaningful:
        return ""
    combined = ",".join(meaningful).upper()
    if combined in RC_TYPEMAP:
        return RC_TYPEMAP[combined]
    if meaningful[0].upper() in RC_TYPEMAP:
        return RC_TYPEMAP[meaningful[0].upper()]
    # TEL/EMAIL with only a PREF marker fall back like get_assoc()
    if combined in ("", "PREF", "INTERNET"):
        return {"TEL": "main", "EMAIL": "other"}.get(prop, combined.lower())
    return meaningful[0]


def rc_stored_type(prop, subtype):
    """rcube_vcard::set() save direction: form subtype -> stored TYPE.
    phone gets the phonetypemap rewrite first; then the flipped typemap
    applies for all non-email fields (address: addresstypemap)."""
    tu = (subtype or "").upper()
    if not tu:
        return ""
    typ = subtype
    if prop == "EMAIL":
        return subtype.lower()
    if prop == "TEL" and tu in RC_PHONETYPEMAP:
        typ = RC_PHONETYPEMAP[tu]
    elif prop == "ADR" and tu in RC_ADDRESSTYPEMAP:
        typ = RC_ADDRESSTYPEMAP[tu]
    # NOTE: set()'s array_flip($typemap) lookup is keyed by $type_uc while
    # the flip's keys are the lowercase typemap VALUES, so it never matches
    # lowercase form subtypes (verified live: form 'homefax' stores
    # TYPE=homefax, 'workfax' stores TYPE=workfax, 'other' stays other and
    # is dropped by export()).
    return typ.lower()

def vcard_encode(f):
    """Serialize a contact dict to the stored vCard.

    Roundcube builds the stored blob in rcube_contacts::convert_save_data()
    via rcube_vcard::export(false) — identical bytes to the download export,
    minus CATEGORIES. Delegate to vcard_export() so stored vcards are
    byte-identical to the reference."""
    return vcard_export(f)


def _vc_esc(v):
    """rcube_vcard v3 escaping: backslash, semicolon, CR drop, LF -> \\n.

    Roundcube trims stored property values (oracle: trailing space dropped).
    Note: commas are NOT escaped in v3 (verified against Roundcube 1.7.5)."""
    return ((v or "").strip().replace("\\", "\\\\").replace(";", "\\;")
            .replace("\r", "").replace("\n", "\\n"))


def _vc_fold(line):
    """Hard-fold a property line at 76 chars, continuation ' ' + 76 (oracle)."""
    if len(line) <= 76:
        return [line]
    out = [line[:76]]
    rest = line[76:]
    while rest:
        out.append(" " + rest[:76])
        rest = rest[76:]
    return out


def _vc_typ(typ):
    """v3 TYPE= parameter; rcube_vcard::export() lowercases TYPE parts and
    drops 'other' (non-standard) and 'internet' (redundant); with nothing
    left the attribute is omitted entirely."""
    parts = [t for t in (typ or "").lower().split(",")
             if t and t not in ("other", "internet")]
    return ";TYPE=" + ",".join(parts) if parts else ""


def vcard_export(f, categories=()):
    """Byte-exact Roundcube 1.7.5 vCard 3.0 export of a parsed contact dict.

    Field order mirrors rcube_contacts CONTACT_COLTYPES; CATEGORIES lists
    group names. f uses the util.vcard_parse() dict shape."""
    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    n = ";".join(_vc_esc(f.get(k)) for k in
                 ("surname", "firstname", "middlename", "prefix", "suffix"))
    lines.append("N:" + n)
    # rcube_vcard::export(): "Make sure FN is not empty (RFC2426)" — fall back
    # to the primary email address when no display name is set
    fn = f.get("name") or next((v for _t, v in (f.get("emails") or []) if v), "")
    lines.append("FN:" + _vc_esc(fn))
    for typ, val in f.get("emails") or []:
        if val:
            lines.append("EMAIL" + _vc_typ(rc_stored_type("EMAIL", typ))
                         + ":" + _vc_esc(val))
    if f.get("nickname"):
        lines.append("NICKNAME:" + _vc_esc(f["nickname"]))
    if f.get("jobtitle"):
        lines.append("TITLE:" + _vc_esc(f["jobtitle"]))
    if f.get("organization"):
        lines.append("ORG:" + _vc_esc(f["organization"]))
    if f.get("department"):
        lines.append("X-DEPARTMENT:" + _vc_esc(f["department"]))
    if f.get("gender"):
        lines.append("X-GENDER:" + _vc_esc(f["gender"]))
    if f.get("maidenname"):
        lines.append("X-MAIDENNAME:" + _vc_esc(f["maidenname"]))
    for typ, val in f.get("phones") or []:
        if val:
            lines.append("TEL" + _vc_typ(rc_stored_type("TEL", typ)) + ":" + _vc_esc(val))
    for addr in f.get("addresses") or []:
        typ, street, locality, zipcode, region, country = (list(addr) + [""] * 6)[:6]
        if any((street, locality, zipcode, region, country)):
            # RFC value order: ext;post;street;city;region;postcode;country
            lines.append("ADR" + _vc_typ(rc_stored_type("ADR", typ)) + ":;;"
                         + _vc_esc(street) + ";" + _vc_esc(locality) + ";"
                         + _vc_esc(region) + ";" + _vc_esc(zipcode) + ";"
                         + _vc_esc(country))
    if f.get("birthday"):
        lines.append("BDAY;VALUE=date:" + _vc_esc(f["birthday"]))
    if f.get("anniversary"):
        lines.append("X-ANNIVERSARY;VALUE=date:" + _vc_esc(f["anniversary"]))
    for typ, val in f.get("websites") or []:
        if val:
            lines.append("URL" + _vc_typ(rc_stored_type("URL", typ)) + ":" + _vc_esc(val))
    for svc, val in f.get("im") or []:
        tag = IM_SERVICE_NAMES.get((svc or "").lower())
        if tag and val:
            lines.append(tag + ":" + _vc_esc(val))
    if f.get("notes"):
        lines.append("NOTE:" + _vc_esc(f["notes"]))
    for k, tag in (("assistant", "X-ASSISTANT"), ("manager", "X-MANAGER"),
                   ("spouse", "X-SPOUSE")):
        if f.get(k):
            lines.append(tag + ":" + _vc_esc(f[k]))
    cats = [c for c in (categories or []) if c]
    if cats:
        lines.append("CATEGORIES:" + ";".join(_vc_esc(c) for c in cats))
    lines.append("END:VCARD")
    out = []
    for ln in lines:
        out.extend(_vc_fold(ln))
    return "\r\n".join(out) + "\r\n"


def _vcard_unesc(v):
    out, i = [], 0
    while i < len(v):
        ch = v[i]
        if ch == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            out.append({"n": "\n", ";": ";", ",": ",", "\\": "\\"}.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def vcard_parse(text):
    """Inverse of vcard_encode; tolerant of missing/unknown lines."""
    f = {"name": "", "prefix": "", "firstname": "", "middlename": "",
         "surname": "", "suffix": "", "nickname": "", "organization": "",
         "department": "", "jobtitle": "", "gender": "", "birthday": "",
         "notes": "", "emails": [], "phones": [], "addresses": [],
         "maidenname": "", "anniversary": "", "assistant": "", "manager": "",
         "spouse": "", "websites": [], "im": []}
    if not text or "BEGIN:VCARD" not in text:
        return f
    # unfold RFC5322-style continuation lines (CRLF + space/tab)
    unfolded = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += raw[1:]
        else:
            unfolded.append(raw)
    for raw in unfolded:
        raw = raw.strip("\r")
        if not raw or ":" not in raw:
            continue
        head, val = raw.split(":", 1)
        val = _vcard_unesc(val)
        parts = head.split(";")
        prop = parts[0].upper()
        # raw TYPE= parameter; get_assoc() resolves it via the vcard typemap
        # and forces "other" for email/phone/address/website without one
        typ = ""
        for p in parts[1:]:
            if p.upper().startswith("TYPE="):
                typ = p.split("=", 1)[1].lower()
        if prop == "FN":
            f["name"] = val
        elif prop == "N":
            bits = val.split(";") + [""] * 5
            f["surname"], f["firstname"], f["middlename"], f["prefix"], f["suffix"] = bits[:5]
        elif prop == "NICKNAME":
            f["nickname"] = val
        elif prop == "ORG":
            f["organization"] = val
        elif prop == "X-DEPARTMENT":
            f["department"] = val
        elif prop == "TITLE":
            f["jobtitle"] = val
        elif prop == "EMAIL":
            f["emails"].append((rc_subtype("EMAIL", typ), val))
        elif prop == "TEL":
            f["phones"].append((rc_subtype("TEL", typ), val))
        elif prop == "ADR":
            bits = val.split(";") + [""] * 7
            f["addresses"].append((rc_subtype("ADR", typ), bits[2], bits[3], bits[5], bits[4], bits[6]))
        elif prop in ("GENDER", "X-GENDER"):
            f["gender"] = val
        elif prop in ("BIRTHDAY", "BDAY"):
            f["birthday"] = val
        elif prop in ("X-MAIDENNAME", "MAIDENNAME"):
            f["maidenname"] = val
        elif prop in ("X-ANNIVERSARY", "ANNIVERSARY"):
            f["anniversary"] = val
        elif prop in ("X-ASSISTANT", "ASSISTANT"):
            f["assistant"] = val
        elif prop in ("X-MANAGER", "MANAGER"):
            f["manager"] = val
        elif prop in ("X-SPOUSE", "SPOUSE"):
            f["spouse"] = val
        elif prop == "URL":
            f["websites"].append((rc_subtype("URL", typ), val))
        elif prop in IM_SERVICE_TAGS:
            f["im"].append((IM_SERVICE_TAGS[prop], val))
        elif prop == "NOTE":
            f["notes"] = val
    return f


def check_email(email_addr):
    """rcube_utils::check_email() (rcube_utils.php:85-159). The DNS branch
    only runs when email_dns_check is on (it is off), so this is the whole
    effective check on the reference."""
    import ipaddress

    if re.search(r"[\x00-\x1f\x7f\x80-\x9f]", email_addr):  # \p{Cc}
        return False
    if len(email_addr.encode()) > 254:
        return False
    pos = email_addr.rfind("@")
    if not pos:
        return False
    domain_part = email_addr[pos + 1:]
    local_part = email_addr[:pos]
    if local_part.startswith('"'):
        local_quoted = re.sub(r'\\(["\\])', "", local_part[1:-1])
        if re.search(r'\\|"', local_quoted):
            return False
    elif (re.search(r"(^\.|\.\.|\.$)", local_part)
          or re.search(r'[ ",:;<>@]', local_part)):
        return False
    m = re.match(r"^\[((IPv6:[0-9a-f:.]+)|([0-9.]+))\]$", domain_part, re.I)
    if m:
        try:
            ipaddress.ip_address(re.sub(r"^IPv6:", "", m.group(1), flags=re.I))
            return True
        except ValueError:
            return False
    domain_array = domain_part.split(".")
    if len(domain_array) < 2:
        return False
    for part in domain_array:
        if not re.match(r"^((xn--)?([A-Za-z0-9][A-Za-z0-9-]{0,61}[A-Za-z0-9])|([A-Za-z0-9]))$", part):
            return False
    last_part = domain_array[-1]
    if not last_part.startswith("xn--") and (  # noqa: SIM103 - mirrors rcube_utils::check_email()
            re.search(r"[^a-zA-Z0-9]", last_part)
            or re.match(r"^[0-9]+$", last_part)):
        return False
    return True
