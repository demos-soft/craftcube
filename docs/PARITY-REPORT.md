# CraftCube ↔ Roundcube 1.7.5 parity report

Date: 2026-11-03 · Reference: Roundcube 1.7.5 (PHP, Elastic skin) · Clone: CraftCube (Flask/SQLite)
Staging: k8s3.lan — CraftCube :30090, reference :30091, shared Dovecot IMAP + Mailpit SMTP
Method: every behavior validated live against the reference; where bytes matter, PHP
oracles were executed inside the reference pod and locked into the test suite.

## Wire / mail engine — parity
- Send wire format: CRLF endings, Q-encoding of non-ASCII headers, PEAR Mail_mime
  style boundaries, `wordwrap` port, QP body wrapping — byte-compared via captured
  raw messages (`tests/test_mail_wire.py`).
- `rcube_mime::unfold_flowed()` ported; 14/14 against in-pod PHP oracle
  (`tests/test_unfold_flowed.py`).
- Reply/reply-all/reply-list/forward prefills: recipient rules ported from
  `rcmail_sendmail::compose_header_value()` (self-drop, hidden `_to`/`_cc`,
  List-Post follow-up, Reply-To, Mail-Followup-To). 8/8 cases byte-equal.
- HTML compose wash: `app/compose_wash.py` ports the `rcube_utils` CSS engine
  (`mod_css_styles` 60/60 oracle), `rcube_washtml` attribute allow-list, body
  promotion, link/mailto callbacks, container ids (`replybody1`, `v1` prefixes),
  draft re-open double-prefix quirk. FIX-1/FIX-2/PAR-D/FINAL-A replies byte-equal
  live (`tests/test_compose_wash.py`).
- Drafts (`\Draft`, Sent-folder save, MDN request handling) verified live.

## Addressbook — parity
- vCard 3.0 export byte-equal (76-char fold, value trimming, v3 no comma-escape,
  `TYPE=other` dropped, CONTACT_COLTYPES order, surname-sorted export-all).
- Search on normalized `words` (`normalize_string`/`tokenize_string` ports, PHP
  accent maps dumped from the pod, 9/9 oracle; 13/13 live search matrix).
- Group name collisions (`Group 2`, `Group 3`, …) per `unique_groupname()`.
- Contact photos: separate blob, upload/delete semantics, own endpoint; subtype
  select lists (email/address 3, phone 13) and gender values match Elastic.

## Settings — parity
- All settings sections/controls present; 66-control persistence matrix
  (incl. the two editor prefs): MATRIX FAILS: NONE (live POST → DB →
  re-render verification; baseline restored, 66 keys in users.preferences).
- Per-folder view mode live-verified: folder pref `threads` renders
  SORT=REFERENCES-style thread roots/children (seeded reply chains
  correctly), explicit `?_mode=list` overrides, restore to `list` clean.
- Live application verified for pagesize, skip_deleted, date_format, prefer_html,
  message_show_email, reply_mode, forward_attachment, name listing, view modes.
- `enable_autolink` / `keep_formatting_default` added (persisted; autolink has no
  Craft consumer yet — documented accepted gap).
- Identity rows `Name <email>` + reference ordering; responses/folders CRUD
  fields match; folders view gains parent + per-folder list/threads view mode.

## Message operations — parity (A/B vs reference, IMAP-verified)
- List search semantics: `_sf=subject|from|body|text|all` hit sets verified
  against seeded fixtures (5/5).
- Craft ops: flag/flagtoggle/unread/markallread row classes; copy (source
  kept), move, delete→Trash verified by message identity — note IMAP COPY/
  MOVE assigns new UIDs, checks must key on subject, not source UID.
- Delete semantics decoded from reference: Roundcube's server `delete`
  action is PERMANENT (raw \Deleted+expunge); the UI 'delete' is JS that
  issues move-to-Trash (app.js move_messages), with permanent delete inside
  Trash, in delete_junk, or on Shift. Craft's server-side delete replicates
  the effective UI behavior incl. all three edge cases.
- RC web-ops A/B'd in the shared mailbox: reference XHR move/delete succeed
  (`_target_mbox` is the move target param) and are visible from Craft
  instantly (shared Dovecot).
- New: `undelete` ported (clears \Deleted; the Mark → "As not deleted"
  popup item shown iff `flag_for_deletion && !skip_deleted`, per elastic).
- Export (zipdownload plugin, enabled on the reference): all formats × 1/2
  messages byte-equal including Content-Disposition — eml/maildir = zip
  `<mbox>.zip` of `<uid> <subject16>.eml`, mbox = zip of `<mbox>.mbox` with
  UTC RFC4155 From_-lines and \r\n padding; exports stream stored bytes
  (no synthesized Date). The reference has no raw single-eml mode.
- Message import A/B green: eml→1, mbox→n, combined multi-file exact
  counts; zip unpack path mirrored from import.php.

## Views — visual verdict (light + dark)
Geometry + computed-style diff (taskmenu, toolbar, list, tabs, search form,
footer, list header, first row) vs reference, both modes:
- login, settings general/identities/responses/folders, addressbook, contact,
  compose, mail list, message: style/geometry equal within tolerance.
- Dark palettes: 100% equal across all views.
- About page: chrome-less like the reference; 1 diff = unicorn logo (branding).

Accepted architectural differences (direct-URL page shapes, not bugs):
- Craft renders message/compose/contact direct URLs inside the full list layout;
  the reference renders bare framed shapes for hand-typed URLs.
- Reference DOM keeps sidebar quicksearch on full-page compose/contact views.
- `addressbook/searchform` diff is a probe selector artifact (form vs input;
  real inputs measured 1px apart).
- Mail list scroll height 55px apart (row content), About plugin table has rows
  on the reference only (installed plugins).

Fixes carried to the clone during this phase: message-list column overflow
(`#mailact { display: contents }`, vendored fixed table layout), cid: inline
images (resolve → inline URL, unresolvable → dropped, referred parts excluded
from attachment chips), nested-multipart view crash, `From <addr> on <date>`
spacing, selected-row highlight class.

## Staging stack / Helm — done
- `helm/craftcube`: app + Dovecot + Mailpit in-chart, 3 PVCs, NodePorts;
  `helm lint` clean; full render passes `kubectl apply --dry-run=client`
  against the live cluster (11 resources).
- `helm/craftcube/values-staging.yaml` reproduces the k8s3 staging install.
- Reference Roundcube lives in `staging/k8s3/roundcube-reference.yaml`
  (test fixture, not part of the product chart).

## Settings frame, info-box and validation round (2026-11-03, second pass)
- Preference-frame layout ported to the Elastic/Bootstrap contract
  (`tr.form-group.row`, `td.title.col-sm-6`/`td.col-sm-6`, custom-control
  switches, `custom-select form-control pretty-select`, fontgroup
  input-group, mailto colspan row, client-side advanced-fieldset collapse).
  Row geometry is pixel-identical to the reference frame (pitch 39px,
  matching y-offsets on the compose section; Special Folders frame A/B:
  structure, control types, widths and colours all match).
- Timezone dropdown generated at runtime exactly like PHP
  (`DateTimeZone::listIdentifiers` + DST fold + ordering): 420/420 options
  identical to the live reference.
- `prefer_html` off ⇒ `show_images` disabled + forced to “none” (reference
  coupling mirrored in render and in browser-like persistence).
- Folder tree/special-folder selectors use LIST ∩ LSUB (+INBOX), matching
  the reference tree (`INBOX`, `Drafts`, `Sent` in the shared mailbox).
- Info boxes are now the client-side `#messagestack` (port of
  `rcmail.display_message`: 5 s default, 10 s error/warning, dedupe, click
  dismiss, framed→parent forwarding, elastic icon/span markup). Live DOM of
  a triggered box matches the reference.
- Server-side validation parity, A/B-verified exact text/type/value
  retention: `noemailwarning`, `emailformaterror` (incl. the PHP
  `check_email()` edge rejecting `postmaster@localhost`), `formincomplete`,
  `nonamewarning`, `namecannotbeempty`, `nametoolong`, `forbiddencharacter`;
  `folderpurged` / `folderexpunged` confirmations. Forms re-render with the
  submitted values like the reference.
- Default identity is seeded with an empty display name (like
  `rcmail::startup`); the identities list renders `<email>` exactly as
  Elastic.
- Visual verdict (browser screenshots, light mode; dark palettes are
  byte-identical vendored CSS): login, settings landing, all 8 preference
  frames, Special Folders frame, identities, contacts, mail list, message
  view, compose, info box. Remaining accepted divergences: TinyMCE strip vs
  the reference's minimal built-in editor on compose, direct-URL page
  shapes, About unicorn block.
- Round 2 committed as `5e9624a` (frame + LSUB + info-box + validation),
  `1b8c5fe` (tzdata), `ad6ccfd` (row markup, autofocus, info-box DOM,
  identity seed).

## Plugin infrastructure round (2026-11-04)

- Engine port (`app/plugins.py`): `rcube_plugin_api`/`rcube_plugin` equivalents —
  plugins at `plugins/<name>/<name>.py` (class `<name>`), enabled list via
  `CRAFTCUBE_PLUGINS` (default `zipdownload`), per-request registration state,
  `exec_hook` with abort/break/dynamic-handler semantics, `register_action`
  with `plugin.` prefixing and task-qualified keys, template containers and
  objects, `include_script`/`include_stylesheet`/`add_label`, generic
  `/plugin/<name>/<action>` dispatch route (login required, unknown 404),
  `/plugins/<name>/<file>` static asset route. Core hook call sites wired:
  `ready`, `login_after`, `render_page`, `folders_list`, `message_before_send`,
  `loginform_content`, `listcontrols`/`mailboxoptions` containers and more.
  `tests/test_plugins.py` covers the contract (124 tests total).
- `zipdownload` port — corrected against the live 1.7.5 reference (the earlier
  `_uids[]` reading was wrong; the reference reads `get_uids()`, i.e. **`_uid`**
  POST array / comma list with `uid-MBOX` multifolder tokens):
  - messages: `<folder>.zip` (or `messages.zip` for multi-folder), mbox mode →
    one `<name>.mbox` entry with RFC4155 `From ` lines from INTERNALDATE
    (`D M d H:i:s Y`, UTC), `^>*From ` body quoting, blank line between
    messages; eml/maildir modes → identical `<uid> <subject16>.eml` entries
    (subject via `_filename_from_subject` + `_convert_filename` basename +
    zipdownload_charset), multi-folder entries prefixed `<mbox>/`.
  - attachments: zip named from the sanitized **message subject**
    (`ATTACH-PROBE-1.zip`), entry names basename+charset, duplicate suffix
    `file(1).txt` (not `file 2.txt`).
  - Reference no-ops: a plain GET of the plugin action renders the mail UI
    (JS never GETs it; single-message download is the core `viewsource`
    action with `_save=1`).
- `viewsource _save=1` port on `/message` (`app/views.py`): raw stored bytes,
  `Content-Type: text/plain;charset=<declared, us-ascii/missing → UTF-8>` (RC
  normalizes us-ascii away), `Content-Disposition: attachment;
  filename="<subject-sanitized-128>.eml"` — filename rule from
  `viewsource::filename_from_subject`.
- `additional_message_headers` port: `message_before_send` hook, `%u/%l/%d`
  expansion; enabled on both stacks with an `X-Staging-Probe` header.
- Live A/B on k8s3 (2026-11-04): export suite 0 diffs — mbox single/two,
  maildir/eml single, multi-folder `messages.zip` — zip entry names, per-entry
  SHA256 and Content-Disposition all equal; viewsource `.eml` body SHA +
  headers equal; attachments zip name + contents equal; send-hook header
  `X-Staging-Probe: via test at example.org` stored identically by PHP plugin
  and Python port. The reference pod was instrumented temporarily for the
  contract discovery and fully restored (`php -l` clean, no debug residue).

## Quality gates
- pytest: 124 passed · ruff: all checks passed · eslint: clean (config warning only)
- Cluster: craftcube / craftcube-dovecot / craftcube-mailpit / roundcube-reference
  all 1/1 ready; both web UIs HTTP 200.

## Not (yet) reverse-engineered
Thread
expand/collapse UI (SORT=REFERENCES-style grouping + depth indentation
implemented and live-verified per folder), caching layer, Sieve, spell
check, PGP, autolink behavior, `mailto_handler` behavior.
(Message import/export, the zipdownload export formats and the Roundcube-style
plugin infrastructure are done — see the plugin infrastructure round.)
