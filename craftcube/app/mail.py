"""IMAP/SMTP access layer (imaplib/smtplib) with a Roundcube-like API.

One IMAP connection per request (flask.g); credentials come from the login
form (or the configured admin account when per-user passwords are disabled).
"""
import email
import email.utils
import imaplib
import smtplib
import ssl as _ssl
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .util import parse_header_date, format_address

# fetched envelope: uid, flags, size, date, from, to, subject, reply-to, in-reply-to, message-id, attachments hint
FETCH_ITEMS = "(FLAGS INTERNALDATE RFC822.SIZE ENVELOPE BODYSTRUCTURE)"

SORTS = {
    "arrival": (lambda m: m["uid"] or 0, True),
    "date": (lambda m: m["date"].timestamp() if m.get("date") else 0, True),
    "subject": (lambda m: (m.get("subject") or "").lower(), False),
    "from": (lambda m: (m.get("from") or "").lower(), False),
    "to": (lambda m: (m.get("to") or "").lower(), False),
    "cc": (lambda m: (m.get("cc") or "").lower(), False),
    "fromto": (lambda m: (m.get("from") or m.get("to") or "").lower(), False),
    "size": (lambda m: m.get("size") or 0, True),
}

SEARCH_FILTERS = {
    "all": None,
    "unread": ["UNSEEN"],
    "flagged": ["FLAGGED"],
    "answered": ["ANSWERED"],
    "unanswered": ["UNANSWERED"],
}

SEARCH_INTERVALS = {
    "all": None,
    "today": ["SINCE"],   # today
    "last7": ["SINCE"],   # -7d
    "last14": ["SINCE"],
    "last30": ["SINCE"],
    "thismonth": None,    # implemented specially
}



class MailError(Exception):
    pass


class Imap:
    """Thin, stateless wrapper around one IMAP connection."""

    def __init__(self, host, port, user, password, use_ssl=False):
        try:
            if use_ssl:
                self.conn = imaplib.IMAP4_SSL(host, port, ssl_context=_ssl.create_default_context())
            else:
                self.conn = imaplib.IMAP4(host, port)
                try:
                    self.conn.starttls()
                except imaplib.IMAP4.error:
                    pass  # server without STARTTLS (local dev)
            self.conn.login(user, password)
        except (imaplib.IMAP4.error, OSError) as e:
            raise MailError(str(e))
        self.selected = None

    def logout(self):
        try:
            self.conn.logout()
        except Exception:
            pass

    # ------------------------------------------------------------ folders

    def list_folders(self):
        typ, data = self.conn.list()
        out = []
        if typ != "OK":
            return out
        import re
        for line in data or []:
            s = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            m = re.match(r"^\((?P<flags>[^)]*)\)\s+(?:(?P<delim>\".\"|NIL)\s+)?(?P<name>.*)$", s)
            if not m:
                continue
            flags = m.group("flags").split()
            name = m.group("name").strip()
            if name.startswith('"') and name.endswith('"') and len(name) > 1:
                name = name[1:-1]
            special = None
            for f in flags:
                fu = f.lstrip("\\").lower()
                if fu in ("drafts", "sent", "trash", "junk"):
                    special = fu
            low = name.lower()
            if special is None:
                if low in ("drafts", "draft"):
                    special = "drafts"
                elif low in ("sent", "sent items", "sent messages"):
                    special = "sent"
                elif low in ("trash", "deleted messages", "bin"):
                    special = "trash"
                elif low in ("junk", "spam", "junk e-mail"):
                    special = "junk"
            out.append({"name": name, "flags": flags, "special": special,
                        "inferior": "\\Noselect" in flags})
        # INBOX first
        out.sort(key=lambda f: (f["name"].upper() != "INBOX", f["name"].lower()))
        return out

    def status(self, folder):
        try:
            typ, data = self.conn.status(_q(folder), "(MESSAGES UNSEEN)")
        except imaplib.IMAP4.error:
            return 0, 0
        if typ != "OK" or not data or not data[0]:
            return 0, 0
        s = data[0].decode() if isinstance(data[0], bytes) else data[0]
        import re
        m = re.search(r"MESSAGES (\d+)", s)
        u = re.search(r"UNSEEN (\d+)", s)
        return (int(m.group(1)) if m else 0), (int(u.group(1)) if u else 0)

    def create_folder(self, name):
        typ, msg = self.conn.create(_q(name))
        if typ != "OK":
            raise MailError(msg)

    def delete_folder(self, name):
        typ, msg = self.conn.delete(_q(name))
        if typ != "OK":
            raise MailError(msg)

    def rename_folder(self, old, new):
        typ, msg = self.conn.rename(_q(old), _q(new))
        if typ != "OK":
            raise MailError(msg)

    def subscribe(self, name):
        self.conn.subscribe(_q(name))

    # ------------------------------------------------------------ select / search

    def select(self, folder, readonly=False):
        typ, data = self.conn.select(_q(folder), readonly=readonly)
        if typ != "OK":
            raise MailError(f"Cannot select folder {folder}")
        self.selected = folder
        return int(data[0])

    def uid_search(self, criteria):
        typ, data = self.conn.uid("SEARCH", None, *(criteria if isinstance(criteria, (list, tuple)) else (criteria,)))
        if typ != "OK":
            return []
        return [int(x) for x in (data[0].split() if data and data[0] else [])]

    # ------------------------------------------------------------ messages

    def fetch_envelopes(self, uids):
        """Return list of message dicts for the given UIDs."""
        if not uids:
            return []
        out = []
        seq = ",".join(str(u) for u in uids)
        typ, data = self.conn.uid("FETCH", seq, FETCH_ITEMS)
        if typ != "OK":
            return out
        for item in _iter_fetch(data):
            m = _parse_fetch(item)
            if m:
                out.append(m)
        return out

    def fetch_message(self, uid):
        typ, data = self.conn.uid("FETCH", str(uid), "(RFC822 FLAGS)")
        if typ != "OK":
            raise MailError("Message not found")
        raw = None
        for item in _iter_fetch(data):
            if isinstance(item, tuple) and len(item) > 1 and item[1]:
                raw = item[1]
                break
        if raw is None:
            raise MailError("Message not found")
        return email.message_from_bytes(raw)

    def fetch_part(self, uid, section):
        typ, data = self.conn.uid("FETCH", str(uid), f"(BODY.PEEK[{section}])")
        for item in _iter_fetch(data):
            if isinstance(item, tuple) and len(item) > 1 and item[1]:
                return item[1]
        raise MailError("Part not found")

    def set_flags(self, uids, flags, mode="store"):
        seq = ",".join(str(u) for u in uids)
        verb = "STORE" if mode == "store" else ("+FLAGS" if mode == "add" else "-FLAGS")
        # imaplib flags must be a single '(FLAGS)' string argument
        typ, _ = self.conn.uid("STORE", seq, verb, _flagstr(flags))
        return typ == "OK"

    def copy(self, uids, dest):
        seq = ",".join(str(u) for u in uids)
        typ, msg = self.conn.uid("COPY", seq, _q(dest))
        if typ != "OK":
            raise MailError(msg)

    def append(self, folder, raw_bytes, flags=()):
        typ, msg = self.conn.append(_q(folder), _flagstr(list(flags)) if flags else None, None, raw_bytes)
        if typ != "OK":
            raise MailError(f"Append failed: {msg}")

    def expunge(self):
        self.conn.expunge()

    def quota(self):
        try:
            typ, data = self.conn.quota("root", "")
            return data
        except Exception:
            return None


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _flagstr(flags):
    return "(" + " ".join(flags) + ")"


def _iter_fetch(data):
    return [d for d in (data or []) if d not in (None, b"", ())]


def _parse_fetch(item):
    if not isinstance(item, tuple):
        return None
    meta = item[0].decode(errors="replace") if isinstance(item[0], bytes) else str(item[0])
    import re
    uid_m = re.search(r"UID (\d+)", meta)
    size_m = re.search(r"RFC822\.SIZE (\d+)", meta)
    flags = [f.decode() if isinstance(f, bytes) else f
             for f in (imaplib.ParseFlags(meta.encode()) if "FLAGS" in meta else [])]
    m = {
        "uid": int(uid_m.group(1)) if uid_m else None,
        "size": int(size_m.group(1)) if size_m else 0,
        "flags": flags,
        "seen": "\\Seen" in flags,
        "flagged": "\\Flagged" in flags,
        "deleted": "\\Deleted" in flags,
        "answered": "\\Answered" in flags,
        "attachments": "ATTACHMENT" in meta.upper() or 'name "' in meta,
    }
    env = _parse_envelope(meta)
    m.update(env)
    return m


def _parse_envelope(meta):
    """Extract date/from/to/subject from the FETCH response ENVELOPE (best effort)
    plus INTERNALDATE."""
    import re
    out = {"date": None, "date_str": "", "from": "", "from_email": "", "to": "", "subject": "",
           "in_reply_to": "", "message_id": ""}
    m = re.search(r"INTERNALDATE \"([^\"]+)\"", meta)
    if m:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(m.group(1))
            out["date"] = dt
            out["date_str"] = m.group(1)
        except Exception:
            pass
    return out


def _envelope_from_message(msg):
    from .util import header_addresses
    frm = header_addresses(msg, "From")
    to = header_addresses(msg, "To")
    return {
        "from": frm[0][0] if frm else "",
        "from_email": frm[0][1] if frm else "",
        "to": ", ".join(format_address(*a) for a in to) if to else "",
        "subject": _decode_header(msg.get("Subject", "")) or "(no subject)",
    }


def _decode_header(value):
    if not value:
        return value
    parts = email.header.decode_header(value)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "latin-1", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


class Mailbox:
    """High-level mail API used by the views."""

    def __init__(self, imap, config, default_email):
        self.imap = imap
        self.config = config
        self.default_email = default_email

    def conf(self, key):
        try:
            return getattr(self.config, key)
        except AttributeError:
            return self.config[key]

    def folders(self):
        folders = self.imap.list_folders()
        res = []
        for f in folders:
            if f.get("inferior"):
                continue
            total, unseen = self.imap.status(f["name"])
            f["total"], f["unseen"] = total, unseen
            res.append(f)
        return res

    def special(self, kind):
        conf = self.conf({"drafts": "DRAFTS_FOLDER", "sent": "SENT_FOLDER",
                          "trash": "TRASH_FOLDER"}[kind])
        for f in self.imap.list_folders():
            if f["special"] == kind:
                return f["name"]
        return conf

    def message_list(self, folder, page=1, page_size=20, sort="date", order="desc",
                     search=None, search_mods=None, search_filter="all",
                     search_interval="all", search_scope="base"):
        if search_scope == "all":
            return self._search_all_folders(page, page_size, sort, order, search,
                                            search_mods, search_filter, search_interval)
        if search_scope == "sub":
            names = [f["name"] for f in self.imap.list_folders()
                     if f["name"] == folder or f["name"].startswith(folder + "/")]
            merged = []
            for name in names:
                d = self._list_one(name, page_size, search, search_mods,
                                   search_filter, search_interval)
                for m in d["items"]:
                    m["folder"] = name
                merged.extend(d["items"])
            return self._paginate(merged, page, page_size, sort, order)
        return self._list_one(folder, page_size, search, search_mods,
                              search_filter, search_interval, page=page,
                              sort=sort, order=order)

    def _search_criteria(self, search, mods, search_filter, search_interval):
        crit = []
        if search_filter and search_filter != "all":
            crit += SEARCH_FILTERS.get(search_filter) or []
        if search_interval and search_interval != "all":
            import datetime
            today = datetime.date.today()
            if search_interval == "today":
                since = today
            elif search_interval == "thismonth":
                since = today.replace(day=1)
            else:
                days = {"last7": 7, "last14": 14, "last30": 30}.get(search_interval, 7)
                since = today - datetime.timedelta(days=days)
            crit += ["SINCE", since.strftime("%d-%b-%Y")]
        if search:
            mods = mods or ["subject", "from", "to", "body"]
            fields = {"subject": "SUBJECT", "from": "FROM", "to": "TO",
                      "cc": "CC", "body": "BODY", "text": "TEXT"}
            terms = []
            for mod in mods:
                f = fields.get(mod)
                if f and f not in terms:
                    terms += [f, _q(search)]
            if not terms:
                terms = ["TEXT", _q(search)]
            # interleaved right-associated OR chain:
            # OR SUBJECT "x" OR FROM "x" OR TO "x" BODY "x"
            if len(terms) > 2:
                pairs = [terms[i:i + 2] for i in range(0, len(terms), 2)]
                chain = []
                for idx, pair in enumerate(pairs):
                    if idx < len(pairs) - 1:
                        chain.append("OR")
                    chain += pair
                crit += chain
            else:
                crit += terms
        return crit or ["ALL"]

    def _list_one(self, folder, page_size, search=None, mods=None,
                  search_filter="all", search_interval="all", page=1,
                  sort="date", order="desc"):
        total = self.imap.select(folder, readonly=True)
        crit = self._search_criteria(search, mods, search_filter, search_interval)
        uids = self.imap.uid_search(crit)
        MAX_SCAN = 400
        window = uids[-MAX_SCAN:]
        msgs = self._enrich(folder, window)
        return self._paginate(msgs, page, page_size, sort, order, uidvalidity=total)

    def _paginate(self, msgs, page, page_size, sort, order, uidvalidity=0):
        key, _asc = SORTS.get(sort, SORTS["date"])
        reverse = order != "asc"
        try:
            msgs.sort(key=key, reverse=reverse)
        except TypeError:
            msgs.sort(key=lambda m: str(key(m)), reverse=reverse)
        pages = max(1, (len(msgs) + page_size - 1) // page_size) if page_size else 1
        page = max(1, min(page, pages))
        start = (page - 1) * (page_size or len(msgs) or 1)
        items = msgs[start:start + (page_size or len(msgs))]
        return {
            "items": items, "page": page, "pages": pages,
            "total": len(msgs), "first": start + 1 if msgs else 0,
            "last": start + len(items), "uidvalidity": uidvalidity,
            "uids": [m["uid"] for m in msgs],
        }

    def _search_all_folders(self, page, page_size, sort, order, search, mods,
                            search_filter, search_interval):
        merged = []
        for f in self.imap.list_folders():
            if f.get("inferior"):
                continue
            try:
                d = self._list_one(f["name"], None, search, mods,
                                   search_filter, search_interval)
            except MailError:
                continue
            for m in d["items"]:
                m["folder"] = f["name"]
            merged.extend(d["items"])
        return self._paginate(merged, page, page_size, sort, order)


    def _enrich(self, folder, uids):
        """Envelope data is unreliable to parse from raw IMAP FETCH meta, so we
        fetch headers (BODY.PEEK[HEADER.FIELDS ...]) which parse cleanly."""
        if not uids:
            return []
        seq = ",".join(str(u) for u in uids)
        typ, data = self.imap.conn.uid(
            "FETCH", seq,
            "(FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO CONTENT-TYPE)])")
        out = []
        if typ != "OK":
            return out
        import re
        sent = self.special("sent")
        for item in _iter_fetch(data):
            if not isinstance(item, tuple):
                continue
            meta = item[0].decode(errors="replace") if isinstance(item[0], bytes) else str(item[0])
            raw = item[1] if len(item) > 1 and item[1] else b""
            uid_m = re.search(r"UID (\d+)", meta)
            size_m = re.search(r"RFC822\.SIZE (\d+)", meta)
            flags = [f.decode() if isinstance(f, bytes) else f
                     for f in (imaplib.ParseFlags(meta.encode()) if "FLAGS" in meta else [])]
            msg = email.message_from_bytes(raw)
            d = parse_header_date(msg)
            ct = (msg.get_content_type() or "")
            # attachment hint from BODYSTRUCTURE: disposition "attachment" or a
            # filename parameter anywhere in the structure
            attach = bool(re.search(r'"attachment"|\("application', meta)) or \
                ct in ("multipart/mixed", "message/rfc822") or bool(msg.get_filename())
            subject = _decode_header(msg.get("Subject", "")) or ""
            in_reply_to = _decode_header(msg.get("In-Reply-To", "") or "") \
                or _decode_header(msg.get("References", "") or "")
            info = _envelope_from_message(msg)
            # Elastic shows sender in normal folders, recipients in Sent
            fromto = info["to"] if (sent and folder == sent) else info["from"]
            out.append({
                "uid": int(uid_m.group(1)) if uid_m else None,
                "size": int(size_m.group(1)) if size_m else 0,
                "flags": flags,
                "seen": "\\Seen" in flags,
                "flagged": "\\Flagged" in flags,
                "deleted": "\\Deleted" in flags,
                "answered": "\\Answered" in flags,
                "date": d,
                "attachments": attach,
                "replied": bool(in_reply_to.strip()),
                "forwarded": subject.lower().lstrip(" \t").startswith(("fwd:", "fw:", "aw:", "wg:")),
                "subject": subject,
                "fromto": fromto,
                **{k: v for k, v in info.items() if k not in ("subject",)},
            })
        return out

    def get_message(self, folder, uid, mark_seen=True):
        self.imap.select(folder)
        msg = self.imap.fetch_message(uid)
        if mark_seen and not self._is_seen(folder, uid):
            self.imap.set_flags([uid], ["\\Seen"], mode="add")
        return msg

    def _is_seen(self, folder, uid):
        typ, data = self.imap.conn.uid("FETCH", str(uid), "(FLAGS)")
        if typ == "OK" and data and data[0]:
            s = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
            return "\\Seen" in s
        return False

    def flag_state(self, folder, uid):
        self.imap.select(folder)
        typ, data = self.imap.conn.uid("FETCH", str(uid), "(FLAGS)")
        if typ == "OK" and data and data[0]:
            s = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
            return "\\Flagged" in s
        return False

    def raw_message(self, folder, uid):
        self.imap.select(folder, readonly=True)
        return self.imap.fetch_message(uid)

    def part_body(self, folder, uid, section):
        self.imap.select(folder, readonly=True)
        return self.imap.fetch_part(uid, section)

    def set_flags(self, folder, uids, flags, mode):
        self.imap.select(folder)
        self.imap.set_flags(uids, flags, mode=mode)

    def delete(self, folder, uids):
        trash = self.special("trash")
        self.imap.select(folder)
        if trash and trash != folder:
            self.imap.copy(uids, trash)
            self.imap.set_flags(uids, ["\\Deleted"], mode="add")
        else:
            self.imap.set_flags(uids, ["\\Deleted"], mode="add")
        self.imap.expunge()

    def move(self, folder, uids, dest):
        self.imap.select(folder)
        self.imap.copy(uids, dest)
        self.imap.set_flags(uids, ["\\Deleted"], mode="add")
        self.imap.expunge()

    def copy(self, folder, uids, dest):
        self.imap.select(folder)
        self.imap.copy(uids, dest)

    def empty_folder(self, folder):
        self.imap.select(folder)
        uids = self.imap.uid_search(["ALL"])
        if uids:
            self.imap.expunge()

    def save_draft(self, raw_bytes, replace_uid=None):
        drafts = self.special("drafts") or "Drafts"
        try:
            self.imap.create_folder(drafts)
        except MailError:
            pass
        if replace_uid:
            self.delete_draft(replace_uid)
        self.imap.append(drafts, raw_bytes, ["\\Draft", "\\Seen"])

    def delete_draft(self, uid):
        drafts = self.special("drafts") or "Drafts"
        try:
            self.imap.select(drafts)
            self.imap.set_flags([int(uid)], ["\\Deleted"], mode="add")
            self.imap.expunge()
        except (MailError, ValueError, TypeError):
            pass

    def send(self, msg: EmailMessage, raw_bytes):
        cfg = self
        smtp_user = getattr(self, "smtp_user", None)
        smtp_pass = getattr(self, "smtp_pass", None)
        # envelope recipients include Bcc; the header itself must not be
        # transmitted to the other recipients (RFC 5322 §5)
        rcpts = []
        for h in ("To", "Cc", "Bcc"):
            rcpts += [a for _d, a in email.utils.getaddresses([msg.get(h, "") or ""]) if a]
        if "Bcc" in msg:
            del msg["Bcc"]
        try:
            if cfg.conf("SMTP_SSL"):
                s = smtplib.SMTP_SSL(cfg.conf("SMTP_HOST"), cfg.conf("SMTP_PORT"), timeout=30)
            else:
                s = smtplib.SMTP(cfg.conf("SMTP_HOST"), cfg.conf("SMTP_PORT"), timeout=30)
                try:
                    s.starttls()
                except smtplib.SMTPException:
                    pass
            if smtp_user and smtp_pass:
                try:
                    s.login(smtp_user, smtp_pass)
                except smtplib.SMTPException:
                    pass  # relay without auth (mailpit)
            s.sendmail(msg.get("From", smtp_user or ""), rcpts, msg.as_string())
            s.quit()
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(str(e))
        sent = self.special("sent")
        if sent:
            try:
                self.imap.create_folder(sent)
            except MailError:
                pass
            self.imap.append(sent, raw_bytes, ["\\Seen"])


def build_message(from_addr, from_name, to, cc, bcc, subject, body, html=False,
                  attachments=None, in_reply_to=None, references=None, reply_to=None,
                  priority=None, mdn=False, followup_to=None):
    """Compose an RFC2822 message. attachments: [(filename, ctype, bytes)]."""
    msg = EmailMessage()
    frm = format_address(from_name, from_addr) if from_name else from_addr
    msg["From"] = frm
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    if subject:
        msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="craftcube.local")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if reply_to:
        msg["Reply-To"] = reply_to
    if followup_to:
        msg["Followup-To"] = followup_to
    if priority and priority != "3":
        msg["X-Priority"] = priority
        msg["Importance"] = {"1": "highest", "2": "high", "4": "low", "5": "lowest"}.get(priority, "normal")
    if mdn:
        msg["Disposition-Notification-To"] = frm

    if attachments:
        # EmailMessage builds multipart/mixed with the body part itself
        msg.set_content(body or "", subtype="html" if html else "plain")
        for fname, ctype, data in attachments:
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=maintype or "application",
                               subtype=subtype or "octet-stream", filename=fname)
        return msg
    if html:
        msg.set_content(body or "", subtype="html", cte="quoted-printable")
    else:
        msg.set_content(body or "")
    return msg
