"""CraftCube localization: gettext PO/POT catalogues, no PHP.

Each language is a single po file, Poedit-friendly:

    app/locale/<lang>/LC_MESSAGES/craftcube.po   (translated)
    app/locale/craftcube.pot                     (template, empty msgstrs)

msgid space: the reference's *labels* domain keys are bare; *messages*
domain keys carry a ``messages.`` prefix (matching the flat catalogue the
old PHP loader produced, so domain lookups and the reverse English->key
index behave identically). languages.yaml next to the template is the
language index (names + aliases, formerly index.inc).

Like rcube::load_language() (rcube.php:685) the texts start from the
complete en_US catalogue and layer the user's language on top: entries
with an empty msgstr are untranslated and fall back to English, and
fuzzy-flagged entries (Poedit marks them after a template update) count
as untranslated too. gettext() also does the $var substitution
(rcube.php:609-620) and the '[name]' marker for unknown keys.

Keep the languages in sync with the dev tool:

    .venv/bin/python tools/i18n.py verify        # key + $placeholder parity
    .venv/bin/python tools/i18n.py extract       # keys used in code/templates
    .venv/bin/python tools/i18n.py add/remove/sync/list
"""

import os
import re

import polib

LOC_DIR = os.path.join(os.path.dirname(__file__), "locale")

PO_SUBPATH = os.path.join("LC_MESSAGES", "craftcube.po")
POT_PATH = os.path.join(LOC_DIR, "craftcube.pot")

# parsed catalogue cache: lang -> {msgid: msgstr}; fuzzy-flag index
_cache = {}
_fuzzy_index = {}
# languages.yaml cache
_lang_meta = None

_NAME_RE = re.compile(r"[A-Za-z]{2,3}(?:_[A-Za-z0-9]{2,4})?$")
_PLACEHOLDER = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def po_path(lang):
    return os.path.join(LOC_DIR, lang, PO_SUBPATH)


def clear_cache():
    """Drop parsed caches (tests and tools patching LOC_DIR)."""
    global _lang_meta, _rev_cache
    _cache.clear()
    _fuzzy_index.clear()
    _lang_meta = None
    _rev_cache = None


def load_po(lang):
    """Flat {msgid: msgstr} for a language (fuzzy rows kept: the overlay,
    not the reader, decides they are untranslated). Empty dict if absent."""
    if lang not in _cache:
        texts = {}
        path = po_path(lang)
        if os.path.isfile(path):
            for entry in polib.pofile(path):
                if not entry.msgid:
                    continue  # header
                texts[entry.msgid] = entry.msgstr or ""
        _cache[lang] = texts
    return _cache[lang]


def _fuzzy(lang):
    """msgids flagged fuzzy in a language (Poedit marks those
    after a template update: translation needs review -> untranslated)."""
    if lang not in _fuzzy_index:
        flags = {}
        path = po_path(lang)
        if os.path.isfile(path):
            for entry in polib.pofile(path):
                if entry.msgid and entry.fuzzy:
                    flags[entry.msgid] = True
        _fuzzy_index[lang] = flags
    return _fuzzy_index[lang]


def catalogue(lang):
    """en_US texts with the user language layered on top (rcube.php:691-708).

    Empty msgstrs (rows seeded by tools/i18n.py sync, not yet translated)
    and fuzzy entries are skipped, so they fall back to the English
    baseline.
    """
    texts = {k: v for k, v in load_po("en_US").items() if v}
    norm = language_prop(lang)
    if norm not in ("en", "en_US"):
        fuzzy = _fuzzy(norm)
        texts.update({k: v for k, v in load_po(norm).items() if v and k not in fuzzy})
    return texts


def _index():
    """names / aliases from languages.yaml ($rcube_languages + aliases of the
    vendored index.inc, rcube.php:832-834)."""
    global _lang_meta
    if _lang_meta is None:
        import yaml

        names, aliases = {}, {}
        try:
            with open(os.path.join(LOC_DIR, "languages.yaml"), encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            data = {}
        if isinstance(data.get("names"), dict):
            names = {str(k): str(v) for k, v in data["names"].items()}
        if isinstance(data.get("aliases"), dict):
            aliases = {str(k): str(v) for k, v in data["aliases"].items()}
        _lang_meta = (set(names), aliases, names)
    return _lang_meta


def language_names():
    """code -> display name (the reference's index.inc table)."""
    return _index()[2]


def language_prop(lang):
    """rcube::language_prop() (rcube.php:818): normalize a locale code
    through the reference's language table and aliases."""
    langs, aliases, _names = _index()
    if lang:
        lang = lang.strip().replace("-", "_")
        m = re.match(r"^([A-Za-z]+)[_-]([A-Za-z0-9]+)$", lang)
        if m:
            lang = m.group(1) + "_" + m.group(2).upper()
        if lang not in langs and lang.lower() in aliases:
            lang = aliases[lang.lower()]
        elif lang not in langs:
            short = lang[:2]
            lang = short if short in langs else aliases.get(short, short + "_" + short.upper())
    if not lang or lang not in langs or not os.path.isfile(po_path(lang)):
        lang = "en_US"
    return lang


def available_languages():
    """rcube::list_languages(): locale directories with a po catalogue."""
    return [d for d in sorted(os.listdir(LOC_DIR)) if _NAME_RE.fullmatch(d) and os.path.isfile(po_path(d))]


_rev_cache = None


def en_key(english):
    """Map an English UI string back to its catalogue key (first match)."""
    global _rev_cache
    if _rev_cache is None:
        _rev_cache = {}
        for k, v in load_po("en_US").items():
            if isinstance(v, str) and v:
                _rev_cache.setdefault(v.strip(), k)
    return _rev_cache.get(english.strip())


def translate_en(text, lang):
    """Translate a hardcoded English UI string through its catalogue key."""
    key = en_key(text)
    return gettext(key, lang) if key else text


# catalogue keys the client-side scripts need (rcube app.env.labels):
# dialog texts and button captions produced in JS, not in templates
JS_LABEL_KEYS = [
    "ok",
    "cancel",
    "close",
    "send",
    "ignore",
    "restore",
    "delete",
    "discard",
    "sendreceipt",
    "sendalwaysto",
    "mdnrequest",
    "windowopenerror",
    "insertcontact",
    "listoptionstitle",
    "save",
    "download",
    "deletemessagesconfirm",
    "purgefolderconfirm",
    "deletefolderconfirm",
    "confirmationtitle",
    "deletecontactconfirm",
    "deleteidentityconfirm",
    "deleteresponseconfirm",
    "restoremessage",
    "restoresavedcomposedata",
    "notsentwarning",
    # mail list refresh + import dialog (ui.js checkmail / mail_import)
    "loading",
    "import",
    "importmessages",
    "selectimportfile",
    # GoogieSpell plain-text checker (googiespell.js lang_*)
    "checking",
    "checkspelling",
    "resumeediting",
    "revertto",
    "nospellerrors",
    "addtodict",
    # draft save feedback (app.js save_draft -> rcmail.response_display)
    "messagesaved",
]


def js_labels(lang):
    """The catalogue slice client JS reads (rcube env.labels).

    Dialog texts live in the messages domain (Roundcube resolves bare
    label lookups against messages too, rcube::gettext), so a key is
    taken from the bare msgid first, then messages.<key>.
    """
    texts = catalogue(lang)
    out = {}
    for k in JS_LABEL_KEYS:
        v = texts.get(k) or texts.get(f"messages.{k}") or ""
        out[k] = v if v else f"[{k}]"
    return out


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
