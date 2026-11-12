"""rcube_utils CSS engine + rcube_washtml compose-wash port.

Byte-parity targets captured from the reference Roundcube 1.7.5 pod on k8s3
staging (2026-11-03): rcube_utils::mod_css_styles/sanitize_css_block oracle
and side-by-side reply-compose prefills. Used for the compose html source
part only (prepare_html_body/wash_html); the message view keeps the plain
util.sanitize_html path.

Known nuance: pathological inputs (nested <html>/<body> documents) are
normalized by PHP's DOM parser in ways this regex/parser port does not
replicate exactly; plain fragments and single-body documents match.
"""
import html as _html
import re
from html.parser import HTMLParser

# ------------------------------------------------ rcube_utils::xss_entity_decode

def xss_entity_decode(content):
    out = _html.unescape(_html.unescape(content))
    out = out.strip(" \t\n\r\0\x0B")
    out = re.sub(r"(^<!--|-->$)", "", out).strip(" \t\n\r\0\x0B")
    out = re.sub(r"\\([0-9a-f]{2,6})\s*",
                 lambda m: chr(int(m.group(1), 16)), out, flags=re.I)
    out = re.sub(r"\\([^0-9a-f])", r"\1", out, flags=re.I)
    out = re.sub(r"/\*.*?\*/", "", out, flags=re.S)
    return re.sub(r"<[^>]*>", "", out)


# ------------------------------------------------ rcube_utils::parse_css_block

def remove_css_comments(style):
    pos = 0
    while (pos := style.find("/*", pos)) != -1:
        end = style.find("*/", pos + 2)
        if end == -1:
            style = style[:pos]
            break
        style = style[:pos] + style[end + 2:]
    return style


def parse_css_block(style):
    style = remove_css_comments(style)
    style = re.sub(r"[\r\n]+", " ", style)
    style = style.strip()
    length = len(style)
    result = []
    pos = 0
    while pos < length:
        colon_pos = style.find(":", pos)
        if colon_pos <= 0:  # PHP truthiness: false and 0 both end the loop
            break
        name = style[pos:colon_pos].lower().strip()
        q = False
        s = False
        i = colon_pos
        for i in range(colon_pos + 1, length):
            ch = style[i]
            if ch in "\"'" and style[i - 1] != "\\":
                if q == ch:
                    q = False
                elif q is False:
                    q = ch
            elif ch == "(" and q is False and style[i - 1] != "\\":
                q = "("
            elif ch == ")" and q == "(" and style[i - 1] != "\\":
                q = False
            if q is False:
                s = ch == ";"
                if s or i == length - 1:
                    break
        value_len = i - colon_pos - (1 if s else 0)
        value = style[colon_pos + 1:colon_pos + 1 + value_len].strip()
        name = name.lstrip("; \t\r\n")
        if name and not re.search(r"[^a-z-]", name) and value and value != ";":
            result.append((name, value))
        pos = i + 1
    return result


def explode_css_property_block(style):
    style = re.sub(r"\s+", " ", style)
    result = []
    strlen = len(style)
    q = False
    p = 0
    for i in range(strlen):
        ch = style[i]
        if ch in "\"'" and (i == 0 or style[i - 1] != "\\"):
            if q == ch:
                q = False
            elif not q:
                q = ch
        if (not q and ch == " "
                and (i == 0 or not re.search(r"[,(]", style[i - 1]))):
            result.append(style[p:i])
            p = i + 1
    result.append(style[p:])
    return [str(x) for x in result]


# ------------------------------------------------ rcube_utils::sanitize_css_block

def _url_callback(url, allow_remote):
    if url.startswith("data:image"):
        return url
    if allow_remote and re.match(r"^https?://[a-z0-9/._+-]+$", url, re.I):
        return url
    return None


def sanitize_css_block(styles, allow_remote=False):
    output = []
    for prop, value in parse_css_block(styles):
        if prop == "page":
            continue
        if prop == "position" and "fixed" in value.lower():
            value = "absolute"
        elif re.search(r"expression|image-set", value, re.I):
            continue
        else:
            orig = value
            value = ""
            for val in explode_css_property_block(orig):
                if re.search(r"\burl\s*\(", val, re.I):
                    bad = False

                    def _sub(m):
                        nonlocal bad
                        checked = _url_callback(m.group(2), allow_remote)
                        if checked is None:
                            bad = True
                            return m.group(0)
                        return m.group(1) + "url(" + checked + ")"

                    val = re.sub(r"(\b)url\s*\(\s*['\"]?([^'\"\)]*)['\"]?\s*\)",
                                 _sub, val, flags=re.I)
                    if not bad and val:
                        value += " " + val
                elif re.search(r";.+", val):
                    continue
                else:
                    value += " " + val
                    if (val and re.match(r"^(left|right|top|bottom|width|height)", prop, re.I)
                            and re.match(r"^[0-9]+$", val)):
                        value += "px"
        if value:
            output.append(prop + ": " + value.strip())
    return "; ".join(output) + ";" if output else ""


# ------------------------------------------------ rcube_utils::mod_css_styles

def mod_css_styles(source, container_id, allow_remote=False, prefix=""):
    source = xss_entity_decode(source)
    if "@import" in source.lower():
        return "/* evil! */"
    if "{" not in source:
        return "/* invalid! */"
    source = re.sub(r"(^\s*<!--)|(-->\s*$)", "", source, flags=re.M)
    if re.search(r"\\[0-9a-fA-F]{2}", source):
        return "/* evil! */"
    if "/*" in source or "<!--" in source:
        return "/* evil! */"

    uniq = "00000000010000000002"  # rcube_string_replacer uniq ident (fixed per instance)
    blocks = {}
    counter = [0]

    last_pos = 0
    while True:
        pos = source.find("{", last_pos)
        if pos <= 0:  # PHP: false or 0 end the loop
            break
        pos2 = source.find("}", pos)
        if pos2 <= 0:
            pos2 = len(source) - 1
        if source[pos2] != "}":
            pos2 += 1
            source += "}"
        nested = source.find("{", pos + 1)
        if nested != -1 and nested < pos2:
            pos = nested
        length = pos2 - pos - 1
        styles = sanitize_css_block(source[pos + 1:pos + 1 + length], allow_remote)
        key = counter[0]
        counter[0] += 1
        blocks[key] = f" {styles} " if styles else ""
        repl = f"##{uniq}##{key}##"
        source = source[:pos + 1] + repl + source[pos + 1 + length:]
        last_pos = pos2 - (length - len(repl))

    excl = f"(?!##{uniq}##\\d+##)"
    regexp = re.compile(
        r"(^\s*|,\s*|\}\s*|\{\s*|@[^;{]*[;{]\s*)"
        r"(" + excl + r":?[a-z0-9._#*\[:][a-z0-9._:\(\)#=~ \[\]\"|\>\+\$\^-]*)",
        re.I | re.M)

    def cb(m):
        replace = m.group(2)
        if replace.lower().startswith(":root"):
            replace = replace[5:]
        if prefix:
            replace = replace.replace(".", "." + prefix).replace("#", "#" + prefix)
        if container_id:
            replace = "#" + container_id + " " + replace
        replace = re.sub(r"\s+", " ", replace)
        return m.group(0).replace(m.group(2), replace)

    if container_id or prefix:
        source = regexp.sub(cb, source)

    if container_id:
        source = re.sub(rf"#{re.escape(container_id)}\s+body",
                        f"#{container_id}", source, flags=re.I)

    for key, val in blocks.items():
        source = source.replace(f"##{uniq}##{key}##", val)
    return source


# ------------------------------------------------ rcube_washtml::wash_style

def wash_style(style):
    style = xss_entity_decode(style)
    style = re.sub(r"[\n\r\t]+", " ", style)
    return sanitize_css_block(style, allow_remote=False).rstrip(";")


# ------------------------------------------------ compose wash (washtml subset)

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "param", "source", "track", "wbr"}
_DROP_WITH_CONTENT = {"script", "title", "noframes"}
_VOID_DROP = {"meta", "link", "base"}
_LINK_ATTR_ALLOW = ["href", "name", "target", "onclick", "id", "class", "style",
                    "title", "rel", "type", "media", "alt", "coords", "nohref",
                    "hreflang", "shape"]
_NAME_PREFIX_TAGS = {"a", "img", "input", "form", "select", "textarea"}


def _esc_ent_compat(s):
    """htmlspecialchars ENT_COMPAT|ENT_HTML401: & < > \" only."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _esc_ent_quotes(s):
    """ENT_QUOTES|ENT_SUBSTITUTE."""
    return _esc_ent_compat(s).replace("'", "&#039;")


_WASH_ATTRIBS = {
    "name", "class", "title", "alt", "width", "height", "align", "nowrap", "col",
    "row", "id", "rowspan", "colspan", "cellspacing", "cellpadding", "valign",
    "bgcolor", "color", "border", "bordercolorlight", "bordercolordark", "face",
    "marginwidth", "marginheight", "axis", "abbr", "char", "charoff", "clear",
    "compact", "coords", "vspace", "hspace", "cellborder", "size", "lang", "dir",
    "usemap", "shape", "media", "background", "src", "poster", "href", "headers",
    "start", "reversed", "type", "rows", "cols", "disabled", "readonly", "checked",
    "multiple", "value", "for",
}
_BODY_ATTRIBS = {"alink", "background", "bgcolor", "link", "text", "vlink"}
_LINK_ATTR_ALLOW_SET = set(_LINK_ATTR_ALLOW)
_MAILTO_RE = re.compile(r"^mailto:(.+)$", re.I | re.S)
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)+$")
_IMAGE_SRC_TAGS = {"img", "input"}


def _jq(s):
    """rcube::JQ — single-quoted JS string escaping."""
    return (s.replace("\\", "\\\\").replace("'", "\\'")
             .replace("\n", "\\n").replace("\r", "\\r"))


def _wash_link(href, prefix=None):
    """rcube_washtml::wash_link()."""
    if len(href) and not re.match(r"^(javascript|vbscript|data:)", href, re.I):
        if href[0] == "#" and prefix is not None:
            return "#" + prefix + href[1:]
        if re.match(r"^[a-zA-Z._-]+$", href):
            return "http://" + href
        if re.match(r"^([a-z][a-z0-9.+-]+:|//|#).+", href, re.I):
            return href
    return ""


def _wash_uri_image(url):
    """wash_uri($url, true) with allow_remote=false: keep inline data images;
    anything remote/cid-unmapped is blocked (attr dropped, show_washed=false)."""
    m = re.match(r"^data:(image/[a-z0-9.+-]+);", url, re.I)
    return url if m else ""


def _wash_mailto(href):
    """washtml_link_callback mailto branch -> (href, onclick) or None."""
    m = _MAILTO_RE.match(href)
    if not m:
        return None
    import email.utils
    import urllib.parse
    url_parts = _html.unescape(m.group(1)).split("?", 1)
    mailto = urllib.parse.unquote(url_parts[0])
    url = urllib.parse.unquote(url_parts[1]) if len(url_parts) > 1 else ""
    addrs, strings = [], []
    for raw in mailto.split(","):
        raw = raw.strip()
        _name, addr = email.utils.parseaddr(raw)
        if addr and _EMAIL_RE.match(addr):
            addrs.append(addr)
            strings.append(raw)
    if addrs:
        onclick = ("return rcmail.command('compose','"
                   + _jq(",".join(strings) + (("?" + url) if url else ""))
                   + "',this)")
        return ("mailto:" + ",".join(addrs), onclick)
    return "#NOP", ""




def compose_wash_html(raw, container_id=None, css_prefix=""):
    """rcube_washtml wash() as configured by
    rcmail_action_mail_index::wash_html() for inline compose html
    (prepare_html_body): wash_attribs on every node (id/class/for/name
    css_prefix, style sanitizing, link/image url washing), then the
    a/area/body/style callbacks. Only <body> children survive; body becomes
    a <div> seeded with the container id (a source body id wins, prefixed),
    bgcolor/text/background folded into style."""
    from .util import _ALLOWED_TAGS

    class W(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out = []
            self.skip = 0
            self.in_style = False
            self.style_src = []

        # wash_attribs(): returns (tag, washed_attrs) or None when all gone
        def _wash_attribs(self, tag, attrs):
            allow = _WASH_ATTRIBS | _BODY_ATTRIBS if tag == "body" else _WASH_ATTRIBS
            out = {}  # washed string order = source order, first dup wins
            seen = set()
            for k, v in attrs:
                k = (k or "").lower()
                if k in seen:
                    continue
                seen.add(k)
                v = v or ""
                if k == "style":
                    if v:
                        v = wash_style(v)
                        if not v:
                            continue
                    out[k] = v
                    continue
                if k not in allow:
                    continue
                if (css_prefix and (k in ("id", "class", "for")
                        or (k == "name" and tag in _NAME_PREFIX_TAGS))):
                    v = re.sub(r"(\S+)", css_prefix + r"\1", v)
                elif k == "xmlns" and "://" not in v:
                    continue
                if tag in _IMAGE_SRC_TAGS and k in ("src", "poster"):
                    v = _wash_uri_image(v.strip())
                    if not v:
                        continue
                elif k == "href":
                    v = _wash_link(v, css_prefix or None)
                    if not v:
                        continue
                out[k] = v
            return out

        def _emit(self, tag, d, esc):
            parts = [f'{k}="{esc(v)}"' for k, v in d.items()]
            return (" " + " ".join(parts)) if parts else ""

        def _dump(self, tag, attrs, selfclose=False):
            if tag in _VOID_DROP:
                return
            if tag in _DROP_WITH_CONTENT and not selfclose:
                self.skip += 1
                return
            if self.skip:
                return
            if tag == "style":
                self.in_style = True
                self.style_src = []
                return
            if tag == "body":
                return  # handled by the region split below (callback)
            if tag not in _ALLOWED_TAGS:
                return  # tag dropped, content kept (dumpHtml fallback)
            d = self._wash_attribs(tag, attrs)
            if tag in ("a", "area"):
                # washtml_link_callback on the already-washed attribs
                d = {k: v for k, v in d.items() if k in _LINK_ATTR_ALLOW_SET}
                href = d.get("href")
                if href is not None:
                    href = re.sub(r"[\x00-\x1F]", "", href)
                    d["href"] = href
                    mm = _wash_mailto(href) if href else None
                    if mm is not None:
                        d["href"] = mm[0]
                        if mm[1]:
                            d["onclick"] = mm[1]
                        elif mm[0] == "#NOP":
                            d["onclick"] = ""
                    elif href and href[0] != "#":
                        d["target"] = "_blank"
                        d["rel"] = ((d.get("rel") or "") + " noopener").strip()
                    if d["href"] and d["href"][0] != "#":
                        d["rel"] = ((d.get("rel") or "") + " noreferrer").strip()
                # html::tag() re-serializes with ENT_COMPAT
                s = self._emit(tag, d, _esc_ent_compat)
                self.out.append(f"<{tag}{s}>")
                return
            s = self._emit(tag, d, _esc_ent_quotes)
            if tag in _VOID or selfclose:
                self.out.append(f"<{tag}{s} />")
            else:
                self.out.append(f"<{tag}{s}>")

        def handle_starttag(self, tag, attrs):
            self._dump(tag, attrs)

        def handle_startendtag(self, tag, attrs):
            self._dump(tag, attrs, selfclose=True)

        def handle_endtag(self, tag):
            if tag in _DROP_WITH_CONTENT:
                self.skip = max(0, self.skip - 1)
                return
            if self.skip:
                return
            if tag == "style":
                self.in_style = False
                css = "".join(self.style_src)
                out_css = mod_css_styles(css, container_id, False, css_prefix)
                if out_css:
                    self.out.append('<style type="text/css">' + out_css + "</style>")
                return
            if tag not in _ALLOWED_TAGS or tag in _VOID:
                return
            self.out.append(f"</{tag}>")

        def handle_data(self, data):
            if self.in_style:
                self.style_src.append(data)
                return
            if not self.skip:
                self.out.append(_esc_ent_compat(data))

    raw = raw or ""
    # DOM semantics: only <body> children survive; without an explicit
    # <body> the whole fragment survives, minus trailing whitespace
    body_span = re.search(r"<body\b([^>]*)>(.*)</body\s*>", raw, re.S | re.I)
    if body_span:
        body_attr_src, raw = body_span.group(1), body_span.group(2)
    else:
        body_attr_src, raw = "", raw.rstrip()
    w = W()
    w.feed(raw)
    content = "".join(w.out)

    # washtml_callback('body'): attrs arrive already washed (id/class
    # prefixed, style sanitized); bgcolor/text/background fold into style
    attrs = {"id": container_id} if container_id else {}
    style_parts = []
    washed_body = w._wash_attribs("body", [
        (k, "" if v is None else (_html.unescape(v[1:-1])
                                  if v[:1] in ('"', "'") and v[-1:] == v[:1] else _html.unescape(v)))
        for k, v in re.findall(
            r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\">]+))?",
            body_attr_src)])
    for k, v in washed_body.items():
        low = k.lower()
        if low == "bgcolor" and re.match(r"^([a-z0-9#]+)$", v, re.I):
            style_parts.append("background-color: " + v)
        elif low == "text" and re.match(r"^([a-z0-9#]+)$", v, re.I):
            style_parts.append("color: " + v)
        elif low == "background" and re.match(r"^(static\.php/|https?://)([^\s();]+)$", v):
            style_parts.append(f"background-image: url({v})")
        else:
            if low == "id" and container_id:
                attrs["id"] = v  # replaces the container id, keeps position
            else:
                attrs[k] = v
    if style_parts:
        base = attrs.get("style", "").strip("; ")
        attrs["style"] = (base + ("; " if base else "")) + "; ".join(style_parts)

    s = (" " + " ".join(f'{k}="{_esc_ent_compat(v)}"' for k, v in attrs.items())) if attrs else ""
    return f"<div{s}>{content}</div>"
