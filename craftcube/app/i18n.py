"""CraftCube localization: YAML catalogues, no PHP.

The catalogues under app/locale/<lang>/ are plain YAML files — one per
domain (labels.yaml, messages.yaml) — converted 1:1 from the reference
Roundcube *.inc files (Roundcube, GPL-3.0+; the original English texts
remain the upstream work). languages.yaml next to them is the language
index (names + aliases, formerly index.inc).

Like rcube::load_language() (rcube.php:685) the texts start from the
complete en_US catalogue and layer the user's language on top, so
missing keys fall back to English; gettext() also does the $var
substitution (rcube.php:609-620) and the '[name]' marker for unknown
keys.

Keep the languages in sync with the dev tool:

    .venv/bin/python tools/i18n.py verify        # key + $placeholder parity
    .venv/bin/python tools/i18n.py extract       # keys used in code/templates
    .venv/bin/python tools/i18n.py add/remove/sync
"""

import os
import re

import yaml

LOC_DIR = os.path.join(os.path.dirname(__file__), "locale")

DOMAINS = ("labels", "messages")

# parsed catalogue cache: lang -> {key: text}
_cache = {}
# parsed YAML domain cache: (lang, domain) -> {key: text}
_domain_cache = {}
# languages.yaml cache
_lang_meta = None

_NAME_RE = re.compile(r"[A-Za-z]{2,3}(?:_[A-Za-z0-9]{2,4})?$")
_PLACEHOLDER = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _load_yaml(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if v is None:
            out[str(k)] = ""  # empty row: untranslated
        elif isinstance(v, str):
            out[str(k)] = v
        else:  # mis-typed scalar (int/bool/date)
            out[str(k)] = str(v)
    return out


def _load_domain(lang, domain):
    key = (lang, domain)
    if key not in _domain_cache:
        _domain_cache[key] = _load_yaml(os.path.join(LOC_DIR, lang, f"{domain}.yaml"))
    return _domain_cache[key]


def _load(lang):
    """Flat catalogue for a language: labels plain, messages prefixed.

    Same shape the old PHP-parsed catalogues had, so domain lookups and
    the reverse English->key index keep working unchanged.
    """
    if lang not in _cache:
        texts = dict(_load_domain(lang, "labels"))
        for k, v in _load_domain(lang, "messages").items():
            texts[f"messages.{k}"] = v
        _cache[lang] = texts
    return _cache[lang]


def catalogue(lang):
    """en_US texts with the user language layered on top (rcube.php:691-708).

    Empty values (rows seeded by tools/i18n.py sync, not yet translated)
    are skipped, so they fall back to the English baseline.
    """
    texts = dict(_load("en_US"))
    norm = language_prop(lang)
    if norm not in ("en", "en_US"):
        texts.update({k: v for k, v in _load(norm).items() if v})
    return texts


def _languages_yaml_path():
    return os.path.join(LOC_DIR, "languages.yaml")


def _index():
    """names / aliases from languages.yaml ($rcube_languages + aliases of the
    vendored index.inc, rcube.php:832-834)."""
    global _lang_meta
    if _lang_meta is None:
        names, aliases = {}, {}
        try:
            with open(_languages_yaml_path(), encoding="utf-8") as fh:
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
    if not lang or lang not in langs or not os.path.isdir(os.path.join(LOC_DIR, lang)):
        lang = "en_US"
    return lang


def available_languages():
    """rcube::list_languages(): locale directories with a labels catalogue."""
    return [
        d
        for d in sorted(os.listdir(LOC_DIR))
        if _NAME_RE.fullmatch(d) and os.path.isfile(os.path.join(LOC_DIR, d, "labels.yaml"))
    ]


_rev_cache = None


def en_key(english):
    """Map an English UI string back to its catalogue key (first match)."""
    global _rev_cache
    if _rev_cache is None:
        _rev_cache = {}
        for k, v in _load("en_US").items():
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
    taken from labels first, then messages.<key>.
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
