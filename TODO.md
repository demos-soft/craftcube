- [x] Dark mode toggle switch still not matching (d13cd05 — button flips to sun / "Light mode" while dark is on, like the reference)
- [x] Dark mode not fully working on some pages (d13cd05 — dark sweep: mail 53.2% -> 3.9%, rest <= 1.4%)
- [x] Mail compose page header with options not matching the original (2227ea2 — From options use format_email_recipient; options panel hot-column diff empty)
- [x] Mail page header contains unwanted signs and numbers (2095142 — literal line-number prefixes removed from the toolbar template)
- [x] WYSIWYG editor shall have a white background and black font as default settings (verified: vendored embed.min.css matches the reference; compose-dark diff 0.18%)
- [x] Create openapi compatible yaml file for the backend REST API (2deab50 — openapi.yaml, 42 paths / 55 ops, validator clean)
- [x] Add meaningful linting rules for frontend and backend. Respect clean code rules. (a3e9990 ruff config, 3aa3734 ESLint flat config)
- [x] Apply linting rules to code (4da1b2f backend, bbe9708 frontend; ruff + eslint clean, pixel parity unchanged)
- [x] Add unittests (e70c0f7 — 56 pytest tests; caught and fixed the two-default-identities bug 388f6a3)
- [x] Move README.md to AGENTS.md. AGENTS.md is for agents, README.md is for humans (ca4253a)
- [x] Add Containerfile for Craftcube (465a3d2 — builds, serves, compose uses it as the single image definition)
- [x] Add helm chart for deployment of Craftcube to a kubernetes cluster (b3fb594 — lint + template verified across variants)
- [x] Create README.md for humans with instructions on how to set up, install and configure Craftcube as Webmail client (Apache, Ngning, Helm, test harness) (8a0b4cf)
- [x] Bug: In Compose view "Responses" and "Spell" submenu not as in roundcube (a9e622f — placeholder markup, enchant language order, 35px/0 .5rem rows; popups measure identical 182x116 / 182x110 / 182x145)
- [x] Bug: In Mail view, teplying to a mail in html format not possible. HTML gets converted to text and TinyMCE starts in text mode. Might all replying/forwarding options (391ef3b — full compose_editor_mode table + reply/forward body pipeline; ground-truth bodies match byte-for-byte for all 5 htmleditor values)
- [x] Bug: In Mail view, submenus "Reply all" and "Forward" do not match roundcube design (0b4c0ed — bootstrap popover shell, active/aria-disabled states, List-Post-gated Reply list item; popups measured identical 180px/35px rows)
- [x] Bug: In Mail view, clicking on an Email in the list (2nd col), the Email shall open in 3rd col. Currently only the title works as link (21370de — row click focuses/previews like Elastic; checkbox only in selection mode)
- [x] Bug: In Mail view, the opened Email in third row disappears after a while and gets unselected in 2nd row. (21370de — auto-refresh keeps the previewed _uid and focus)
- [x] Bug: In Settings view, some settings do not get saved. Ensure every User setting is saved and honored by the code. All default setting shall match roundcubes default settings. (7676d1f + spellcheck/autosave/extwin/MDN batches 3d1aa3e, 8b8a368, fd6a60f — save round-trip 0 problems; read_when_deleted default fixed; prefs honored incl. pretty_date, skip_deleted, show_images, inline_images, reply_same_folder, logout purge/expunge, spellcheck ignores + before-send, draft autosave/localstorage, extwin popups, mdn_requests (ask/autosend/known/trusted/ignore), message_show_email, default_charset, force_7bit; remaining unhonored prefs only guard features CraftCube has no counterpart for — autocomplete dropdown, multiple addressbook sources, mailvelope, background recent-check, RFC2231 folding, contact sub-type order)
- [x] Bug: In Settings view, some Settings are hidden (collapsed) by default in Roundcube, but not Craftcube (e322f31 — fieldset.advanced rendered as div.collapse with closed legend; visible/hidden parity across all 8 sections, framed diff 0.51%)
- [x] Bug: In Settings view, List of selectable languages does not match roundcube. Language switch not working. (9623fa0 vendored the reference catalogues; language pref now drives html lang, task rail, folder names, page titles, settings, toolbar tooltips, JS dialogs and flash messages via rcube-style gettext/language_prop/get_label)

## Staging parity sweep (uncommitted; verified on k8s3 CraftCube:30090 vs reference Roundcube:30091)
- [x] Search parity incl. search_mods persistence — UID-set A/B audit (craftcube-sweep/audit_search4.py) green across subject/from/to/body/headerless/scope cases
- [x] Contact edit/show vCard parity — byte-exact stored vCards vs live RC oracle (test_vcard live byte-parity test), RC subtype typemaps/order, add-field menus, display-name composition
- [x] Contact show labels/order — RC locale labels (Mobile/Home Fax/Home Page/Other), RC personal row order, no source row; live text diff vs RC framed show = identical
- [x] Addressbook group tree caret — div.treetoggle + aria tree states, pixel-identical geometry
- [x] Mail list toolbar Threads button — always rendered (Select|Threads|Options), was wrongly hidden in preview mode
- [x] Standalone message reader — /message renders dedicated reader (no redirect), Print/prev/next toolbar, top-boundary prev disabled
- [x] Plain-text body rendering — text2html filter (div.pre + nl2br + quotes + sig + linkify) matches RC; shell preview & reader, vision 98/PASS
- [x] Login button visibility — skip .formbuttons clone when no .header target; geometry identical
- [x] Preferences bulk save — SQLite WAL + set_user_prefs bulk write; liveness starvation fixed (stress p95 35ms); unchecked checkbox clearing needs hidden _section
- [x] Visual verdicts (visual-verdict skill): login 96, mail 94, message 98, addressbook 93, reader ~90 — all pass threshold
- [x] Unit suite 156 tests pass (reader, contact form/show, vcards, typemaps, tree, converters)
- [x] Fresh full prefs_matrix rerun after WAL deploy (out8 exit 0 — matrix green, 0 fails)
- [x] Framed identity/response editors — bare `_framed=1` contract, form id=form Save buttons, pretty switches, propform beautification, parent-list row upsert (`cc_settings_row_upsert`, `_saved=insert|update`); visual 93 / 95, settings General section 98
- [x] IMAP socket timeout (30s) — stalled synchronous reads no longer wedge gunicorn workers; pod memory 1Gi
- [x] Bare framed contact editor — shared include + `action-edit/add` body class, full-page re-render dict-row guards, hidden `_cid` replay fallback
- [x] Contact editor JS overlays — fieldset.propform row + grouped input-group decoration, image-upload delete overlay + smart-upload hidden form, drag/drop `droptarget`, Save dirty-state; live-verified incl. byte-exact drop→save→/contact/N/photo roundtrip
- [x] Contact photo upload — `_upload=1` immediate upload for existing contacts (fields untouched), DataTransfer staging into main form for new contacts
- [x] Contact editor visual parity — 96/PASS after 21px in-flow `#ff_photo_file` line-box fix + `addfield select fit-content` CSS; element-chain geometry pixel-identical (header y 14, tabs y 433 both sides)
- [x] Compose visual parity — 96/PASS (toolbar order Save/Attach/Signature/Responses/Spell, From/To/Subject rows, Options-and-attachments panel; only delta was a transient caret in the focused To field)
- [x] Full suite 165 tests; working tree re-baked into registry `:stage` (Docker+OCI manifests), rollout verified pod==tree md5
- [x] Sweep work committed to `dev` in 9 feature commits (helm, store, vcard, mail, settings, contacts, ui-overlays, docs)

## Post-sweep defect fixes (user-reported; committed 9553586..0c082b9 on dev, baked image 72ffdfa0b4e1)
- [x] Language switch does not apply — three stacked causes: dead framed prefs Save button (form lacked `id="form"`, outside-form button lacked `form="form"`), no RC-style `reload(500)` window reload after language change (prefs_save.php parity), hardcoded `<html lang="en">` on 8 templates; browser E2E: de_DE auto-reload into German rail and back (9553586)
- [x] Folder settings — four causes: short-key storage (`trash` vs RC `trash_mbox` full keys), `Mailbox.special()` lookup key, selectors now tree-ordered RC-style with `---` + INBOX guard, added Archive + Divide-archive-by rows, folder-manager subscription state from LSUB (Dovecot omits \Subscribed in LIST); delete-to-Trash verified E2E incl. confirm dialog and move-back (0978821)
- [x] Message list checkbox swallowed — row click handler ran preview logic with `preventDefault()` on checkbox clicks; INPUT-target early return like RC rowselection (18bf423)
- [x] Archive group fieldset + plugin labels — reference renders 'Divide archive by' in `fieldset.archive` (legend 'Archive', archive plugin domain); ported the plugin's settings labels verbatim into 6 locales, legend/options translate (de Archiv/Archiv aufteilen nach, live-verified); geometry gap 53px == RC; visual verdict 96 PASS (0c082b9)
- [x] Staging pod restart loop — 1s liveness on `/` behind 2 sync gunicorn workers starved by slow IMAP renders; added IMAP-free `/healthz`, probes -> /healthz timeout 3s, gthread 4w x 8 threads; 40-req load: p95 0.15s, 0 restarts (c80e5b0)
- [x] Full suite 176 tests; both defect flows re-verified in real browser against the re-baked image; staging restored (en_US, no special-folder prefs, Trash unsubscribed, test message in INBOX)

## Settings section visual+control sweep (completed; commits 9dd5c8a, 2f92371; baked image ed62c09bfb79)
- [x] Control-name audit vs reference across all 8 framed sections — zero RC-only and zero CC-only form controls; every section field-count delta explained (chrome/meta names only)
- [x] Server section — added archive-plugin 'Mark the message as read on archive' row (between Junk-delete and Maintenance) + localized `readonarchive` labels in 6 locales; final side-by-side screenshots are byte-identical (md5 match)
- [x] Encryption section — Mailvelope notice now the elastic `alert alert-warning` banner with icon column, shown via plain DOM JS (jQuery `$` copy never ran, banner was invisible); beautifyPropform no longer stacks col-sm-4/8 onto cells that already carry col-sm-* (the double class made cols 2/3-wide and caused horizontal overflow). Toggle geometry 626@640 and banner link color now identical; visual verdict 92 PASS (2f92371)
- [x] Remaining section visual verdicts: Mailbox 95, Message View 98, Compose options 96, Address Book 98 — all PASS (accepted minor: transient focus rings; RC framed-page hairline frame)
- [x] Full suite 178; staging DB verified clean after rollout (user prefs: all special folders '', language en_US, read_on_archive 0); no restart loop regression
