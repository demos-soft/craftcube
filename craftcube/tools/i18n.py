#!/usr/bin/env python3
"""CraftCube translation catalogue maintenance tool (dev-only).

Catalogues are gettext PO files, editable with Poedit:

    app/locale/<lang>/LC_MESSAGES/craftcube.po
    app/locale/craftcube.pot          (template, built from en_US)

msgid space: the reference's *labels* domain keys are bare msgids;
*messages* domain keys carry a ``messages.`` prefix (app/i18n.py resolves
both). Empty msgstr means "untranslated: falls back to en_US at runtime";
fuzzy entries (Poedit's marker after a template update) count as
untranslated too and should be reviewed.

Commands
  verify              key parity vs template + $placeholder consistency
                      (exit 1 on errors; --strict escalates warnings)
  extract             keys referenced in code vs the template;
                      --unused lists the reverse, --write scaffolds
  add KEY             add one msgid to template + en_US text (+ all other
                      languages empty, English fallback until translated)
  remove PATTERN      remove msgid(s) (fnmatch ok) everywhere incl. template
  sync                seed missing keys as empty entries; --prune drops
                      keys the template no longer has; --fill seeds the
                      English text instead of empty
  list                languages with translated/total/fuzzy counts

Examples
  .venv/bin/python tools/i18n.py verify --stats
  .venv/bin/python tools/i18n.py add mykey --domain messages --text "Saved."
  .venv/bin/python tools/i18n.py sync --only-present
  .venv/bin/python tools/i18n.py remove oldkey 'messages.stale*'

Dependencies: polib (a runtime dependency too - app/i18n.py uses it).
Run verify before committing catalogue changes.
"""

import argparse
import fnmatch
import json
import os
import re
import sys

try:
    import polib
except ImportError:
    sys.stderr.write("tools/i18n.py needs polib: pip install polib\n")
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # craftcube/
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LOC_DIR = os.path.join(ROOT, "app", "locale")
PO_SUBPATH = os.path.join("LC_MESSAGES", "craftcube.po")
BASELINE = "en_US"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.]*$")
PLACEHOLDER = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
LANG_DIR_RE = re.compile(r"[A-Za-z]{2,3}(?:_[A-Za-z0-9]{2,4})?$")

HEADER_METADATA = {
    "Project-Id-Version": "CraftCube",
    "MIME-Version": "1.0",
    "Content-Type": "text/plain; charset=UTF-8",
    "Content-Transfer-Encoding": "8bit",
    "Plural-Forms": "nplurals=2; plural=(n != 1);",
    "X-CraftCube-Note": (
        "Edit with Poedit or tools/i18n.py; empty entries fall back to en_US; run tools/i18n.py verify after updating."
    ),
}


# ----------------------------------------------------------------- plumbing
def pot_path():
    return os.path.join(LOC_DIR, "craftcube.pot")


def po_path(lang):
    return os.path.join(LOC_DIR, lang, PO_SUBPATH)


def new_po(lang=None):
    po = polib.POFile()
    po.metadata = dict(HEADER_METADATA)
    if lang:
        po.metadata["Language"] = lang
    return po


def load_po(lang=BASELINE, create=False):
    path = po_path(lang)
    if os.path.isfile(path):
        return polib.pofile(path)
    if create:
        return new_po(lang)
    raise SystemExit(f"no catalogue for {lang}: {path}")


def save_po(lang, po):
    po.metadata.setdefault("Project-Id-Version", "CraftCube")
    po.metadata["Content-Type"] = "text/plain; charset=UTF-8"
    if not po.metadata.get("Language"):
        po.metadata["Language"] = lang
    path = po_path(lang)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    po.save(path)


def load_template():
    """msgid order + key universe: the .pot, or en_US when none exists yet."""
    if os.path.isfile(pot_path()):
        return polib.pofile(pot_path())
    return load_po(lang=BASELINE)


def save_template(po):
    out = new_po()
    for e in po:
        if e.msgid:
            out.append(polib.POEntry(msgid=e.msgid, msgstr=""))
    out.save(pot_path())


def languages(only_present=False):
    out = []
    for d in sorted(os.listdir(LOC_DIR)):
        if not LANG_DIR_RE.fullmatch(d) or not os.path.isdir(os.path.join(LOC_DIR, d)):
            continue
        if os.path.isfile(po_path(d)) or not only_present:
            out.append(d)
    return out


def parse_langs(arg, only_present=False):
    """--lang accepts comma-separated codes; 'all' = every locale dir."""
    if not arg or arg == "all":
        return languages(only_present)
    out = []
    for tok in arg.split(","):
        tok = tok.strip()
        if tok:
            if tok not in languages():
                sys.exit(f"unknown language: {tok} (known: {', '.join(languages())})")
            out.append(tok)
    return out


def _keyset(po):
    return [e.msgid for e in po if e.msgid]


def _textmap(po):
    """msgid -> msgstr, fuzzy entries excluded (untranslated)."""
    return {e.msgid: (e.msgstr or "") for e in po if e.msgid and not e.fuzzy}


def _load_languages_yaml():
    import yaml

    path = os.path.join(LOC_DIR, "languages.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}


# ------------------------------------------------------------------- verify
def cmd_verify(args):
    langs = parse_langs(args.lang, only_present=True)
    template = load_template()
    tkeys = _keyset(template)
    en = _textmap(load_po(lang=BASELINE))
    tset = set(tkeys)
    tph = {k: set(PLACEHOLDER.findall(en.get(k, ""))) for k in tkeys}
    errors = []
    warnings = []
    rows = []
    for lang in langs:
        if lang == BASELINE:
            continue
        po = load_po(lang=lang)
        meta = po.metadata or {}
        ctype = meta.get("Content-Type", "")
        if meta.get("Language") != lang or "UTF-8" not in ctype:
            errors.append(
                f"{lang}: bad header (Language: {meta.get('Language')!r}, "
                f"Content-Type: {ctype!r}) - check Poedit catalog properties"
            )
        kset = set(_keyset(po))
        texts = _textmap(po)
        for k in tkeys:
            if k not in kset:
                errors.append(f"{lang}: missing key '{k}'")
        for k in sorted(kset - tset):
            errors.append(f"{lang}: key not in template: '{k}'")
        for k in sorted(kset & tset):
            v = texts.get(k)
            if not v:
                continue  # empty = untranslated, placeholders N/A
            if tph.get(k) != set(PLACEHOLDER.findall(v)):
                issue = "{}: placeholders differ for '{}' ({}: {}; en_US: {})".format(
                    lang, k, lang, sorted(set(PLACEHOLDER.findall(v))) or "-", sorted(tph.get(k)) or "-"
                )
                # usually inherited upstream drift; --strict escalates
                (errors if args.strict else warnings).append(issue)
            if args.strict and v == en.get(k) and len(v) > 3:
                errors.append(f"{lang}: untranslated (copies English): '{k}'")
        if args.stats:
            have = sum(1 for k in tkeys if texts.get(k))
            fuzzy = sum(1 for e in po if e.fuzzy)
            total = len(tkeys) or 1
            rows.append(
                f"{lang:<8} {100.0 * have / total:5.1f}% ({have}/{total})" + (f" {fuzzy} fuzzy" if fuzzy else "")
            )
    # baseline + template sanity
    empty_en = [k for k in tkeys if not en.get(k)]
    if empty_en:
        errors.append(f"en_US: baseline incomplete for {len(empty_en)} key(s): {empty_en[:5]}")
    if tset != set(en):
        errors.append("template and en_US key sets diverge (fix with: tools/i18n.py sync / add / remove)")
    meta = _load_languages_yaml()
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
        f"verify: OK ({len(langs)} language(s), baseline {BASELINE}, "
        f"template craftcube.pot; {len(warnings)} warning(s))"
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
            if "locale" in dirpath.split(os.sep):
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
        from app import i18n as app_i18n

        key_refs |= set(app_i18n.JS_LABEL_KEYS)
    except ImportError:  # tool must run standalone too
        pass
    return key_refs, literals


def cmd_extract(args):
    key_refs, literals = scan_sources()
    template = load_template()
    tkeys = _keyset(template)
    en = _textmap(load_po(lang=BASELINE))

    def referenced(k):
        if k in key_refs:
            return True
        v = (en.get(k) or "").strip()
        return bool(v) and v in literals

    known = set(tkeys)
    missing = sorted(k for k in key_refs if KEY_RE.match(k) and k not in known and f"messages.{k}" not in known)
    unused = sorted(k for k in tkeys if not referenced(k))

    print(f"referenced keys : {len(tkeys) - len(unused)}")
    print(f"template keys   : {len(tkeys)}")
    print(f"used but missing from template: {len(missing)}")
    for k in missing:
        print("  + " + k)
    if args.unused or args.write:
        print(f"in template, no reference found: {len(unused)}")
        for k in unused[:400]:
            print("  - " + k)
        if len(unused) > 400:
            print(f"  ... ({len(unused)} total)")
    if args.write and missing:
        tpo = load_template()
        for k in missing:
            tpo.append(polib.POEntry(msgid=k, msgstr=""))
        save_template(tpo)
        for lang in languages(only_present=True):
            po = load_po(lang=lang)
            for k in missing:
                po.append(polib.POEntry(msgid=k, msgstr=""))
            save_po(lang, po)
        print(f"scaffolded {len(missing)} key(s); en_US texts must be filled in before verify passes")
    return 0


# ---------------------------------------------------------------------- add
def cmd_add(args):
    msgid = args.key if args.domain in (None, "labels") else f"messages.{args.key}"
    if not KEY_RE.match(msgid):
        sys.exit(f"bad key {msgid!r} (want lowercase letters/digits/_/.): {KEY_RE.pattern}")
    if not args.text:
        sys.exit("add: --text (the en_US baseline text) is required")
    template = load_template()
    if msgid in set(_keyset(template)):
        print(f"skip: {msgid} already in the template")
        return 1
    langs = parse_langs(args.lang)
    template.append(polib.POEntry(msgid=msgid, msgstr=""))
    save_template(template)
    for lang in langs:
        po = load_po(lang=lang, create=True)
        po.append(polib.POEntry(msgid=msgid, msgstr=args.text if lang == BASELINE else ""))
        save_po(lang, po)
    print(f"added '{msgid}' to template + {len(langs)} language(s)")
    return 0


# ------------------------------------------------------------------- remove
def cmd_remove(args):
    langs = parse_langs(args.lang)
    template = load_template()
    removed = 0
    for pat in args.keys:
        hits = [k for k in _keyset(template) if fnmatch.fnmatchcase(k, pat)]
        if not hits:
            print(f"no key matching {pat!r}")
        for k in hits:
            template.remove(template.find(k))
            removed += 1
    save_template(template)
    for lang in langs:
        if lang not in languages(only_present=True):
            continue
        po = load_po(lang=lang)
        for pat in args.keys:
            for k in [k for k in _keyset(po) if fnmatch.fnmatchcase(k, pat)]:
                po.remove(po.find(k))
        save_po(lang, po)
    print(f"removed {removed} msgid(s) from template + {len(langs)} language(s)")
    return 0


# --------------------------------------------------------------------- sync
def cmd_sync(args):
    template = load_template()
    tkeys = _keyset(template)
    en = _textmap(load_po(lang=BASELINE))
    langs = parse_langs(args.lang, only_present=args.only_present)
    seeded = pruned = changed = 0
    for lang in langs:
        exists = lang in languages(only_present=True)
        if not exists and args.only_present:
            continue
        po = load_po(lang=lang, create=True)
        have = {e.msgid: e for e in po if e.msgid}
        rebuilt = []
        for k in tkeys:
            if k in have:
                rebuilt.append(have[k])
            else:
                rebuilt.append(polib.POEntry(msgid=k, msgstr=en.get(k, "") if args.fill else ""))
                seeded += 1
        extra = [k for k in have if k not in set(tkeys)]
        if args.prune:
            pruned += len(extra)
        else:
            rebuilt += [have[k] for k in extra]
        if [e.msgid for e in rebuilt] != [e.msgid for e in po if e.msgid]:
            changed += 1
            po[:] = rebuilt
            save_po(lang, po)
    print(f"sync: +{seeded} row(s) seeded, -{pruned} pruned, {changed} language file(s) rewritten")
    if seeded:
        print("next: translate the empty rows (Poedit), then: tools/i18n.py verify")
    return 0


# --------------------------------------------------------------------- list
def cmd_list(args):
    template = load_template()
    tkeys = _keyset(template)
    for lang in languages(only_present=True):
        po = load_po(lang=lang)
        texts = _textmap(po)
        done = sum(1 for k in tkeys if texts.get(k))
        fuzzy = sum(1 for e in po if e.fuzzy)
        line = f"{lang:<8} {done:5}/{len(tkeys)} translated"
        if fuzzy:
            line += f" {fuzzy} fuzzy"
        print(line)
    return 0


# --------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="tools/i18n.py",
        description="CraftCube translation catalogue maintenance (PO/POT: verify/extract/add/remove/sync/list)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify", help="key/placeholder parity vs template")
    p.add_argument("--lang", default="all")
    p.add_argument("--strict", action="store_true", help="escalate warnings (placeholders, English copies) to errors")
    p.add_argument("--stats", action="store_true", help="coverage table")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("extract", help="keys referenced in code vs template")
    p.add_argument("--write", action="store_true", help="scaffold used-but-missing keys")
    p.add_argument("--unused", action="store_true", help="list template keys with no reference")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("add", help="add one msgid everywhere")
    p.add_argument("key")
    p.add_argument("--domain", choices=("labels", "messages"), default="labels")
    p.add_argument("--lang", default="all")
    p.add_argument("--text", default=None, help="en_US baseline text (required)")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("remove", help="remove msgid(s), globs allowed")
    p.add_argument("keys", nargs="+")
    p.add_argument("--lang", default="all")
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("sync", help="add template keys missing in languages")
    p.add_argument("--lang", default="all")
    p.add_argument("--fill", action="store_true", help="seed the English text instead of empty")
    p.add_argument("--prune", action="store_true", help="also delete keys unknown to the template")
    p.add_argument("--only-present", action="store_true", help="skip languages without catalogue files")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("list", help="languages with translated counts")
    p.set_defaults(fn=cmd_list)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
