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


def folders_for_menu():
    return imap_box().folders()


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
    sort = request.args.get("_sort") or "date"
    order = request.args.get("_sort_order") or "desc"
    search = request.args.get("_q") or request.args.get("_search") or ""
    mods = []
    for m in request.args.getlist("_sm") + (request.args.get("_sm_csv") or "").split(","):
        mods += [x for x in m.split(",") if x]
    sfilter = request.args.get("_sf") or "all"
    sinterval = request.args.get("_si") or "all"
    sscope = request.args.get("_ss") or "base"
    searching = bool(search or sfilter != "all" or sinterval != "all")
    try:
        listing = box.message_list(folder, page=page, sort=sort, order=order,
                                   search=search or None, search_mods=mods or None,
                                   search_filter=sfilter, search_interval=sinterval,
                                   search_scope=sscope if searching else "base")
    except MailError as e:
        flash(str(e), "error")
        listing = {"items": [], "page": 1, "pages": 1, "total": 0, "first": 0, "last": 0, "uids": []}
    uid = request.args.get("_uid")
    return render("mail", "mail.html", folder=folder, listing=listing,
                  sort=sort, order=order, search=search,
                  search_mods=mods, search_filter=sfilter,
                  search_interval=sinterval, search_scope=sscope,
                  searching=searching, preview_uid=uid,
                  message_count=listing["total"])


@bp.route("/message")
@login_required
def message_view():
    box = imap_box()
    folder = request.args.get("_mbox") or "INBOX"
    uid = request.args.get("_uid")
    if not uid:
        abort(404)
    framed = request.args.get("_framed") == "1"
    try:
        msg = box.get_message(folder, uid, mark_seen=request.args.get("_noseen") != "1")
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
    rendered = []
    for p in parts:
        try:
            payload = p.get_payload(decode=True) or b""
            charset = p.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            text, charset = "", "utf-8"
        if p.get_content_type() == "text/html":
            rendered.append(("html", util.sanitize_html(text)))
        else:
            rendered.append(("plain", text))
    headers = []
    for h in ("From", "To", "Cc", "Subject", "Date", "Reply-To", "Message-ID"):
        v = msg.get(h)
        if v:
            headers.append((h, _decode_header(str(v))))
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
    ctx = dict(folder=folder, uid=uid, msg=msg,
               subject=_decode_header(msg.get("Subject", "") or "(no subject)"),
               headers=headers, parts=rendered, attachments=attachments,
               framed=framed)
    if framed:
        return render_template("message_part.html", **ctx, task="mail")
    return render("mail", "message.html", **ctx)


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
    folder = request.form.get("_mbox") or "INBOX"
    command = request.form.get("_act")
    uids = _uids_from_request()
    if uids:
        try:
            if command == "read":
                box.set_flags(folder, uids, ["\\Seen"], "add")
            elif command == "unread":
                box.set_flags(folder, uids, ["\\Seen"], "remove")
            elif command == "flag":
                box.set_flags(folder, uids, ["\\Flagged"], "add")
            elif command == "unflag":
                box.set_flags(folder, uids, ["\\Flagged"], "remove")
            elif command == "delete":
                box.delete(folder, uids)
                flash(f"{len(uids)} message(s) deleted.", "confirmation")
            elif command == "move":
                dest = request.form.get("_dest")
                box.move(folder, uids, dest)
                flash(f"Moved to {dest}.", "confirmation")
            elif command == "copy":
                dest = request.form.get("_dest")
                box.copy(folder, uids, dest)
                flash(f"Copied to {dest}.", "confirmation")
        except MailError as e:
            flash(str(e), "error")
    nxt = request.form.get("_return") or url_for("views.mail", _mbox=folder)
    return redirect(nxt)


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
               "in_reply_to": "", "references": ""}
    attachments_kept = []
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

    if source_msg is not None:
        if mode == "reply":
            rt = source_msg.get("Reply-To") or source_msg.get("From")
            prefill["to"] = _decode_header(rt) if rt else ""
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
            prefill["body"] = _quote(source_msg)
            prefill["in_reply_to"] = source_msg.get("Message-ID", "") or ""
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
        elif mode == "forward":
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["subject"] = subj if subj.lower().startswith("fw:") else f"Fwd: {subj}"
            prefill["body"] = _quote(source_msg, header=True)
            prefill["in_reply_to"] = source_msg.get("Message-ID", "") or ""
        else:  # draft / compose-from-message
            prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
            prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
            prefill["subject"] = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["body"] = _quote(source_msg, header=False)
            if source_msg.is_multipart():
                for p in source_msg.walk():
                    if p.get_filename():
                        attachments_kept.append({
                            "filename": p.get_filename(),
                            "ctype": p.get_content_type(),
                            "data": p.get_payload(decode=True) or b"",
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

        msg = build_message(
            ident["email"], ident["name"], to, cc, bcc, subject, body, html=html,
            attachments=attachments or None,
            in_reply_to=request.form.get("_in_reply_to") or None,
            references=request.form.get("_references") or None,
            reply_to=request.form.get("_reply_to") or None,
        )
        raw = msg.as_bytes()
        act = request.form.get("_action", "send")
        try:
            if act == "save":
                box.save_draft(raw, replace_uid=int(draft_uid) if draft_uid else None)
                flash("Draft saved.", "confirmation")
                return redirect(url_for("views.mail", _mbox=box.special("drafts") or "Drafts"))
            allrec = to + cc + bcc
            plain = msg
            if not html:
                plain = msg
            # smtplib needs the combined recipient list
            box.send(msg, raw)
            flash("Message sent successfully.", "confirmation")
            return redirect(url_for("views.mail", _mbox=box.special("sent") or "INBOX"))
        except MailError as e:
            flash(str(e), "error")
            prefill.update(to=", ".join(to), cc=", ".join(cc), bcc=", ".join(bcc),
                           subject=subject, body=body, html="1" if html else "")
    return render("mail", "compose.html", prefill=prefill, identities=identities,
                  folders=folders)


# ---------------------------------------------------------------- addressbook

@bp.route("/contacts")
@login_required
def contacts():
    store = get_store()
    q = request.args.get("_q", "").strip()
    group = request.args.get("_group", type=int)
    page = int(request.args.get("_page", 1) or 1)
    size = current_app.config["PAGE_SIZE"]
    rows = store.contacts(session["user_id"], query=q or None, group=group,
                          offset=(page - 1) * size, limit=size + 1)
    more = len(rows) > size
    rows = rows[:size]
    groups = store.contactgroups(session["user_id"])
    return render("addressbook", "addressbook.html", rows=rows, q=q, group=group,
                  groups=groups, page=page, more=more)


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
        name = request.form.get("name", "").strip()
        emails = [e.strip() for e in request.form.get("email", "").replace("\n", ",").split(",") if e.strip()]
        firstname = request.form.get("firstname", "").strip()
        surname = request.form.get("surname", "").strip()
        if not name:
            name = " ".join(filter(None, [firstname, surname])) or (emails[0] if emails else "Unnamed")
        data = {"name": name, "email": ", ".join(emails), "firstname": firstname,
                "surname": surname, "vcard": ""}
        new_id = store.contact_save(session["user_id"], data, contact_id=cid)
        flash("Contact saved.", "confirmation")
        return redirect(url_for("views.contact_view", cid=new_id))
    return render("addressbook", "contactedit.html", row=row)


@bp.post("/contact/<int:cid>/delete")
@login_required
def contact_delete(cid):
    store = get_store()
    store.contact_delete(session["user_id"], [cid])
    flash("Contact deleted.", "confirmation")
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
    store = get_store()
    user = store._conn().execute("SELECT * FROM users WHERE user_id = ?", (session["user_id"],)).fetchone()
    return render("settings", "settings.html", user=user)


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
