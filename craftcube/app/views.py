"""All HTTP views: login, mail, compose, addressbook, settings."""
import email
import functools
import io

from flask import (Blueprint, Response, abort, current_app, flash, g,
                   redirect, render_template, request, session, url_for,
                   make_response)

from .auth import hash_password, verify_password
from .mail import Imap, MailError, Mailbox, build_message, _decode_header
from . import util

bp = bp_current = Blueprint("views", __name__)


# ---------------------------------------------------------------- helpers

def login_required(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("views.login", _next=request.path))
        return f(*a, **kw)
    return wrapper


def get_store():
    return current_app.store


def imap_box():
    """Open the per-request IMAP-backed mailbox (cached on flask.g)."""
    if getattr(g, "_mailbox", None) is not None:
        return g._mailbox
    cfg = current_app.config
    username = session["username"]
    password = session.get("imap_password") or ""
    if not current_app.config["PER_USER_PASSWORDS"]:
        username = cfg.get("IMAP_ADMIN_USER") or username
        password = cfg.get("IMAP_ADMIN_PASS") or password
    try:
        imap = Imap(cfg["IMAP_HOST"], cfg["IMAP_PORT"], username, password, cfg["IMAP_SSL"])
    except MailError as e:
        raise e
    box = Mailbox(imap, cfg, default_email=username)
    box.smtp_user, box.smtp_pass = username, password
    box.prefs = current_app.store.get_user_prefs(session.get("user_id") or 0)
    g._mailbox = box
    return box


@bp.teardown_request
def _close_imap(exc):
    box = getattr(g, "_mailbox", None)
    if box is not None:
        box.imap.logout()


@bp.before_request
def _load_user():
    if session.get("user_id"):
        g.user = get_store().get_user(session["username"])
        g.prefs = get_store().get_user_prefs(session["user_id"])


def folder_label(name, prefs=None):
    """Roundcube-style folder display name: INBOX -> Inbox, basename of subfolders,
    special folders titled-cased; raw name when 'show_real_foldernames' is on."""
    if (prefs or {}).get("show_real_foldernames"):
        return name
    base = name.rsplit("/", 1)[-1]
    if base.upper() == "INBOX":
        return "Inbox"
    return base[:1].upper() + base[1:]


def folders_for_menu():
    prefs = g.get("prefs") or {}
    out = []
    for f in imap_box().folders():
        f = dict(f)
        f["display"] = folder_label(f["name"], prefs)
        out.append(f)
    return out


def render(task, tmpl, **ctx):
    g.task = task
    ctx.setdefault("folders", folders_for_menu())
    return render_template(tmpl, **ctx)


def parse_recipients(value):
    out = []
    for part in (value or "").replace("\n", ",").split(","):
        part = part.strip()
        if "@" in part or "<" in part:
            out.append(part)
    return out


def identity_from_form(form, existing=None):
    return {
        "name": form.get("name", "").strip(),
        "organization": form.get("organization", "").strip(),
        "email": form.get("email", "").strip(),
        "reply_to": form.get("reply_to", "").strip(),
        "bcc": form.get("bcc", "").strip(),
        "signature": form.get("signature", ""),
        "html_signature": 1 if form.get("html_signature") else 0,
        "standard": 1 if form.get("standard") else 0,
    }


# ---------------------------------------------------------------- login

@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("views.mail"))
    error = None
    if request.method == "POST":
        username = request.form.get("_user", "").strip()
        password = request.form.get("_pass", "")
        cfg = current_app.config
        store = get_store()
        ok, auth_user, auth_pass = False, username, password
        if not cfg["PER_USER_PASSWORDS"] and cfg.get("IMAP_ADMIN_PASS"):
            auth_user, auth_pass = cfg.get("IMAP_ADMIN_USER", username), cfg["IMAP_ADMIN_PASS"]
        try:
            Imap(cfg["IMAP_HOST"], cfg["IMAP_PORT"], auth_user, auth_pass, cfg["IMAP_SSL"]).logout()
            ok = True
        except MailError:
            ok = False
        if not ok:
            # fall back to stored hash (offline IMAP / local accounts)
            u = store.get_user(username)
            ok = bool(u and verify_password(password, u["password"]))
        if ok:
            u = store.get_user(username)
            if not u:
                uid = store.create_user(username, hash_password(password))
            else:
                uid = u["user_id"]
                if password:
                    store.set_user_password(uid, hash_password(password))
            store.touch_login(uid)
            session["user_id"] = uid
            session["username"] = username
            session["imap_password"] = password
            # make sure default identity exists
            if not store.identities(uid):
                store.identity_save(uid, {
                    "name": username, "organization": "", "email": username,
                    "reply_to": "", "bcc": "", "signature": "", "html_signature": 0, "standard": 1,
                })
            return redirect(request.args.get("_next") or url_for("views.mail"))
        error = "Login failed. Check your user name and password."
    return render_template("login.html", task="login", error=error,
                           folders=[], product_name=current_app.config["PRODUCT_NAME"])


@bp.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("views.login"))


# ---------------------------------------------------------------- mail

@bp.route("/")
@login_required
def index():
    return redirect(url_for("views.mail"))


@bp.route("/mail")
@login_required
def mail():
    box = imap_box()
    folder = request.args.get("_mbox") or "INBOX"
    page = int(request.args.get("_page", 1) or 1)
    sort = request.args.get("_sort")
    if sort is None:
        sort = "date"
    order = request.args.get("_sort_order") or "desc"
    search = request.args.get("_q") or ""
    mods = []
    for m in request.args.getlist("_sm") + (request.args.get("_sm_csv") or "").split(","):
        mods += [x for x in m.split(",") if x]
    sfilter = request.args.get("_sf") or "all"
    sinterval = request.args.get("_si") or "all"
    sscope = request.args.get("_ss") or "base"
    list_mode = request.args.get("_mode") or (
        "threads" if (getattr(box, "prefs", None) or {}).get("viewmode") == "threads" else "list")
    searching = bool(search or sfilter != "all" or sinterval != "all")
    try:
        pspec = (getattr(box, "prefs", {}).get("mail_pagesize")
                 or getattr(box, "prefs", {}).get("pagesize"))
        listing = box.message_list(folder, page=page, sort=sort, order=order,
                                   page_size=(int(pspec) if pspec else None) or 20,
                                   search=search or None, search_mods=mods or None,
                                   search_filter=sfilter, search_interval=sinterval,
                                   search_scope=sscope if searching else "base",
                                   threads=(list_mode == "threads"))
    except MailError as e:
        flash(str(e), "error")
        listing = {"items": [], "page": 1, "pages": 1, "total": 0, "first": 0, "last": 0, "uids": []}
    uid = request.args.get("_uid")
    quota_used, quota_kb = (0, 0)
    try:
        quota_used, quota_kb = box.quota_usage()
    except Exception:
        pass
    return render("mail", "mail.html", folder=folder,
                  folder_title=folder_label(folder, getattr(box, "prefs", None) or g.get("prefs") or {}),
                  listing=listing,
                  sort=sort, order=order, search=search,
                  search_mods=mods, search_filter=sfilter,
                  search_interval=sinterval, search_scope=sscope,
                  list_mode=list_mode,
                  searching=searching, preview_uid=uid,
                  quota_used=quota_used, quota_kb=quota_kb,
                  message_count=listing["total"])


def _msg_date(msg):
    dt = util.parse_header_date(msg)
    return util.to_local(dt) if dt else None


def _hdr(msg, name):
    v = msg.get(name)
    return _decode_header(str(v)) if v else ""


def build_message_ctx(box, folder, uid, mark_seen=True, allow_remote=None):
    try:
        msg = box.get_message(folder, uid, mark_seen=mark_seen)
    except MailError:
        abort(404)
    parts = []
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_disposition() == "attachment":
                continue
            if p.get_content_type() in ("text/plain", "text/html"):
                parts.append(p)
    else:
        parts = [msg]
    sender_domain = ""
    fm = email.utils.parseaddr(_hdr(msg, "From"))[1]
    if "@" in fm:
        sender_domain = fm.rsplit("@", 1)[1].lower()
    # remote-content protection (Elastic: "To protect your privacy remote
    # resources have been blocked." + Allow button, allowed per sender)
    allowed = allow_remote
    if allowed is None:
        allowed = sender_domain in (get_store().get_user_prefs(
            session["user_id"]).get("remote_senders") or [])
    rendered = []
    remote_blocked = False
    for p in parts:
        try:
            payload = p.get_payload(decode=True) or b""
            charset = p.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            text, charset = "", "utf-8"
        if p.get_content_type() == "text/html":
            safe = util.sanitize_html(text)
            if not allowed and util.contains_remote_content(safe):
                safe = util.block_remote_content(safe)
                remote_blocked = True
            rendered.append(("html", safe))
        else:
            rendered.append(("plain", text))
    headers = []
    for h in ("From", "To", "Cc", "Bcc", "Subject", "Date", "Reply-To",
              "Followup-To", "Message-ID", "In-Reply-To", "References"):
        v = _hdr(msg, h)
        if v:
            headers.append((h, v))
    attachments = []
    if msg.is_multipart():
        for i, p in enumerate(msg.walk()):
            fn = p.get_filename()
            if fn or p.get_content_disposition() == "attachment":
                attachments.append({
                    "part": str(i),
                    "filename": fn or f"part{i}.bin",
                    "ctype": p.get_content_type(),
                    "size": len(p.get_payload(decode=True) or b""),
                })
    # prev/next within the folder (arrival order; matches date-desc listings)
    prev_uid = next_uid = None
    try:
        uids = sorted(int(u) for u in box.imap.conn.uid("SEARCH", None, "ALL")[1][0].split())
    except Exception:
        uids = []
    try:
        i = uids.index(int(uid))
        prev_uid = uids[i + 1] if i + 1 < len(uids) else None   # newer = previous entry
        next_uid = uids[i - 1] if i > 0 else None
    except (ValueError, IndexError):
        pass
    return dict(folder=folder, uid=uid, msg=msg,
                subject=_hdr(msg, "Subject") or "(no subject)",
                headers=headers, parts=rendered, attachments=attachments,
                sender=util.header_addresses(msg, "From")[:1],
                sender_domain=sender_domain,
                remote_blocked=remote_blocked,
                date=_msg_date(msg), prev_uid=prev_uid, next_uid=next_uid)


@bp.route("/message")
@login_required
def message_view():
    box = imap_box()
    folder = request.args.get("_mbox") or "INBOX"
    uid = request.args.get("_uid")
    if not uid:
        abort(404)
    if request.args.get("_source"):
        raw = box.raw_message(folder, uid)
        return Response(raw.as_string(), mimetype="text/plain; charset=utf-8")
    framed = request.args.get("_framed") == "1"
    ctx = build_message_ctx(box, folder, uid,
                            mark_seen=request.args.get("_noseen") != "1",
                            allow_remote=True if request.args.get("_load") == "remote" else None)
    if request.args.get("_load") == "remote" and ctx["sender_domain"]:
        prefs = get_store().get_user_prefs(session["user_id"])
        senders = set(prefs.get("remote_senders") or [])
        senders.add(ctx["sender_domain"])
        get_store().set_user_pref(session["user_id"], "remote_senders", sorted(senders))
        ctx = build_message_ctx(box, folder, uid, mark_seen=False, allow_remote=True)
        ctx["remote_blocked"] = False
    ctx["framed"] = framed
    ctx["print"] = request.args.get("_print") == "1"
    # prev/next navigation within the folder (same order as the message list)
    prev_uid = next_uid = None
    if not framed:
        try:
            order_uids = box.message_list(folder, page=1, page_size=100000,
                                          sort="date", order="desc")["uids"]
            if uid in order_uids:
                idx = order_uids.index(uid)
                prev_uid = order_uids[idx + 1] if idx + 1 < len(order_uids) else None
                next_uid = order_uids[idx - 1] if idx > 0 else None
        except Exception:
            pass
    ctx["prev_uid"] = prev_uid
    ctx["next_uid"] = next_uid
    if framed:
        return render_template("message_part.html", **ctx, task="mail")
    return render("mail", "message.html", **ctx)


@bp.route("/message/export")
@login_required
def message_export():
    """Export messages — the zipdownload plugin's three formats:
    eml (single raw .eml), mbox (zip with one RFC4155 mbox), maildir
    (zip with '<uid> <subject>.eml' entries)."""
    box = imap_box()
    folder = request.args.get("_mbox") or "INBOX"
    uids = (request.form.getlist("_uids[]") + request.args.getlist("_uids[]")
            if request.method == "POST" else list(request.args.getlist("_uids[]")))
    uid = request.args.get("_uid")
    if uid and uid not in uids:
        uids.append(uid)
    if not uids:
        abort(404)
    fmt = request.args.get("_format") or "eml"
    import io as _io
    import re as _re
    import zipfile

    def raw_for(u):
        try:
            raw = box.raw_message(folder, u)
        except MailError:
            abort(404)  # unknown uid: 404, not a server error
        if raw is None:
            abort(404)
        return raw

    if fmt == "eml" and len(uids) == 1:
        raw = raw_for(uids[0])
        subject = _hdr(raw, "Subject") or "message"
        fname = _re.sub(r"[^A-Za-z0-9 ._-]", "_", subject)[:80] + ".eml"
        return Response(raw.as_string(), mimetype="message/rfc822", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{fname}",
        })

    from email.utils import parseaddr
    from datetime import timezone as _tz
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if fmt == "mbox":
            body = b""
            for u in uids:
                raw = raw_for(u)
                frm = parseaddr(str(raw.get("From", "")))[1] or "MAILER-DAEMON"
                frm = _re.sub(r"\s", "-", frm)
                d = _msg_date(raw) or util.to_local(__import__("datetime").datetime.now(_tz.utc))
                # RFC4155 "From " separator line + escaped in-body separators
                body += (
                    f"From {frm} {d.strftime('%a %b %d %H:%M:%S %Y')}\r\n".encode()
                    + _re.sub(rb"(?m)^From ", b">From ", raw.as_bytes()) + b"\n")
            z.writestr("messages.mbox", body)
            zname = "messages.zip"
        else:  # maildir: <folder>/<uid> <subject>.eml
            for u in uids:
                raw = raw_for(u)
                subject = _hdr(raw, "Subject") or ""
                subject = _re.sub(r"[^A-Za-z0-9 ._ -]", "", subject)[:16]
                path = folder.replace("/", "/") + "/" if folder.upper() != "INBOX" else ""
                z.writestr(f"{path}{u}{' ' + subject if subject else ''}.eml", raw.as_string())
            zname = folder.rsplit("/", 1)[-1] + ".zip"
    return Response(buf.getvalue(), mimetype="application/zip", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{zname}",
    })


@bp.post("/message/import")
@login_required
def message_import():
    """Import messages into a folder (Elastic 'Import' — MIME or Mbox upload)."""
    box = imap_box()
    folder = request.form.get("_mbox") or "INBOX"
    f = request.files.get("_file")
    if not f or not f.filename:
        flash("No file uploaded.", "error")
        return redirect(url_for("views.mail", _mbox=folder))
    data = f.read()
    fmt = request.form.get("_format") or "MIME"
    count = 0
    try:
        if fmt == "Mbox":
            import mailbox as _mb
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tf:
                tf.write(data)
                tname = tf.name
            for msg in _mb.mbox(tname):
                box.imap.append(folder, msg.as_bytes())
                count += 1
            import os as _os
            _os.unlink(tname)
        else:
            box.imap.append(folder, data)
            count = 1
        flash(f"{count} message(s) imported.", "confirmation")
    except Exception as e:  # noqa: BLE001
        flash(f"Import failed: {e}", "error")
    return redirect(url_for("views.mail", _mbox=folder))


@bp.route("/attachment")
@login_required
def attachment():
    box = imap_box()
    folder = request.args.get("_mbox") or "INBOX"
    uid = request.args.get("_uid")
    part = request.args.get("_part")
    if not (uid and part is not None):
        abort(404)
    raw = box.raw_message(folder, uid)
    target = None
    if raw.is_multipart():
        for i, p in enumerate(raw.walk()):
            if str(i) == str(part):
                target = p
                break
    if target is None:
        abort(404)
    data = target.get_payload(decode=True) or b""
    fn = target.get_filename() or "attachment.bin"
    ctype = target.get_content_type()
    disposition = "inline" if request.args.get("_inline") else "attachment"
    return Response(data, mimetype=ctype, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{fn}",
    })


def _uids_from_request():
    uids = request.form.getlist("_uids[]") or request.form.getlist("_uids")
    if not uids and request.form.get("_uid"):
        uids = [request.form["_uid"]]
    return [int(u) for u in uids]


@bp.post("/mail/act")
@login_required
def mail_act():
    box = imap_box()
    folder = request.form.get("_mbox_override") or request.form.get("_mbox") or "INBOX"
    command = request.form.get("_act")
    uids = _uids_from_request()
    # cross-folder actions from a search-across-folders listing
    box_map = request.form.get("_box_map")
    if box_map:
        grouped = {}
        for pair in box_map.split(","):
            if ":" in pair:
                u, b = pair.split(":", 1)
                grouped.setdefault(b, []).append(int(u))
        for b, us in grouped.items():
            _run_mail_action(box, command, b, us)
        return redirect(request.form.get("_return") or url_for("views.mail", _mbox=folder))
    if uids or command in ("empty", "markallread", "compact"):
        # 'Show next message after delete' preference: remember the neighbour of
        # the deleted message BEFORE deleting, to reopen it after the redirect.
        ret_uid = request.form.get("_return_uid", "")
        next_preview = None
        if (command == "delete" and ret_uid
                and (getattr(box, "prefs", None) or {}).get("display_next")):
            try:
                next_preview = _next_uid_after(box, folder, ret_uid, uids)
            except Exception:
                next_preview = None
        try:
            _run_mail_action(box, command, folder, uids,
                             dest=request.form.get("_dest"))
        except MailError as e:
            flash(str(e), "error")
        if next_preview:
            return redirect(url_for("views.mail", _mbox=folder, _uid=next_preview))
    nxt = request.form.get("_return") or url_for("views.mail", _mbox=folder)
    return redirect(nxt)


def _next_uid_after(box, folder, ref_uid, removed):
    """First remaining uid after ref_uid (newest-first order), given the
    folder's uid order BEFORE the removal."""
    uids = [str(u) for u in box.message_list(folder, page=1, page_size=100000,
                                             sort="date", order="desc")["uids"]]
    removed = {str(u) for u in removed}
    try:
        idx = uids.index(str(ref_uid))
    except ValueError:
        idx = 0
    for u in uids[idx + 1:]:
        if u not in removed:
            return u
    for u in reversed(uids[:idx]):
        if u not in removed:
            return u
    return None


def _run_mail_action(box, command, folder, uids, dest=None):
    try:
        if command == "read":
            box.set_flags(folder, uids, ["\\Seen"], "add")
        elif command == "unread":
            box.set_flags(folder, uids, ["\\Seen"], "remove")
        elif command in ("flag", "flagtoggle"):
            if command == "flagtoggle":
                state = box.flag_state(folder, uids[0]) if len(uids) == 1 else False
                box.set_flags(folder, uids, ["\\Flagged"], "remove" if state else "add")
            else:
                box.set_flags(folder, uids, ["\\Flagged"], "add")
        elif command == "unflag":
            box.set_flags(folder, uids, ["\\Flagged"], "remove")
        elif command == "delete":
            box.delete(folder, uids)
            flash(f"{len(uids)} message(s) deleted.", "confirmation")
        elif command == "archive":
            target = box.archive(folder, uids)
            flash(f"Archived to {target}.", "confirmation")
        elif command == "compact":
            box.compact(folder)
            flash(f"Folder {folder} compacted.", "confirmation")
        elif command == "empty":
            box.empty_folder(folder)
            flash(f"Folder {folder} emptied.", "confirmation")
        elif command == "markallread":
            n = box.mark_all_read(folder)
            flash(f"{n} message(s) marked as read.", "confirmation")
        elif command == "move":
            if dest:
                box.move(folder, uids, dest)
                flash(f"Moved to {dest}.", "confirmation")
        elif command == "copy":
            if dest:
                box.copy(folder, uids, dest)
                flash(f"Copied to {dest}.", "confirmation")
    except MailError as e:
        flash(str(e), "error")


# ---------------------------------------------------------------- compose

def _quote(msg, header=True):
    frm = msg.get("From", "")
    dt = util.parse_header_date(msg)
    body = ""
    for p in (msg.walk() if msg.is_multipart() else [msg]):
        if p.get_content_type() == "text/plain":
            try:
                body = (p.get_payload(decode=True) or b"").decode(p.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                body = ""
            break
    if not body:
        for p in (msg.walk() if msg.is_multipart() else [msg]):
            if p.get_content_type() == "text/html":
                try:
                    raw = (p.get_payload(decode=True) or b"").decode(p.get_content_charset() or "utf-8", errors="replace")
                    body = util.sanitize_html(raw)
                except Exception:
                    body = ""
                break
    if header:
        body = f"\n\nOn {util.fmt_datetime(dt)}, {frm} wrote:\n" + \
               "\n".join("> " + l for l in body.splitlines())
    return body


@bp.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    box = imap_box()
    store = get_store()
    uid_of = request.args.get("_uid") or request.form.get("_uid")
    mode = request.args.get("_mode") or request.form.get("_mode") or ""
    draft_uid = request.args.get("_draft") or request.form.get("_draft")
    identities = store.identities(session["user_id"])
    folders = folders_for_menu()

    prefill = {"to": "", "cc": "", "bcc": "", "subject": "", "body": "", "html": "",
               "in_reply_to": "", "references": "", "reply_to": "", "followup_to": "",
               "priority": "3", "mdn": False, "dsn": False}
    # defaults from Settings > Preferences (Composing Messages)
    prefs = getattr(box, "prefs", None) or {}
    prefill["mdn"] = bool(prefs.get("mdn_default"))
    prefill["dsn"] = bool(prefs.get("dsn_default"))
    # Roundcube semantics: reply_all_mode 1 = reply to mailing list only;
    # forward_attachment 1 = forward as attachment. Legacy values still work.
    if mode == "reply" and str(prefs.get("reply_mode", "0")) in ("all",):
        mode = "replyall"
    elif mode == "reply" and (str(prefs.get("reply_mode", "0")) == "list"
                              or str(prefs.get("reply_all_mode", "0")) == "1"):
        mode = "replylist"
    if mode == "forward" and (prefs.get("forward_mode") == "attachment"
                              or str(prefs.get("forward_attachment", "0")) == "1"):
        mode = "forward-attachment"
    attachments_kept = []
    attach_original = None   # (filename, bytes) for forward-as-attachment
    source_msg = None
    if uid_of:
        src_folder = request.values.get("_mbox") or "INBOX"
        try:
            source_msg = box.raw_message(src_folder, uid_of)
        except MailError:
            source_msg = None
    elif draft_uid:
        drafts = box.special("drafts")
        try:
            source_msg = box.raw_message(drafts, draft_uid) if drafts else None
            mode = "draft"
        except MailError:
            source_msg = None

    def _orig_filename():
        s = _decode_header(source_msg.get("Subject", "") or "") or "message"
        import re as _re
        return _re.sub(r"[^A-Za-z0-9 ._-]", "_", s)[:80] + ".eml"

    if source_msg is not None:
        if mode == "reply":
            rt = source_msg.get("Reply-To") or source_msg.get("From")
            prefill["to"] = _decode_header(rt) if rt else ""
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
            prefill["body"] = _quote(source_msg)
            prefill["in_reply_to"] = source_msg.get("Message-ID", "") or ""
            prefill["references"] = " ".join(
                x for x in ([_decode_header(source_msg.get("References", "") or "")]
                            + ([prefill["in_reply_to"]] if prefill["in_reply_to"] else [])) if x)
        elif mode == "replyall":
            addrs = []
            for h in ("Reply-To", "From", "To", "Cc"):
                v = source_msg.get(h)
                if v:
                    for disp, addr in email.utils.getaddresses([v]):
                        if addr and addr.lower() != session["username"].lower():
                            addrs.append(util.format_address(disp, addr))
            seen = set()
            uniq = [a for a in addrs if not (a.lower() in seen or seen.add(a.lower()))]
            prefill["to"] = uniq[0] if uniq else ""
            prefill["cc"] = ", ".join(uniq[1:])
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
            prefill["body"] = _quote(source_msg)
            prefill["in_reply_to"] = source_msg.get("Message-ID", "") or ""
        elif mode == "replylist":
            ml = source_msg.get("List-Post") or source_msg.get("Reply-To") or source_msg.get("From")
            v = _decode_header(ml) if ml else ""
            # List-Post looks like <mailto:team@list.example>
            import re as _re
            m = _re.search(r"mailto:([^>\s]+)", v or "")
            prefill["to"] = m.group(1) if m else (v or "")
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
            prefill["body"] = _quote(source_msg)
            prefill["in_reply_to"] = source_msg.get("Message-ID", "") or ""
        elif mode in ("forward", "forward-attachment", "bounce"):
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            if mode == "bounce":
                # resend verbatim: same To/Subject/attachments, no quoting
                prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
                prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
                prefill["subject"] = subj
                prefill["body"] = _quote(source_msg, header=False)
                prefill["in_reply_to"] = ""
            else:
                prefill["subject"] = subj if subj.lower().startswith(("fw:", "fwd:")) else f"Fwd: {subj}"
                prefill["body"] = _quote(source_msg, header=True)
                prefill["in_reply_to"] = ""
            if mode == "forward-attachment":
                attach_original = (_orig_filename(), box.raw_message(
                    request.values.get("_mbox") or "INBOX", uid_of).as_bytes())
            else:
                for p in source_msg.walk() if source_msg.is_multipart() else []:
                    if p.get_filename():
                        attachments_kept.append({
                            "filename": p.get_filename(),
                            "ctype": p.get_content_type(),
                            "data": p.get_payload(decode=True) or b"",
                            "size": len(p.get_payload(decode=True) or b""),
                        })
        elif mode == "edit":  # edit as new: keep everything verbatim
            prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
            prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
            prefill["subject"] = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["body"] = _quote(source_msg, header=False)
            for p in source_msg.walk() if source_msg.is_multipart() else []:
                if p.get_filename():
                    attachments_kept.append({
                        "filename": p.get_filename(),
                        "ctype": p.get_content_type(),
                        "data": p.get_payload(decode=True) or b"",
                        "size": len(p.get_payload(decode=True) or b""),
                    })
        else:  # draft / compose-from-message
            prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
            prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
            prefill["subject"] = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["body"] = _quote(source_msg, header=False)
            for p in source_msg.walk() if source_msg.is_multipart() else []:
                if p.get_filename():
                    attachments_kept.append({
                        "filename": p.get_filename(),
                        "ctype": p.get_content_type(),
                        "data": p.get_payload(decode=True) or b"",
                        "size": len(p.get_payload(decode=True) or b""),
                    })

    if request.method == "POST":
        ident_id = request.form.get("_ident")
        ident = store.identity(session["user_id"], ident_id) if ident_id else store.default_identity(session["user_id"])
        ident = ident or {"name": session["username"], "email": session["username"]}
        to = parse_recipients(request.form.get("_to"))
        cc = parse_recipients(request.form.get("_cc"))
        bcc = parse_recipients(request.form.get("_bcc"))
        subject = request.form.get("_subject", "")
        body = request.form.get("_body", "")
        html = request.form.get("_format") == "html"
        if not to and not cc and not bcc:
            flash("No recipients given.", "error")
            return render("mail", "compose.html", prefill=prefill, identities=identities,
                          folders=folders, error="No recipients given.")
        files = request.files.getlist("_file")
        attachments = [(f.filename, f.mimetype, f.read()) for f in files if f.filename]
        attachments += [(a["filename"], a["ctype"], a["data"]) for a in attachments_kept]
        if attach_original:
            attachments.append((attach_original[0], "message/rfc822", attach_original[1]))

        msg = build_message(
            ident["email"], ident["name"], to, cc, bcc, subject, body, html=html,
            attachments=attachments or None,
            in_reply_to=request.form.get("_in_reply_to") or None,
            references=request.form.get("_references") or None,
            reply_to=request.form.get("_reply_to") or None,
            followup_to=request.form.get("_followupto") or None,
            priority=request.form.get("_priority") or None,
            mdn=bool(request.form.get("_mdn")),
        )
        act = request.form.get("_action", "send")
        try:
            if act == "save":
                # the draft keeps its Bcc header
                box.save_draft(msg.as_bytes(), replace_uid=int(draft_uid) if draft_uid else None)
                flash("Draft saved.", "confirmation")
                return redirect(url_for("views.mail", _mbox=box.special("drafts") or "Drafts"))
            # smtplib needs the combined recipient list (incl. Bcc); the
            # transmitted header block and the Sent copy must not carry Bcc
            store_target = request.form.get("_store_target")
            box.send(msg, msg.as_bytes(),
                     store_target=store_target if store_target is not None else None)
            if draft_uid:
                box.delete_draft(draft_uid)
            # 'Collected addresses' prefs: store recipients (type 1) and the
            # replied-to sender as a trusted sender (type 2), like Roundcube.
            try:
                up = getattr(box, "prefs", None) or {}
                cr = str(up.get("collected_recipients", "1"))
                if cr == "1":
                    import email.utils as _eu
                    for raw in (to + cc + bcc):
                        nm, addr = _decode_header(raw.rsplit("<", 1)[0] if "<" in raw else raw), \
                            _eu.parseaddr(raw)[1]
                        if addr:
                            store.collected_upsert(session["user_id"], 1,
                                                   (nm or "").strip() or addr, addr)
                if mode in ("reply", "replyall", "replylist") and source_msg is not None:
                    import email.utils as _eu
                    frm = source_msg.get("From") or ""
                    nm, addr = _decode_header(frm), _eu.parseaddr(frm)[1]
                    if addr and str(up.get("collected_senders", "2")) == "2":
                        store.collected_upsert(session["user_id"], 2, nm or addr, addr)
            except Exception:
                pass  # never fail a send over address bookkeeping
            flash("Message sent successfully.", "confirmation")
            if store_target == "":  # "don't save"
                return redirect(url_for("views.mail", _mbox=box.special("drafts") or "INBOX"))
            return redirect(url_for("views.mail", _mbox=store_target or box.special("sent") or "INBOX"))
        except MailError as e:
            flash(str(e), "error")
            prefill.update(to=", ".join(to), cc=", ".join(cc), bcc=", ".join(bcc),
                           subject=subject, body=body, html="1" if html else "")
    return render("mail", "compose.html", prefill=prefill, identities=identities,
                  responses=store.responses(session["user_id"]),
                  folders=folders, mode=mode, uid_of=uid_of,
                  draft_uid=draft_uid, attachments_kept=attachments_kept,
                  keep_formatting=(mode == "edit"))


# ---------------------------------------------------------------- addressbook

SOURCES = {"0": "Personal Addresses", "1": "Collected Recipients", "2": "Trusted Senders"}


@bp.route("/contacts")
@login_required
def contacts():
    store = get_store()
    q = request.args.get("_q", "").strip()
    group = request.args.get("_group", type=int)
    source = request.args.get("_source") or "0"
    if source not in SOURCES:
        source = "0"
    page = int(request.args.get("_page", 1) or 1)
    size = current_app.config["PAGE_SIZE"]
    readonly = source != "0"
    aprefs = g.get("prefs") or {}
    if readonly:
        allrows = store.collected_list(session["user_id"], int(source), q or None)
    else:
        allrows = store.contacts(session["user_id"], query=q or None, group=group)
    # prefs: sorting column and contact name listing mode
    sort_col = aprefs.get("addressbook_sort_col", "surname")

    def _key(r):
        keys = r.keys()
        col = sort_col if sort_col in keys else "name"
        return ((r[col] if col in keys else "") or r["name"] or r["email"] or "").lower()
    allrows = sorted(allrows, key=_key)
    listing_mode = str(aprefs.get("addressbook_name_listing", "0"))
    if listing_mode != "0":
        def _disp(r):
            keys = r.keys()
            f = (r["firstname"] or "") if "firstname" in keys else ""
            s = (r["surname"] or "") if "surname" in keys else ""
            if listing_mode == "1":
                return " ".join(filter(None, [f, s])) or r["name"] or r["email"]
            if listing_mode == "2":
                return " ".join(filter(None, [s, f])) or r["name"] or r["email"]
            if listing_mode == "3":
                return ", ".join(filter(None, [s, f])) or r["name"] or r["email"]
            return r["name"]
        allrows = [{**r, "name": _disp(r)} for r in allrows]
    try:
        size = int(aprefs.get("addressbook_pagesize")
                   or current_app.config["PAGE_SIZE"]) or current_app.config["PAGE_SIZE"]
    except (TypeError, ValueError):
        size = current_app.config["PAGE_SIZE"]
    total = len(allrows)
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(page, pages))
    rows = allrows[(page - 1) * size: page * size]
    more = page < pages
    groups = store.contactgroups(session["user_id"])
    return render("addressbook", "addressbook.html", rows=rows, q=q, group=group,
                  source=source, sources=SOURCES, readonly=readonly,
                  groups=groups, page=page, more=more, total=total,
                  list_title=("Search" if q else SOURCES[source]),
                  search_mods=["name", "firstname", "surname", "email", "*"])


@bp.route("/contact/<int:cid>")
@login_required
def contact_view(cid):
    store = get_store()
    row = store.contact(session["user_id"], cid)
    if not row:
        abort(404)
    groups = store.contactgroups(session["user_id"])
    member_of = [g["contactgroup_id"] for g in groups
                 if cid in [m["contact_id"] for m in store.contactgroup_members(g["contactgroup_id"])]]
    framed = request.args.get("_framed") == "1"
    if framed:
        return render_template("contact_framed.html", row=row, groups=groups, member_of=member_of, task="addressbook")
    return render("addressbook", "contact.html", row=row, groups=groups, member_of=member_of)


@bp.route("/contact/edit/<int:cid>", methods=["GET", "POST"])
@bp.route("/contact/new", defaults={"cid": None}, methods=["GET", "POST"])
@login_required
def contact_edit(cid):
    store = get_store()
    row = store.contact(session["user_id"], cid) if cid else None
    if cid and not row:
        abort(404)
    if request.method == "POST":
        form = request.form
        def pairs(prefix):
            vals = form.getlist(f"_{prefix}_value[]")
            types = form.getlist(f"_{prefix}_type[]")
            return [(types[i] if i < len(types) else "", v.strip())
                    for i, v in enumerate(vals) if v.strip()]
        ext = {
            "prefix": form.get("prefix", "").strip(),
            "firstname": form.get("firstname", "").strip(),
            "middlename": form.get("middlename", "").strip(),
            "surname": form.get("surname", "").strip(),
            "suffix": form.get("suffix", "").strip(),
            "nickname": form.get("nickname", "").strip(),
            "organization": form.get("organization", "").strip(),
            "department": form.get("department", "").strip(),
            "jobtitle": form.get("jobtitle", "").strip(),
            "gender": form.get("gender", "").strip(),
            "birthday": form.get("birthday", "").strip(),
            "notes": form.get("notes", ""),
            "emails": pairs("email"),
            "phones": pairs("phone"),
            "addresses": [tuple(a) for a in zip(
                form.getlist("_atype[]"), form.getlist("_astreet[]"),
                form.getlist("_alocality[]"), form.getlist("_azip[]"),
                form.getlist("_aregion[]"), form.getlist("_acountry[]"))
                if any(x.strip() for x in a)],
        }
        name = form.get("name", "").strip()
        emails = [v for _t, v in ext["emails"]]
        firstname, surname = ext["firstname"], ext["surname"]
        if not name:
            name = " ".join(filter(None, [firstname, surname])) or (emails[0] if emails else "Unnamed")
        ext["name"] = name
        data = {"name": name, "email": ", ".join(emails), "firstname": firstname,
                "surname": surname, "vcard": util.vcard_encode(ext)}
        new_id = store.contact_save(session["user_id"], data, contact_id=cid)
        flash("Contact saved.", "confirmation")
        return redirect(url_for("views.contact_view", cid=new_id))
    ext = util.vcard_parse(row["vcard"]) if row and row["vcard"] else util.vcard_parse("")
    return render("addressbook", "contactedit.html", row=row, ext=ext,
                  contact_types=util.CONTACT_TYPES)


@bp.post("/contact/<int:cid>/delete")
@login_required
def contact_delete(cid):
    store = get_store()
    store.contact_delete(session["user_id"], [cid])
    flash("Contact deleted.", "confirmation")
    return redirect(url_for("views.contacts"))


@bp.route("/contacts/export")
@login_required
def contacts_export():
    """vCard export — 'Export all' / 'Export selected' (contacts.vcf)."""
    store = get_store()
    cids = request.args.getlist("_cid")
    if cids:
        rows = [store.contact(session["user_id"], int(c)) for c in cids]
        rows = [r for r in rows if r]
    else:
        rows = store.contacts(session["user_id"])
    parts = []
    for r in rows:
        vc = r["vcard"] or util.vcard_encode({"name": r["name"],
                                              "emails": [("", r["email"])]})
        parts.append(vc)
    body = "\r\n".join(parts) + "\r\n" if parts else ""
    return Response(body, mimetype="text/vcard", headers={
        "Content-Disposition": 'attachment; filename="contacts.vcf"'})


@bp.post("/contacts/import")
@login_required
def contacts_import():
    """Import contacts from an uploaded .vcf file."""
    store = get_store()
    f = request.files.get("_file")
    if not f or not f.filename:
        flash("No file uploaded.", "error")
        return redirect(url_for("views.contacts"))
    text = f.read().decode("utf-8", errors="replace")
    count = 0
    for chunk in text.split("BEGIN:VCARD")[1:]:
        vcard = "BEGIN:VCARD" + chunk.split("END:VCARD")[0] + "END:VCARD"
        ext = util.vcard_parse(vcard)
        name = ext["name"] or " ".join(filter(None, [ext["firstname"], ext["surname"]]))
        emails = [v for _t, v in ext["emails"]]
        if not name and not emails:
            continue
        name = name or (emails[0] if emails else "Unnamed")
        data = {"name": name, "email": ", ".join(emails),
                "firstname": ext["firstname"], "surname": ext["surname"],
                "vcard": util.vcard_encode(ext)}
        store.contact_save(session["user_id"], data)
        count += 1
    flash(f"{count} contact(s) imported.", "confirmation")
    return redirect(url_for("views.contacts"))


@bp.get("/contact/<int:cid>/qrcode")
@login_required
def contact_qrcode(cid):
    """Contact QR code (SVG), like Roundcube's contacts/qrcode action."""
    store = get_store()
    row = store.contact(session["user_id"], cid)
    if not row:
        abort(404)
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        abort(404)
    ext = util.vcard_parse(row["vcard"]) if row["vcard"] else {}
    # QR input is limited: only common fields, as Roundcube does
    fields = {k: ext.get(k) for k in ("name", "firstname", "surname", "middlename",
                                      "nickname", "organization", "jobtitle",
                                      "prefix", "suffix")}
    fields["emails"] = ext.get("emails")
    fields["phones"] = ext.get("phones")
    data = util.vcard_encode({k: v for k, v in fields.items() if v})
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


@bp.post("/contact/group")
@login_required
def contact_group_assign():
    """Assign / remove selected contacts to/from a group (More ▸ Assign/Remove)."""
    store = get_store()
    gid = request.form.get("_gid", type=int)
    cids = [int(x) for x in request.form.getlist("_uids[]")]
    action = request.form.get("_do") or "assign"
    if gid and cids:
        if action == "remove":
            store.contactgroup_remove(gid, cids)
            flash("Removed from list.", "confirmation")
        else:
            store.contactgroup_add(gid, cids)
            flash("Added to list.", "confirmation")
    return redirect(url_for("views.contacts"))


@bp.post("/contact/delete")
@login_required
def contacts_delete():
    store = get_store()
    ids = [int(x) for x in request.form.getlist("_uids[]") or request.form.getlist("_uids")]
    if ids:
        store.contact_delete(session["user_id"], ids)
        flash(f"{len(ids)} contact(s) deleted.", "confirmation")
    return redirect(url_for("views.contacts"))


@bp.post("/contactgroup/add")
@login_required
def contactgroup_add():
    store = get_store()
    name = request.form.get("name", "").strip()
    if name:
        store.contactgroup_save(session["user_id"], name)
    return redirect(url_for("views.contacts"))


@bp.post("/contactgroup/<int:gid>/delete")
@login_required
def contactgroup_delete(gid):
    store = get_store()
    store.contactgroup_delete(session["user_id"], gid)
    return redirect(url_for("views.contacts"))


@bp.post("/contactgroup/<int:gid>/rename")
@login_required
def contactgroup_rename(gid):
    store = get_store()
    name = request.form.get("name", "").strip()
    if name:
        store.contactgroup_save(session["user_id"], name, group_id=gid)
    return redirect(url_for("views.contacts"))


@bp.post("/contact/collected/delete")
@login_required
def collected_delete():
    """Delete selected entries from Collected Recipients / Trusted Senders."""
    store = get_store()
    atype = request.form.get("_source", type=int) or 1
    emails = request.form.getlist("_uids[]")
    if emails:
        store.collected_delete(session["user_id"], atype, emails)
        flash(f"{len(emails)} entry(s) deleted.", "confirmation")
    return redirect(url_for("views.contacts", _source=atype))


@bp.post("/contact/<int:cid>/group/<int:gid>")
@login_required
def contact_group_add(cid, gid):
    store = get_store()
    store.contactgroup_add(gid, [cid])
    flash("Added to list.", "confirmation")
    return redirect(url_for("views.contact_view", cid=cid))


@bp.post("/contact/<int:cid>/group/<int:gid>/remove")
@login_required
def contact_group_remove(cid, gid):
    store = get_store()
    store.contactgroup_remove(gid, [cid])
    return redirect(url_for("views.contact_view", cid=cid))


# ---------------------------------------------------------------- settings

@bp.route("/settings")
@login_required
def settings():
    return redirect(url_for("views.settings_preferences"))


@bp.post("/settings/password")
@login_required
def settings_password():
    store = get_store()
    old = request.form.get("_current", "")
    new = request.form.get("_new", "")
    confirm = request.form.get("_confirm", "")
    user = store.get_user(session["username"])
    if not verify_password(old, user["password"]):
        flash("Current password is incorrect.", "error")
    elif len(new) < 4:
        flash("New password too short.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    else:
        store.set_user_password(session["user_id"], hash_password(new))
        flash("Password changed.", "confirmation")
        session["imap_password"] = new
    return redirect(url_for("views.settings"))


@bp.route("/settings/preferences", methods=["GET", "POST"])
@login_required
def settings_preferences():
    store = get_store()
    prefs = dict(store.get_user_prefs(session["user_id"]))
    # prefs are stored at the top level of the user prefs dict; folder keys
    # use the same names as Mailbox.special(kind): drafts/sent/trash/archive/junk
    if request.method == "POST":
        for key in ("timezone", "time_format", "date_format", "refresh_interval",
                    "reply_mode", "forward_mode", "html_editor"):
            if key in request.form:
                prefs[key] = request.form[key].strip()
        for form_key, pref_key in (("drafts_mbox", "drafts"), ("sent_mbox", "sent"),
                                   ("trash_mbox", "trash"), ("archive_mbox", "archive"),
                                   ("junk_mbox", "junk")):
            val = request.form.get(form_key, "").strip()
            if val:
                prefs[pref_key] = val
            else:
                prefs.pop(pref_key, None)
        for key in ("pretty_date", "display_next", "check_all_folders",
                    "mdn_default", "dsn_default", "reply_same_folder",
                    "show_real_foldernames"):
            prefs[key] = 1 if request.form.get(key) else 0
        for key in ("pagesize", "read_time"):
            if key in request.form:
                try:
                    prefs[key] = max(0, int(request.form[key]))
                except ValueError:
                    pass
        for key, value in list(prefs.items()):
            store.set_user_pref(session["user_id"], key, value)
        flash("Preferences saved.", "confirmation")
        return redirect(url_for("views.settings_preferences"))
    folders = [f["name"] for f in folders_for_menu()]
    return render("settings", "preferences.html", prefs=prefs, mail_folders=folders)


@bp.route("/settings/responses")
@login_required
def responses():
    store = get_store()
    rows = store.responses(session["user_id"])
    return render("settings", "responses.html", rows=rows)


@bp.route("/settings/response/edit/<int:rid>", methods=["GET", "POST"])
@bp.route("/settings/response/new", defaults={"rid": None}, methods=["GET", "POST"])
@login_required
def response_edit(rid):
    store = get_store()
    row = store.response(session["user_id"], rid) if rid else None
    if rid and not row:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        body = request.form.get("body", "")
        if name:
            new_id = store.response_save(session["user_id"], name, body,
                                         html=1 if request.form.get("html") else 0,
                                         rid=rid)
            flash("Response saved.", "confirmation")
            return redirect(url_for("views.responses"))
        flash("Name is required.", "error")
    return render("settings", "responseedit.html", row=row)


@bp.post("/settings/response/<int:rid>/delete")
@login_required
def response_delete(rid):
    get_store().response_delete(session["user_id"], rid)
    flash("Response deleted.", "confirmation")
    return redirect(url_for("views.responses"))


@bp.route("/settings/identities")
@login_required
def identities():
    store = get_store()
    rows = store.identities(session["user_id"])
    return render("settings", "identities.html", rows=rows)


@bp.route("/settings/identity/edit/<int:iid>", methods=["GET", "POST"])
@bp.route("/settings/identity/new", defaults={"iid": None}, methods=["GET", "POST"])
@login_required
def identity_edit(iid):
    store = get_store()
    row = store.identity(session["user_id"], iid) if iid else None
    if iid and not row:
        abort(404)
    if request.method == "POST":
        data = identity_from_form(request.form, row)
        if not data["email"]:
            flash("E-mail address is required.", "error")
        else:
            store.identity_save(session["user_id"], data, identity_id=iid)
            flash("Identity saved.", "confirmation")
            return redirect(url_for("views.identities"))
    return render("settings", "identityedit.html", row=row)


@bp.post("/settings/identity/<int:iid>/delete")
@login_required
def identity_delete(iid):
    store = get_store()
    store.identity_delete(session["user_id"], iid)
    flash("Identity deleted.", "confirmation")
    return redirect(url_for("views.identities"))


# ---------------------------------------------------------------- folders

@bp.route("/settings/folders")
@login_required
def folders_view():
    box = imap_box()
    return render("settings", "folders.html", all_folders=box.folders())


@bp.post("/settings/folders")
@login_required
def folders_act():
    box = imap_box()
    act = request.form.get("_act")
    try:
        if act == "create":
            name = request.form.get("name", "").strip()
            if name:
                box.imap.create_folder(name)
                box.imap.subscribe(name)
                flash(f"Folder {name} created.", "confirmation")
        elif act == "rename":
            old = request.form.get("folder")
            new = request.form.get("name", "").strip()
            if old and new and old != new:
                box.imap.rename_folder(old, new)
                flash("Folder renamed.", "confirmation")
        elif act == "delete":
            name = request.form.get("folder")
            if name:
                box.imap.delete_folder(name)
                flash(f"Folder {name} deleted.", "confirmation")
        elif act == "empty":
            name = request.form.get("folder")
            if name:
                box.empty_folder(name)
                flash(f"Folder {name} emptied.", "confirmation")
    except MailError as e:
        flash(str(e), "error")
    return redirect(url_for("views.folders_view"))


# ---------------------------------------------------------------- about

@bp.route("/about")
@login_required
def about():
    return render("settings", "about.html")
