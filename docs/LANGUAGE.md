# CraftCube translations (YAML catalogues)

PHP is gone: the Roundcube `.inc` catalogues were converted 1:1 to YAML
and nothing parses PHP at runtime anymore. Texts still originate from
the Roundcube reference localization (GPL-3.0+, see `app/locale/COPYING`).

## Layout

    app/locale/languages.yaml        language index (names + aliases)
    app/locale/<lang>/labels.yaml    UI labels   (menus, buttons, fields)
    app/locale/<lang>/messages.yaml  messages    (errors, confirmations, notices)
    tools/i18n.py                    dev tool: verify / extract / add / remove / sync / list

`en_US` is the baseline. At runtime the user's language is layered over
en_US (`app/i18n.py: catalogue()`); an **empty value means "not
translated yet"** and falls back to English, so partial translations are
always safe. Variables are PHP-style: `$user`, `$count` ... substituted
by `gettext(key, lang, vars={...})`; templates use `{{ _('key') }}` and
the `|lc` filter for English literals.

Dev tool dependencies (venv only, the app itself just needs PyYAML):

    pip install -r requirements-dev.txt

## Add a translation string

1. Add the English text to the baseline:

       .venv/bin/python tools/i18n.py add mykey --domain labels \
           --text "My new label"
       # message-domain keys are qualified: messages.mykey
       .venv/bin/python tools/i18n.py add messages.mywarning \
           --domain messages --text "Something went wrong: $msg"

   (or edit `app/locale/en_US/labels.yaml` / `messages.yaml` by hand -
   keys are sorted topically, match the neighbours).

2. Seed the key in every other language as an empty fallback row:

       .venv/bin/python tools/i18n.py sync --only-present

3. Translate what you can (empty rows stay valid until someone does),
   then gate the change:

       .venv/bin/python tools/i18n.py verify

   `verify` fails on keys missing in a language / unknown to en_US, on
   non-string YAML scalars and (with `--strict`) on placeholder drift or
   rows that just copy English. Placeholder mismatches on legacy rows
   are warnings; fix them when you touch the row.

Use the same `$vars` as the English text, keep `[key]`-style brackets
out of translations, and quote anything YAML might re-type (`"16:9"`,
`"No"`, `"5"`) - `tools/i18n.py` writes files through ruamel and quotes
such values automatically, so prefer editing via `add --force` /
re-running `sync` over hand-editing when unsure.

To drop a string again (after removing its code references):

    .venv/bin/python tools/i18n.py remove mykey messages.mywarning

`extract --unused` lists baseline keys with no reference in code,
templates or JS; `extract --write` scaffolds keys that code references
but the baseline lacks.

## Add a language

1. Create the directory and copy the (empty) key skeleton from another
   language - empty values = full English fallback:

       cp -r app/locale/en_US app/locale/xx_YY
       .venv/bin/python tools/i18n.py sync --lang xx_YY --only-present

2. Register it in `app/locale/languages.yaml`:

       names:
         xx_YY: Language Name (Native script)
       aliases:
         xx: xx_YY        # so a bare Accept-Language 'xx' resolves

   Naming follows the reference: ISO 639-1 language + ISO 3166-1 Alpha-2
   country, e.g. `pt_BR`, and the display format `English (Native)` used
   by the other rows.

3. Translate the rows, then gate:

       .venv/bin/python tools/i18n.py verify --lang xx_YY
       .venv/bin/python tools/i18n.py verify --stats --lang xx_YY   # coverage

The settings language picker lists every catalogue directory, so nothing
else is required; `i18n.language_prop()` normalises `xx`, `xx-YY`, ...
through languages.yaml (unknown codes fall back to en_US).

## Importing from upstream Roundcube

Copy the texts from `roundcubemail/program/localization/<lang>/{labels,
messages}.inc` into the YAML rows (any PHP-literal -> YAML conversion is
fine as long as `verify` passes), then seed missing keys with `sync`.
Do not re-add `.inc` files - `tests/test_i18n.py::test_no_php_files_ship_in_locale`
enforces a YAML-only tree.
