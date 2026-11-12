"""Roundcube-style localization.

The catalogues under app/locale/<lang>/ are the reference's own
program/localization/*.inc files (Roundcube, GPL-3.0+). Like
rcube::load_language() (rcube.php:685) the texts start from the complete
en_US catalogue and layer the user's language on top, so missing keys
fall back to English; gettext() also does the $var substitution
(rcube.php:609-620) and the '[name]' marker for unknown keys.
"""
import os
import re

LOC_DIR = os.path.join(os.path.dirname(__file__), "locale")

# parsed catalogue cache: lang -> {key: text}
_cache = {}

# $labels['key'] = 'value';  /  $messages['key'] = "...";
_ENTRY = re.compile(
    r"^\$(labels|messages)\['([^']+)'\]\s*=\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')\s*;",
    re.M,
)
_ESCAPES = {"\\'": "'", '\\"': '"', "\\\\": "\\", "\\n": "\n", "\\r": "\r",
            "\\t": "\t", "\\$": "$"}


def _unescape(raw):
    if raw[0] == '"':
        body = raw[1:-1]
        out = []
        i = 0
        while i < len(body):
            two = body[i:i + 2]
            if two in _ESCAPES:
                out.append(_ESCAPES[two])
                i += 2
            else:
                out.append(body[i])
                i += 1
        return "".join(out)
    # single-quoted PHP strings escape only \' and \\
    body = raw[1:-1]
    return body.replace("\\'", "'").replace("\\\\", "\\")


def _load(lang):
    if lang in _cache:
        return _cache[lang]
    texts = {}
    for domain in ("labels", "messages"):
        path = os.path.join(LOC_DIR, lang, f"{domain}.inc")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            continue
        for dom, key, raw in _ENTRY.findall(src):
            if dom == domain:
                texts[key] = _unescape(raw)
    _cache[lang] = texts
    return texts


def catalogue(lang):
    """en_US texts with the user language layered on top (rcube.php:691-708)."""
    texts = dict(_load("en_US"))
    norm = language_prop(lang)
    if norm not in ("en", "en_US"):
        texts.update(_load(norm))
    return texts


_index_cache = None


def _index():
    """$rcube_languages / $rcube_language_aliases from the vendored index.inc
    (rcube.php:832-834)."""
    global _index_cache
    if _index_cache is None:
        langs, aliases = set(), {}
        path = os.path.join(LOC_DIR, "index.inc")
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            src = ""
        for m in re.finditer(r"\$rcube_language(s|_aliases)\s*=\s*\[(.*?)\];", src, re.S):
            kind, body = m.group(1), m.group(2)
            pairs = re.findall(r"'([^']+)'\s*=>\s*'([^']*)'", body)
            if kind == "s":
                langs = {k for k, _v in pairs}
            else:
                aliases = dict(pairs)
        _index_cache = (langs, aliases)
    return _index_cache


def language_prop(lang):
    """rcube::language_prop() (rcube.php:818): normalize a locale code
    through the reference's language table and aliases."""
    langs, aliases = _index()
    if lang:
        lang = lang.strip().replace("-", "_")
        m = re.match(r"^([a-zA-Z]+)[_-]([a-zA-Z0-9]+)$", lang)
        if m:
            lang = m.group(1) + "_" + m.group(2).upper()
        if lang not in langs and lang.lower() in aliases:
            lang = aliases[lang.lower()]
        elif lang not in langs:
            short = lang[:2]
            lang = short if short in langs else aliases.get(short, short + "_" + short.upper())
    if not lang or lang not in langs or not os.path.isdir(os.path.join(LOC_DIR, lang)):
        lang = "en_US"
    return lang


def available_languages():
    """rcube::list_languages(): locale directories with a labels catalogue."""
    return [d for d in sorted(os.listdir(LOC_DIR))
            if os.path.isdir(os.path.join(LOC_DIR, d))
            and os.path.isfile(os.path.join(LOC_DIR, d, "labels.inc"))]


_rev_cache = None


def en_key(english):
    """Map an English UI string back to its catalogue key (first match)."""
    global _rev_cache
    if _rev_cache is None:
        _rev_cache = {}
        for k, v in _load("en_US").items():
            if isinstance(v, str):
                _rev_cache.setdefault(v.strip(), k)
    return _rev_cache.get(english.strip())


def translate_en(text, lang):
    """Translate a hardcoded English UI string through its catalogue key."""
    key = en_key(text)
    return gettext(key, lang) if key else text


# catalogue keys the client-side scripts need (rcube app.env.labels):
# dialog texts and button captions produced in JS, not in templates
JS_LABEL_KEYS = [
    "ok", "cancel", "close", "send", "ignore", "restore", "delete", "discard",
    "sendreceipt", "sendalwaysto", "mdnrequest", "windowopenerror", "insertcontact",
    "listoptionstitle", "save", "download",
    "deletemessagesconfirm", "purgefolderconfirm", "deletefolderconfirm",
    "confirmationtitle",
    "deletecontactconfirm",
    "deleteidentityconfirm", "deleteresponseconfirm",
    "restoremessage", "restoresavedcomposedata", "notsentwarning",
    # mail list refresh + import dialog (ui.js checkmail / mail_import)
    "loading", "import", "importmessages", "selectimportfile",
]


def js_labels(lang):
    """The catalogue slice client JS reads (rcube env.labels)."""
    texts = catalogue(lang)
    return {k: texts.get(k, f"[{k}]") for k in JS_LABEL_KEYS}


def translate_sections(sections, lang):
    """Localize prefs section titles and option labels in place-ish."""
    if lang == "en_US":
        return sections
    for sec in sections.values():
        sec["label"] = translate_en(sec["label"], lang)
        for _cls, _legend, fields in sec["blocks"]:
            for f in fields:
                if f.get("title"):
                    f["title"] = translate_en(f["title"], lang)
                if f.get("options"):
                    f["options"] = [(v, translate_en(t, lang)) for v, t in f["options"]]
        # legends live in the block tuple; rebuild blocks with translated legend
        sec["blocks"] = [(c, translate_en(leg, lang), fs) for c, leg, fs in sec["blocks"]]
    return sections


def gettext(name, lang=None, vars=None, domain=None):
    texts = catalogue(lang or "en_US")
    if domain and f"{domain}.{name}" in texts:
        text = texts[f"{domain}.{name}"]
    elif name in texts:
        text = texts[name]
    else:
        # rcube.php:606 - missing keys show as [name]
        return f"[{name}]"
    if vars:
        for key, value in vars.items():
            text = text.replace("$" + key, str(value))
    return text
