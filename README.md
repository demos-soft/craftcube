<p align="center">
  <img src="craftcube/app/static/images/logo.svg" width="110" alt="CraftCube logo">
</p>

# CraftCube

CraftCube is a webmail client: a Python re-implementation of the
[Roundcube Webmail](https://roundcube.net) user interface, built to look
and behave like Roundcube's default *Elastic* skin. Mail itself lives on a
standard IMAP server — CraftCube reads over IMAP and sends over SMTP,
exactly like Roundcube does; a small SQLite database holds users,
identities, contacts and settings.

- **Backend:** Python 3.11+ / Flask, SQLite (Roundcube-derived schema)
- **API:** described in [`craftcube/openapi.yaml`](craftcube/openapi.yaml)
- **Skin:** Elastic CSS/fonts/icons vendored from Roundcube (GPL-2.0, © The Roundcube Authors)

---

## Quick start (Docker test stack)

The repository ships a complete local mail environment: CraftCube plus
Dovecot (IMAP) and Mailpit (SMTP front-end with a web UI). From the
repository root:

    cd docker
    docker compose up -d --build

| Service | URL | Notes |
|---|---|---|
| CraftCube | http://localhost:8080 | login `test@example.org` / `secret` |
| Mailpit web UI | http://localhost:8025 | browse everything received |
| SMTP for test mail | localhost:1025 | relays into the Dovecot mailboxes |

Send a test message:

    python3 - <<'EOF'
    import smtplib
    from email.message import EmailMessage
    m = EmailMessage()
    m['From'], m['To'], m['Subject'] = 'alice@example.org', 'test@example.org', 'Hello'
    m.set_content('body')
    smtplib.SMTP('localhost', 1025).send_message(m)
    EOF

Any IMAP account you can authenticate as may sign in; the first login
auto-creates the CraftCube user and a default identity.

## Running against your own mail server

CraftCube needs only an IMAP and an SMTP endpoint. Either run the
container image directly:

    docker build -t craftcube ./craftcube        # or `podman build`
    docker run -d -p 8080:8000 \
      -e CRAFTCUBE_IMAP_HOST=imap.example.org \
      -e CRAFTCUBE_SMTP_HOST=smtp.example.org \
      -e CRAFTCUBE_SMTP_PORT=587 \
      -e CRAFTCUBE_SECRET="$(openssl rand -hex 32)" \
      -v craftcube-data:/data \
      craftcube

or run from source:

    cd craftcube
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    CRAFTCUBE_IMAP_HOST=imap.example.org CRAFTCUBE_SMTP_HOST=smtp.example.org \
    .venv/bin/python run.py                    # http://localhost:8000

## Configuration

All configuration is environment-driven.

| Variable | Default | Meaning |
|---|---|---|
| `CRAFTCUBE_DB` | `./data/craftcube.sqlite` | SQLite database path (use a volume!) |
| `CRAFTCUBE_IMAP_HOST` / `PORT` / `SSL` | `localhost` / `143` / `0` | IMAP server |
| `CRAFTCUBE_SMTP_HOST` / `PORT` / `SSL` | `localhost` / `1025` / `0` | SMTP relay |
| `CRAFTCUBE_DRAFTS` / `SENT` / `TRASH` | `Drafts` / `Sent` / `Trash` | special folders; Dovecot `\SpecialUse` flags are auto-detected first |
| `CRAFTCUBE_PER_USER_PASSWORDS` | `1` | `1`: log in with each user's own IMAP password. `0`: shared mailbox using `CRAFTCUBE_IMAP_ADMIN_USER` / `CRAFTCUBE_IMAP_ADMIN_PASS` |
| `CRAFTCUBE_SECRET` | dev key | Flask session signing key — **always set** in production |
| `CRAFTCUBE_PRODUCT_NAME` | `CraftCube` | name shown in title, login, about |
| `CRAFTCUBE_PAGE_SIZE` | `50` | messages per page (matches the reference `mail_pagesize`) |

## Reverse proxy

CraftCube speaks plain HTTP on port 8000 and has no TLS of its own —
terminate TLS in your proxy. No special paths; forward everything.

### Nginx

    server {
        listen 443 ssl http2;
        server_name mail.example.org;
        ssl_certificate     /etc/letsencrypt/live/mail.example.org/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/mail.example.org/privkey.pem;

        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            client_max_body_size 25m;   # compose attachments
        }
    }

### Apache

    <VirtualHost *:443>
        ServerName mail.example.org
        SSLEngine on
        SSLCertificateFile    /etc/letsencrypt/live/mail.example.org/fullchain.pem
        SSLCertificateKeyFile /etc/letsencrypt/live/mail.example.org/privkey.pem

        ProxyPreserveHost On
        ProxyPass        / http://127.0.0.1:8000/
        ProxyPassReverse / http://127.0.0.1:8000/
        RequestHeader set X-Forwarded-Proto "https"

        # compose attachments; raise as needed
        LimitRequestBody 26214400
    </VirtualHost>

Requires `mod_proxy`, `mod_proxy_http` and `mod_ssl`.

## Kubernetes (Helm)

    helm install craftcube ./helm/craftcube \
      --set secret.flaskSecret="$(openssl rand -hex 32)" \
      --set config.imap.host=imap.example.org \
      --set config.smtp.host=smtp.example.org \
      --set ingress.enabled=true \
      --set ingress.hosts[0].host=mail.example.org

The chart creates a Deployment, Service, optional Ingress, a Secret for
the session key, and a PVC for the SQLite database. See
[`helm/craftcube/README.md`](helm/craftcube/README.md) for all values.
Keep `replicaCount` at 1 unless the volume is ReadWriteMany (SQLite).

## Tests and code quality

    cd craftcube
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest                      # unit tests
    .venv/bin/ruff check app tests        # backend lint

    npm ci && npx eslint app/static       # frontend lint

`pytest` runs fully offline on a temporary SQLite database; the running
Docker stack is never touched.

## Feature overview

Login/logout with DB-backed sessions and failed-login tracking · folder
tree with unread counts · message list with sorting, paging, quick
search and threading · message view with sanitized HTML, attachments,
print and external-window modes · compose with identities, HTML/plain
TinyMCE editor, attachments, reply/forward quoting, drafts and sent-folder
saving · address book with contact groups and collected senders ·
settings: preferences, identities, responses, folder management ·
dark mode, responsive Elastic layout.

## Documentation map

| File | Audience | Content |
|---|---|---|
| `README.md` (this file) | operators | setup, install, configuration |
| `AGENTS.md` | AI agents / contributors | re-implementation state, architecture, parity notes |
| `craftcube/openapi.yaml` | integrators | HTTP API description |
| `helm/craftcube/README.md` | operators | chart values reference |
| `docker/docker-compose.yml` | developers | local test stack definition |

## License note

The skin assets (CSS, fonts, icons) originate from the Roundcube Elastic
skin and are GPL-2.0, © The Roundcube Authors.
