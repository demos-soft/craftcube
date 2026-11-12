# CraftCube translations (gettext PO/POT catalogues)

PHP is gone and the intermediate YAML step is gone too: catalogues are
standard **gettext PO files** — no PHP, no compiled `.mo`, editable with
any PO editor (**Poedit** recommended). Runtime is pure Python (`polib`)
and loads the `.po` sources directly. Texts still originate from the
Roundcube reference localization (GPL-3.0+, see `app/locale/COPYING`).

## Layout

    app/locale/craftcube.pot                    template (generated from en_US)
    app/locale/<lang>/LC_MESSAGES/craftcube.po  one catalogue per language
    app/locale/languages.yaml                   language index (names + aliases)
    tools/i18n.py                               dev tool: verify / extract / add / remove / sync / list

`en_US` is the baseline holding the master English texts; every other
language carries the same msgid set. An **empty `msgstr` means "not
translated yet"** and falls back to the en_US text at runtime, so partial
translations always render a complete UI. **Fuzzy entries count as
untranslated** too (Poedit marks entries fuzzy when the English changed —
a translator reviews and un-marks them; Poedit: "Confirm"/Ctrl+Enter).

Variables keep the legacy PHP style: `$user`, `$count` ... substituted by
`gettext(key, lang, vars={...})`; templates use `{{ _('key') }}` and the
`|lc` filter for English literals. A missing key renders as `[keyname]`.

### One file, two domains

The reference kept `labels` and `messages` in separate files. CraftCube
uses one PO file per language and marks the messages domain with a
**`messages.` msgid prefix**:

| domain   | msgid example    | used by                                 |
|----------|------------------|-----------------------------------------|
| labels   | `compose`        | menus, buttons, fields (`gettext`, `|lc`) |
| messages | `messages.saved` | notices, errors, confirmations          |

In Poedit these are just ordinary (prefixed) entries; nothing extra to
configure. Keys are lowercase `[a-z0-9_.]`; keep the reference's key
names where the string came from it.

The tool needs `polib` + `PyYAML` — both are runtime requirements, so the
app venv is enough: `.venv/bin/python tools/i18n.py ...`.

## Edit with Poedit

1. Open `app/locale/de_DE/LC_MESSAGES/craftcube.po` (catalogue properties
   are preset: UTF-8, `Language: de_DE`).
2. When the English changed, use *Update from the template* against
   `app/locale/craftcube.pot`: new strings appear empty, changed ones go
   fuzzy.
3. Translate, save, gate before committing:

       .venv/bin/python tools/i18n.py verify

Any gettext-aware editor works too (Lokalize, Weblate, VS Code i18n
extensions, plain text) — just keep UTF-8 and run `verify` afterwards.

## Add a translation string

1. Add the msgid everywhere at once (template + en_US text + empty rows
   in the other 87 languages):

       .venv/bin/python tools/i18n.py add mykey --domain labels \
           --text "My new label"
       # message-domain keys are qualified: messages.mykey
       .venv/bin/python tools/i18n.py add mywarning --domain messages \
           --text "Something went wrong: $msg"

2. Or let the extractor scaffold it: `tools/i18n.py extract --write`
   finds keys referenced in code/templates/JS but missing from the
   template (fill the en_US text afterwards). Code references look like
   `gettext("mykey")`, `_("mykey")`, Jinja `{{ gettext('mykey') }}`.

3. Gate:

       .venv/bin/python tools/i18n.py verify

   `verify` fails on msgids missing in a language / unknown to the
   template and on bad headers, and flags `$placeholder` drift
   (warnings; `--strict` escalates them plus rows that just copy
   English). Use the same `$vars` as the English text.

To drop a string again (after removing its code references):

    .venv/bin/python tools/i18n.py remove mykey 'messages.mywarning*'

`extract --unused` lists template keys with no reference; `sync --prune`
removes them from every language.

## Add a language

1. Register it in `app/locale/languages.yaml`:

       names:
         xx_YY: Language Name (Native script)
       aliases:
         xx: xx_YY        # so a bare Accept-Language 'xx' resolves

   Naming follows the reference: ISO 639-1 + ISO 3166-1 Alpha-2
   (`pt_BR`), display format `English (Native)`.

2. Create the catalogue — the tool writes the file with correct headers
   and every template key, empty (= full English fallback):

       .venv/bin/python tools/i18n.py sync --lang xx_YY

3. Translate (Poedit or otherwise), then gate:

       .venv/bin/python tools/i18n.py verify --lang xx_YY
       .venv/bin/python tools/i18n.py verify --stats   # coverage table

The settings language picker lists every catalogue directory, so nothing
else is required; `i18n.language_prop()` normalises `xx`, `xx-YY`, ...
through languages.yaml (unknown codes fall back to en_US).

## Importing from upstream Roundcube

Copy texts from `roundcubemail/program/localization/<lang>/{labels,
messages}.inc` into the matching msgstrs (prefix messages-domain keys
with `messages.`), seed anything missing with `sync`, and gate with
`verify`. Do not re-add `.inc` files —
`tests/test_i18n.py::test_no_php_files_ship_in_locale` enforces a PHP-free
tree, and `test_po_tree_is_gettext_standard` enforces the gettext layout.

## Regenerating the whole tree

`app/i18n.py`'s `JS_LABEL_KEYS` list, `tools/extract_patterns.json`, and
`tools/i18n.py sync` are the maintenance surface. A full template
refresh is just: template and en_US share the key universe (verify
enforces it), so edit en_US + run `sync --only-present`, then `verify`.
