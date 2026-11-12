# CraftCube Helm Chart

Installs CraftCube (Flask webmail, IMAP/SMTP-backed) on Kubernetes.

## Install

    helm install craftcube ./helm/craftcube \
      --set secret.flaskSecret="$(openssl rand -hex 32)" \
      --set config.imap.host=imap.example.org \
      --set config.smtp.host=smtp.example.org

Then reach it via `kubectl port-forward` (see NOTES.txt) or enable
`ingress.enabled=true` with your host.

## Key values

| Value | Default | Meaning |
|---|---|---|
| `image.repository` / `image.tag` | `craftcube` / chart appVersion | container image (build it from `craftcube/Containerfile`) |
| `config.imap.*` / `config.smtp.*` | example.org | mail servers CraftCube talks to |
| `config.perUserPasswords` | `"1"` | user's own IMAP password; `"0"` = shared admin mailbox via `secret.imapAdmin*` |
| `secret.flaskSecret` | — (required) | Flask session signing key |
| `secret.existingSecret` | `""` | consume a pre-created Secret (keys: `flask-secret`, `imap-admin-user`, `imap-admin-pass`) |
| `persistence.*` | 1Gi RWO | SQLite database volume at `/data` |
| `replicaCount` | 1 | keep at 1: SQLite on a RWO volume is single-writer |
| `ingress.*` | disabled | standard hosts/TLS block |

All values map to the `CRAFTCUBE_*` environment variables documented in
the top-level README.

## Notes

- The first login of any IMAP account auto-provisions its CraftCube user
  row and default identity; there is no bootstrap admin.
- Liveness/readiness probe `GET /` (302 to the login page counts up).
