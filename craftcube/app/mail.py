"""IMAP/SMTP access layer (imaplib/smtplib) with a Roundcube-like API.

One IMAP connection per request (flask.g); credentials come from the login
form (or the configured admin account when per-user passwords are disabled).
"""
import contextlib
import email
import email.utils
import imaplib
import re
import smtplib
import ssl as _ssl
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from .util import format_address, parse_header_date

# fetched envelope: uid, flags, size, date, from, to, subject, reply-to, in-reply-to, message-id, attachments hint
# LIST-POST drives the reference's per-message "ml" flag (reply-list enable)
FETCH_ITEMS = ("(FLAGS INTERNALDATE RFC822.SIZE ENVELOPE BODYSTRUCTURE "
               "BODY.PEEK[HEADER.FIELDS (LIST-POST)])")

SORTS = {
    "": (lambda m: m["uid"] or 0, True),          # no sorting (arrival order)
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
    # reference offers these two when skip_deleted is off
    # (actions/mail/index.php:1551)
    "deleted": ["DELETED"],
    "undeleted": ["UNDELETED"],
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
                with contextlib.suppress(imaplib.IMAP4.error):
                    # server without STARTTLS (local dev)
                    self.conn.starttls()
            self.conn.login(user, password)
        except (imaplib.IMAP4.error, OSError) as e:
            raise MailError(str(e)) from e
        self.selected = None

    def logout(self):
        with contextlib.suppress(Exception):
            # best-effort teardown; nothing to act on
            self.conn.logout()

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
        # Roundcube's list_sorted(): INBOX first, then special mail folders in
        # config mail_folders order (Drafts, Sent, Junk, Trash, Archive), then
        # remaining folders alphabetically.
        rc_special_order = {"drafts": 1, "sent": 2, "junk": 3, "trash": 4,
                            "archive": 5}
        out.sort(key=lambda f: (
            0 if f["name"].upper() == "INBOX" else
            rc_special_order.get(f["special"], 6),
            f["name"].lower()))
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
        typ, data = self.conn.uid("FETCH", str(uid), "(RFC822 FLAGS INTERNALDATE)")
        if typ != "OK":
            raise MailError("Message not found")
        raw = None
        idate = None
        for item in _iter_fetch(data):
            if isinstance(item, tuple) and len(item) > 1:
                meta = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                m = re.search(r"INTERNALDATE \"([^\"]+)\"", meta)
                if m:
                    idate = m.group(1)
                if item[1] and raw is None:
                    raw = item[1]
            elif isinstance(item, (bytes, str)):
                m = re.search(r"INTERNALDATE \"([^\"]+)\"",
                              item.decode() if isinstance(item, bytes) else item)
                if m:
                    idate = m.group(1)
        if raw is None:
            raise MailError("Message not found")
        msg = email.message_from_bytes(raw)
        # Roundcube's storage layer reports the INTERNALDATE as the message
        # date when there is no Date header (rcube_imap get_headers); reply
        # and forward headers depend on it.
        if idate and not msg.get("Date"):
            with contextlib.suppress(ValueError, TypeError):
                msg["Date"] = parsedate_to_datetime(idate).strftime(
                    "%a, %d %b %Y %H:%M:%S %z")
        return msg

    def fetch_part(self, uid, section):
        _typ, data = self.conn.uid("FETCH", str(uid), f"(BODY.PEEK[{section}])")
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
        # dovecot answers '[APPENDUID <valid> <uid>] ...' — hand the new uid
        # back so autosave can replace the draft it just wrote (app.js keeps
        # env.draft_id to avoid saving the same content twice)
        try:
            m = re.search(rb"\[APPENDUID \d+ (\d+)\]", msg[0])
            return int(m.group(1)) if m else None
        except (TypeError, IndexError, AttributeError):
            return None

    def expunge(self):
        self.conn.expunge()

    def quota(self):
        try:
            _typ, data = self.conn.quota("root", "")
            return data
        except Exception:
            # server without QUOTA extension (RFC 2087)
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
    # the (LIST-POST) header literal is present only when the message has one
    tail = b"".join(x for x in item[1:] if isinstance(x, bytes)).lower() if len(item) > 1 else b""
    m = {
        "ml": b"list-post" in tail,
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
        with contextlib.suppress(ValueError, TypeError):
            dt = parsedate_to_datetime(m.group(1))
            out["date"] = dt
            out["date_str"] = m.group(1)
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


def thread_messages(msgs):
    """Group messages into threads the way IMAP SORT=REFERENCES does: a message
    joins the thread of the message whose Message-ID it references; a thread is
    ordered by the sort position of its earliest message, messages within a
    thread by date (oldest first)."""
    mid_idx = {}
    for i, m in enumerate(msgs):
        if m.get("mid") and m["mid"] not in mid_idx:
            mid_idx[m["mid"]] = i
    # union-find over message indexes
    parent = list(range(len(msgs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, m in enumerate(msgs):
        for ref in m.get("refs") or []:
            j = mid_idx.get(ref)
            if j is not None:
                union(i, j)
    groups = {}
    for i in range(len(msgs)):
        groups.setdefault(find(i), []).append(i)
    out = []
    # thread rank = best (first) position of any of its messages in the sorted list
    for _root, idxs in sorted(groups.items(), key=lambda kv: min(kv[1])):
        idxs.sort(key=lambda i: msgs[i]["date"].timestamp() if msgs[i].get("date") else 0)
        for depth, i in enumerate(idxs):
            msgs[i]["depth"] = depth
        out.extend(msgs[i] for i in idxs)
    return out


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
        # user preference (Settings > Special Folders) wins over config defaults
        user_pref = (getattr(self, "prefs", None) or {}).get(kind)
        if user_pref:
            return user_pref
        try:
            conf = self.conf({"drafts": "DRAFTS_FOLDER", "sent": "SENT_FOLDER",
                              "trash": "TRASH_FOLDER", "archive": "ARCHIVE_FOLDER",
                              "junk": "JUNK_FOLDER"}[kind])
        except KeyError:
            conf = None
        for f in self.imap.list_folders():
            if f["special"] == kind:
                return f["name"]
        return conf

    def message_list(self, folder, page=1, page_size=20, sort="date", order="desc",
                     search=None, search_mods=None, search_filter="all",
                     search_interval="all", search_scope="base", threads=False):
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
            return self._paginate(merged, page, page_size, sort, order,
                                  threads=threads)
        return self._list_one(folder, page_size, search, search_mods,
                              search_filter, search_interval, page=page,
                              sort=sort, order=order, threads=threads)

    def _search_criteria(self, search, mods, search_filter, search_interval):
        crit = []
        if search_filter and search_filter != "all":
            crit += SEARCH_FILTERS.get(search_filter) or []
        elif (getattr(self, "prefs", None) or {}).get("skip_deleted") \
                and not search_filter:
            # rcube_imap::search adds UNDELETED to every listing when the
            # skip_deleted pref is on (rcube_imap.php:1500)
            crit += ["UNDELETED"]
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
            # header-based modifiers: HEADER "<name>" (Elastic offers all of these)
            headers = {"replyto": "Reply-To", "followupto": "Followup-To",
                       "bcc": "Bcc", "sender": "Sender"}
            terms = []
            for mod in mods:
                if mod in headers:
                    terms.append(["HEADER", _q(headers[mod]), _q(search)])
                    continue
                f = fields.get(mod)
                if f and [f, _q(search)] not in terms:
                    terms.append([f, _q(search)])
            if not terms:
                terms = [["TEXT", _q(search)]]
            # interleaved right-associated OR chain:
            # OR SUBJECT "x" OR FROM "x" OR TO "x" BODY "x"
            if len(terms) > 1:
                chain = []
                for idx, pair in enumerate(terms):
                    if idx < len(terms) - 1:
                        chain.append("OR")
                    chain += pair
                crit += chain
            else:
                crit += terms[0]
        return crit or ["ALL"]

    def _list_one(self, folder, page_size, search=None, mods=None,
                  search_filter="all", search_interval="all", page=1,
                  sort="date", order="desc", threads=False):
        total = self.imap.select(folder, readonly=True)
        crit = self._search_criteria(search, mods, search_filter, search_interval)
        uids = self.imap.uid_search(crit)
        MAX_SCAN = 400
        window = uids[-MAX_SCAN:]
        msgs = self._enrich(folder, window)
        return self._paginate(msgs, page, page_size, sort, order, uidvalidity=total,
                              threads=threads)

    def _paginate(self, msgs, page, page_size, sort, order, uidvalidity=0,
                  threads=False):
        key, _asc = SORTS.get(sort, SORTS["date"])
        reverse = order != "asc"
        try:
            msgs.sort(key=key, reverse=reverse)
        except TypeError:
            msgs.sort(key=lambda m: str(key(m)), reverse=reverse)
        if threads:
            msgs = thread_messages(msgs)
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
        header_fields = ("FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO "
                         "REFERENCES CONTENT-TYPE LIST-POST")
        typ, data = self.imap.conn.uid(
            "FETCH", seq,
            f"(FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE"
            f" BODY.PEEK[HEADER.FIELDS ({header_fields})])")
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
            mid = _decode_header(msg.get("Message-ID", "") or "").strip()
            refs = [r.strip() for r in
                    (msg.get("References", "") or "").replace("\n", " ").split()
                    if r.strip()]
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
                # reference 'ml' flag: presence of a List-Post header
                # (program/actions/mail/index.php:591) enables Reply list
                "ml": bool(_decode_header(msg.get("List-Post", ""))),
                "forwarded": subject.lower().lstrip(" \t").startswith(("fwd:", "fw:", "aw:", "wg:")),
                "subject": subject,
                "fromto": fromto,
                "mid": mid,
                "refs": refs,
                "reply": bool(in_reply_to.strip()),
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

    def flags_of(self, folder, uid):
        """Raw flag list of one message (used for $MDNSent before read-marking)."""
        self.imap.select(folder, readonly=True)
        typ, data = self.imap.conn.uid("FETCH", str(uid), "(FLAGS)")
        if typ == "OK" and data and data[0]:
            s = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
            # response is e.g. '44 (FLAGS (\\Seen $MDNSent))' — the FLAGS list
            # is the LAST parenthesised group (the leading item list is UID)
            start = s.rfind("(")
            end = s.rfind(")")
            if start >= 0 and end > start:
                return [f.strip() for f in s[start + 1:end].split()]
        return []

    def add_flag(self, folder, uid, flag):
        # Dovecot rejects \MDNSENT as a *system* flag; Roundcube therefore
        # uses the $MDNSent keyword (rcube_imap_generic.php:45 maps the
        # MDNSENT flag name to it). Returns whether the store succeeded.
        self.imap.select(folder)
        return bool(self.imap.set_flags([uid], [flag], mode="add"))

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
        prefs = getattr(self, "prefs", None) or {}
        trash = self.special("trash")
        self.imap.select(folder)
        if prefs.get("read_when_deleted"):
            self.imap.set_flags(uids, ["\\Seen"], mode="add")
        # 'Directly delete messages in Junk': no trash copy, straight delete
        if prefs.get("delete_junk") and self.special("junk") == folder:
            self.imap.set_flags(uids, ["\\Deleted"], mode="add")
            self.imap.expunge()
            return
        if trash and trash != folder:
            self.imap.copy(uids, trash)
            self.imap.set_flags(uids, ["\\Deleted"], mode="add")
        else:
            self.imap.set_flags(uids, ["\\Deleted"], mode="add")
        if prefs.get("flag_for_deletion"):
            return  # leave \\Deleted flags; the folder is compacted later
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
            self.imap.set_flags(uids, ["\\Deleted"], mode="add")
            self.imap.expunge()

    def logout_actions(self):
        """rcmail::logout_actions() (rcmail.php:1020): purge the Trash
        (logout_purge: 'all' or N days) and expunge INBOX (logout_expunge)."""
        from datetime import datetime, timedelta
        prefs = getattr(self, "prefs", None) or {}
        purge = str(prefs.get("logout_purge", "never") or "never")
        trash = self.special("trash")
        if purge not in ("never", "", "0", "None") and trash:
            def purge_folder(f):
                try:
                    self.imap.select(f)
                except MailError:
                    return
                uids = []
                if purge == "all":
                    uids = self.imap.uid_search(["ALL"])
                else:
                    with contextlib.suppress(ValueError):
                        days = int(purge)
                        before = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
                        uids = self.imap.uid_search(["BEFORE", before])
                if uids:
                    self.imap.set_flags(uids, ["\\Deleted"], mode="add")
                    self.imap.expunge()
            purge_folder(trash)
        if prefs.get("logout_expunge"):
            try:
                self.imap.select("INBOX")
                self.imap.expunge()
            except MailError:
                pass

    def mark_all_read(self, folder):
        self.imap.select(folder)
        uids = self.imap.uid_search(["UNSEEN"])
        if uids:
            self.imap.set_flags(uids, ["\\Seen"], mode="add")
        return len(uids)

    def compact(self, folder):
        """EXPUNGE the folder (Elastic 'Compact' action)."""
        self.imap.select(folder)
        self.imap.expunge()

    def archive(self, folder, uids):
        target = self.special("archive")
        prefs = getattr(self, "prefs", None) or {}
        if not target or target == folder:
            raise MailError("No archive folder configured")
        # 'Divide archive by' (archive plugin archive_type): subfolder per
        # year/month; unsupported groupings archive flat like 'None'.
        atype = prefs.get("archive_type") or ""
        if atype in ("year", "month", "tbmonth"):
            date = None
            try:
                envs = self.imap.fetch_envelopes([int(uids[0])])
                if envs:
                    date = envs[0].get("date")
            except Exception:
                date = None
            if date:
                y = date.strftime("%Y")
                m = date.strftime("%m")
                sub = {"year": y, "month": f"{y}/{m}",
                       "tbmonth": f"{y}/{y}-{m}"}[atype]
                target = f"{target}/{sub}"
                with contextlib.suppress(Exception):
                    # folder tree already exists (or connection hiccup; the
                    # copy below still surfaces real failures)
                    self.imap.create_folder(target)
        self.imap.select(folder)
        self.imap.copy(uids, target)
        if prefs.get("read_on_archive"):
            self.imap.set_flags(uids, ["\\Seen"], mode="add")
        self.imap.set_flags(uids, ["\\Deleted"], mode="add")
        self.imap.expunge()
        return target

    def unread_count(self, folder):
        try:
            _total, unseen = self.imap.status(folder)
            return unseen
        except Exception:
            # folder missing or STATUS unsupported
            return 0

    def quota_usage(self):
        """Return (used_bytes, quota_kb) or (0, 0) when unsupported."""
        try:
            typ, data = self.imap.conn.getquota("ROOT")
        except Exception:
            return 0, 0
        if typ != "OK" or not data or not data[0]:
            return 0, 0
        import re
        s = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
        m = re.search(r"STORAGE (\d+) (\d+)", s)
        if not m:
            return 0, 0
        return int(m.group(1)) * 1024, int(m.group(2))

    def save_draft(self, raw_bytes, replace_uid=None):
        drafts = self.special("drafts") or "Drafts"
        try:
            self.imap.create_folder(drafts)
        except MailError:
            pass
        if replace_uid:
            self.delete_draft(replace_uid)
        return self.imap.append(drafts, raw_bytes, ["\\Draft", "\\Seen"])

    def delete_draft(self, uid):
        drafts = self.special("drafts") or "Drafts"
        try:
            self.imap.select(drafts)
            self.imap.set_flags([int(uid)], ["\\Deleted"], mode="add")
            self.imap.expunge()
        except (MailError, ValueError, TypeError):
            pass

    def send(self, msg: EmailMessage, raw_bytes, store_target=None):
        """Send via SMTP, then store a copy. store_target: None → the Sent
        special folder, '' → don't store, otherwise that folder."""
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
            raise MailError(str(e)) from e
        if store_target == "":
            return
        sent = store_target or self.special("sent")
        if sent:
            try:
                self.imap.create_folder(sent)
            except MailError:
                pass
            self.imap.append(sent, raw_bytes, ["\\Seen"])


def build_message(from_addr, from_name, to, cc, bcc, subject, body, html=False,
                  attachments=None, in_reply_to=None, references=None, reply_to=None,
                  priority=None, mdn=False, followup_to=None, force_7bit=False):
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
        try:
            (body or "").encode("ascii")
            msg.set_content(body or "", subtype="html" if html else "plain")
        except UnicodeEncodeError:
            cte = "quoted-printable" if (force_7bit or html) else "8bit"
            msg.set_content(body or "", subtype="html" if html else "plain", cte=cte)
        for fname, ctype, data in attachments:
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=maintype or "application",
                               subtype=subtype or "octet-stream", filename=fname)
        return msg
    if html:
        msg.set_content(body or "", subtype="html", cte="quoted-printable")
    else:
        # rcmail_sendmail.php:292 - plain bodies with non-ASCII content use
        # quoted-printable when force_7bit is on, otherwise 8bit; pure-ASCII
        # bodies stay 7bit (set_content's own fallback)
        try:
            (body or "").encode("ascii")
            msg.set_content(body or "")
        except UnicodeEncodeError:
            msg.set_content(body or "", cte="quoted-printable" if force_7bit else "8bit")
    return msg
