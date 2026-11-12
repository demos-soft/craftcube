#!/usr/bin/env python3
"""CraftCube translation catalogue maintenance tool (dev-only).

Catalogues are YAML: app/locale/<lang>/labels.yaml and messages.yaml,
plus app/locale/languages.yaml (code -> display name, aliases). en_US is
the baseline; other languages layer over it at runtime, so an empty or
missing value falls back to English.

Commands
  verify    key + $placeholder parity of every language vs en_US (CI gate)
  extract   keys referenced in code/templates/JS vs the en_US baseline
            (--write scaffolds used-but-missing keys into en_US)
  add       add one or more keys to any language(s)
  remove    delete key(s) from language(s)
  sync      add en_US keys missing in other languages (--fill seeds the
            English text for translators; --prune drops keys unknown to en_US)
  list      keys of a language/domain (optional *glob* filter)

Examples
  .venv/bin/python tools/i18n.py verify
  .venv/bin/python tools/i18n.py verify --stats
  .venv/bin/python tools/i18n.py extract --unused
  .venv/bin/python tools/i18n.py extract --write
  .venv/bin/python tools/i18n.py add mykey --domain messages --text "Saved."
  .venv/bin/python tools/i18n.py sync --fill            # stage new rows
  .venv/bin/python tools/i18n.py sync --prune           # drop stale rows
  .venv/bin/python tools/i18n.py remove oldkey --lang de_DE

Only en_US entries need real text; translations left as '' fall back to
English at runtime. Run verify before committing catalogue changes.

Dependencies: ruamel.yaml (dev venv: pip install ruamel.yaml). The app
itself only needs PyYAML.
"""

import argparse
import fnmatch
import json
import os
import re
import sys

import yaml  # PyYAML: same loader the app uses, ground truth for quoting

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap
except ImportError:
    sys.stderr.write("tools/i18n.py needs ruamel.yaml: pip install ruamel.yaml\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # craftcube/
LOC = os.path.join(ROOT, "app", "locale")
DOMAINS = ("labels", "messages")
BASELINE = "en_US"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.]*$")
PLACEHOLDER = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
LANG_DIR_RE = re.compile(r"[A-Za-z]{2,3}(?:_[A-Za-z0-9]{2,4})?$")

yaml_rt = YAML(typ="rt")
yaml_rt.width = 10_000_000  # never wrap: one long line beats folded scalars
yaml_rt.allow_unicode = True
yaml_rt.indent(mapping=2, sequence=4, offset=2)

HEADER_TMPL = [
    "# CraftCube catalogue {dom} for {lang}. Keep languages in sync with",
    "# tools/i18n.py (verify / sync / add / remove). Empty values fall back",
    "# to the en_US baseline at runtime.",
]


# ----------------------------------------------------------------- plumbing
def cat_path(lang, dom):
    return os.path.join(LOC, lang, dom + ".yaml")


def load_cat(lang, dom):
    path = cat_path(lang, dom)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = yaml_rt.load(fh)
    if data is None:
        data = CommentedMap()
    # keep the file header alive across round-trips
    data.yaml_set_start_comment(chr(10).join(ln.format(dom=dom, lang=lang) for ln in HEADER_TMPL))
    return data


def _needs_quotes(text):
    """True when yaml.safe_load would NOT give this string back as a str
    (sexagesimal '16:9', YAML 1.1 bools 'No'/'on', ints, null ...)."""
    if text == "" or text.strip() != text:
        return True  # empty needs quotes; unquoted YAML strips padding
    try:
        return not isinstance(yaml.safe_load(text), str)
    except Exception:
        return True


def _quote_strings(data):
    from ruamel.yaml.scalarstring import SingleQuotedScalarString

    for k, v in list(data.items()):
        v = str(v)
        data[k] = SingleQuotedScalarString(v) if _needs_quotes(v) else v
    return data


def save_cat(lang, dom, data):
    path = cat_path(lang, dom)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not isinstance(data, CommentedMap):
        data = CommentedMap(data)
    _quote_strings(data)
    with open(path, "w", encoding="utf-8") as fh:
        yaml_rt.dump(data, fh)


def languages():
    return sorted(d for d in os.listdir(LOC) if LANG_DIR_RE.fullmatch(d) and os.path.isdir(os.path.join(LOC, d)))


def load_languages_yaml():
    with open(os.path.join(LOC, "languages.yaml"), encoding="utf-8") as fh:
        return yaml_rt.load(fh)


def parse_langs(arg):
    """--lang accepts comma-separated codes; 'all' = every locale dir."""
    if not arg or arg == "all":
        return languages()
    out = []
    for tok in arg.split(","):
        tok = tok.strip()
        if tok:
            if tok not in languages():
                sys.exit("unknown language: {} (known: {})".format(tok, ", ".join(languages())))
            out.append(tok)
    return out


def parse_domains(arg):
    return DOMAINS if arg == "both" else (arg,)


def check_key(key):
    if not KEY_RE.match(key):
        sys.exit(f"bad key {key!r} (want lowercase letters/digits/_/.): {KEY_RE.pattern}")


def dom_of_key(key):
    """messages.* refers to the messages domain; bare keys are labels."""
    if key.startswith("messages."):
        return "messages", key[len("messages.") :]
    return "labels", key


# ------------------------------------------------------------------- verify
def cmd_verify(args):
    langs = parse_langs(args.lang)
    baseline = {d: (load_cat(BASELINE, d) or {}) for d in DOMAINS}
    errors = []
    warnings = []
    rows = []
    for lang in langs:
        stats = {}
        for dom in DOMAINS:
            base = baseline[dom]
            cat = load_cat(lang, dom)
            if cat is None:
                if lang != BASELINE:
                    stats[dom] = (0, len(base))
                continue
            for k, v in cat.items():
                if not isinstance(v, str):
                    errors.append(
                        f"{lang}/{dom}: value for '{k}' is {type(v).__name__}, not a string (quote it in the YAML)"
                    )
            keys = set(cat)
            bkeys = set(base)
            missing = bkeys - keys
            extra = keys - bkeys
            if lang != BASELINE:
                for k in sorted(missing):
                    errors.append(f"{lang}/{dom}: missing key '{k}'")
                for k in sorted(extra):
                    errors.append(f"{lang}/{dom}: key not in {BASELINE}: '{k}'")
            for k in sorted(keys & bkeys):
                if lang != BASELINE and not str(cat[k]):
                    continue  # empty = untranslated, placeholders N/A
                want = set(PLACEHOLDER.findall(str(base[k])))
                got = set(PLACEHOLDER.findall(str(cat[k])))
                if want != got:
                    issue = "{}/{}: placeholders differ for '{}' (en_US: {}; {}: {})".format(
                        lang, dom, k, sorted(want) or "-", lang, sorted(got) or "-"
                    )
                    # usually inherited upstream drift; --strict escalates
                    (errors if args.strict else warnings).append(issue)
                if (
                    args.strict
                    and lang != BASELINE
                    and cat[k]
                    and str(cat[k]) == str(base[k])
                    and len(str(base[k])) > 3
                ):
                    errors.append(f"{lang}/{dom}: untranslated (copies English): '{k}'")
            stats[dom] = (len(keys & bkeys), len(base))
        if args.stats and lang != BASELINE:
            have = sum(v[0] for v in stats.values())
            total = sum(v[1] for v in stats.values()) or 1
            rows.append(f"{lang:<8} {100.0 * have / total:5.1f}% ({have}/{total})")
    # languages.yaml sanity
    meta = load_languages_yaml()
    named = set(meta.get("names") or {})
    for lang in langs:
        if lang not in named:
            errors.append(f"languages.yaml: no display name for '{lang}'")
    for code in sorted(named):
        if code not in languages():
            errors.append(f"languages.yaml: '{code}' has no catalogue directory")

    for line in rows:
        print(line)
    for w in warnings:
        print("WARN  " + w)
    if errors:
        for e in errors:
            print("ERROR " + e)
        print(f"verify: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(
        f"verify: OK ({len(langs)} language(s), baseline {BASELINE}, domains "
        f"{'/'.join(DOMAINS)}; {len(warnings)} warning(s)"
    )
    return 0


# ------------------------------------------------------------------ extract
SOURCE_GLOBS = [
    ("app", (".py", ".html", ".js")),
    ("plugins", (".py",)),
]

JS_HELPER = re.compile(r"\bcc_get_label\s*\(\s*['\"]([^'\"]+)['\"]")


def _load_patterns():
    with open(os.path.join(HERE, "extract_patterns.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _literal_keys(kwarg_text, py_lit):
    """First string literal of a gettext(...) argument list = the key."""
    m = py_lit.search(kwarg_text or "")
    return m.group(2) if m else None


def scan_sources():
    """Returns (key_refs, literals).

    key_refs  strings referenced where a catalogue KEY is expected:
              gettext('k', ...), add_label('k'), cc_get_label('k').
    literals  every quoted literal in the sources: an English UI literal
              reverse-maps to its key via translate_en()/`|lc`, so a
              catalogue key whose en_US *value* equals one of these is used.
    """
    pats = _load_patterns()
    gettext_kwarg = re.compile(pats["gettext_kwarg"])
    py_lit = re.compile(pats["python_literal"])
    add_label = re.compile(pats["add_label_call"])

    key_refs = set()
    literals = set()
    for subdir, exts in SOURCE_GLOBS:
        for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, subdir)):
            if "__pycache__" in dirpath or "/." in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith(exts):
                    continue
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    text = fh.read()
                for m in gettext_kwarg.finditer(text):
                    k = _literal_keys(m.group(1), py_lit)
                    if k:
                        key_refs.add(k)
                for m in add_label.finditer(text):
                    for _q, lit in py_lit.findall(m.group(1)):
                        key_refs.add(lit)
                for k in JS_HELPER.findall(text):
                    key_refs.add(k)
                for _q, lit in py_lit.findall(text):
                    literals.add(lit)
    # the app's JS label list (if importable without a full app boot)
    try:
        sys.path.insert(0, ROOT)
        from app import i18n as app_i18n

        key_refs |= set(app_i18n.JS_LABEL_KEYS)
    except ImportError:  # tool must run standalone too
        pass
    return key_refs, literals


def cmd_extract(args):
    key_refs, literals = scan_sources()
    baseline = {d: (load_cat(BASELINE, d) or CommentedMap()) for d in DOMAINS}
    en_by_domain = {"labels": baseline["labels"], "messages": baseline["messages"]}

    def referenced(dom, k):
        full = dom + "." + k if dom == "messages" else k
        if full in key_refs or (dom == "labels" and k in key_refs):
            return True
        v = str(en_by_domain[dom].get(k, ""))
        return bool(v) and (v in literals or v.strip() in literals)

    cat_keys = {("labels", k) for k in baseline["labels"]}
    cat_keys |= {("messages", k) for k in baseline["messages"]}

    # used-but-missing: bare key references unknown to both domains
    known = {k for _d, k in cat_keys} | {d + "." + k for d, k in cat_keys}
    missing = sorted(k for k in key_refs if KEY_RE.match(k) and k not in known)
    unused = sorted(d + "." + k if d == "messages" else k for d, k in cat_keys if not referenced(d, k))

    print(f"referenced keys : {len(cat_keys) - len(unused)}")
    print(f"baseline keys   : {len(cat_keys)}")
    print(f"used but missing from {BASELINE}: {len(missing)}")
    for k in missing:
        print("  + " + k)
    if args.unused or args.write:
        print(f"in baseline, no reference found: {len(unused)}")
        for k in unused[:400]:
            print("  - " + k)
        if len(unused) > 400:
            print(f"  ... ({len(unused)} total)")
    if args.write and missing:
        data = baseline["labels"]
        for k in missing:
            data[k] = ""
        save_cat(BASELINE, "labels", data)
        for k in missing:
            print(f"added labels.{k} (empty; fill in the English text)")
    return 0


# ---------------------------------------------------------------------- add
def cmd_add(args):
    langs = parse_langs(args.lang)
    doms = parse_domains(args.domain)
    added = 0
    for raw in args.keys:
        _key_dom, key = dom_of_key(raw)
        check_key(key)
        for dom in doms:
            if raw.startswith("messages.") and dom == "labels":
                continue  # explicit domain prefix wins over 'both'
            for lang in langs:
                data = load_cat(lang, dom) or CommentedMap()
                if lang == BASELINE:
                    value = args.text if args.text is not None else ""
                else:
                    value = args.text if (args.text is not None and args.fill_en) else ""
                if key in data:
                    if not args.force:
                        print(f"skip {lang}/{dom}.{key} (exists; --force to overwrite)")
                        continue
                    data[key] = value
                elif args.after and args.after in data:
                    items = list(data.items())
                    idx = next(i for i, (k, _v) in enumerate(items) if k == args.after)
                    data.insert(idx + 1, key, value)
                else:
                    data[key] = value
                save_cat(lang, dom, data)
                added += 1
    joined = ", ".join(langs)
    print(f"added/updated {added} entr{'y' if added == 1 else 'ies'} in {joined}")
    return 0


# ------------------------------------------------------------------- remove
def cmd_remove(args):
    langs = parse_langs(args.lang)
    removed = 0
    for raw in args.keys:
        key = dom_of_key(raw)[1]
        matched_any = False
        for lang in langs:
            for dom in DOMAINS:
                if raw.startswith("messages.") and dom != "messages":
                    continue
                data = load_cat(lang, dom)
                if data is None:
                    continue
                hits = [k for k in list(data) if fnmatch.fnmatchcase(k, key)]
                if not hits:
                    continue
                matched_any = True
                for k in hits:
                    del data[k]
                    removed += 1
                    print(f"- {lang}/{dom}.{k}")
                save_cat(lang, dom, data)
        if not matched_any:
            print(f"no key matching {raw!r} in {', '.join(langs)}")
    print(f"removed {removed} entr{'y' if removed == 1 else 'ies'}")
    return 0


# --------------------------------------------------------------------- sync
def cmd_sync(args):
    langs = [lg for lg in parse_langs(args.lang) if lg != BASELINE]
    base = {d: (load_cat(BASELINE, d) or CommentedMap()) for d in DOMAINS}
    added = pruned = 0
    for lang in langs:
        for dom in DOMAINS:
            data = load_cat(lang, dom)
            if data is None:
                if args.only_present:
                    continue
                data = CommentedMap()
            missing = [k for k in base[dom] if k not in data]
            for k in missing:
                seed = str(base[dom][k]) if args.fill else ""
                data[k] = seed
                added += 1
            extra = [k for k in list(data) if k not in base[dom]]
            if args.prune:
                for k in extra:
                    del data[k]
                    pruned += 1
            if missing or (args.prune and extra):
                save_cat(lang, dom, data)
    print(f"sync: +{added} row(s) seeded, -{pruned} pruned, across {len(langs)} language(s)")
    if added:
        print("next: translate the empty rows, then run: tools/i18n.py verify")
    return 0


# --------------------------------------------------------------------- list
def cmd_list(args):
    for lang in parse_langs(args.lang):
        for dom in parse_domains(args.domain):
            data = load_cat(lang, dom) or {}
            for k in data:
                if not args.pattern or fnmatch.fnmatchcase(k, args.pattern):
                    v = str(data[k])
                    print(f"{lang}/{dom}.{k} = {v if not args.values else repr(v)}")


# --------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="tools/i18n.py",
        description="CraftCube translation catalogue maintenance (verify/extract/add/remove/sync/list)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify", help="key/placeholder parity vs en_US")
    p.add_argument("--lang", default="all")
    p.add_argument("--strict", action="store_true", help="also flag translations identical to the English text")
    p.add_argument("--stats", action="store_true", help="coverage table")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("extract", help="keys referenced in code vs baseline")
    p.add_argument("--write", action="store_true", help="scaffold used-but-missing keys into en_US labels")
    p.add_argument("--unused", action="store_true", help="list baseline keys with no reference")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("add", help="add key(s)")
    p.add_argument("keys", nargs="+")
    p.add_argument("--domain", choices=("labels", "messages", "both"), default="labels")
    p.add_argument("--lang", default=BASELINE)
    p.add_argument("--text", default=None, help="English text (en_US)")
    p.add_argument("--after", default=None, help="insert after this existing key")
    p.add_argument("--force", action="store_true", help="overwrite existing")
    p.add_argument("--fill-en", action="store_true", help="also seed the English text into other languages")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("remove", help="remove key(s), globs allowed")
    p.add_argument("keys", nargs="+")
    p.add_argument("--lang", default="all")
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("sync", help="add baseline keys missing in other languages")
    p.add_argument("--lang", default="all")
    p.add_argument("--fill", action="store_true", help="seed the English text instead of an empty value")
    p.add_argument("--prune", action="store_true", help="also delete keys unknown to the baseline")
    p.add_argument("--only-present", action="store_true", help="skip languages without catalogue files")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("list", help="list keys")
    p.add_argument("pattern", nargs="?", default=None)
    p.add_argument("--lang", default=BASELINE)
    p.add_argument("--domain", choices=("labels", "messages", "both"), default="both")
    p.add_argument("--values", action="store_true")
    p.set_defaults(fn=cmd_list)

    args = ap.parse_args(argv)
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
