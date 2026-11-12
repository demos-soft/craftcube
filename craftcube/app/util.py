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
            out.append(fmt[i + 1]); i += 2; continue
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
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(ZoneInfo(tzname))
        except Exception:
            pass
    return to_local(dt)

def fmt_pref_time(dt, prefs):
    if dt is None:
        return ""
    prefs = prefs or {}
    tf = prefs.get("time_format", "H")
    # reference stores PHP formats ('H:i'); legacy CraftCube used 'H'/'h'
    fmt = php_strftime(tf, to_local_tz(dt, prefs.get("timezone"))) \
        if ":" in tf else \
        to_local_tz(dt, prefs.get("timezone")).strftime(
            "%H:%M" if tf == "H" else "%I:%M %p")
    return fmt

def fmt_pref_date(dt, prefs):
    """Message view date honouring date_format/pretty_date/time_format prefs."""
    if dt is None:
        return ""
    prefs = prefs or {}
    dt = to_local_tz(dt, prefs.get("timezone"))
    df = prefs.get("date_format", "long")
    base = php_strftime(df, dt) if any(c in df for c in "Yydj") \
        else dt.strftime(DATE_FORMATS.get(df, DATE_FORMATS["long"]))
    if prefs.get("pretty_date"):
        # Roundcube 'pretty' style: weekday + human date + time
        return dt.strftime("%a, ") + base + " " + fmt_pref_time(dt, prefs)
    return base + " " + fmt_pref_time(dt, prefs) \
        if any(c in df for c in "Yydj") and prefs.get("show_pref_time", 1) \
        else base

def list_pref_date(dt, prefs):
    """Message-list date honouring timezone + time_format prefs."""
    if dt is None:
        return ""
    prefs = prefs or {}
    dt = to_local_tz(dt, prefs.get("timezone"))
    now = to_local_tz(datetime.now(timezone.utc), prefs.get("timezone"))
    tf = prefs.get("time_format", "H")
    tfmt = php_strftime(tf, dt) if ":" in tf else ("%H:%M" if tf == "H" else "%I:%M %p")
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


# ---------------------------------------------------------------- vcards

CONTACT_TYPES = ["work", "home", "other"]

def vcard_encode(f):
    """Serialize extended contact fields to a minimal vCard 4.0."""
    lines = ["BEGIN:VCARD", "VERSION:4.0"]
    def esc(v):
        return (v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lines.append("FN:" + esc(f.get("name")))
    lines.append("N:%s;%s;%s;%s;%s" % tuple(esc(f.get(k)) for k in
                 ("surname", "firstname", "middlename", "prefix", "suffix")))
    if f.get("nickname"):
        lines.append("NICKNAME:" + esc(f["nickname"]))
    if f.get("organization"):
        lines.append("ORG:" + esc(f["organization"]))
    if f.get("department"):
        lines.append("X-DEPARTMENT:" + esc(f["department"]))
    if f.get("jobtitle"):
        lines.append("TITLE:" + esc(f["jobtitle"]))
    for typ, val in f.get("emails") or []:
        if val:
            lines.append("EMAIL;TYPE=%s:%s" % (typ or "work", esc(val)))
    for typ, val in f.get("phones") or []:
        if val:
            lines.append("TEL;TYPE=%s:%s" % (typ or "work", esc(val)))
    for addr in f.get("addresses") or []:
        typ, street, locality, zipcode, region, country = (list(addr) + [""] * 6)[:6]
        if any((street, locality, zipcode, region, country)):
            lines.append("ADR;TYPE=%s:;;%s;%s;%s;%s;%s" % (
                typ or "home", esc(street), esc(locality), esc(region),
                esc(zipcode), esc(country)))
    if f.get("gender"):
        lines.append("GENDER:" + esc(f["gender"]))
    if f.get("birthday"):
        lines.append("BIRTHDAY:" + esc(f["birthday"]))
    if f.get("notes"):
        lines.append("NOTE:" + esc(f["notes"]))
    lines.append("END:VCARD")
    return "\n".join(lines)


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
         "notes": "", "emails": [], "phones": [], "addresses": []}
    if not text or "BEGIN:VCARD" not in text:
        return f
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or ":" not in raw:
            continue
        head, val = raw.split(":", 1)
        val = _vcard_unesc(val)
        parts = head.split(";")
        prop = parts[0].upper()
        typ = "work"
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
            f["emails"].append((typ, val))
        elif prop == "TEL":
            f["phones"].append((typ, val))
        elif prop == "ADR":
            bits = val.split(";") + [""] * 7
            f["addresses"].append((typ, bits[2], bits[3], bits[5], bits[4], bits[6]))
        elif prop == "GENDER":
            f["gender"] = val
        elif prop == "BIRTHDAY":
            f["birthday"] = val
        elif prop == "NOTE":
            f["notes"] = val
    return f
