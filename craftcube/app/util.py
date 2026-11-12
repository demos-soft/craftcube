"""Shared helpers: dates, sizes, HTML sanitizing, header parsing."""
import email
import email.utils
import html as _html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

# ---------------------------------------------------------------- dates/sizes

def to_local(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
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

def fmt_list_date(dt):
    """Elastic message-list date: 'Fri 22:45' inside the current week,
    '23 Sep' this year, '23.10.25' older."""
    if dt is None:
        return ""
    dt = to_local(dt)
    now = datetime.now().astimezone()
    if (now - dt).days < 7 and dt.isocalendar()[:2] == now.isocalendar()[:2]:
        return dt.strftime("%a %H:%M")
    if dt.year == now.year:
        return dt.strftime("%d %b")
    return dt.strftime("%d.%m.%y")

def fmt_summary_date(dt):
    if dt is None:
        return ""
    return to_local(dt).strftime("%Y-%m-%d %H:%M")


# Preferred date/time formatting (settings > preferences) ---------------------

DATE_FORMATS = {
    "long": "%e %B %Y %H:%M",       # 9 January 2026 14:05
    "short": "%d.%m.%y %H:%M",      # 09.01.26 14:05
    "yyyy-mm-dd": "%Y-%m-%d %H:%M",
    "mm/dd/yyyy": "%m/%d/%Y %H:%M",
}

def to_local_tz(dt, tzname=None):
    """Convert to local zone, or to the IANA zone named in prefs."""
    if dt is None:
        return None
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(ZoneInfo(tzname))
        except Exception:
            pass
    return to_local(dt)

def fmt_pref_time(dt, prefs):
    if dt is None:
        return ""
    fmt = "%H:%M" if (prefs or {}).get("time_format", "H") == "H" else "%I:%M %p"
    return to_local_tz(dt, (prefs or {}).get("timezone")).strftime(fmt)

def fmt_pref_date(dt, prefs):
    """Message view date honouring date_format/pretty_date/time_format prefs."""
    if dt is None:
        return ""
    prefs = prefs or {}
    dt = to_local_tz(dt, prefs.get("timezone"))
    if prefs.get("pretty_date"):
        # Roundcube 'pretty' style: weekday + human date + time
        return dt.strftime("%a, ") + dt.strftime(DATE_FORMATS.get(
            prefs.get("date_format", "long"), DATE_FORMATS["long"])) + \
            " " + fmt_pref_time(dt, prefs)
    fmt = DATE_FORMATS.get(prefs.get("date_format", "long"), DATE_FORMATS["long"])
    return dt.strftime(fmt)

def list_pref_date(dt, prefs):
    """Message-list date honouring timezone + time_format prefs."""
    if dt is None:
        return ""
    prefs = prefs or {}
    dt = to_local_tz(dt, prefs.get("timezone"))
    now = to_local_tz(datetime.now(timezone.utc), prefs.get("timezone"))
    tfmt = "%H:%M" if prefs.get("time_format", "H") == "H" else "%I:%M %p"
    if dt.date() == now.date():
        return dt.strftime(tfmt)
    if dt.year == now.year:
        return dt.strftime("%d %b")
    return dt.strftime("%d.%m.%y")

def fmt_datetime(dt):
    if dt is None:
        return ""
    return dt.strftime("%a, %d %b %Y %H:%M %z")

def human_size(n):
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return ""

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
_ALLOWED_ATTR_RE = re.compile(r"^(href|src|alt|title|width|height|colspan|rowspan|align|valign|border|bgcolor|color|size|face|class|id|style)$")
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
