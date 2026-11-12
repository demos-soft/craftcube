"""zipdownload — port of the Roundcube zipdownload plugin.

Registers the two plugin actions of the reference:

* ``plugin.zipdownload.messages``    - export a message selection as a zip
  (eml/maildir: '<uid> <subject16>.eml' entries; mbox: one '<mbox>.mbox'
  entry; the archive itself is always '<mbox>.zip').
* ``plugin.zipdownload.attachments`` - all attachments of a message as
  'attachments.zip'.

Config (config.inc.py, like the PHP config.inc.php.dist):
zipdownload_attachments (-1 disables the attachment zip),
zipdownload_selection (size cap for the message export),
zipdownload_charset (filename charset inside the archive).
"""

import io
import re
import zipfile
from typing import ClassVar

from flask import Response, abort, request

from app.plugins import Plugin


class zipdownload(Plugin):
    CONFIG: ClassVar[dict] = {
        # show the attachment-zip link above this many attachments; -1 off
        "zipdownload_attachments": 1,
        # max total message size for the messages export (falsy = disabled)
        "zipdownload_selection": "50MB",
        "zipdownload_charset": "ISO-8859-1",
    }

    def init(self):
        self.load_config()
        self.charset = self.config.get("zipdownload_charset", "ISO-8859-1")
        self.register_action("plugin.zipdownload.attachments",
                             self.download_attachments)
        self.register_action("plugin.zipdownload.messages",
                             self.download_messages)

    # ------------------------------------------------------------------
    # helpers mirroring the PHP plugin's private helpers
    MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    WDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    @staticmethod
    def _filename_from_subject(s):
        # zipdownload::_filename_from_subject()
        s = re.sub(r"[\t\n\r\x00\x0B]+\s*", " ", s)
        return s.strip(" ./_")

    def _convert_filename(self, s):
        # zipdownload::_convert_filename(): basename, backslash -> '-',
        # control chars stripped, UTF-8 -> zipdownload_charset
        s = s.replace("\\", "-")            # PHP: str_replace before basename
        s = s.rsplit("/", 1)[-1]              # POSIX basename
        s = re.sub(r"[\x00-\x1F\x7F]", "", s)
        cs = self.charset.lower()
        if cs in ("utf-8", "utf8"):
            return s
        try:
            return s.encode(cs, "replace").decode(cs, "replace")
        except LookupError:
            return s

    def _uid_selection(self):
        """rcmail_action::get_uids() over the POST request (reference reads
        POST only; GET is accepted for Craft's server-rendered menus):
        ``_uid`` array or comma list, each ``uid`` or ``uid-MBOX``."""
        src = request.form if request.method == "POST" else request.args
        vals = src.getlist("_uid[]")
        if not vals:
            # scalar form: comma-separated list (get_uids explode(','))
            vals = [u for u in (src.get("_uid") or "").split(",") if u.strip()]
        default = (src.get("_mbox") or "INBOX").strip() or "INBOX"
        groups = {}
        for tok in (str(v).strip() for v in vals):
            if not tok:
                continue
            uid, sep, mbox = tok.partition("-")
            mbox = mbox if sep and mbox else default
            groups.setdefault(mbox, []).append(uid)
        return groups

    @staticmethod
    def _mbox_internaldate(msg):
        """INTERNALDATE '01 Nov 2026 12:00:00 +0000' -> struct_time in UTC."""
        import email.utils as eu
        from datetime import UTC
        idate = getattr(msg, "_internaldate", None)
        if not idate:
            return None
        try:
            dt = eu.parsedate_to_datetime(idate)
            return dt.astimezone(UTC)
        except (ValueError, TypeError):
            return None

    def _mbox_stamp(self, dt):
        # PHP DateTime::format('D M d H:i:s Y') in UTC, C locale
        if dt is None:
            from datetime import UTC, datetime
            dt = datetime.now(UTC)
        return (f"{self.WDAYS[dt.weekday()]} {self.MONTHS[dt.month - 1]} "
                f"{dt.day:02d} {dt:%H:%M:%S} {dt.year}")

    def download_messages(self):
        """rcmail_action_plugin_zipdownload::download_messages() plus
        _download_messages(): selection from ``_uid`` (POST), zip entry
        names, RFC4155 mbox stream filter and the <folder>|messages name."""
        from app.views import _hdr, imap_box  # lazy: no cycle

        groups = self._uid_selection()
        if not groups:
            abort(404)
        fmt = (request.form.get("_mode") or request.args.get("_mode")
               or request.args.get("_format") or "eml")
        box = imap_box()
        multifolder = len(groups) > 1

        def raw_bytes(m):
            # stored wire bytes; get_raw_body() equivalent
            return getattr(m, "_raw_bytes", None) or m.as_bytes()

        def fetch(mbox, u):
            try:
                m = box.raw_message(mbox, u)
            except Exception:
                abort(404)  # unknown uid: 404, not a server error
            if m is None:
                abort(404)
            return m

        buf = io.BytesIO()
        base = "messages" if multifolder else next(iter(groups))
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if fmt == "mbox":
                from email.utils import parseaddr
                body = b""
                keys = [(mbox, u) for mbox, us in groups.items() for u in us]
                for i, (mbox, u) in enumerate(keys):
                    raw = fetch(mbox, u)
                    frm = parseaddr(str(raw.get("From", "")))[1] or "MAILER-DAEMON"
                    frm = re.sub(r"\s", "-", frm)
                    header = f"From {frm} {self._mbox_stamp(self._mbox_internaldate(raw))}\r\n"
                    # zipdownload_mbox_filter: quote ^>*From lines (in place,
                    # preserving the stored bytes exactly)
                    quoted = re.sub(rb"(?m)^(>*From )", rb">\1", raw_bytes(raw))
                    chunk = header.encode() + quoted
                    if not chunk.endswith(b"\r\n"):
                        chunk += b"\r\n"
                    body += chunk
                    if i < len(keys) - 1:
                        body += b"\r\n"
                z.writestr(base + ".mbox", body)
            else:  # maildir / eml layout (identical in the reference)
                for mbox, us in groups.items():
                    path = mbox.replace("/", "/") + "/" if multifolder else ""
                    for u in us:
                        raw = fetch(mbox, u)
                        subject = self._convert_filename(self._filename_from_subject(
                            (_hdr(raw, "Subject") or "")[:16]))
                        z.writestr(f"{path}{u}{' ' + subject if subject else ''}.eml",
                                   raw_bytes(raw))
        return Response(buf.getvalue(), mimetype="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{base}.zip"',
        })

    # ------------------------------------------------------------------
    def download_attachments(self):
        """All attachments of one message as 'attachments.zip'."""
        from app.views import imap_box

        if int(self.config.get("zipdownload_attachments", 1)) < 0:
            abort(404)
        box = imap_box()
        folder = request.args.get("_mbox") or "INBOX"
        uid = request.args.get("_uid")
        if not uid:
            abort(404)
        try:
            msg = box.raw_message(folder, uid)
        except Exception:
            abort(404)
        if msg is None:
            abort(404)
        buf = io.BytesIO()
        names: dict = {}

        def uniq(name):
            # avoidDuplicates(): 'file.txt', 'file(1).txt', 'file(2).txt'
            if name not in names:
                names[name] = 1
                return name
            stem, sep, ext = name.rpartition(".")
            cand = f"{stem}({names[name]}).{ext}" if sep else f"{name}({names[name]})"
            names[name] += 1
            names.setdefault(cand, 1)
            return cand

        def walk(part):
            if part.get_content_maintype() == "multipart":
                for sub in part.get_payload() or []:
                    if hasattr(sub, "get_content_maintype"):
                        walk(sub)
                return
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" not in disp:
                return
            name = part.get_filename() or f"part{len(names) + 1}.bin"
            # _create_displayname(): _convert_filename (basename + charset)
            # then duplicate-suffix numbering
            name = uniq(self._convert_filename(name) or f"part{len(names) + 1}.bin")
            # zipdownload_charset governs entry names; ASCII-safe for the
            # sanitizer below, non-latin names keep UTF-8 (zip utf-8 flag)
            payload = part.get_payload(decode=True) or b""
            zinfo = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            z.writestr(zinfo, payload)

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            walk(msg)
        # 1.7.x: archive name = sanitized message subject, else 'attachments'
        # (zipdownload.php: _filename_from_subject($message->subject))
        from app.views import _hdr
        subject = self._filename_from_subject(_hdr(msg, "Subject") or "")
        zname = (subject or "attachments") + ".zip"
        return Response(buf.getvalue(), mimetype="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{zname}"',
        })
