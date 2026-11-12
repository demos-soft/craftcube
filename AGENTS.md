# CraftCube

A webmail client reverse-engineered from [Roundcube Webmail](https://roundcube.net)
(the reference sources are vendored in `../roundcubemail`), re-implemented in
Python with the look & feel of Roundcube's default *Elastic* skin.

Backend: Flask + SQLite (schema mirrors `roundcubemail/SQL/sqlite.initial.sql`:
users, contacts, contactgroups, identities, session, searches, ...).
Mail itself lives on an IMAP server; CraftCube talks IMAP for reading and
SMTP for sending, exactly like Roundcube does.

## Run with Docker (recommended)

    cd docker
    docker compose up -d --build

* App:        http://localhost:8000   (login: `test@example.org` / `secret`)
* Mailpit UI: http://localhost:8025   (send test mail: POST :1025 relays into the mailbox)
* IMAP:       localhost:1143 (dovecot, maildir-backed; also accepts LMTP-style delivery)

Stack: `craftcube` (Flask + gunicorn + SQLite volume) · `dovecot` (IMAP + a
tiny stdlib SMTP receiver that appends to the Maildir) · `mailpit` (SMTP
front-end + web preview, auto-relays everything into dovecot).

Send a test message from anywhere:

    python3 -c "import smtplib;from email.message import EmailMessage; \
      m=EmailMessage(); m['From']='alice@example.org'; m['To']='test@example.org'; \
      m['Subject']='Hello'; m.set_content('body'); \
      s=smtplib.SMTP('localhost',1025); s.send_message(m)"

## Run locally (venv)

    cd craftcube
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    CRAFTCUBE_IMAP_HOST=localhost CRAFTCUBE_IMAP_PORT=1143 \
    CRAFTCUBE_SMTP_HOST=localhost  CRAFTCUBE_SMTP_PORT=2525 \
    .venv/bin/python run.py        # http://localhost:8000

(The SMTP port for direct delivery is the receiver inside the dovecot
container; map it with `docker compose port dovecot 2525` or send via :1025.)

## Configuration (env)

| Variable | Default | Meaning |
|---|---|---|
| `CRAFTCUBE_DB` | `./data/craftcube.sqlite` | SQLite database path |
| `CRAFTCUBE_IMAP_HOST/PORT/SSL` | localhost/143/0 | IMAP server |
| `CRAFTCUBE_SMTP_HOST/PORT/SSL` | localhost/1025/0 | SMTP relay |
| `CRAFTCUBE_DRAFTS/SENT/TRASH` | Drafts/Sent/Trash | special folders (auto-detected via IMAP specials first) |
| `CRAFTCUBE_PRODUCT_NAME` | CraftCube | shown in title/login/about |
| `CRAFTCUBE_SECRET` | dev key | Flask secret key |
| `CRAFTCUBE_PER_USER_PASSWORDS` | 1 | authenticate IMAP with the user's own password; set 0 + `IMAP_ADMIN_USER/PASS` for shared-mailbox mode |

The first login of an unknown user auto-creates the user row (Roundcube-style
`users` table, PBKDF2-HMAC-SHA256 password hash) and a default identity.

## Features (the Roundcube core, reverse-engineered)

* Login/logout, DB-backed sessions, failed-login tracking, password change
* Mail: folder tree w/ unread counts, message list (sort, paging, quick
  search), preview pane in iframe, read/flag states, delete→Trash, move/copy,
  plain/HTML parts (sanitized), attachments (open/download)
* Compose: identities, To/Cc/Bcc, attachments, reply/reply-all/forward with
  quoting, drafts (IMAP \Draft), sent-folder saving via SMTP
* Address book: contacts (CRUD, search) + contact lists (groups)
* Settings: identities CRUD, folder management (create/rename/delete/empty),
  user settings
* Elastic skin look: dark task rail with icons, 4-column layout, dark-mode
  toggle (cookie `colorMode`), responsive layout classes
* Product named **CraftCube** everywhere (logo/title); skin assets are the
  Elastic skin's own CSS/fonts (Roundcube, © The Roundcube Authors, GPL-2.0)
* Translations: pure YAML catalogues (no PHP) — `app/locale/<lang>/{labels,
  messages}.yaml` + `languages.yaml` index, en_US baseline with per-language
  overlay (empty rows fall back to English). Dev tool `tools/i18n.py`
  (verify/extract/add/remove/sync/list) keeps all languages in sync;
  see `docs/LANGUAGE.md` for how to add a language or a string.

## Layout

    craftcube/app/
      __init__.py  create_app; config; template filters
      config.py    env-driven settings
      store.py     SQLite layer (Roundcube-derived schema)
      auth.py      PBKDF2 password hashing
      mail.py      IMAP/SMTP layer (imaplib/smtplib)
      views.py     all routes (login, mail, message, compose, contacts, settings)
      util.py      dates, sizes, header parsing, HTML sanitizer
      templates/   Jinja2 clones of the Elastic templates
      static/      Elastic styles.css + fonts + CraftCube logo + craftcube.js
    craftcube/Containerfile  production image (gunicorn on :8000)
    docker/        dovecot config, docker-compose.yml (app + IMAP + SMTP stack)

## Not (yet) reverse-engineered

Thread collapse/expand UI (grouping + indentation are implemented), caching
layer, plugins, Sieve filters, spell checking,
message import/export, identities signature auto-insert toggle, PGP.
