"""IMAP/SMTP access layer (imaplib/smtplib) with a Roundcube-like API.

One IMAP connection per request (flask.g); credentials come from the login
form (or the configured admin account when per-user passwords are disabled).
"""
import contextlib
import email
import email.utils
import hashlib
import imaplib
import os
import random
import re
import smtplib
import ssl as _ssl
import string
import time
import unicodedata
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from . import util
from .util import format_address, parse_header_date, to_local

# fetched envelope: uid, flags, size, date, from, to, subject, reply-to, in-reply-to, message-id, attachments hint
# LIST-POST drives the reference's per-message "ml" flag (reply-list enable)
FETCH_ITEMS = ("(FLAGS INTERNALDATE RFC822.SIZE ENVELOPE BODYSTRUCTURE "
               "BODY.PEEK[HEADER.FIELDS (LIST-POST)])")

def _coll(s):
    """Sort key approximating JS localeCompare (accent- and case-blind)."""
    return "".join(c for c in unicodedata.normalize("NFD", str(s).casefold())
                   if not unicodedata.combining(c))

def _subject_key(s):
    """Dovecot subject_sort_cmp semantics: strip repeated Re:/Fw:/... prefixes,
    drop spaces, compare accent- and case-blind."""
    s = str(s or "")
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"^\s*(re|fw|fwd|aw|sv|vs):\s*", "", s, count=1, flags=re.I)
    return _coll(s).replace(" ", "").replace("\t", "")

SORTS = {
    "": (lambda m: m["uid"] or 0, True),          # no sorting (arrival order)
    "arrival": (lambda m: m["uid"] or 0, True),
    "date": (lambda m: m["date"].timestamp() if m.get("date") else 0, True),
    "subject": (lambda m: _subject_key(m.get("subject") or ""), False),
    "from": (lambda m: _coll(m.get("from") or ""), False),
    "to": (lambda m: _coll(m.get("to") or ""), False),
    "cc": (lambda m: _coll(m.get("cc") or ""), False),
    "fromto": (lambda m: _coll(m.get("from") or m.get("to") or ""), False),
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

    def list_folders(self, subscribed_only=False):
        typ, data = self.conn.list()
        subscribed = None
        if subscribed_only:
            # the reference's mail tree lists subscribed folders only
            # (rcube_imap::listfolders()). PHP's LIST RETURN (SUBSCRIBED)
            # is rejected by this Dovecot, so intersect LIST with LSUB —
            # the fallback the reference itself falls back to.
            subscribed = set()
            try:
                styp, sdata = self.conn.lsub('""', '"*"')
            except imaplib.IMAP4.error:
                styp, sdata = "NO", None
            if styp == "OK":
                import re as _re
                for line in sdata or []:
                    s = line.decode(errors="replace") if isinstance(
                        line, bytes) else str(line)
                    mm = _re.match(
                        r"^\((?P<flags>[^)]*)\)\s+(?:\".\"|NIL)\s+(?P<name>.*)$",
                        s)
                    if mm:
                        nm = mm.group("name").strip()
                        if nm.startswith('"') and nm.endswith('"'):
                            nm = nm[1:-1]
                        subscribed.add(nm)
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
        if subscribed is not None:
            # intersect with LSUB; INBOX is implicitly subscribed
            out = [f for f in out
                   if f["name"] in subscribed or f["name"].upper() == "INBOX"]
        # Roundcube's list_sorted(): INBOX first, then special mail folders in
        # config mail_folders order (Drafts, Sent, Junk, Trash, Archive), then
        # remaining folders alphabetically.
        rc_special_order = {"drafts": 1, "sent": 2, "junk": 3, "trash": 4,
                            "archive": 5}
        out.sort(key=lambda f: (
            0 if f["name"].upper() == "INBOX" else
            rc_special_order.get(f["special"], 6),
            f["name"].lower()))
        if subscribed_only and out and out[0]["name"].upper() != "INBOX":
            # INBOX is implicitly subscribed even when absent from LSUB
            out.insert(0, {"name": "INBOX", "flags": ["\\Subscribed"],
                           "special": None, "inferior": False})
        elif subscribed_only and not out:
            out = [{"name": "INBOX", "flags": ["\\Subscribed"],
                    "special": None, "inferior": False}]
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

    def create_folder(self, name, subscribe=False):
        typ, msg = self.conn.create(_q(name))
        if typ != "OK":
            raise MailError(msg)
        # rcube_imap::create_folder(): "try to subscribe it" when asked
        # (all runtime auto-creations in the reference pass subscribe=true)
        if subscribe:
            self.subscribe(name)

    def unsubscribe(self, name):
        self.conn.unsubscribe(_q(name))

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
        # keep the untouched wire bytes (exports must not carry the
        # synthesized Date; rcube get_raw_body streams the stored message)
        setattr(msg, "_raw_bytes", raw)  # noqa: B010 - dynamic payload stash
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

    def folders(self, subscribed_only=False):
        folders = self.imap.list_folders(subscribed_only=subscribed_only)
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
                and search_filter in (None, "", "all"):
            # rcube_imap::search adds UNDELETED to every listing when the
            # skip_deleted pref is on (rcube_imap.php:1500); an explicit
            # filter (e.g. 'deleted') wins over the pref
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
            if d is None:
                # rcube_imap_generic.php:2182 — non-existent/empty Date:
                # header, use INTERNALDATE
                im = re.search(r'INTERNALDATE "([^"]+)"', meta)
                if im:
                    from datetime import datetime
                    try:
                        d = to_local(datetime.strptime(
                            im.group(1), "%d-%b-%Y %H:%M:%S %z"))
                    except ValueError:
                        d = None
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
            self.imap.create_folder(drafts, subscribe=True)
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

    def send(self, msg: EmailMessage, raw_bytes, store_target=None, extra_rcpts=None):
        """Send via SMTP, then store a copy. store_target: None → the Sent
        special folder, '' → don't store, otherwise that folder.
        extra_rcpts: Bcc addresses — envelope only, never a header
        (rcmail_sendmail::send_message / create_message_header)."""
        cfg = self
        smtp_user = getattr(self, "smtp_user", None)
        smtp_pass = getattr(self, "smtp_pass", None)
        rcpts = []
        for h in ("To", "Cc"):
            rcpts += [a for _d, a in email.utils.getaddresses([msg.get(h, "") or ""]) if a]
        rcpts += [a for a in (extra_rcpts or []) if a]
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
            s.sendmail(msg.get("From", smtp_user or ""), rcpts, wire_bytes(msg))
            s.quit()
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(str(e)) from e
        if store_target == "":
            return
        sent = store_target or self.special("sent")
        if sent:
            try:
                self.imap.create_folder(sent, subscribe=True)
            except MailError:
                pass
            self.imap.append(sent, raw_bytes, ["\\Seen"])


def build_message(from_addr, from_name, to, cc, bcc, subject, body, html=False,
                  attachments=None, in_reply_to=None, references=None, reply_to=None,
                  priority=None, mdn=False, followup_to=None, force_7bit=False,
                  flowed=True, keepformatting=False):
    """Compose an RFC2822 message the way rcmail_sendmail::create_message()
    does: same header set and order (MIME-Version, Date, From, To, Cc,
    Subject, Reply-To + Mail-Reply-To, Mail-Followup-To, In-Reply-To,
    References, Message-ID, X-Sender, DNT, X-Priority), format=flowed plain
    bodies (send_format_flowed default true; keepformatting disables),
    US-ASCII charset for ASCII bodies, <md5@sender-domain> Message-IDs.
    Bcc is never a header (envelope only). attachments: [(filename, ctype, bytes)]."""
    import hashlib
    from email.message import Message
    msg = Message()   # plain Message: set_raw/items stay verbatim
    frm = format_address(from_name, from_addr) if from_name else from_addr

    enc = encode_header_value

    def hdr(name, value):
        msg.set_raw(name, enc(name, value))   # verbatim: no policy re-parse

    hdr("MIME-Version", "1.0")
    hdr("Date", email.utils.formatdate(localtime=True))
    hdr("From", frm)
    if to:
        hdr("To", ", ".join(to))
    if cc:
        hdr("Cc", ", ".join(cc))
    if subject:
        hdr("Subject", subject)
    if reply_to:
        hdr("Reply-To", reply_to)
        hdr("Mail-Reply-To", reply_to)
    if followup_to:
        hdr("Mail-Followup-To", followup_to)
    if in_reply_to:
        hdr("In-Reply-To", in_reply_to)
    if references:
        hdr("References", references)
    domain = from_addr.rpartition("@")[2] or "localhost"
    uid_seed = f"{time.time()}{os.getpid()}{random.random()}"  # noqa: S311 - id, not crypto
    hdr("Message-ID", "<" + hashlib.md5(uid_seed.encode(), usedforsecurity=False).hexdigest()
        + "@" + domain + ">")
    hdr("X-Sender", from_addr)
    if mdn:
        hdr("Disposition-Notification-To", frm)
    if priority and priority != "3":
        label = {"1": "Highest", "2": "High", "4": "Low", "5": "Lowest"}.get(str(priority))
        if label:
            hdr("X-Priority", f"{priority} ({label})")

    flowed = flowed and not keepformatting

    def line_prep(text):
        text = text or ""
        if flowed:
            text = util.format_flowed(text, 74)
        elif not keepformatting:
            text = util.wordwrap_rc(text, 72, "\r\n", False)
        text = util.wordwrap_rc(text, 998, "\r\n", True)
        return re.sub(r"\r?\n", "\r\n", text)

    def text_charset_cte(txt):
        try:
            txt.encode("ascii")
            return "US-ASCII", "7bit"
        except UnicodeEncodeError:
            pass
        return ("UTF-8", "quoted-printable") if force_7bit else ("UTF-8", "8bit")

    def text_part(txt, sub=True):
        cs, cte = text_charset_cte(txt)
        data = txt.encode("ascii" if cs == "US-ASCII" else "utf-8")
        if cte == "quoted-printable":
            data = _qp_body(data, keep_trailing=False)
        ct = "text/plain; charset=" + cs
        if flowed:
            ct += ";\r\n format=flowed"
        heads = [("Content-Transfer-Encoding", cte), ("Content-Type", ct)] if sub \
            else [("Content-Type", ct), ("Content-Transfer-Encoding", cte)]
        return _rc_part(heads, data)

    top_headers = list(msg.items())

    if html:
        body_crlf = re.sub(r"\r?\n", "\r\n", body or "")
        hosted = ('<html><head><meta http-equiv="Content-Type" content="text/html;'
                  ' charset=UTF-8" /></head><body style=\'font-size: 10pt;'
                  " font-family: Verdana,Geneva,sans-serif'>\r\n"
                  + body_crlf + "\r\n</body></html>\r\n")
        html_part = _rc_part(
            [("Content-Transfer-Encoding", "quoted-printable"),
             ("Content-Type", "text/html; charset=UTF-8")],
            _qp_body(hosted.encode("utf-8")))
        plain_body = line_prep(util.html_to_text(body or "", width=0))
        parts = []
        if plain_body.strip():
            parts.append(text_part(plain_body, sub=True))
        parts.append(html_part)
    else:
        parts = [text_part(line_prep(body))]

    if not attachments and len(parts) == 1:
        # top-level single part: Content-Type before Content-Transfer-Encoding
        solo = parts[0]
        ordered = [(n, v) for n, v in (("Content-Type", solo.get("Content-Type")),
                                       ("Content-Transfer-Encoding",
                                        solo.get("Content-Transfer-Encoding"))) if v]
        top = _rc_part(top_headers + ordered, solo.get_payload())
    elif not attachments:
        top = _rc_part(top_headers, None, children=parts,
                       content_type=f'multipart/alternative;\r\n boundary="{_boundary()}"')
    else:
        boundary = _boundary()
        if len(parts) > 1:
            body_child = _rc_part(
                [("Content-Type", f'multipart/alternative;\r\n boundary="{boundary}"')],
                None, children=parts)
        else:
            body_child = parts[0]
        pl = body_child.get_payload()
        if len(parts) == 1 and isinstance(pl, (bytes, str)) and pl and not pl.endswith("\r\n"):
            body_child.set_payload(pl + "\r\n")  # setTXTBody(..., append_newline)
        children = [body_child]
        for fname, ctype, data in attachments or []:
            children.append(_attachment_part(fname, ctype, data))
        top = _rc_part(top_headers, None, children=children,
                       content_type=f'multipart/mixed;\r\n boundary="{boundary}"')
    return top


_COMMA_HEADERS = {
    "from", "to", "cc", "bcc", "sender", "reply-to",
    "resent-from", "resent-to", "resent-cc", "resent-bcc",
    "resent-sender", "resent-reply-to", "mail-reply-to", "mail-followup-to",
    "return-receipt-to", "disposition-notification-to",
}

_Q2047_OK = set(string.ascii_letters + string.digits) | set("!*+-/")


def _encode_header_value(value, prefix_len=0):
    """Mail_mimePart::encodeMB() Q-scheme (mbstring is present in RC): walk
    characters; a multi-octet char never straddles encoded-word folds;
    line_length starts at prefix_len; folds between encoded-words."""
    prefix, suffix = "=?UTF-8?Q?", "?="
    max_len = 75 - len(prefix) - len(suffix)
    result = ""
    line_length = prefix_len
    for ch in value:
        if ch == " ":
            enc, clen = "_", 1
        elif ch.isascii() and ch in _Q2047_OK:
            enc, clen = ch, 1
        else:
            enc = "".join(f"={b:02X}" for b in ch.encode("utf-8"))
            clen = len(enc)
        if line_length + clen > max_len:
            if result:
                result += "\n"
            line_length = 0
        result += enc
        line_length += clen
    return prefix + result.replace("\n", suffix + "\r\n " + prefix) + suffix


def _php_wordwrap(text, width=76, brk="\r\n "):
    """PHP wordwrap(): '\n'-delimited lines wrapped independently at spaces."""
    out = []
    for line in text.split("\n"):
        cur = ""
        parts = []
        started = False
        for word in line.split(" "):
            if not started:
                cur, started = word, True
            elif len(cur) + 1 + len(word) <= width:
                cur += " " + word
            else:
                parts.append(cur)
                cur = word
        parts.append(cur)
        out.append(brk.join(parts))
    return "\n".join(out)


_EMAIL_RX = re.compile(r'(<[^<>\s"@]+@[^<>\s"@]+>|[^\s<>"@]+@[^\s<>"@]+)$')


def encode_header_value(name, value):
    """Mail_mimePart::encodeHeader(): structured address headers keep the
    addr-spec raw and Q-encode only the display phrase; other headers are
    encoded whole when they contain non-ASCII."""
    if not value:
        return value
    if name.lower() in _COMMA_HEADERS:
        parts, cur, quoted = [], "", False
        for ch in value:
            if ch == '"':
                quoted = not quoted
            if ch == "," and not quoted:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        acc = ""
        for part in parts:
            part = re.sub(r"\r?\n[\s\t]*", " ", part).strip()
            if not part:
                continue
            acc += ", " if acc else f"{name}: "
            m = _EMAIL_RX.search(part)
            if m:
                addr = m.group(0)
                word = part[:m.start()].strip()
                if word and not word.isascii():
                    if len(word) > 1 and word[0] == '"' and word[-1] == '"':
                        word = word[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                    pos = acc.rfind("\r\n")
                    last_len = len(acc) - (pos + 2) if pos != -1 else len(acc)
                    word = _encode_header_value(word, last_len)
                elif word and not (word[0] == '"' and word[-1] == '"') \
                        and re.search(r'[()<>\.\[\]@,;:"]', word):
                    word = '"' + word.replace("\\", "\\\\").replace('"', '\\"') + '"'
                acc += (word + " " + addr) if word else addr
            else:
                # Mail_mime: no addr-spec found, don't encode
                acc += part
            acc = _php_wordwrap(acc, 76, "\r\n ")
        return re.sub(rf"^{re.escape(name)}:(\r\n)* ", "", acc)
    if not re.search(r"[^\s!-~]", value):
        return value
    if len(value) > 1 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].replace('\"', '"').replace("\\\\", "\\")
    return _encode_header_value(value, len(name) + 2)


def _b64_body(data):
    import base64
    b64 = base64.encodebytes(data).rstrip(b"\n")
    return b64.replace(b"\n", b"\r\n")   # chunk_split($s, 76, CRLF), no trailing CRLF


def _qp_body(data, keep_trailing=True):
    import quopri
    out = quopri.encodestring(re.sub(rb"\r\n", b"\n", data)).replace(b"\n", b"\r\n")
    trailing = out.endswith(b"\r\n") and data.endswith(b"\r\n")
    out = re.sub(rb"(\r\n)+$", b"", out)
    return out + (b"\r\n" if keep_trailing and trailing else b"")


def _boundary():
    # Mail_mime uniqueid(): '=_<md5 hex>'
    seed = f"{time.time()}{os.getpid()}{random.random()}"  # noqa: S311 - id, not crypto
    return "=_" + hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()


def _rc_part(headers, payload=None, children=None, content_type=None):
    """Raw header/value MIME node (email.message.Message with set_raw)."""
    from email.message import Message
    p = Message()
    for n, v in headers:
        p.set_raw(n, v)
    if content_type:
        p.set_raw("Content-Type", content_type)
    if children is not None:
        p.set_payload(list(children))
    elif payload is not None:
        p.set_payload(payload)
    return p


def _attachment_part(fname, ctype, data):
    """Mail_mimePart subpart: CTE first, then Content-Type with name= and
    Content-Disposition with filename= on a folded line (RFC2231 if non-ASCII)."""
    def qname(key, val):
        if val.isascii() and not re.search(r'[\s"\\:;<>,@\[\]()]', val):
            return key + "=" + val          # Mail_mime: atom, unquoted
        from urllib.parse import quote
        if val.isascii():
            return f'{key}="{val.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"'
        return f"{key}*0*=UTF-8''{quote(val, safe='')}"
    disp = f"attachment;\r\n {qname('filename', fname)};\r\n size={len(data)}"
    return _rc_part(
        [("Content-Transfer-Encoding", "base64"),
         ("Content-Type", (ctype or "application/octet-stream")
          + ";\r\n " + qname("name", fname)),
         ("Content-Disposition", disp)],
        _b64_body(data))


def wire_bytes(msg) -> bytes:
    """Serialize verbatim with CRLF like PHP Mail_mime: headers, blank line,
    body; multipart children each behind '--boundary', closing '--boundary--'."""
    def ser(m):
        buf = bytearray()
        for n, v in m.items():
            buf += (f"{n}: {v}" + "\r\n").encode("utf-8")
        payload = m.get_payload()
        if isinstance(payload, list):
            mm = re.search(r'boundary="([^"]+)"', m.get("Content-Type") or "")
            b = (mm.group(1) if mm else "boundary").encode()
            buf += b"\r\n"
            for child in payload:
                buf += b"--" + b + b"\r\n"
                buf += ser(child)
                buf += b"\r\n"
            buf += b"--" + b + b"--\r\n"
        else:
            buf += b"\r\n"
            if isinstance(payload, (bytes, bytearray)):
                buf += bytes(payload)
            elif payload is not None:
                buf += str(payload).encode("utf-8")
        return bytes(buf)
    return ser(msg)
