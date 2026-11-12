"""All HTTP views: login, mail, compose, addressbook, settings."""

import base64
import contextlib
import email
import email.utils
import functools
import io
import json
import re
import secrets
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape as html_escape
from html import unescape

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import compose_wash, i18n, prefs_data, prefs_sections, util
from .auth import hash_password, verify_password
from .mail import (
    SEARCH_FILTERS,
    Imap,
    Mailbox,
    MailError,
    _decode_header,
    _search_has_attachment,
    build_message,
    wire_bytes,
)
from .plugins import get_api
from .store import _UNSET


def mail_mods_norm(v):
    """Legacy short search-filter names -> the reference's raw IMAP values."""
    return SEARCH_FILTERS.get(v, v) if v else "ALL"


def ph(name, args):
    """Trigger a plugin hook (rcube_plugin_api::exec_hook)."""
    return get_api().exec_hook(name, args)


PREF_SECTIONS = prefs_sections.sections

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


@bp.after_request
def _no_cache(resp):
    # rcube_output::nocacheing_headers() — dynamic pages are never cached
    # (browsers otherwise heuristically re-serve stateful views like /message)
    stamp = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resp.headers.setdefault("Expires", stamp)
    resp.headers.setdefault("Last-Modified", stamp)
    resp.headers.setdefault("Cache-Control", "private, no-cache, no-store, must-revalidate, post-check=0, pre-check=0")
    resp.headers.setdefault("Pragma", "no-cache")
    return resp


@bp.before_request
def _load_user():
    if session.get("user_id"):
        g.user = get_store().get_user(session["username"])
        # Roundcube semantics: the effective config is always the full set of
        # defaults overlaid with the user's saved preferences.
        g.prefs = {**prefs_sections.DEFAULTS, **get_store().get_user_prefs(session["user_id"])}
        # Roundcube keeps browser-detected timezone in the *session*
        # (rcmail::get_offset/remote_autodetect); the 'timezone' preference
        # stays 'auto' until the user picks a zone explicitly.
        if g.prefs.get("timezone") in (None, "", "auto"):
            g.prefs["timezone"] = session.get("tz") or None
        # rcmail language: user preference normalized by language_prop()
        g.lang = i18n.language_prop(g.prefs.get("language") or "en_US")
    else:
        # anonymous: rcube falls back to the browser's Accept-Language
        g.lang = i18n.language_prop(
            request.accept_languages.best_match(sorted(i18n.available_languages()), default="en_US")
        )


def folder_label(name, prefs=None):
    """Roundcube-style folder display name: INBOX -> Inbox, basename of subfolders,
    special folders use the reference's labels (rcube_label 'inbox' etc.);
    raw name when 'show_real_foldernames' is on."""
    if (prefs or {}).get("show_real_foldernames"):
        return name
    base = name.rsplit("/", 1)[-1]
    key = base.lower()
    # rcmail_action::localize_foldername(): only folders whose class has a
    # catalogue label get translated; others keep their display name
    if key in ("inbox", "drafts", "sent", "trash", "junk", "archive") and key in i18n.catalogue(g.get("lang", "en_US")):
        return i18n.gettext(key, g.get("lang", "en_US"))
    return base[:1].upper() + base[1:]


def folders_for_menu():
    prefs = g.get("prefs") or {}
    out = []
    # reference mail tree: subscribed folders only (rcube_imap::listfolders)
    for f in imap_box().folders(subscribed_only=True):
        f = dict(f)
        f["display"] = folder_label(f["name"], prefs)
        out.append(f)
    # rcmail::listfolders(): 'folders_list' fires with the folder tree
    out = ph("folders_list", {"folders": out})["folders"]
    # render_folder_tree_html fills env.mailboxes_list depth-first; the
    # folder-selector (move/copy) uses that order, not the flat special-order
    # list (INBOX, its children, then siblings)
    return flatten_tree(out)


def flatten_tree(entries):
    """Depth-first flattening of the nested folder tree (reference
    env.mailboxes_list order used by folder_selector)."""
    roots = folder_tree(entries)
    flat = []

    def walk(nodes):
        for f in nodes:
            flat.append(f)
            walk(f["sub"])

    walk(roots)
    return flat


def folder_tree(entries):
    """Nested copy of a flat folder list (reference treelist renders the
    imap hierarchy: children live in a <ul> under their parent's caret;
    '/' is the namespace separator, cf. rcube::get_bool_arg('sep'))."""
    by = {}
    for f in entries:
        f = dict(f)
        f["sub"] = []
        by[f["name"].upper()] = f
    # keep server (alphabetical) order; parents precede children naturally
    result = []
    for src in entries:
        f = by[src["name"].upper()]
        idx = f["name"].rfind("/")
        parent = by.get(f["name"][:idx].upper()) if idx > 0 else None
        if parent is not None and parent is not f:
            parent["sub"].append(f)
        else:
            result.append(f)
    return result


def _framed_arg():
    """Preserve the _framed=1 flow marker through redirects (reference
    keeps loading framed pages inside their parent frame)."""
    from flask import request as _rq

    return "1" if (_rq.args.get("_framed") == "1" or _rq.form.get("_framed") == "1") else None


def render(task, tmpl, **ctx):
    g.task = task
    ctx.setdefault("folders", folders_for_menu())
    if task == "mail":
        # sidebar renders the nested tree (reference treelist); the flat
        # list stays for move/copy selectors and filters
        ctx.setdefault("folder_tree", folder_tree(ctx["folders"]))
    # rcube_output_html::render(): plugins may amend the template properties
    ctx = ph("render_page", {"template": tmpl, "task": task, "props": ctx})["props"]
    # Roundcube page titles: "<product> :: <task title>" (mail list uses the
    # folder name, message view the subject; compose keeps the default)
    if "page_title" not in ctx:
        # reference set_pagetitle(): the fixed task titles are gettext keys,
        # mail list uses the (already localized) folder name, message view
        # the raw subject
        title = {
            "compose.html": i18n.gettext("compose", g.lang),
            "addressbook.html": i18n.gettext("contacts", g.lang),
            "contact.html": i18n.gettext("contacts", g.lang),
            "contactedit.html": i18n.gettext("contacts", g.lang),
            "contact_framed.html": i18n.gettext("contacts", g.lang),
            "preferences.html": i18n.gettext("preferences", g.lang),
            "responses.html": i18n.gettext("preferences", g.lang),
            "responseedit.html": i18n.gettext("preferences", g.lang),
            "identities.html": i18n.gettext("preferences", g.lang),
            "identityedit.html": i18n.gettext("preferences", g.lang),
            "folders.html": i18n.gettext("preferences", g.lang),
        }.get(tmpl, ctx.get("folder_title") or ctx.get("subject_title"))
        ctx["page_title"] = title
    return render_template(tmpl, **ctx)


def parse_recipients(value):
    out = []
    for part in (value or "").replace("\n", ",").split(","):
        part = part.strip()
        if "@" in part or "<" in part:
            out.append(part)
    return out


def identity_from_form(form, existing=None):
    # reference contract (settings/identity_edit.php): _name/_email/_organization/
    # _reply-to/_bcc/_standard/_signature/_html_signature; legacy names are still
    # accepted for robustness
    def g(*keys, default=""):
        for k in keys:
            if k in form:
                return form.get(k)
        return default

    std = g("_standard", "standard")
    html_sig = g("_html_signature", "html_signature")
    return {
        "name": g("_name", "name").strip(),
        "organization": g("_organization", "organization").strip(),
        "email": g("_email", "email").strip(),
        "reply_to": g("_reply-to", "reply_to").strip(),
        "bcc": g("_bcc", "bcc").strip(),
        "signature": g("_signature", "signature"),
        "html_signature": 1 if html_sig and html_sig != "0" else 0,
        "standard": 1 if std and std != "0" else 0,
        # keep the record id so re-rendered forms (noemailwarning etc.)
        # still carry the hidden _iid
        "identity_id": g("_iid") or (dict(existing).get("identity_id", "") if existing is not None else ""),
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
            # stable per-login token like PHP's session_id(); the compose
            # local-storage copy uses it to distinguish sessions (app.js:5440)
            session["sid"] = secrets.token_hex(16)
            session["imap_password"] = password
            # Roundcube keeps the browser-detected timezone in the session
            # only (the stored preference remains 'auto' unless chosen)
            tz = request.form.get("_timezone")
            if tz and tz != "_default_":
                session["tz"] = tz
            # make sure default identity exists
            if not store.identities(uid):
                # Roundcube seeds the default identity with an empty display
                # name (rcmail::startup); the list renders it as "<email>".
                store.identity_save(
                    uid,
                    {
                        "name": "",
                        "organization": "",
                        "email": username,
                        "reply_to": "",
                        "bcc": "",
                        "signature": "",
                        "html_signature": 0,
                        "standard": 1,
                    },
                )
            ph("login_after", {"user_id": uid})
            return redirect(request.args.get("_next") or url_for("views.mail"))
        error = i18n.gettext("loginfailed", g.lang, domain="messages")
    return render_template(
        "login.html",
        task="login",
        error=error,
        folders=[],
        product_name=current_app.config["PRODUCT_NAME"],
        loginform_content=ph("loginform_content", {"content": ""})["content"],
    )


@bp.route("/logout")
@login_required
def logout():
    # rcmail::logout_actions(): purge Trash / expunge INBOX per prefs
    box = imap_box()
    with contextlib.suppress(MailError):
        box.logout_actions()
    ph("session_destroy", {})
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
    if "_save_opts" in request.args:
        # list-options dialog Save (reference set_list_options): the choice
        # becomes the list state (rcmail env + per-folder view mode), not a
        # one-shot URL. Craft is SSR: persist sort/order as user prefs and
        # the mode per folder, then continue on the clean URL.
        store = get_store()
        _ord = (request.args.get("_sort_order") or "desc").lower()
        store.set_user_pref(session["user_id"], "message_sort_col", request.args.get("_sort") or "")
        store.set_user_pref(session["user_id"], "message_sort_order", _ord if _ord in ("asc", "desc") else "desc")
        if request.args.get("_mode") in ("list", "threads"):
            _p = dict(store.get_user_prefs(session["user_id"]))
            _fvm = dict(_p.get("folder_viewmodes") or {})
            _fvm[folder] = request.args["_mode"]
            store.set_user_pref(session["user_id"], "folder_viewmodes", _fvm)
        _qs = {k: v for k, v in request.args.to_dict(flat=False).items() if k != "_save_opts"}
        return redirect(url_for("views.mail", **_qs))
    # config/defaults.inc.php: message_sort_col = '' (no explicit column) →
    # Roundcube sorts by arrival (IMAPSORT UID, desc). Not sent-date.
    # Saved list-options prefs act as the default; explicit URL still wins.
    _up = getattr(box, "prefs", None) or {}
    sort = request.args.get("_sort")
    if sort is None:
        sort = _up.get("message_sort_col") or ""
    order = request.args.get("_sort_order") or _up.get("message_sort_order") or "desc"
    order = order.lower() if order.lower() in ("asc", "desc") else "desc"
    # elastic "smart" From/To column: Sent/Drafts (and subfolders) sort by To
    # (rcmail_action_mail_index::message_list_smart_column_name)
    if sort == "fromto":
        _fp = getattr(box, "prefs", None) or {}
        _pfx = tuple(p for p in (_fp.get("sent_mbox"), _fp.get("drafts_mbox")) if p)
        sort = "to" if _pfx and folder.startswith(_pfx) and folder.upper() != "INBOX" else "from"
    search = request.args.get("_q") or ""
    # search modifiers: reference UI sends _headers (comma list); Craft's SSR
    # form posts _sm checkboxes. Master checkboxes expand like elastic ui.js
    # set_searchmod (sender -> from/replyto/followupto, recipient ->
    # to/cc/bcc, text selects only itself).
    mods = []
    for m in (
        request.args.getlist("_sm") + request.args.getlist("_sm[]") + (request.args.get("_headers") or "").split(",")
    ):
        mods += [x for x in m.split(",") if x]
    if "sender" in mods:
        mods = [m for m in mods if m != "sender"] + ["from", "replyto", "followupto"]
    if "recipient" in mods:
        mods = [m for m in mods if m != "recipient"] + ["to", "cc", "bcc"]
    if "text" in mods:
        mods = ["text"]
    mods = list(dict.fromkeys(mods))
    mods_given = bool(mods)
    sfilter = request.args.get("_filter") or request.args.get("_sf") or "ALL"
    sinterval = request.args.get("_interval") or request.args.get("_si") or ""
    if sinterval == "all":  # legacy alias
        sinterval = ""
    sscope = request.args.get("_scope") or request.args.get("_ss") or "base"
    # rcmail_action_mail_index::search_mods(): '*' default subject+from,
    # Sent/Drafts folders default to subject+to; user prefs persist per-folder
    if not mods:
        prefs_all = getattr(box, "prefs", None) or {}
        stored = prefs_all.get("search_mods") or {}
        special = {}
        for key in ("sent_mbox", "drafts_mbox"):
            if prefs_all.get(key):
                special[prefs_all[key]] = ["subject", "to"]
        eff = stored.get(folder) or stored.get("*") or special.get(folder) or ["subject", "from"]
        if isinstance(eff, dict):
            eff = list(eff.keys())
        mods = list(eff)
    if search and mods_given and sscope != "all" and folder:
        # search.php::update_search_mods() — persist for this folder only
        supported = ["subject", "from", "to", "cc", "bcc", "replyto", "followupto", "body", "text"]
        keep = [m for m in mods if m in supported]
        if keep:
            store = get_store()
            prefs = dict(store.get_user_prefs(session["user_id"]))
            stored = prefs.get("search_mods") or {}
            value = dict.fromkeys(keep, 1)
            if not (isinstance(stored.get(folder), dict) and stored[folder] == value):
                stored[folder] = value
                prefs["search_mods"] = stored
                store.set_user_pref(session["user_id"], "search_mods", stored)
    fvpref = (getattr(box, "prefs", None) or {}).get("folder_viewmodes") or {}
    folder_viewmode = fvpref.get(folder)
    list_mode = request.args.get("_mode") or (
        folder_viewmode
        if folder_viewmode in ("list", "threads")
        else ("threads" if (getattr(box, "prefs", None) or {}).get("viewmode") == "threads" else "list")
    )
    searching = bool(search or mail_mods_norm(sfilter) != "ALL" or sinterval)

    # list-context link carry: reference keeps sort/mode/filter in
    # rcmail.env so paging, column clicks and message back-navigation all
    # reuse the current list state. Craft's equivalent: every in-mail link
    # is built from the same base args.
    link_args = {"_mbox": folder}
    if sort:
        link_args["_sort"] = sort
    if order != "desc":
        link_args["_sort_order"] = order
    link_args["_mode"] = list_mode
    if search:
        link_args["_q"] = search
    if searching and mail_mods_norm(sfilter) != "ALL":
        link_args["_filter"] = sfilter
    if sinterval:
        link_args["_interval"] = sinterval
    if searching and sscope and sscope != "base":
        link_args["_scope"] = sscope

    def mail_url(**over):
        args = dict(link_args)
        for key, val in over.items():
            if val is None:
                args.pop(key, None)
            else:
                args[key] = val
        return url_for("views.mail", **args)

    def message_url(msg_uid, msg_box=None):
        # _back lets the reader's Back link restore this exact list view.
        # The list URL travels base64-encoded — like the reference's _list
        # list-state param — so no nested '?'/&' ever appears in the URL
        return url_for(
            "views.message_view",
            _mbox=msg_box or folder,
            _uid=msg_uid,
            _back=base64.urlsafe_b64encode(request.full_path.encode()).decode().rstrip("="),
        )

    try:
        pspec = getattr(box, "prefs", {}).get("mail_pagesize") or getattr(box, "prefs", {}).get("pagesize")
        listing = box.message_list(
            folder,
            page=page,
            sort=sort,
            order=order,
            page_size=(int(pspec) if pspec else None) or current_app.config["PAGE_SIZE"],
            search=search or None,
            search_mods=mods or None,
            search_filter=sfilter,
            search_interval=sinterval,
            search_scope=sscope if searching else "base",
            threads=(list_mode == "threads"),
        )
    except MailError as e:
        flash(str(e), "error")
        listing = {"items": [], "page": 1, "pages": 1, "total": 0, "first": 0, "last": 0, "uids": []}
    # rcmail_action_mail_index: 'messages_list' lets plugins amend the list
    listing["items"] = ph("messages_list", {"messages": listing["items"], "mbox": folder})["messages"]
    uid = request.args.get("_uid")
    quota_used = quota_kb = 0
    with contextlib.suppress(Exception):
        # server without QUOTA support -> zeros
        quota_used, quota_kb = box.quota_usage()
    folder_unread = 0
    with contextlib.suppress(Exception):
        _total, folder_unread = box.imap.status(folder)
    return render(
        "mail",
        "mail.html",
        folder=folder,
        folder_title=folder_label(folder, getattr(box, "prefs", None) or g.get("prefs") or {}),
        listing=listing,
        mail_url=mail_url,
        message_url=message_url,
        sort=sort,
        order=order,
        search=search,
        search_mods=mods,
        search_filter=mail_mods_norm(sfilter),
        search_interval=sinterval,
        search_scope=sscope,
        search_has_attachment=_search_has_attachment(),
        list_mode=list_mode,
        searching=searching,
        preview_uid=uid,
        action="view" if uid else None,
        quota_used=quota_used,
        quota_kb=quota_kb,
        message_count=listing["total"],
        folder_unread=folder_unread,
    )


def _msg_date(msg):
    dt = util.parse_header_date(msg)
    return util.to_local(dt) if dt else None


def _hdr(msg, name):
    v = msg.get(name)
    return _decode_header(str(v)) if v else ""


# ------------------------------------------------------------ MDN (receipts)
# reference: program/actions/mail/show.php mdn_request_handler() and
# program/actions/mail/sendmdn.php send_mdn()

# ------------------------------------------------------------ reply recipients
# reference: rcmail_sendmail::compose_header_value() for the to/cc headers
# in MODE_REPLY (program/include/rcmail_sendmail.php:1057-1145)


def _reply_recipients(source_msg, mode, ident_email):
    """(to, cc) prefill for reply/replyall/replylist, following the
    reference precedence: Mail-Followup-To (list/all), List-Post mailto
    (list), Mail-Reply-To, Reply-To, From — plus the reply-to-self swap
    (#1487074) and reply-all To+Cc merge with the #1489037 From rule."""
    reply_all = {"replyall": "all", "replylist": "list"}.get(mode)

    def hdr(name):
        v = source_msg.get(name)
        return _decode_header(v) if v else ""

    def decode_all(value):
        return [(n.strip(), a) for n, a in email.utils.getaddresses([value or ""]) if a]

    followup = hdr("Mail-Followup-To")
    frm, to_h, cc_h = hdr("From"), hdr("To"), hdr("Cc")
    replyto_h = hdr("Reply-To")

    fto, replyto_flag = "", False
    if reply_all == "list" and followup:
        fto = followup
    elif reply_all == "list":
        m = re.search(r"<mailto:([^>]+)>", hdr("List-Post"), re.I)
        if m:
            fto = _decode_header(m.group(1))
    elif reply_all and followup:
        fto = followup
    elif hdr("Mail-Reply-To"):
        fto = hdr("Mail-Reply-To")
    elif replyto_h:
        fto = replyto_h
        replyto_flag = True
    elif frm:
        fto = frm

    # reply to a message that was sent by ourselves (#1487074): swap in To:
    if ident_email and not replyto_flag:
        for sender in (fto, frm):
            if any(a.lower() == ident_email.lower() for _n, a in decode_all(sender)):
                fto = to_h
                break

    fcc = ""
    if reply_all and reply_all != "list":
        fcc = to_h + (", " if to_h and cc_h else "") + cc_h
        if replyto_h:
            froms = {a.lower() for _n, a in decode_all(frm)}
            tos = {a.lower() for _n, a in decode_all(to_h)}
            rtos = {a.lower() for _n, a in decode_all(replyto_h)}
            if rtos and tos == rtos and froms - tos:  # #1489037
                fcc = (fcc + ", " + frm) if fcc else frm

    recipients, ident_lc = [], (ident_email or "").lower()

    def tidy(value, field):
        out = []
        for name, addr in decode_all(value):
            lc = addr.lower()
            if field != "to" and lc == ident_lc:  # drop self from cc/bcc
                continue
            if lc in recipients:  # cross-field dedupe, to first
                continue
            out.append(f"{name} <{addr}>" if name and name != addr else addr)
            recipients.append(lc)
        return ", ".join(out)

    return tidy(fto, "to"), tidy(fcc, "cc")


def _identity_for_message(store, user_id, msg):
    """rcmail_sendmail::identity_select($message) with MODE_REPLY: prefer the
    identity matching a To/Cc recipient, then the message's own From:
    (reply-to-self), else the default identity."""
    ids = [dict(r) for r in store.identities(user_id)]
    if not ids:
        return None
    recip, names = [], []
    for h in ("To", "Cc"):
        for nm, addr in util.header_addresses(msg, h):
            recip.append(addr.lower())
            names.append(nm)
    frm = util.header_addresses(msg, "From")[:1]
    frm_name, frm_mail = (frm[0][0], frm[0][1].lower()) if frm else ("", "")
    found = {"to": None, "from": None}
    for idx, ident in enumerate(ids):
        email_a = (ident["email"] or "").lower()
        if frm_mail and frm_mail == email_a:
            if found["from"] is None:
                found["from"] = idx
            if frm_name and ident.get("name") and frm_name == ident["name"]:
                return ident
        if email_a in recip:
            if found["to"] is None:
                found["to"] = idx
            pos = recip.index(email_a)
            if names[pos] and ident.get("name") and names[pos] == ident["name"]:
                return ident
    pick = found["to"] if found["to"] is not None else found["from"]
    if pick is None:
        return store.default_identity(user_id)
    return ids[pick]


def _send_mdn(box, user_id, folder, uid):
    """Build and send the disposition notification; returns
    (sent, error). Flags the message $MDNSent like rcube's MDNSENT."""
    msg = box.raw_message(folder, uid)
    mdn_to = _hdr(msg, "Disposition-Notification-To")
    if not mdn_to:
        return False, None
    store = get_store()
    ident = _identity_for_message(store, user_id, msg)
    if not ident:
        return False, "sendingreceiptfailed"
    from_addr = ident["email"]
    from_name = ident.get("name") or ""
    # envelope recipient: first address in Disposition-Notification-To
    rcpt = util.header_addresses(msg, "Disposition-Notification-To")
    mailto = rcpt[0][1] if rcpt else ""
    if not mailto:
        return False, None
    subject = _hdr(msg, "Subject") or "(no subject)"
    message_id = (_hdr(msg, "Message-ID") or "").strip()
    refs = (_hdr(msg, "References") or "").strip()
    m = EmailMessage()
    m["Date"] = email.utils.formatdate(localtime=True)
    m["From"] = util.format_address(from_name, from_addr) if from_name else from_addr
    m["To"] = mdn_to
    m["Subject"] = f"Return Receipt (read): {subject}"
    m["Message-ID"] = email.utils.make_msgid(domain=from_addr.rsplit("@", 1)[-1] or "craftcube.local")
    m["X-Sender"] = from_addr
    if refs or message_id:
        m["References"] = (refs + " " + message_id).strip()
    if message_id:
        m["In-Reply-To"] = message_id
    # useragent: Roundcube falls back to its own client string
    agent = current_app.config.get("USERAGENT") or "CraftCube"
    m["User-Agent"] = agent
    to_disp = _hdr(msg, "To")
    dt = util.to_local_tz(util.parse_header_date(msg), store.get_user_prefs(user_id).get("timezone"))
    date_long = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
    body = (
        "This is a Return Receipt for your message\r\n\r\n"
        f"\tTo: {to_disp}\r\n"
        f"\tSubject: {subject}\r\n"
        f"\tDate: {date_long}\r\n\r\n"
        "Note: This receipt only acknowledges that the message was displayed "
        "on the recipient's computer. There is no guarantee that the "
        "recipient has read or understood the message contents."
    )
    report = (
        "Final-Recipient: rfc822; " + from_addr + "\r\n"
        f"Original-Message-ID: {message_id}\r\n"
        "Disposition: manual-action/MDN-sent-manually; displayed\r\n"
    )
    if to_disp:
        report += f"Original-Recipient: {to_disp}\r\n"
    report += f"Reporting-UA: {agent}\r\n"
    m.set_content(body)
    # the disposition-notification part (Mail_mime addAttachment inline, 7bit)
    part = EmailMessage()
    part.set_content(report)
    part.replace_header("Content-Type", "message/disposition-notification")
    part["Content-Disposition"] = 'inline; filename="MDNPart2.txt"'
    part.replace_header("Content-Transfer-Encoding", "7bit")
    # multipart/report; report-type="disposition-notification" (RFC 3798):
    # body stays part 1, the notification is appended as part 2
    m.make_mixed()
    m.attach(part)
    m.set_type("multipart/report")
    m.set_param("report-type", "disposition-notification", header="Content-Type")
    try:
        box.send(m, m.as_bytes(), store_target="")
    except MailError as e:
        return False, str(e)
    box.add_flag(folder, uid, "$MDNSent")
    return True, None


def _mdn_request(box, folder, uid, msg):
    """show.php::mdn_request_handler(). Returns (request, save, sender) where
    request=True asks the UI, or None/None/None when nothing applies. Must run
    BEFORE the message is marked \\Seen (the handler requires an unread msg)."""
    mdn_to = _hdr(msg, "Disposition-Notification-To")
    if not mdn_to:
        return None
    prefs = get_store().get_user_prefs(session["user_id"])
    cfg = int(prefs.get("mdn_requests", 0) or 0)
    sender = util.header_addresses(msg, "From")[:1]
    mailto = sender[0][1] if sender else ""
    if not mailto:
        return None
    flags = box.flags_of(folder, uid)
    if "$MDNSent" in flags or "\\Seen" in flags:
        return None
    box_special = {box.special("drafts"), box.special("sent")}
    if folder in box_special:
        return None
    exists = cfg == 1
    if cfg in (3, 4, 5, 6):
        kind = "contacts" if cfg in (3, 4) else "trusted"
        if get_store().contact_email_known(session["user_id"], mailto, kind):
            exists = True
    if exists:
        sent, _err = _send_mdn(box, session["user_id"], folder, uid)
        if sent:
            flash(i18n.gettext("receiptsent", g.lang, domain="messages"), "confirmation")
        else:
            flash(i18n.gettext("errorsendingreceipt", g.lang, domain="messages"), "error")
        return None
    if cfg in (2, 4, 6):
        return None  # ignore request
    name, addr = sender[0]
    full = f"{name} <{addr}>" if name and name != addr else addr
    return {"request": True, "save": cfg if cfg in (3, 5) else 0, "sender": {"mailto": mailto, "string": full}}


def _header_date_short(dt):
    """Reference friendly date used in the collapsed header Date row:
    'Today 14:25', 'Yesterday 09:12', weekday 'Tue 20:37' within the last
    week, plain date otherwise (rcube output date() helpers)."""
    if not dt:
        return ""
    from datetime import datetime

    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    days = (now.date() - dt.date()).days
    if days == 0:
        return "Today " + dt.strftime("%H:%M")
    if 0 < days < 7:
        return dt.strftime("%a %H:%M")
    return dt.strftime("%Y-%m-%d")


def build_message_ctx(box, folder, uid, mark_seen=True, allow_remote=None):
    try:
        msg = box.get_message(folder, uid, mark_seen=False)
    except MailError:
        abort(404)
    # show.php:128 mdn_request_handler() runs while the message is still
    # unread — Roundcube sets \Seen only after the page has been sent
    # (show.php end). Do the same: evaluate first, mark seen after.
    mdn_ctx = None
    with contextlib.suppress(Exception):  # a receipt hiccup must never block the view
        mdn_ctx = _mdn_request(box, folder, uid, msg)
    if mark_seen and not box._is_seen(folder, uid):
        box.set_flags(folder, [uid], ["\\Seen"], "add")
    prefs = get_store().get_user_prefs(session["user_id"])
    # show.php:57-63 — the _format override is remembered per message in the
    # session (msg_formats mbox:uid); effective prefer_html = override else
    # the prefer_html preference (rc default on).
    fmt = (session.get("msg_formats") or {}).get(f"{folder}:{uid}")
    prefer_html = (fmt == "html") if fmt in ("text", "html") else bool(int(prefs.get("prefer_html", 1) or 0))
    # rcube_message body selection: multipart/alternative renders only the
    # preferred flavour (show.php:672, rcube_message first_text_part() falls
    # back to an html2text-converted HTML part when plain is requested);
    # other multipart trees keep all text parts in document order.
    parts = []  # (email_part, convert_html_to_text)

    def _walk(p):
        if p.get_content_maintype() == "multipart":
            if p.get_content_type() == "multipart/alternative":
                subs = [
                    c
                    for c in p.walk()
                    if not c.is_multipart()
                    and c.get_content_type() in ("text/plain", "text/html")
                    and c.get_content_disposition() != "attachment"
                ]
                plains = [c for c in subs if c.get_content_type() == "text/plain"]
                htmls = [c for c in subs if c.get_content_type() == "text/html"]
                if prefer_html:
                    parts.extend((c, False) for c in (htmls[:1] or plains[:1]))
                elif plains:
                    parts.append((plains[0], False))
                elif htmls:
                    parts.append((htmls[0], True))
            else:
                payload = p.get_payload()
                # compat32 multipart payload is a list of sub-messages
                if isinstance(payload, list):
                    for c in payload:
                        if hasattr(c, "get_content_maintype"):
                            _walk(c)
        elif p.get_content_type() in ("text/plain", "text/html") and p.get_content_disposition() != "attachment":
            parts.append((p, False))

    if msg.is_multipart():
        _walk(msg)
    elif msg.get_content_type() in ("text/plain", "text/html") and msg.get_content_disposition() != "attachment":
        parts = [(msg, msg.get_content_type() == "text/html" and not prefer_html)]
    # show.php:118-121 — toggle link offered whenever the message has an
    # inline, non-empty text/html part (rcube_message::has_html_part())
    optional_format = None
    for p in msg.walk() if msg.is_multipart() else [msg]:
        if (
            p.get_content_type() == "text/html"
            and p.get_content_disposition() != "attachment"
            and (p.get_payload(decode=True) or b"").strip()
        ):
            optional_format = "text" if prefer_html else "html"
            break
    sender_domain = ""
    fm = email.utils.parseaddr(_hdr(msg, "From"))[1]
    if "@" in fm:
        sender_domain = fm.rsplit("@", 1)[1].lower()
    # remote-content protection (Elastic: "To protect your privacy remote
    # resources have been blocked." + Allow button, allowed per sender).
    # The show_images pref decides the baseline (actions/mail/index.php:877
    # check_safe + show.php:269): 0 block always, 1 allow for known contacts,
    # 2 allow always, 3 allow for trusted senders.
    allowed = allow_remote
    if allowed is None:
        allowed = sender_domain in (prefs.get("remote_senders") or [])
    if allowed is None or not allowed:
        show_images = str(prefs.get("show_images", "0") or "0")
        if show_images == "2":
            allowed = True
        elif show_images in ("1", "3"):
            kind = "contacts" if show_images == "1" else "trusted"
            allowed = get_store().contact_email_known(session["user_id"], fm, kind)
    rendered = []
    remote_blocked = False
    # washtml in the message view resolves cid: image sources only when a
    # matching MIME part exists; unmatched cid: sources lose the attribute
    # (no broken-image glyph). Resolvable ones point at the inline part URL.
    cid_parts = {}
    if msg.is_multipart():
        for _i, _p in enumerate(msg.walk()):
            _c = (_p.get("Content-ID") or "").strip("<> ")
            if _c:
                cid_parts[_c] = _i

    from urllib.parse import quote

    referred_cids = set()

    def _fix_cid(m):
        cid = m.group(2)
        referred_cids.add(cid)
        if cid in cid_parts:
            return f'src="/attachment?_mbox={quote(folder)}&_uid={uid}&_part={cid_parts[cid]}&_inline=1"'
        return ""

    _CID_SRC_RE = re.compile(r"""\bsrc=(["'])cid:([^"'\s>]+)\1""")
    # text parts without a declared charset decode with default_charset
    # (rcube_message.php:351; reference default ISO-8859-1)
    dcharset = prefs.get("default_charset") or "ISO-8859-1"
    for p, convert in parts:
        try:
            payload = p.get_payload(decode=True) or b""
            charset = p.get_content_charset() or dcharset
            text = payload.decode(charset, errors="replace")
        except Exception:
            text, charset = "", "utf-8"
        if p.get_content_type() == "text/html":
            if convert:
                # first_text_part(): html2text of the raw part body
                rendered.append(("plain", util.html_to_text(text)))
                continue
            text = _CID_SRC_RE.sub(_fix_cid, text)
            safe = util.sanitize_html(text)
            if not allowed and util.contains_remote_content(safe):
                safe = util.block_remote_content(safe)
                remote_blocked = True
            rendered.append(("html", safe))
        else:
            if p.get_param("format") == "flowed":
                text = util.unfold_flowed(text, p.get_param("delsp") == "yes")
            rendered.append(("plain", text))
    headers = []
    for h in (
        "From",
        "To",
        "Cc",
        "Bcc",
        "Subject",
        "Date",
        "Reply-To",
        "Followup-To",
        "Message-ID",
        "In-Reply-To",
        "References",
    ):
        v = _hdr(msg, h)
        if v:
            headers.append((h, v))
    # reference elastic message header (messageSummary): a message WITH a
    # From header renders "From <adr> on <date>"; one WITHOUT a usable From
    # header (e.g. our malformed import test message) collapses to
    # "On <date>" and the details table keeps only the friendly Date row.
    # The sender's own address is NOT special-cased (a self-addressed
    # message still shows "From …", verified against the reference).
    from_addr = util.header_addresses(msg, "From")
    photo_src = url_for("static", filename="images/contactpic.svg")
    with contextlib.suppress(Exception):
        if from_addr:
            pcid = get_store().email_to_contact(session["user_id"], from_addr[0][1])
            if pcid and get_store().contact_photo(session["user_id"], pcid):
                photo_src = url_for("views.contact_photo", cid=pcid)
    date_short = _header_date_short(_msg_date(msg))
    attachments = []
    image_attachments = []
    if msg.is_multipart():
        # cid: references in the rendered HTML keep their part out of the
        # thumbnails (rcube_message::is_referred_attachment, show.php:725)
        referred = (
            set(re.findall(r'cid:([^"\'\s>]+)', " ".join(b for k, b in rendered if k == "html")) or []) | referred_cids
        )
        for i, p in enumerate(msg.walk()):
            fn = p.get_filename()
            cid = (p.get("Content-ID") or "").strip("<> ")
            if (fn or p.get_content_disposition() == "attachment") and cid not in referred:
                entry = {
                    "part": str(i),
                    "filename": fn or f"part{i}.bin",
                    "ctype": p.get_content_type(),
                    "size": len(p.get_payload(decode=True) or b""),
                }
                attachments.append(entry)
                # inline image thumbnails below the body (show.php:714,
                # inline_images pref default true)
                cid = (p.get("Content-ID") or "").strip("<> ")
                if entry["ctype"].startswith("image/") and prefs.get("inline_images", 1) and cid not in referred:
                    image_attachments.append(entry)
    # prev/next within the folder (arrival order; matches date-desc listings)
    prev_uid = next_uid = None
    try:
        uids = sorted(int(u) for u in box.imap.conn.uid("SEARCH", None, "ALL")[1][0].split())
    except Exception:
        uids = []
    try:
        i = uids.index(int(uid))
        prev_uid = uids[i + 1] if i + 1 < len(uids) else None  # newer = previous entry
        next_uid = uids[i - 1] if i > 0 else None
    except (ValueError, IndexError):
        pass
    return {
        "folder": folder,
        "uid": uid,
        "msg": msg,
        "subject": _hdr(msg, "Subject") or "(no subject)",
        "headers": headers,
        "parts": rendered,
        "attachments": attachments,
        "optional_format": optional_format,
        "image_attachments": image_attachments,
        "sender": util.header_addresses(msg, "From")[:1],
        "sender_domain": sender_domain,
        "from_addr": from_addr,
        "to_addr": util.header_addresses(msg, "To"),
        "cc_addr": util.header_addresses(msg, "Cc"),
        "replyto_addr": util.header_addresses(msg, "Reply-To"),
        "has_from": bool(from_addr),
        "photo_src": photo_src,
        "date_short": date_short,
        # reference 'ml' flag -- enables the Reply list menu item
        "list_post": bool(_hdr(msg, "List-Post")),
        "remote_blocked": remote_blocked,
        # env.mdn_request / mdn_request_save / mdn_request_sender (show.php:864)
        "mdn": mdn_ctx,
        "date": _msg_date(msg),
        "prev_uid": prev_uid,
        "next_uid": next_uid,
    }


@bp.route("/message")
@login_required
def message_view():
    box = imap_box()
    folder = request.args.get("_mbox") or "INBOX"
    uid = request.args.get("_uid")
    if not uid:
        abort(404)
    # show.php:57-58 — _format=text|html overrides the display format and is
    # remembered for this message (build_message_ctx reads the session)
    if request.args.get("_format") in ("text", "html"):
        # session[...] assignment (not nested mutation) so Flask's
        # CallbackDict marks the session modified and persists the cookie
        fmts = dict(session.get("msg_formats") or {})
        fmts[f"{folder}:{uid}"] = request.args.get("_format")
        session["msg_formats"] = fmts
    if request.args.get("_save"):
        # rcmail_action_mail_viewsource::_save=1 — raw message download
        # named from the subject ("filename_from_subject"). The reference
        # also GET-checks a request token; CraftCube uses the session.
        raw = box.raw_message(folder, uid)
        subject = _hdr(raw, "Subject") or ""
        name = re.sub(r"[:\t\n\r\x00\x0B/]+\s*", " ", subject[:128])
        name = name.strip(" \t\n\r\x00\x0b./_") or uid
        # headers->charset: RC treats us-ascii/missing as the default
        # charset; emits e.g. "text/plain;charset=UTF-8"
        declared = (raw.get_param("charset", header="Content-Type") or "").strip().strip('"').lower()
        charset = "UTF-8" if declared in ("", "us-ascii", "ascii") else declared
        body = getattr(raw, "_raw_bytes", None) or raw.as_bytes()
        resp = Response(body, mimetype="text/plain")
        resp.headers["Content-Type"] = f"text/plain;charset={charset}"
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}.eml"'
        resp.headers["Content-Length"] = str(len(body))
        return resp
    if request.args.get("_source"):
        raw = box.raw_message(folder, uid)
        return Response(raw.as_string(), mimetype="text/plain; charset=utf-8")
    framed = request.args.get("_framed") == "1"
    # Reference behavior (verified live): ?_action=show renders a dedicated
    # reader page — no list/sidebar columns, toolbar with Print/Previous/Next.
    # The shell-with-preview layout is only for /mail?_uid= (index + preview).
    ctx = build_message_ctx(
        box,
        folder,
        uid,
        mark_seen=request.args.get("_noseen") != "1",
        allow_remote=True if request.args.get("_load") == "remote" else None,
    )
    if request.args.get("_load") == "remote" and ctx["sender_domain"]:
        prefs = get_store().get_user_prefs(session["user_id"])
        senders = set(prefs.get("remote_senders") or [])
        senders.add(ctx["sender_domain"])
        get_store().set_user_pref(session["user_id"], "remote_senders", sorted(senders))
        ctx = build_message_ctx(box, folder, uid, mark_seen=False, allow_remote=True)
        ctx["remote_blocked"] = False
    ctx["framed"] = framed
    # show.php: 'message_read' after the message object is fully built
    ctx = ph("message_read", {"message": ctx["msg"], "mbox": folder, "uid": uid, "props": ctx})["props"]
    ctx["extwin"] = request.args.get("_extwin") == "1"
    # standalone (non-iframe) message pages render the toolbar server-enabled
    # for the viewed message, like the reference action-show page
    if not framed:
        ctx["tb_active"] = True
        ctx.setdefault("action", "show")
    ctx["subject_title"] = ctx.get("subject")
    ctx["print"] = request.args.get("_print") == "1"
    # prev/next navigation within the folder (same order as the message list)
    prev_uid = next_uid = None
    if not framed:
        with contextlib.suppress(Exception):
            # navigation is best-effort: a list fetch hiccup just hides prev/next
            order_uids = [
                str(u) for u in box.message_list(folder, page=1, page_size=100000, sort="", order="desc")["uids"]
            ]
            if uid in order_uids:
                idx = order_uids.index(uid)
                # reference direction: 'prev' is the row ABOVE in the list
                # (newer in date-desc), disabled at the top boundary
                prev_uid = order_uids[idx - 1] if idx > 0 else None
                next_uid = order_uids[idx + 1] if idx + 1 < len(order_uids) else None
    ctx["prev_uid"] = prev_uid
    ctx["next_uid"] = next_uid
    if request.args.get("_headers") == "1":
        # reference `?_action=headers`: raw header source, all headers in
        # wire order, names bold (headers.php headers_output)
        return render_template("headers.html", **ctx, task="mail", action="headers", rawh=list(ctx["msg"].items()))
    if framed:
        return render_template("message_part.html", **ctx, task="mail")
    if request.args.get("_print") == "1":
        # reference dispatch: action print picks the messageprint template —
        # no app chrome, details-view headers, logo top-right
        return render_template("messageprint.html", **ctx, task="mail")
    # Back link restores the exact list view the message was opened from
    # (reference carries this as the base64 _list list-state param); only
    # same-app relative list URLs are accepted.
    back_raw = request.args.get("_back") or ""
    if not back_raw.startswith("/mail"):
        with contextlib.suppress(Exception):
            back_raw = base64.urlsafe_b64decode(back_raw + "=" * (-len(back_raw) % 4)).decode("utf-8", "replace")
    ctx["back_url"] = back_raw if back_raw.startswith("/mail") else None
    return render("mail", "message.html", **ctx)


@bp.route("/utils/text2html", methods=["POST"])
@login_required
def utils_text2html():
    # reference: ?_task=utils&_action=text2html (rcmail_action_utils_text2html)
    from .converters import text2html

    body = request.get_data(as_text=True)
    return Response(text2html(body), content_type="text/html; charset=UTF-8")


@bp.route("/utils/html2text", methods=["POST"])
@login_required
def utils_html2text():
    # reference: ?_task=utils&_action=html2text (rcmail_action_utils_html2text)
    from .converters import html2text

    body = request.get_data(as_text=True)
    text = html2text(body, links=bool(request.args.get("_do_links")), width=int(request.args.get("_width") or 0))
    return Response(text, content_type="text/plain; charset=UTF-8")


@bp.post("/utils/spell")
@login_required
def utils_spell():
    """GoogieSpell plain-text endpoint: mirrors rcmail_action_utils_spell.

    Raw XML request body (<text>…</text> / <learnword>…), `lang` query
    param; reply is rcube_spellchecker::get_xml():
    <spellresult charschecked="N"><c o="O" l="L">sug1\tsug2</c>…
    """
    import html as _html

    from . import spellchecker

    lang = request.values.get("lang") or "en"
    body = request.get_data(as_text=True) or ""
    up = get_store().get_user_prefs(session["user_id"])
    ignore = {k: bool(up.get("spellcheck_ignore_" + k)) for k in ("syms", "nums", "caps")}
    xml_head = '<?xml version="1.0" encoding="UTF-8"?>'
    learn = body.find("<learnword>")
    if learn != -1:
        word = _html.unescape(body[body.index("<text>", learn) + 6 : body.index("</text>", learn)])
        spellchecker.add_word(word)
        return Response(xml_head + "<learnwordresult></learnwordresult>", mimetype="text/xml")
    left = body.find("<text>")
    right = body.rfind("</text>")
    text = _html.unescape(body[left + 6 : right]) if left != -1 and right > left else ""
    if not text:
        return Response(xml_head + '<spellresult charschecked="0"></spellresult>', mimetype="text/xml")
    matches, checked = spellchecker.find_matches(text, lang, ignore=ignore)
    if matches is None:
        # rcmail_action_utils_spell: engine error -> <error> + 500
        return Response(
            xml_head + '<spellresult error="Internal error."></spellresult>', status=500, mimetype="text/xml"
        )
    out = [xml_head, f'<spellresult charschecked="{checked}">']
    for _word, pos, ln, sugg in matches:
        joined = "\t".join(sugg)
        out.append(f'<c o="{pos}" l="{ln}">{joined}</c>')
    out.append("</spellresult>")
    return Response("".join(out), mimetype="text/xml")


@bp.post("/utils/spell_html")
@login_required
def utils_spell_html():
    # reference: rcmail_action_utils_spell_html (pspell engine)
    from . import spellchecker

    method = request.form.get("method", "")
    lang = request.form.get("lang", "en")
    result = {}
    if method == "addToDictionary":
        spellchecker.add_word(request.form.get("word", ""))
        result["result"] = True
    else:
        text = unescape(request.form.get("text", "") or "")
        if text:
            # spellcheck_ignore_* prefs (rcube_spellchecker.php:49-51)
            up = get_store().get_user_prefs(session["user_id"])
            ignore = {k: bool(up.get("spellcheck_ignore_" + k)) for k in ("syms", "nums", "caps")}
            words = spellchecker.check(text, lang, ignore=ignore)
            if words is None:
                return Response(json.dumps({"error": "Internal error."}), status=500, content_type="application/json")
            if words:
                result["words"] = words
                result["dictionary"] = False
    return Response(json.dumps(result), content_type="application/json")


@bp.route("/message/export", methods=["GET", "POST"])
@login_required
def message_export():
    """Export messages - provided by the zipdownload plugin (like the
    reference, where the elastic download menu dispatches the plugin
    action); every format comes back as a zip."""
    plugin = get_api().get_plugin("zipdownload")
    if plugin is None:
        abort(404)  # plugin disabled: no export, like Roundcube
    return plugin.download_messages()


@bp.route("/plugin/<name>/<action>", methods=["GET", "POST"])
@login_required
def plugin_action(name, action):
    """Generic dispatch of a registered plugin action, the Roundcube
    ``_action=plugin.<name>.<action>`` equivalent for CraftCube's URLs."""
    full = f"plugin.{name}.{action}"
    api = get_api()
    if full not in api.state.actions:
        abort(404)
    result = api.exec_action(full)
    if result is None:
        abort(404)
    return result


@bp.post("/message/import")
@login_required
def message_import():
    """Import messages into a folder (Elastic 'Import' uploadform).

    Mirrors rcmail_action_mail_import::run(): accepts multiple `_file[]`
    uploads, detects MIME/mbox by content (zip archives are unpacked first),
    appends each message to the folder via IMAP.
    """
    import mailbox as _mb
    import os as _os
    import re as _re
    import tempfile
    import zipfile

    box = imap_box()
    folder = request.form.get("_mbox") or "INBOX"
    files = request.files.getlist("_file[]") or request.files.getlist("_file")
    files = [f for f in files if f and f.filename]

    def _import_one(data):
        """Return number of messages imported from one blob."""
        head = data[:500].decode("utf-8", "replace")
        first = next((ln for ln in head.splitlines() if ln.strip()), "")
        if first.startswith("From "):
            with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as tf:
                tf.write(data)
                tname = tf.name
            n = 0
            try:
                for msg in _mb.mbox(tname):
                    box.imap.append(folder, msg.as_bytes())
                    n += 1
            finally:
                _os.unlink(tname)
            return n
        if _re.match(r"^[a-z_-]+:\s+.+", first, _re.IGNORECASE):
            box.imap.append(folder, data)
            return 1
        return 0

    count = 0
    max_size = 5 * 1024 * 1024  # matches the uploadform hint (PHP upload_max_filesize)
    try:
        for f in files:
            data = f.read()
            if len(data) > max_size:
                flash(i18n.gettext("filesizeerror", g.lang, {"size": "5 MB"}, "messages"), "error")
                return redirect(url_for("views.mail", _mbox=folder))
            low = f.filename.lower()
            if low.endswith(".zip") or f.mimetype in ("application/zip", "application/x-zip"):
                try:
                    import io

                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        for name in z.namelist():
                            if name.endswith("/"):
                                continue
                            count += _import_one(z.read(name))
                except zipfile.BadZipFile:
                    pass
            else:
                count += _import_one(data)
        if count:
            flash(f"Successfully imported {count} messages", "confirmation")
        else:
            flash(i18n.gettext("importmessageerror", g.lang, domain="messages"), "error")
    except Exception as e:
        flash(f"Import failed! The uploaded file is not a valid message or mailbox file ({e})", "error")
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
    return Response(
        data,
        mimetype=ctype,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{fn}",
        },
    )


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
        if command == "delete" and ret_uid and (getattr(box, "prefs", None) or {}).get("display_next"):
            try:
                next_preview = _next_uid_after(box, folder, ret_uid, uids)
            except Exception:
                next_preview = None
        try:
            _run_mail_action(box, command, folder, uids, dest=request.form.get("_dest"))
        except MailError as e:
            flash(str(e), "error")
        if next_preview:
            return redirect(url_for("views.mail", _mbox=folder, _uid=next_preview))
    nxt = request.form.get("_return") or url_for("views.mail", _mbox=folder)
    return redirect(nxt)


@bp.post("/mail/sendmdn")
@login_required
def mail_sendmdn():
    """rcmail_action_mail_sendmdn::run(): send the disposition notification,
    flash receiptsent/errorsendingreceipt, optionally save the sender
    (_save=3 -> address book, _save=5 -> trusted senders, addcontact.php)."""
    box = imap_box()
    folder = request.form.get("_mbox") or "INBOX"
    uid = request.form.get("_uid")
    sent = False
    if uid:
        try:
            sent, _err = _send_mdn(box, session["user_id"], folder, uid)
        except Exception:  # a failed receipt must never 500
            sent = False
    if sent:
        flash(i18n.gettext("receiptsent", g.lang, domain="messages"), "confirmation")
    else:
        flash(i18n.gettext("errorsendingreceipt", g.lang, domain="messages"), "error")
    save = request.form.get("_save")
    address = request.form.get("_address") or ""
    if sent and save in ("3", "5"):
        # addcontact.php: 5 stores a trusted sender, 3 a regular contact
        store = get_store()
        name, email_addr = email.utils.parseaddr(address)
        if "@" in email_addr:
            if save == "5":
                store.collected_upsert(session["user_id"], 2, name or email_addr, email_addr)
            else:
                with contextlib.suppress(Exception):
                    store.contact_save(
                        session["user_id"],
                        {"name": name or email_addr, "email": email_addr, "firstname": "", "surname": "", "vcard": ""},
                    )
    return jsonify({"sent": sent})


def _next_uid_after(box, folder, ref_uid, removed):
    """First remaining uid after ref_uid (newest-first order), given the
    folder's uid order BEFORE the removal."""
    uids = [str(u) for u in box.message_list(folder, page=1, page_size=100000, sort="", order="desc")["uids"]]
    removed = {str(u) for u in removed}
    try:
        idx = uids.index(str(ref_uid))
    except ValueError:
        idx = 0
    for u in uids[idx + 1 :]:
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
        elif command == "mdnsent":
            # app.js mdn_request_dialog close posts mark _flag=mdnsent after
            # the receipt dialog; rcube maps MDNSENT -> $MDNSent keyword
            for u in uids:
                box.add_flag(folder, u, "$MDNSent")
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
        elif command == "undelete":
            # rcmail webmail.js toggle_delete_status('_flag=undelete'):
            # clears \Deleted so flag_for_deletion-marked messages survive
            box.set_flags(folder, uids, ["\\Deleted"], "remove")
        elif command == "delete":
            box.delete(folder, uids)
            flash(i18n.gettext("messagedeleted", g.lang, domain="messages"), "confirmation")
        elif command == "archive":
            box.archive(folder, uids)
            flash(i18n.gettext("messagemoved", g.lang, domain="messages"), "confirmation")
        elif command == "compact":
            box.compact(folder)
            # folder_expunge.php: 'folderexpunged' (not folderpurged)
            flash(i18n.gettext("folderexpunged", g.lang, domain="messages"), "confirmation")
        elif command == "empty":
            box.empty_folder(folder)
            flash(i18n.gettext("folderpurged", g.lang, domain="messages"), "confirmation")
        elif command == "markallread":
            box.mark_all_read(folder)
            flash(i18n.gettext("messagemarked", g.lang, domain="messages"), "confirmation")
        elif command == "move" and dest:
            box.move(folder, uids, dest)
            flash(i18n.gettext("messagemoved", g.lang, domain="messages"), "confirmation")
        elif command == "copy" and dest:
            box.copy(folder, uids, dest)
            flash(i18n.gettext("messagecopied", g.lang, domain="messages"), "confirmation")
    except MailError as e:
        flash(str(e), "error")


# ---------------------------------------------------------------- compose


def _msg_has_html(msg):
    # rcube_message::has_html_part(): a text/html part that isn't an attachment
    with contextlib.suppress(Exception):
        # malformed MIME structure -> treat as plain text
        for p in msg.walk() if msg.is_multipart() else [msg]:
            if (
                p.get_content_type() == "text/html"
                and not p.get_filename()
                and p.get_content_disposition() != "attachment"
            ):
                return True
    return False


def compose_html_mode(mode, source_msg, prefs, post_is_html=None):
    # rcmail_action_mail_compose::compose_editor_mode() -- the full
    # htmleditor decision table (compose.php:445-472), verified against the
    # running reference for every htmleditor value 0..4:
    #   0 never / 1 always / 2 reply-to-HTML / 3 reply|forward-to-HTML /
    #   4 always except plain-text reply
    html_editor = int(prefs.get("htmleditor", 0) or 0)
    msg_html = bool(prefs.get("prefer_html", 1)) and source_msg is not None and _msg_has_html(source_msg)
    if post_is_html is not None:
        return post_is_html
    if mode in ("draft", "edit"):
        return msg_html
    if mode in ("reply", "replyall", "replylist"):
        return html_editor == 1 or (html_editor >= 2 and msg_html)
    if mode in ("forward", "forward-attachment"):
        return html_editor in (1, 4) or (html_editor == 3 and msg_html)
    return html_editor in (1, 4)  # new message


# ---- reply/forward body composition (program/actions/mail/compose.php) ----


def _preferred_part(msg, prefs):
    """The part used for message (pre)viewing (rcube_message structure):
    the HTML part when prefer_html is on, else the first text/plain.
    Returns (body_text, source_is_html)."""
    parts = list(msg.walk() if msg.is_multipart() else [msg])

    def pick(ctype):
        for p in parts:
            if p.get_content_type() == ctype and not p.get_filename() and p.get_content_disposition() != "attachment":
                with contextlib.suppress(Exception):
                    charset = p.get_content_charset() or "utf-8"
                    body = (p.get_payload(decode=True) or b"").decode(charset, errors="replace")
                    # compose_part_body(): format=flowed/delsp=yes flags
                    flowed = ctype == "text/plain" and p.get_param("format") == "flowed"
                    delsp = flowed and p.get_param("delsp") == "yes"
                    return body, ctype == "text/html", flowed, delsp
        return None

    if prefs.get("prefer_html", 1):
        got = pick("text/html")
        if got:
            return got
    got = pick("text/plain")
    if got:
        return got
    return "", False, False, False


def _remove_signature(body, max_lines=15):
    # rcmail_action_mail_compose::remove_signature()
    body = body.replace("\r\n", "\n")
    sp = body.rfind("-- \n")
    if sp != -1 and (sp == 0 or body[sp - 1] == "\n") and body[sp:].count("\n") < max_lines:
        body = body[: max(0, sp - 1)]
    return body


def _part_body(msg, is_html, prefs, mode):
    # rcmail_action_mail_compose::compose_part_body() for a single content
    # part: convert between source and target format, strip old signature.
    from .converters import text2html

    raw, src_html, flowed, delsp = _preferred_part(msg, prefs)
    strip = mode not in ("draft", "edit", "bounce") and prefs.get("strip_existing_sig", 1)
    if is_html:
        if src_html:
            if mode in ("reply", "replyall", "replylist", "forward", "edit", "draft"):
                # prepare_html_body(): wash_html with container
                # '{mode}body{n}' (none for draft) and css_prefix 'v{n}'
                base = {
                    "reply": "reply",
                    "replyall": "reply",
                    "replylist": "reply",
                    "forward": "forward",
                    "edit": "edit",
                }.get(mode)
                n = _html_part_no(msg, prefs)
                return compose_wash.compose_wash_html(
                    raw, container_id=f"{base}body{n}" if base else None, css_prefix=f"v{n}"
                )
            return util.sanitize_html(raw)
        if strip:
            raw = _remove_signature(raw)
        # plain_body(): rcube_text2html unfolds flowed internally (its
        # wrap=True port is wrappable either way) — unfold up-front
        if flowed:
            raw = util.unfold_flowed(raw, delsp)
        return text2html(raw)
    if src_html:
        # "use html part if it has been used for message (pre)viewing",
        # quoting lines are 2 chars narrower. rcmail->html2text() with the
        # html2text_links default (same conversion as the plain message
        # view: mailto: links stay inline, never numbered).
        ll = int(prefs.get("line_length", 72) or 72)
        return util.html_to_text(raw, width=ll - 2 if mode in ("reply", "replyall", "replylist") else ll)
    if flowed:
        raw = util.unfold_flowed(raw, delsp)
    if strip:
        raw = _remove_signature(raw)
    return raw


def _quote_text(text):
    # rcmail_action_mail_compose::quote_text()
    out = []
    for line in text.strip().splitlines():
        out.append(">" + ("" if line.startswith(">") else " ") + line)
    return "\n".join(out)


def _reply_intro(msg, prefs):
    # get_reply_header(): mailreplyintro with date_long + sender name
    dt = util.to_local_tz(util.parse_header_date(msg), prefs.get("timezone"))
    date = dt.strftime("%Y-%m-%d %H:%M") if dt else ""  # date_long 'Y-m-d H:i'
    disp, addr = email.utils.parseaddr(_decode_header(msg.get("From", "") or ""))
    return f"On {date}, {disp or addr} wrote:"


def _forward_header(msg, is_html, prefs, extended=True):
    # get_forward_header(), plain and HTML variants
    dt = util.to_local_tz(util.parse_header_date(msg), prefs.get("timezone"))
    date = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
    subj = _decode_header(msg.get("Subject", "") or "")
    frm = _decode_header(msg.get("From", "") or "")
    to = _decode_header(msg.get("To", "") or "")
    cc = _decode_header(msg.get("Cc", "") or "")
    replyto = _decode_header(msg.get("Reply-To", "") or "")
    if not is_html:
        prefix = "\n\n\n-------- Original Message --------\n"
        prefix += f"Subject: {subj}\nDate: {date}\nFrom: {frm}\nTo: {to}\n"
        if extended and cc:
            prefix += f"Cc: {cc}\n"
        if extended and replyto and replyto != frm:
            prefix += f"Reply-To: {replyto}\n"
        return prefix + "\n"
    row = '<tr><th align="right" nowrap="nowrap" valign="baseline">{}: </th><td>{}</td></tr>'

    def hdr(value):
        # rcube::Q($hdr, 'replace'): angle-bracket-containing strings (a
        # formatted address) skip escaping entirely (rcube_utils
        # ::rep_specialchars_output), plain ones get &quot; etc.
        if "<" in value and ">" in value:
            return value
        return html_escape(value, quote=False)

    prefix = '<br /><p>-------- Original Message --------</p><table border="0" cellpadding="0" cellspacing="0"><tbody>'
    prefix += row.format("Subject", hdr(subj))
    prefix += row.format("Date", hdr(date))
    prefix += row.format("From", hdr(frm))
    prefix += row.format("To", hdr(to))
    if extended and cc:
        prefix += row.format("Cc", hdr(cc))
    if extended and replyto and replyto != frm:
        prefix += row.format("Reply-To", hdr(replyto))
    return prefix + "</tbody></table><br>"


def _create_reply_body(body, is_html, msg, prefs, mode):
    # create_reply_body(): replylist/replyall are REPLY in the reference
    reply_mode = int(prefs.get("reply_mode", 0) or 0)
    if reply_mode == -1:
        return ""
    indent = reply_mode != 2
    if reply_mode == 2:
        prefix = _forward_header(msg, is_html, prefs, extended=False)
    else:
        intro = _reply_intro(msg, prefs)
        prefix = f'<p id="reply-intro">{html_escape(intro)}</p>' if is_html else intro + "\n"
    if not is_html:
        if indent:
            body = _quote_text(body)
        if reply_mode > 0:
            return "\n\n\n" + prefix + body
        return prefix + body + "\n"
    suffix = ""
    if indent:
        prefix += "<blockquote>"
        suffix += "</blockquote>"
    if reply_mode == 2:
        pass
    elif reply_mode > 0:
        prefix = "<br>" + prefix
    else:
        suffix += "<p><br/></p>"
    return prefix + body + suffix


def _create_forward_body(body, is_html, msg, prefs):
    # create_forward_body()
    return _forward_header(msg, is_html, prefs) + body.strip("\r\n")


def _html_part_no(msg, prefs):
    """1-based index of the chosen html part among the html content parts —
    the static $part_no counter of prepare_html_body() (compose.php:990)."""
    parts = [
        p
        for p in (msg.walk() if msg.is_multipart() else [msg])
        if not p.get_filename()
        and p.get_content_disposition() != "attachment"
        and not p.get_content_type().startswith("multipart/")
    ]
    seq = [i for i, p in enumerate(parts) if p.get_content_type() == "text/html"]
    if not seq:
        return 1
    chosen = seq[0]  # _preferred_part picks the first html part
    return sum(1 for i in seq if i <= chosen)


def _quoted_part(msg, is_html, prefs, mode):
    # compose_part_body() + prepare_html_body(): in HTML mode the washed
    # source part arrives wrapped in its container div; draft/edit keep it
    # unwrapped; reply-family modes are all REPLY in the reference.
    body = _part_body(msg, is_html, prefs, mode)
    if is_html and mode in ("reply", "replyall", "replylist", "forward"):
        # create_reply_body()/create_forward_body() trim the composed body;
        # the container div (html source parts) is emitted by the wash itself
        body = body.strip("\r\n")
    return body


def editor_config(mode, prefs, spellcheck=True):
    # rcmail_action::html_editor() (rcmail_action.php:340-432). The
    # default_font / default_font_size env is set by the compose action
    # only (program/actions/mail/compose.php:133-140), so identity and
    # response editors get no content_style (browser default font).
    lang = "en"
    fam = prefs_data.AVAILABLE_FONTS.get(prefs.get("default_font") or "Verdana") if mode == "" else None
    size = (prefs.get("default_font_size") or "10pt") if mode == "" else None
    if size and size not in prefs_data.AVAILABLE_FONT_SIZES:
        size = "10pt"
    style = []
    if fam:
        style.append(f"font-family: {fam};")
    if size:
        style.append(f"font-size: {size};")
    return {
        "mode": mode,
        "lang": lang,
        "skin_path": "static",
        "spellcheck": 1 if spellcheck else 0,
        "spelldict": 0,
        "content_css": url_for("static", filename="styles/embed.min.css"),
        # rcmail_action::html_editor(): enable_autolink=false removes the
        # TinyMCE autolink plugin; enable_spellcheck=false removes spellchecker
        "disabled_plugins": ([] if prefs.get("enable_autolink", 1) else ["autolink"]) +
                            ([] if spellcheck else ["spellchecker"]),
        "disabled_buttons": [],
        "extra_plugins": [],
        "extra_buttons": [],
        "content_style": ("body {" + " ".join(style) + "}") if style else "",
        "default_font": fam or "",
        "default_font_size": size or "",
    }


def identity_signatures(identities, prefs):
    # rcmail_sendmail::email_identities_field(): signatures[id] = {text, html}
    from .converters import html2text, text2html

    sigs = {}
    top_posting = int(prefs.get("reply_mode", 0) or 0) > 0 and not prefs.get("sig_below")
    separator = "---" if top_posting else "-- "
    add_sep = bool(prefs.get("sig_separator"))
    for i in identities:
        sig = i["signature"] or ""
        if not sig:
            continue
        if i["html_signature"]:
            text = html2text(sig, links=False).strip("\r\n")
            html = sig
        else:
            text = sig
            html = text2html(sig)
        if add_sep and not re.search(r"^--[ -]\r?\n", text):
            text = separator + "\n" + text.lstrip("\r\n")
            html = separator + "<br>" + html
        sigs[str(i["identity_id"])] = {"text": text, "html": html}
    return sigs


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

    prefill = {
        "to": "",
        "cc": "",
        "bcc": "",
        "subject": "",
        "body": "",
        "html": "",
        "in_reply_to": "",
        "references": "",
        "reply_to": "",
        "followup_to": "",
        "priority": "3",
        "mdn": False,
        "dsn": False,
    }
    # defaults from Settings > Preferences (Composing Messages)
    prefs = getattr(box, "prefs", None) or {}
    prefill["mdn"] = bool(prefs.get("mdn_default"))
    prefill["dsn"] = bool(prefs.get("dsn_default"))
    # Roundcube semantics: reply_all_mode 1 = reply to mailing list only;
    # forward_attachment 1 = forward as attachment. Legacy values still work.
    if mode == "reply" and str(prefs.get("reply_mode", "0")) in ("all",):
        mode = "replyall"
    elif mode == "reply" and (
        str(prefs.get("reply_mode", "0")) == "list" or str(prefs.get("reply_all_mode", "0")) == "1"
    ):
        mode = "replylist"
    if mode == "forward" and (
        prefs.get("forward_mode") == "attachment" or str(prefs.get("forward_attachment", "0")) == "1"
    ):
        mode = "forward-attachment"
    attachments_kept = []
    attach_original = None  # (filename, bytes) for forward-as-attachment
    source_msg = None
    src_folder = ""
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

    # html/plain editor decision happens BEFORE the body is composed
    # (compose_editor_mode()); the POST path keeps the client's _is_html and
    # editor.js toggle() syncs the hidden _is_html field.
    post_is_html = (request.form.get("_is_html") == "1") if request.method == "POST" else None
    html_mode = compose_html_mode(mode, source_msg, prefs, post_is_html)

    # rcmail_sendmail::mdn_field(): the receipt checkbox is pre-ticked from
    # the source message's Disposition-Notification-To / Return-Receipt-To
    # header in DRAFT/EDIT modes, else from the mdn_default preference.
    if not post_is_html and mode in ("draft", "edit") and source_msg is not None:
        prefill["mdn"] = bool(source_msg.get("Disposition-Notification-To") or source_msg.get("Return-Receipt-To"))

    def _orig_filename():
        s = _decode_header(source_msg.get("Subject", "") or "") or "message"
        import re as _re

        return _re.sub(r"[^A-Za-z0-9 ._-]", "_", s)[:80] + ".eml"

    if source_msg is not None:
        ident_sel = _identity_for_message(store, session["user_id"], source_msg) or store.default_identity(
            session["user_id"]
        )
        ident_email = (ident_sel or {}).get("email") or session["username"]
        if mode in ("reply", "replyall", "replylist"):
            prefill["to"], prefill["cc"] = _reply_recipients(source_msg, mode, ident_email)
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
            prefill["body"] = _create_reply_body(
                _quoted_part(source_msg, html_mode, prefs, mode), html_mode, source_msg, prefs, mode
            )
            prefill["in_reply_to"] = source_msg.get("Message-ID", "") or ""
            prefill["references"] = " ".join(
                x
                for x in (
                    [_decode_header(source_msg.get("References", "") or "")]
                    + ([prefill["in_reply_to"]] if prefill["in_reply_to"] else [])
                )
                if x
            )
        elif mode in ("forward", "forward-attachment", "bounce"):
            subj = _decode_header(source_msg.get("Subject", "")) or ""
            if mode == "bounce":
                # resend verbatim: same To/Subject/attachments, no quoting
                prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
                prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
                prefill["subject"] = subj
                prefill["body"] = _part_body(source_msg, html_mode, prefs, mode)
                prefill["in_reply_to"] = ""
            else:
                prefill["subject"] = subj if subj.lower().startswith(("fw:", "fwd:")) else f"Fwd: {subj}"
                # "forward as attachment" carries the original in the .eml
                # attachment only; the body stays empty (write_forward_attachments)
                prefill["body"] = (
                    ""
                    if mode == "forward-attachment"
                    else _create_forward_body(
                        _quoted_part(source_msg, html_mode, prefs, mode), html_mode, source_msg, prefs
                    )
                )
                prefill["in_reply_to"] = ""
            if mode == "forward-attachment":
                attach_original = (
                    _orig_filename(),
                    box.raw_message(request.values.get("_mbox") or "INBOX", uid_of).as_bytes(),
                )
            else:
                for p in source_msg.walk() if source_msg.is_multipart() else []:
                    if p.get_filename():
                        attachments_kept.append(
                            {
                                "filename": p.get_filename(),
                                "ctype": p.get_content_type(),
                                "data": p.get_payload(decode=True) or b"",
                                "size": len(p.get_payload(decode=True) or b""),
                            }
                        )
        elif mode == "edit":  # edit as new: keep everything verbatim
            prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
            prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
            prefill["subject"] = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["body"] = _part_body(source_msg, html_mode, prefs, mode)
            for p in source_msg.walk() if source_msg.is_multipart() else []:
                if p.get_filename():
                    attachments_kept.append(
                        {
                            "filename": p.get_filename(),
                            "ctype": p.get_content_type(),
                            "data": p.get_payload(decode=True) or b"",
                            "size": len(p.get_payload(decode=True) or b""),
                        }
                    )
        else:  # draft / compose-from-message
            prefill["to"] = _decode_header(source_msg.get("To", "")) or ""
            prefill["cc"] = _decode_header(source_msg.get("Cc", "")) or ""
            prefill["subject"] = _decode_header(source_msg.get("Subject", "")) or ""
            prefill["body"] = _part_body(source_msg, html_mode, prefs, mode)
            for p in source_msg.walk() if source_msg.is_multipart() else []:
                if p.get_filename():
                    attachments_kept.append(
                        {
                            "filename": p.get_filename(),
                            "ctype": p.get_content_type(),
                            "data": p.get_payload(decode=True) or b"",
                            "size": len(p.get_payload(decode=True) or b""),
                        }
                    )

    prefill["html"] = "1" if html_mode else ""
    if (
        html_mode
        and mode in ("forward", "forward-attachment")
        and source_msg is not None
        and str(prefs.get("forward_attachment", "0")) != "1"
    ):
        # write_compose_attachments() keeps inline (disposition=inline) images
        # only when the body references them; they are carried over as
        # attachments so cid: references keep resolving in the editor.
        for p in source_msg.walk() if source_msg.is_multipart() else []:
            if p.get_content_disposition() == "inline" and p.get_content_maintype() == "image" and not p.get_filename():
                data = p.get_payload(decode=True) or b""
                if data and b"cid:" in prefill["body"].encode("utf-8", errors="ignore"):
                    attachments_kept.append(
                        {
                            "filename": p.get_filename() or "inline.jpg",
                            "ctype": p.get_content_type(),
                            "data": data,
                            "size": len(data),
                        }
                    )

    spell_words = {}
    spell_checked = False
    # open_compose_step / open_window (app.js:2259/4855): in extwin popups
    # the compose screen replaces the redirect-based flow with stay-and-close
    extwin = request.values.get("_extwin") == "1"
    sent_ok = False

    def _compose_render():
        return render(
            "mail",
            "compose.html",
            prefill=prefill,
            identities=identities,
            responses=store.responses(session["user_id"]),
            folders=folders,
            mode=mode,
            uid_of=uid_of,
            draft_uid=draft_uid,
            attachments_kept=attachments_kept,
            action="compose",
            keep_formatting=(mode == "edit" or bool(prefs.get("keep_formatting_default"))),
            html_mode=html_mode,
            editor_cfg=editor_config("", prefs),
            signatures=identity_signatures(identities, prefs),
            identities_map={
                str(i["identity_id"]): {
                    k: v
                    for k, v in (("email", i["email"]), ("replyto", i["reply-to"] or None), ("bcc", i["bcc"] or None))
                    if v
                }
                for i in identities
            },
            editor_env={
                "task": "mail",
                "action": "compose",
                "compose_id": request.form.get("_compose_id")
                or request.args.get("_compose_id")
                or str(secrets.randbelow(900000000) + 100000000),
                "draft_autosave": int(prefs.get("draft_autosave", 300) or 0),
                "save_localstorage": bool(prefs.get("compose_save_localstorage", 1)),
                "user_id": session["user_id"],
                "session_id": session.get("sid", ""),
                "compose_mode": {
                    "draft": "draft",
                    "edit": "edit",
                    "reply": "reply",
                    "replyall": "reply",
                    "replylist": "reply",
                }.get(mode, ""),
                "top_posting": int(prefs.get("reply_mode", 0) or 0) > 0,
                "sig_below": bool(prefs.get("sig_below")),
                "show_sig": str(prefs.get("show_sig", "1")) == "1",
                "spell_lang": "en",
                "composebody": "composebody",
            },
            spell_words=spell_words,
            spell_checked=spell_checked,
            extwin=extwin,
            sent_ok=sent_ok,
        )

    if request.method == "POST":
        ident_id = request.form.get("_ident")
        ident = store.identity(session["user_id"], ident_id) if ident_id else store.default_identity(session["user_id"])
        ident = ident or {"name": session["username"], "email": session["username"]}
        to = parse_recipients(request.form.get("_to"))
        cc = parse_recipients(request.form.get("_cc"))
        bcc = parse_recipients(request.form.get("_bcc"))
        subject = request.form.get("_subject", "")
        body = request.form.get("_body", "")
        html = request.form.get("_is_html") == "1" or request.form.get("_format") == "html"
        if not to and not cc and not bcc:
            flash(i18n.gettext("norecipientwarning", g.lang, domain="messages"), "error")
            return render(
                "mail",
                "compose.html",
                prefill=prefill,
                identities=identities,
                folders=folders,
                error="No recipients given.",
                action="compose",
            )
        files = request.files.getlist("_file")
        attachments = [(f.filename, f.mimetype, f.read()) for f in files if f.filename]
        attachments += [(a["filename"], a["ctype"], a["data"]) for a in attachments_kept]
        if attach_original:
            attachments.append((attach_original[0], "message/rfc822", attach_original[1]))

        # rcmail_sendmail::send(): 'message_outgoing_body' transforms the body
        body = ph("message_outgoing_body", {"body": body, "type": "html" if html else "plain"})["body"]
        msg = build_message(
            ident["email"],
            ident["name"],
            to,
            cc,
            bcc,
            subject,
            body,
            html=html,
            attachments=attachments or None,
            in_reply_to=request.form.get("_in_reply_to") or None,
            references=request.form.get("_references") or None,
            reply_to=request.form.get("_reply_to") or None,
            followup_to=request.form.get("_followupto") or None,
            priority=request.form.get("_priority") or None,
            mdn=bool(request.form.get("_mdn")),
            force_7bit=bool(prefs.get("force_7bit")),
            keepformatting=bool(request.form.get("_keepformatting")),
            mime_param_folding=int(prefs.get("mime_param_folding", 1) or 1),
        )
        act = request.form.get("_action", "send")
        if act == "save" and request.form.get("_ajax"):
            # draft autosave (app.js auto_save_start -> command('savedraft')):
            # store silently and report the draft uid so the next save
            # replaces it instead of piling up copies
            try:
                new_uid = box.save_draft(wire_bytes(msg), replace_uid=int(draft_uid) if draft_uid else None)
                ph("message_draftsaved", {"uid": new_uid, "parentuid": draft_uid})
                return jsonify({"draft_id": new_uid or ""})
            except MailError as e:
                return jsonify({"error": str(e)}), 500
        # spellcheck_before_send (send.php:134-165): check the body before
        # sending unless this form was already checked (a second Send goes
        # through); found words are highlighted on re-render
        if (
            act == "send"
            and prefs.get("spellcheck_before_send")
            and body.strip()
            and not request.form.get("_spellchecked")
        ):
            from . import spellchecker

            lang = (request.form.get("_lang") or "en_US").replace("-", "_")
            ignore = {k: bool(prefs.get("spellcheck_ignore_" + k)) for k in ("syms", "nums", "caps")}
            with contextlib.suppress(Exception):
                words = spellchecker.check(body, lang, ignore=ignore)
                if words:
                    flash(i18n.gettext("mispellingsfound", g.lang, domain="messages"), "error")
                    prefill.update(
                        to=", ".join(to),
                        cc=", ".join(cc),
                        bcc=", ".join(bcc),
                        subject=subject,
                        body=body,
                        html="1" if html else "",
                    )
                    spell_words.update(words)
                    spell_checked = True
                    return _compose_render()
        try:
            if act == "save":
                # the draft keeps its Bcc header
                _du = box.save_draft(wire_bytes(msg), replace_uid=int(draft_uid) if draft_uid else None)
                ph("message_draftsaved", {"uid": _du, "parentuid": draft_uid})
                flash(i18n.gettext("messagesaved", g.lang, domain="messages"), "confirmation")
                return redirect(url_for("views.mail", _mbox=box.special("drafts") or "Drafts"))
            # smtplib needs the combined recipient list (incl. Bcc); the
            # transmitted header block and the Sent copy must not carry Bcc
            store_target = request.form.get("_store_target")
            # rcmail_sendmail::send(): plugins may amend headers or abort
            _h = ph("message_before_send", {"message": msg, "mode": "send"})
            if _h.get("abort"):
                raise MailError("sending aborted by plugin")
            msg = _h.get("message", msg)
            # reply_same_folder (compose.php:241): when the user did not
            # choose an explicit save folder, a reply's copy goes into the
            # folder of the replied-to message
            if (
                store_target in (None, "")
                and prefs.get("reply_same_folder")
                and mode in ("reply", "replyall", "replylist")
                and uid_of
                and src_folder
            ):
                store_target = src_folder
            box.send(
                msg,
                wire_bytes(msg),
                store_target=store_target if store_target is not None else None,
                extra_rcpts=[a for _d, a in email.utils.getaddresses(bcc) if a],
            )
            ph("message_sent", {"result": True, "mode": mode or "compose"})
            if draft_uid:
                box.delete_draft(draft_uid)
            # 'Collected addresses' prefs: store recipients (type 1) and the
            # replied-to sender as a trusted sender (type 2), like Roundcube.
            with contextlib.suppress(Exception):
                # never fail a send over address bookkeeping
                up = getattr(box, "prefs", None) or {}
                cr = str(up.get("collected_recipients", "1"))
                if cr == "1":
                    import email.utils as _eu

                    for raw in to + cc + bcc:
                        nm, addr = _decode_header(raw.rsplit("<", 1)[0] if "<" in raw else raw), _eu.parseaddr(raw)[1]
                        if addr:
                            store.collected_upsert(session["user_id"], 1, (nm or "").strip() or addr, addr)
                if mode in ("reply", "replyall", "replylist") and source_msg is not None:
                    import email.utils as _eu

                    frm = source_msg.get("From") or ""
                    nm, addr = _decode_header(frm), _eu.parseaddr(frm)[1]
                    if addr and str(up.get("collected_senders", "2")) == "2":
                        store.collected_upsert(session["user_id"], 2, nm or addr, addr)
            flash(i18n.gettext("messagesent", g.lang, domain="messages"), "confirmation")
            if extwin:
                # sent_successfully (app.js:5974): an extwin popup stays on
                # the locked form and closes itself after a second
                sent_ok = True
                return _compose_render()
            if store_target == "":  # "don't save"
                return redirect(url_for("views.mail", _mbox=box.special("drafts") or "INBOX"))
            return redirect(url_for("views.mail", _mbox=store_target or box.special("sent") or "INBOX"))
        except MailError as e:
            flash(str(e), "error")
            prefill.update(to=", ".join(to), cc=", ".join(cc), subject=subject, body=body, html="1" if html else "")
            return _compose_render()

    return _compose_render()


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
        size = (
            int(aprefs.get("addressbook_pagesize") or current_app.config["PAGE_SIZE"])
            or current_app.config["PAGE_SIZE"]
        )
    except (TypeError, ValueError):
        size = current_app.config["PAGE_SIZE"]
    total = len(allrows)
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(page, pages))
    rows = allrows[(page - 1) * size : page * size]
    more = page < pages
    if request.args.get("_dialog") == "1":
        # Elastic recipient_selector(): the contacts list inside a dialog iframe
        return render_template(
            "recipient_dialog.html",
            rows=rows,
            q=q,
            source=source,
            readonly=readonly,
            page=page,
            more=more,
            total=total,
            pages=pages,
        )
    groups = store.contactgroups(session["user_id"])
    return render(
        "addressbook",
        "addressbook.html",
        rows=rows,
        q=q,
        group=group,
        source=source,
        sources=SOURCES,
        readonly=readonly,
        groups=groups,
        page=page,
        more=more,
        total=total,
        list_title=("Search" if q else SOURCES[source]),
        search_mods=["name", "firstname", "surname", "email", "*"],
    )


@bp.route("/contact/<int:cid>")
@login_required
def contact_view(cid):
    store = get_store()
    row = store.contact(session["user_id"], cid)
    if not row:
        abort(404)
    groups = store.contactgroups(session["user_id"])
    member_of = [
        g["contactgroup_id"]
        for g in groups
        if cid in [m["contact_id"] for m in store.contactgroup_members(g["contactgroup_id"])]
    ]
    framed = request.args.get("_framed") == "1"
    has_photo = store.contact_photo(session["user_id"], cid) is not None
    ext = util.vcard_parse(row["vcard"]) if row["vcard"] else util.vcard_parse("")
    _order_group_rows(ext)  # show page uses the same subtype row ordering
    if framed:
        return render_template(
            "contact_framed.html",
            row=row,
            groups=groups,
            member_of=member_of,
            has_photo=has_photo,
            ext=ext,
            task="addressbook",
        )
    return render(
        "addressbook", "contact.html", row=row, groups=groups, member_of=member_of, has_photo=has_photo, ext=ext
    )


@bp.get("/contact/<int:cid>/photo")
@login_required
def contact_photo(cid):
    data = get_store().contact_photo(session["user_id"], cid)
    if not data:
        abort(404)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    elif data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "application/octet-stream"
    return Response(data, mimetype=mime)


def _compose_display_name(ext, full_email=False):
    """rcube_addressbook::compose_display_name(): join prefix, firstname,
    middlename, surname, suffix; when that is empty (or equals the address)
    derive the name from the primary email — full address with
    $full_email, else the local part split on ./-/_ and capitalized."""
    fn = " ".join(
        p
        for p in (
            ext.get(k)
            for k in
            # array_intersect_key() preserves the record key order,
            # which is CONTACT_COLTYPES order: firstname, surname come
            # before middlename/prefix/suffix (verified against a live
            # RC save: "Grace Hopper Murray Right RADM")
            ("firstname", "surname", "middlename", "prefix", "suffix")
        )
        if p
    )
    fn = " ".join(fn.split())
    emails = [v for _t, v in (ext.get("emails") or []) if v]
    email0 = emails[0] if emails else ""
    if email0 and (not fn or fn == email0):
        if full_email:
            return email0
        local = email0.split("@", 1)[0]
        m = re.search(r"(.*)[.\-_](.*)", local)
        fn = " ".join(_php_ucfirst(x) for x in m.groups()).strip() if m else _php_ucfirst(local)
    return fn


def _php_ucfirst(s):
    return s[:1].upper() + s[1:] if s else s


def _contact_head_props(ext):
    """elastic render_contact_form() head section: the display name is
    'unset' (row hidden, listed under the rel=head Add-field menu) when it
    equals the composed name (compose_display_name with name forced empty,
    full_email=false)."""
    dname = _compose_display_name({**ext, "name": ""}, full_email=False)
    ext["name_explicit"] = bool(ext.get("name")) and ext["name"] != dname
    _order_group_rows(ext)


# rcmail_action_contacts_index::contact_field_values(): group rows are
# emitted iterating the coltype's subtype list first, then any values with
# subtypes outside the list in record order (stable).
RC_SUBTYPE_ORDER = {
    "emails": ["home", "work", "other"],
    "phones": [
        "home",
        "home2",
        "work",
        "work2",
        "mobile",
        "main",
        "homefax",
        "workfax",
        "car",
        "pager",
        "video",
        "assistant",
        "other",
    ],
    "addresses": ["home", "work", "other"],
    "websites": ["homepage", "work", "blog", "profile", "other"],
    "im": ["aim", "icq", "msn", "yahoo", "jabber", "skype"],
}


def _order_group_rows(ext):
    for key, order in RC_SUBTYPE_ORDER.items():
        rows = ext.get(key) or []
        ext[key] = sorted(rows, key=lambda r, o=order: o.index(r[0]) if r[0] in o else len(o))


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
        # rcmail.command('upload-photo') equivalent: the hidden
        # #upload-formFrm posts only _upload/_cid/_photo (elastic
        # image_upload_input); record fields stay untouched
        if form.get("_upload") == "1":
            up = request.files.get("_photo")
            if up and up.filename and cid and row is not None:
                data = {k: row[k] for k in ("name", "email", "firstname", "surname", "vcard", "words")}
                store.contact_save(session["user_id"], data, contact_id=cid, photo=up.read())
                flash(i18n.gettext("successfullysaved", g.lang, domain="messages"), "confirmation")
            if cid:
                return redirect(url_for("views.contact_edit", cid=cid, _framed=_framed_arg()))
            return redirect(url_for("views.contact_edit", _framed=_framed_arg()))

        # reference contract (contacts/save.php + elastic contact form):
        # _firstname/_surname/... _subtype_email[]+_email[],
        # _subtype_phone[]+_phone[], _subtype_address[]+_street[]/_locality[]/
        # _zipcode[]/_region[]/_country[], _subtype_website[]+_website[],
        # _subtype_im[]+_im[], _gender/_birthday/_notes plus single-valued
        # _maidenname/_anniversary/_assistant/_manager/_spouse. Legacy names
        # (no underscore / _email_value[] etc.) remain accepted.
        def fv(key, legacy=None, default=""):
            if key in form:
                return form.get(key) or default
            if legacy and legacy in form:
                return form.get(legacy) or default
            return default

        def pairs(legacy_prefix, key, legacy_type=None):
            vals = form.getlist(key) or form.getlist(legacy_prefix)
            tk = legacy_type or (legacy_prefix.replace("_value", "_type"))
            types = form.getlist(tk)
            return [(types[i] if i < len(types) else "", v.strip()) for i, v in enumerate(vals) if v and v.strip()]

        ext = {
            "prefix": fv("_prefix", "prefix").strip(),
            "firstname": fv("_firstname", "firstname").strip(),
            "middlename": fv("_middlename", "middlename").strip(),
            "surname": fv("_surname", "surname").strip(),
            "suffix": fv("_suffix", "suffix").strip(),
            "nickname": fv("_nickname", "nickname").strip(),
            "organization": fv("_organization", "organization").strip(),
            "department": fv("_department", "department").strip(),
            "jobtitle": fv("_jobtitle", "jobtitle").strip(),
            "gender": fv("_gender", "gender").strip(),
            "birthday": fv("_birthday", "birthday").strip(),
            "notes": fv("_notes", "notes"),
            "maidenname": fv("_maidenname").strip(),
            "anniversary": fv("_anniversary").strip(),
            "assistant": fv("_assistant").strip(),
            "manager": fv("_manager").strip(),
            "spouse": fv("_spouse").strip(),
            "emails": pairs("_email_value[]", "_email[]", "_subtype_email[]"),
            "phones": pairs("_phone_value[]", "_phone[]", "_subtype_phone[]"),
            "websites": pairs("_website_value[]", "_website[]", "_subtype_website[]"),
            "im": pairs("_im_value[]", "_im[]", "_subtype_im[]"),
            "addresses": [
                tuple(a)
                for a in zip(
                    form.getlist("_subtype_address[]") or form.getlist("_atype[]"),
                    form.getlist("_street[]") or form.getlist("_astreet[]"),
                    form.getlist("_locality[]") or form.getlist("_alocality[]"),
                    form.getlist("_zipcode[]") or form.getlist("_azip[]"),
                    form.getlist("_region[]") or form.getlist("_aregion[]"),
                    form.getlist("_country[]") or form.getlist("_acountry[]"),
                    strict=False,
                )  # parallel form lists; trailing empties are dropped below
                if any(x.strip() for x in a)
            ],
        }
        name = fv("_name", "name").strip()
        ext["name"] = name
        # rcmail_action_contacts_save::process_input():285-293 — generate the
        # display name before validation (must happen before emails are
        # normalized), then reset it when it equals the primary address
        ext["emails"] = [(t, email.utils.parseaddr(v)[1] or v) for t, v in ext["emails"] if v.strip()]
        emails = [v for _t, v in ext["emails"]]
        if not name:
            name = _compose_display_name(ext, full_email=True)
            email0 = emails[0] if emails else ""
            if email0 and name == email0:
                name = ""
            ext["name"] = name
        firstname, surname = ext["firstname"], ext["surname"]
        data = {
            "name": name,
            "email": ", ".join(emails),
            "firstname": firstname,
            "surname": surname,
            "vcard": util.vcard_encode(ext),
            "words": util.contact_words(ext),
        }
        # rcube_contacts::validate() requires some name or email
        # (rcube_contacts.php:631-639 'nonamewarning'); contacts/save.php:55-58
        # shows it as a warning and re-renders the form with the posted record
        if not (firstname + surname + name) and not emails:
            flash(i18n.gettext("nonamewarning", g.lang, domain="messages"), "warning")
            _contact_head_props(ext)
            return _contactedit_out(row=data, ext=ext, cid=cid, replay=True)
        # RC save.php:62-72: photo '-del-' deletes, otherwise an upload replaces
        photo = _UNSET
        if form.get("delete_photo") or form.get("_photo") == "-del-":
            photo = b""
        elif (up := (request.files.get("_photo") or request.files.get("photo"))) and up.filename:
            photo = up.read()
        new_id = store.contact_save(session["user_id"], data, contact_id=cid, photo=photo)
        flash(i18n.gettext("successfullysaved", g.lang, domain="messages"), "confirmation")
        return redirect(url_for("views.contact_view", cid=new_id, _framed=_framed_arg()))
    ext = util.vcard_parse(row["vcard"]) if row and row["vcard"] else util.vcard_parse("")
    # RC add-contact dialog pre-fills the address; we deep-link instead:
    # /contact/new?_email=… starts the form with that address filled in
    if row is None and (pre := request.args.get("_email")) and not ext["emails"]:
        ext["emails"] = [("work", pre)]
    _contact_head_props(ext)
    return _contactedit_out(row=row, ext=ext, cid=cid)


def _contactedit_out(row, ext, cid, replay=False):
    # reference edit-contact renders bare (html.iframe, no shell) inside the
    # addressbook #contentframe when _framed=1; standalone keeps the full page
    business_mode = str((getattr(g, "prefs", {}) or {}).get("contact_form_mode", "private")) == "business"

    def _subtypes(types):
        if not business_mode:
            return list(types)
        work = [t for t in types if "work" in t]
        return work + [t for t in types if t not in work]

    ctx = {
        "row": row,
        "ext": ext,
        "cid": cid,
        "replay": replay,
        "action": "edit" if cid else "add",
        "business_mode": business_mode,
        "contact_types": _subtypes(util.CONTACT_TYPES),
        "contact_phone_types": _subtypes(util.CONTACT_PHONE_TYPES),
        "contact_website_types": _subtypes(util.CONTACT_WEBSITE_TYPES),
        "contact_im_types": list(util.CONTACT_IM_TYPES),
    }
    if request.args.get("_framed") == "1":
        return render_template("contactedit_framed.html", task="addressbook", **ctx)
    return render("addressbook", "contactedit.html", **ctx)


@bp.post("/contact/<int:cid>/delete")
@login_required
def contact_delete(cid):
    store = get_store()
    store.contact_delete(session["user_id"], [cid])
    flash(i18n.gettext("contactdeleted", g.lang, domain="messages"), "confirmation")
    return redirect(url_for("views.contacts"))


@bp.post("/contacts/group-addmembers")
@bp.post("/contacts/group-delmembers")
@login_required
def contact_group_members_toggle():
    """rcmail.group_member_change(): XHR group-addmembers/group-delmembers
    with _cid/_gid (program/js/app.js group_member_change)."""
    store = get_store()
    add = request.path.endswith("group-addmembers")
    cid = request.form.get("_cid", type=int)
    gid = request.form.get("_gid", type=int)
    row = store.contact(session["user_id"], cid) if cid else None
    result = None
    groups = {g["contactgroup_id"] for g in store.contactgroups(session["user_id"])}
    if row and gid in groups:
        members = [m["contact_id"] for m in store.contactgroup_members(gid)]
        if add and cid not in members:
            store.contactgroup_add(gid, [cid])
        elif not add and cid in members:
            store.contactgroup_remove(gid, [cid])
        count = len([m["contact_id"] for m in store.contactgroup_members(gid)])
        key = "contactaddedtogroup" if add else "contactremovedfromgroup"
        result = {
            "action": "group-members",
            "exec": [{"group": gid, "count": count}],
            "label": i18n.gettext(key, g.lang, domain="messages"),
        }
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return (jsonify(result or {}), 200)
    flash(
        i18n.gettext("contactaddedtogroup" if add else "contactremovedfromgroup", g.lang, domain="messages"),
        "confirmation",
    )
    return redirect(url_for("views.contact_view", cid=cid) if cid else url_for("views.contacts"))


# ------------------------------------------------------------ RC-style XHRs
# rcmail_output_json envelope: {"action": <action>, "exec": "cmd;\ncmd;\n"}


def _rc_json(action, cmds):
    payload = {"action": action, "exec": "".join(c + "\n" for c in cmds)}
    return Response(json.dumps(payload, separators=(",", ":")), mimetype="application/json")


def _js(*args):
    return ",".join(json.dumps(a, separators=(",", ":")) for a in args)


@bp.get("/mail/getunread")
@bp.get("/mail/check-recent")
@login_required
def mail_recent():
    """rcmail_action_mail_getunread / _check_recent.

    Roundcube caches per-folder unseen counts in the session and only sends
    changed counts on later calls; Craft is stateless, so every call answers
    like a first call: one set_unread_count per subscribed folder, and
    set_trash_count for the trash folder (getunread semantics)."""
    box = imap_box()
    prefs = g.get("prefs") or {}
    trash = prefs.get("trash_mbox")
    check_recent = request.path.endswith("/check-recent")
    cmds = []
    try:
        folders = [f["name"] for f in box.folders(subscribed_only=True)]
    except MailError:
        folders = []
    # check_recent.php: when 'check all folders' is off, only the current
    # folder is recounted; other folders keep their cached badges.
    check_all = bool(prefs.get("check_all_folders"))
    if check_recent and not check_all:
        folders = [request.args.get("_mbox") or "INBOX"]
    for name in folders:
        try:
            total, unseen = box.imap.status(name)
        except MailError:
            continue
        if check_recent:
            # send_unread_count(): 4th arg mark, '' when no change tracking
            cmds.append("this.set_unread_count({});".format(_js(name, unseen, name == "INBOX", "")))
        else:
            cmds.append("this.set_unread_count({});".format(_js(name, unseen, name == "INBOX")))
        if trash and name == trash:
            cmds.append(f"this.set_trash_count({total});")
    return _rc_json("check_recent" if check_recent else "getunread", cmds)


@bp.get("/mail/autocomplete")
@login_required
def mail_autocomplete():
    """rcmail_action_mail_autocomplete -> this.ksearch_query_results()."""
    term = request.args.get("_search") or request.args.get("_term") or ""
    reqid = request.args.get("_reqid") or ""
    maxnum = int(current_app.config.get("AUTOCOMPLETE_MAX", 15))
    store = get_store()
    contacts, sort_keys = {}, {}
    prefs = getattr(g, "prefs", {}) or {}
    single = bool(prefs.get("autocomplete_single"))
    if term:
        term_lc = term.lower()
        for row in store.contacts(session["user_id"], query=term):
            f = util.vcard_parse(row["vcard"])
            emails = [e for _t, e in f["emails"] if e]
            if not emails and row["email"]:
                emails = [row["email"]]
            name = row["name"] or " ".join(x for x in (row["firstname"], row["surname"]) if x)
            idx = 0
            for email in emails:
                contact = f"{name} <{email}>" if name else email
                # multi-email records only list addresses matching the term
                if len(emails) > 1 and term_lc not in contact.lower():
                    continue
                if contact in contacts:
                    continue
                disp = name or email
                contacts[contact] = {
                    "name": contact,
                    "type": None,
                    "id": str(row["contact_id"]),
                    "source": "sql",
                    "fields": {"name": disp, "email": email},
                }
                sort_keys[contact] = f"{disp} {idx:03d}"
                idx += 1
                if single:
                    break
                if len(contacts) >= maxnum:
                    break
            if len(contacts) >= maxnum:
                break
        # matching contact groups (distribution lists)
        for grp in store.contactgroups(session["user_id"]):
            if len(contacts) >= maxnum:
                break
            if term_lc not in grp["name"].lower():
                continue
            gname = grp["name"]
            try:
                n = len(store.contactgroup_members(grp["contactgroup_id"]))
            except Exception:
                n = 0
            if n and gname not in contacts:
                label = f"{gname} ({n})"
                contacts[gname] = {
                    "name": label,
                    "fields": {"name": label},
                    "type": "group",
                    "id": str(grp["contactgroup_id"]),
                    "source": "sql",
                }
                sort_keys[gname] = gname
        result = [contacts[k] for k in sorted(sort_keys, key=sort_keys.__getitem__)]
    else:
        result = []
    cmd = f"this.ksearch_query_results({_js(result, term, reqid)});"
    return _rc_json("autocomplete", [cmd])


@bp.route("/contacts/export")
@login_required
def contacts_export():
    """vCard export — 'Export all' / 'Export selected' (contacts.vcf).

    Mirrors rcmail_action_contacts_export: regenerates Roundcube's vCard 3.0
    bytes from the stored record plus live group membership (CATEGORIES)."""
    store = get_store()
    cids = request.args.getlist("_cid")
    if cids:
        rows = [store.contact(session["user_id"], int(c)) for c in cids]
        rows = [r for r in rows if r]
    else:
        rows = store.contacts(session["user_id"])
        # reference export iterates the default list order (ORDER BY surname)
        rows = sorted(rows, key=lambda r: r["surname"] or "")
    groups = store.contactgroups(session["user_id"])
    cat_of = {}
    for grp in groups:
        for m in store.contactgroup_members(grp["contactgroup_id"]):
            cat_of.setdefault(m["contact_id"], []).append(grp["name"])
    parts = []
    for r in rows:
        ext = util.vcard_parse(r["vcard"]) if r["vcard"] else util.vcard_parse("")
        if not ext["name"]:
            ext["name"] = r["name"] or ""
        if not ext["emails"] and r["email"]:
            ext["emails"] = [("work", e.strip()) for e in r["email"].split(",")]
        parts.append(util.vcard_export(ext, categories=cat_of.get(r["contact_id"], [])))
    body = "".join(parts)
    return Response(
        body,
        content_type="text/vcard; charset=UTF-8",
        headers={"Content-Disposition": 'attachment; filename="contacts.vcf"'},
    )


@bp.post("/contacts/import")
@login_required
def contacts_import():
    """Import contacts from an uploaded .vcf file."""
    store = get_store()
    f = request.files.get("_file")
    if not f or not f.filename:
        flash(i18n.gettext("fileuploaderror", g.lang, domain="messages"), "error")
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
        data = {
            "name": name,
            "email": ", ".join(emails),
            "firstname": ext["firstname"],
            "surname": ext["surname"],
            "vcard": util.vcard_encode(ext),
            "words": util.contact_words(ext),
        }
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
    fields = {
        k: ext.get(k)
        for k in (
            "name",
            "firstname",
            "surname",
            "middlename",
            "nickname",
            "organization",
            "jobtitle",
            "prefix",
            "suffix",
        )
    }
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
            flash(i18n.gettext("contactremovedfromgroup", g.lang, domain="messages"), "confirmation")
        else:
            store.contactgroup_add(gid, cids)
            flash(i18n.gettext("contactaddedtogroup", g.lang, domain="messages"), "confirmation")
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
    flash(i18n.gettext("contactaddedtogroup", g.lang, domain="messages"), "confirmation")
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
    # Reference shows the preferences list with nothing selected and the
    # watermark pane until a section row is clicked (?_task=settings landing).
    return render_settings_landing()


@bp.route("/settings/preferences", methods=["GET", "POST"])
@bp.route("/settings/preferences/<section>", methods=["GET", "POST"])
@login_required
def settings_preferences(section=None):
    store = get_store()
    prefs = dict(store.get_user_prefs(session["user_id"]))
    framed = request.args.get("_framed") == "1"
    if request.method == "POST":
        return prefs_save(store, prefs, request.form.get("_section") or "general", framed=framed)
    folders = [f["name"] for f in folders_for_menu()]
    sections = i18n.translate_sections(PREF_SECTIONS(prefs, folders), g.lang)
    if section not in sections:
        return render_settings_landing()
    blocks = sections[section]["blocks"]
    if framed:
        # reference: section forms render bare inside #preferences-frame
        return render_template("prefs_framed.html", task="settings", sections=sections, section=section, blocks=blocks)
    # Deep link: show the landing with this section opened in the frame.
    return render_settings_landing(open_section=section)


def render_settings_landing(open_section=None):
    store = get_store()
    prefs = dict(store.get_user_prefs(session["user_id"]))
    folders = [f["name"] for f in folders_for_menu()]
    return render(
        "settings",
        "preferences.html",
        prefs=prefs,
        mail_folders=folders,
        sections=i18n.translate_sections(PREF_SECTIONS(prefs, folders), g.lang),
        section=None,
        blocks=[],
        open_section=open_section,
    )


def prefs_save(store, prefs, section, framed=False):
    old_lang = prefs.get("language") or "en_US"
    submitted = prefs_sections.apply_form(prefs, request.form)
    store.set_user_prefs(session["user_id"], submitted)
    # rcmail_action_settings_prefs_save saves and then reloads the language,
    # so the confirmation already shows in the new language
    g.lang = i18n.language_prop(prefs.get("language") or "en_US")
    new_lang = prefs.get("language") or "en_US"
    if new_lang != old_lang:
        # prefs_save.php: load_language() + output->command('reload', 500);
        # verified live on the reference: saving a language change reloads
        # the whole window (parent frame included) so the task-menu labels
        # re-render translated without any manual refresh.
        from html import escape as _esc

        flash(i18n.gettext("successfullysaved", g.lang, domain="messages"), "confirmation")
        return Response(
            '<!DOCTYPE html><html><body><div class="voice">'
            + _esc(i18n.gettext("successfullysaved", g.lang, domain="messages"))
            + "</div><script>setTimeout(function(){var t=window;"
            "if (window.parent !== window) { try { void window.parent.document;"
            " t = window.parent; } catch (e) {} } t.location.reload();"
            "}, 500);</script></body></html>"
        )
    flash(i18n.gettext("successfullysaved", g.lang, domain="messages"), "confirmation")
    if framed:
        return redirect(url_for("views.settings_preferences", section=section, _framed="1"))
    return redirect(url_for("views.settings_preferences", section=section))


@bp.route("/settings/responses")
@login_required
def responses():
    store = get_store()
    rows = store.responses(session["user_id"])
    edit = request.args.get("_edit")
    edit_row = None
    if edit and edit != "new":
        edit_row = store.response(session["user_id"], int(edit))
        if not edit_row:
            abort(404)
    return render(
        "settings",
        "responses.html",
        rows=rows,
        editing=bool(edit),
        edit_row=edit_row,
        framed_page=request.args.get("_framed") == "1",
        editor_cfg=editor_config("response", store.get_user_prefs(session["user_id"])),
    )


@bp.route("/settings/responses", methods=["POST"])
@bp.route("/settings/response/edit/<int:rid>", methods=["GET", "POST"])
@bp.route("/settings/response/new", defaults={"rid": None}, methods=["GET", "POST"])
@login_required
def response_edit(rid=None):
    store = get_store()
    if rid is None and request.args.get("_edit", "").isdigit():
        rid = int(request.args["_edit"])
    row = store.response(session["user_id"], rid) if rid else None
    if rid and not row:
        abort(404)
    framed = request.args.get("_framed") == "1"

    def out(row_ctx):
        cfg = editor_config("response", store.get_user_prefs(session["user_id"]))
        if framed:
            return render_template("responseedit_framed.html", task="settings", row=row_ctx, editor_cfg=cfg)
        return render("settings", "responseedit.html", row=row_ctx, editor_cfg=cfg)

    if request.method == "POST":
        # reference contract (settings/response_save.php): _id/_name/_text/_is_html;
        # legacy names (name/body/html) remain accepted
        name = (request.form.get("_name") or request.form.get("name") or "").strip()
        body = request.form.get("_text")
        if body is None:
            body = request.form.get("body", "")
        is_html_val = request.form.get("_is_html", request.form.get("html"))
        is_html = 1 if is_html_val and is_html_val != "0" else 0
        if name and body.strip():
            new_id = store.response_save(session["user_id"], name, body, html=is_html, rid=rid)
            flash(i18n.gettext("successfullysaved", g.lang, domain="messages"), "confirmation")
            # reference keeps the record open in the edit frame after save;
            # app.js update_response_row(id, name, add) then syncs the parent list
            return redirect(
                url_for(
                    "views.response_edit",
                    rid=new_id,
                    _framed=_framed_arg(),
                    _saved="insert" if rid is None else "update",
                )
            )
        # response_save.php:55-59: show_message('formincomplete','error') +
        # overwrite_action('edit-response', post) - the form re-renders with
        # the submitted values and a sticky error box
        flash(i18n.gettext("formincomplete", g.lang, domain="messages"), "error")
        row = {"name": name, "body": body, "html": is_html, "response_id": rid}
    return out(row)


@bp.post("/settings/response/<int:rid>/delete")
@login_required
def response_delete(rid):
    get_store().response_delete(session["user_id"], rid)
    flash(i18n.gettext("deletedsuccessfully", g.lang, domain="messages"), "confirmation")
    return redirect(url_for("views.responses", _framed=_framed_arg()))


@bp.route("/settings/identities")
@login_required
def identities():
    store = get_store()
    rows = store.identities(session["user_id"])
    edit = request.args.get("_edit")
    edit_row = None
    if edit and edit != "new":
        edit_row = store.identity(session["user_id"], int(edit))
        if not edit_row:
            abort(404)
    return render(
        "settings",
        "identities.html",
        rows=rows,
        editing=bool(edit),
        edit_row=edit_row,
        framed_page=request.args.get("_framed") == "1",
        editor_cfg=editor_config("identity", store.get_user_prefs(session["user_id"])),
    )


@bp.route("/settings/identities", methods=["POST"])
@bp.route("/settings/identity/edit/<int:iid>", methods=["GET", "POST"])
@bp.route("/settings/identity/new", defaults={"iid": None}, methods=["GET", "POST"])
@login_required
def identity_edit(iid=None):
    store = get_store()
    if iid is None and request.args.get("_edit", "").isdigit():
        iid = int(request.args["_edit"])
    row = store.identity(session["user_id"], iid) if iid else None
    if iid and not row:
        abort(404)
    framed = request.args.get("_framed") == "1"

    def out(row_ctx):
        # reference: the frame page (_level=2 style) is a bare propform;
        # the standalone (non-framed) URL keeps the full page shell
        cfg = editor_config("identity", store.get_user_prefs(session["user_id"]))
        if framed:
            return render_template("identityedit_framed.html", task="settings", row=row_ctx, editor_cfg=cfg)
        return render("settings", "identityedit.html", row=row_ctx, editor_cfg=cfg)

    if request.method == "POST":
        data = identity_from_form(request.form, row)
        # identity_save.php: empty email -> warning + re-render form (#keep post)
        if not data["email"]:
            flash(i18n.gettext("noemailwarning", g.lang, domain="messages"), "warning")
            return out(data)
        # identity_save.php:93-97: rcube_utils::check_email failure
        if not util.check_email(data["email"]):
            flash(i18n.gettext("emailformaterror", g.lang, domain="messages", vars={"email": data["email"]}), "error")
            return out(data)
        new_id = store.identity_save(session["user_id"], data, identity_id=iid)
        flash(i18n.gettext("successfullysaved", g.lang, domain="messages"), "confirmation")
        # reference keeps the record open in the edit frame after save;
        # app.js update_identity_row(id, name, add) then syncs the parent list
        return redirect(
            url_for(
                "views.identity_edit",
                iid=new_id or iid,
                _framed=_framed_arg(),
                _saved="insert" if iid is None else "update",
            )
        )
    return out(row)


@bp.post("/settings/identity/<int:iid>/delete")
@login_required
def identity_delete(iid):
    store = get_store()
    store.identity_delete(session["user_id"], iid)
    flash(i18n.gettext("deletedsuccessfully", g.lang, domain="messages"), "confirmation")
    return redirect(url_for("views.identities", _framed=_framed_arg()))


# ---------------------------------------------------------------- folders


@bp.route("/settings/folders")
@login_required
def folders_view():
    box = imap_box()
    allf = box.folders()
    q = request.args.get("_q")
    if q:
        allf = [f for f in allf if q.lower() in f["name"].lower()]
    flt = request.args.get("_filter")
    if flt == "":  # "Personal": hide special folders
        allf = [f for f in allf if not f["special"] and f["name"].upper() != "INBOX"]
    uprefs = get_store().get_user_prefs(session["user_id"])
    for f in allf:
        f["display_name"] = folder_label(f["name"])
        # LSUB-derived per-folder subscription (see Imap.list_folders)
        f["subscribed"] = bool(f.get("subscribed"))
    edit = request.args.get("_edit")
    if edit and edit != "new" and edit not in {f["name"] for f in allf}:
        edit = None  # deep link to a folder that no longer exists
    if edit and request.args.get("_framed") == "1":
        # reference: the folder properties form lives in the settings
        # content frame (folder_edit.php); the list page never re-renders
        return _folderedit_framed(box, uprefs, allf, edit)
    roots = _folder_roots(allf)
    # toolbar states are data-driven from the selected row (elastic
    # selection handler): delete needs a non-special non-INBOX folder,
    # purge needs messages > 0 — carry both as data attributes
    # delete protection follows folder_edit/folders_list semantics: only
    # INBOX and folders configured as a special *_mbox are protected
    # (a folder merely *named* Drafts stays deletable — verified live)
    configured = {
        uprefs.get(k) for k in ("drafts_mbox", "sent_mbox", "junk_mbox", "trash_mbox", "archive_mbox") if uprefs.get(k)
    }
    for f in allf:
        msgs, _size = box.imap.status_size(f["name"])
        f["messages"] = msgs
        f["protected"] = f["name"].upper() == "INBOX" or f["name"] in configured
        f["li_id"] = "rcmli" + base64.b64encode(f["name"].encode()).decode()
    return render(
        "settings",
        "folders.html",
        all_folders=allf,
        tree=roots,
        folder_filter=flt if flt is not None else "---",
        q=q or "",
        framed_page=request.args.get("_framed") == "1",
        edit_folder=edit if edit else None,
    )


def _folder_roots(allf):
    """Reference folder tree order: INBOX first, siblings alphabetical
    case-insensitively, children nested under their parent li."""
    by = {f["name"]: f for f in allf}
    for f in allf:
        f["sub"] = []
    roots = []
    for f in sorted(allf, key=lambda x: x["name"].lower()):
        parent = by.get(f["name"].rsplit("/", 1)[0]) if "/" in f["name"] else None
        if parent is not None:
            parent["sub"].append(f)
        else:
            roots.append(f)
    for f in allf:
        f["sub"].sort(key=lambda x: x["name"].lower())
    roots.sort(key=lambda x: (0 if x["name"].upper() == "INBOX" else 1, x["name"].lower()))
    return roots


def _show_bytes(n):
    """rcube::show_byte_conversion_size(): 0 renders bare '0', values divide
    by 1023 with the localized byte units (B/KB/MB/GB)."""
    if not n:
        return "0"
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= div:
            return f"{round(n / 1023 / (div / 1023))} {unit}"
    return f"{n} B"


def _folderedit_framed(box, uprefs, allf, edit):
    is_new = edit == "new"
    # folder_edit.php: a folder configured as special (or INBOX) shows a
    # plaintext location block; a merely same-named folder stays editable
    configured = {
        uprefs.get(k) for k in ("drafts_mbox", "sent_mbox", "junk_mbox", "trash_mbox", "archive_mbox") if uprefs.get(k)
    }
    is_inbox = (not is_new) and (edit.upper() == "INBOX" or edit in configured)
    disp_name = edit.rsplit("/", 1)[-1]
    for f in allf:
        if f["name"] == edit:
            disp_name = f["display_name"]
    parent_of = "" if is_new or "/" not in edit else edit.rsplit("/", 1)[0]
    fvm = uprefs.get("folder_viewmodes") or {}
    # folder_edit.php:198: no stored view_mode -> config default_list_mode
    # (unset on the reference) -> 'list'
    viewmode = fvm.get(edit) or "list"
    parents = []

    def walk(nodes, depth):
        for f in nodes:
            parents.append((f["name"], f["display_name"], depth))
            walk(f["sub"], depth + 1)

    for f in allf:
        f.setdefault("sub", [])
    walk(_folder_roots(allf), 0)
    msgs, size_str = None, None
    if not is_new:
        m, z = box.imap.status_size(edit)
        msgs, size_str = m, _show_bytes(z or 0)
    return render_template(
        "folderedit_framed.html",
        task="settings",
        lang=uprefs.get("language") or "en_US",
        edit_folder=edit,
        is_new=is_new,
        is_inbox=is_inbox,
        disp_name=disp_name,
        name_value="" if is_new else edit.rsplit("/", 1)[-1],
        parent_of=parent_of,
        parents=parents,
        viewmode=viewmode,
        msgs=msgs,
        size_str=size_str,
        saved=request.args.get("_saved") == "1",
    )


@bp.post("/settings/folders")
@login_required
def folders_act():
    box = imap_box()
    act = request.form.get("_act")
    try:
        store = get_store()

        def save_viewmode(name):
            # RC stores per-folder view_mode in user folder_data
            vm = request.form.get("viewmode")
            if vm in ("list", "threads"):
                prefs = store.get_user_prefs(session["user_id"])
                fvm = dict(prefs.get("folder_viewmodes") or {})
                fvm[name] = vm
                store.set_user_pref(session["user_id"], "folder_viewmodes", fvm)

        def folder_name_error(nm):
            # rcmail_action_settings_folder_save::run() checks
            # (folder_save.php:48-59 + rcube_storage::folder_validate)
            if not nm:
                return i18n.gettext("namecannotbeempty", g.lang, domain="messages")
            if len(nm) > 128:
                return i18n.gettext("nametoolong", g.lang, domain="messages")
            if "/" in nm:  # hierarchy delimiter
                return i18n.gettext("forbiddencharacter", g.lang, domain="messages") + " (/)"
            return None

        if act == "create":
            name = request.form.get("name", "").strip()
            parent = request.form.get("parent", "").strip()
            error = folder_name_error(name)
            if error:
                flash(error, "error")
                return redirect(url_for("views.folders_view", _framed=_framed_arg()))
            if name:
                full = f"{parent}/{name}" if parent else name
                box.imap.create_folder(full)
                box.imap.subscribe(full)
                save_viewmode(full)
                flash(i18n.gettext("foldercreated", g.lang, domain="messages"), "confirmation")
                if _framed_arg():
                    # framed save: land on the new folder's editor, whose
                    # inline script bounces the top window to the list with
                    # the folder selected (reference reload-list contract)
                    return redirect(url_for("views.folders_view", _edit=full, _framed="1", _saved="1"))
                return redirect(url_for("views.folders_view"))
        elif act == "rename":
            old = request.form.get("folder")
            new = request.form.get("name", "").strip()
            parent = request.form.get("parent")
            if old and not new:
                # protected (special) folder editor: no name is submitted,
                # only the view mode persists
                save_viewmode(old)
                flash(i18n.gettext("folderupdated", g.lang, domain="messages"), "confirmation")
                if _framed_arg():
                    return redirect(url_for("views.folders_view", _edit=old, _framed="1", _saved="1"))
                return redirect(url_for("views.folders_view"))
            if old:
                error = folder_name_error(new)
                if error:
                    flash(error, "error")
                    return redirect(url_for("views.folders_view", _edit=old, _framed=_framed_arg()))
            if old and new:
                base = old.rsplit("/", 1)[0] if "/" in old else ""
                if parent is None:
                    parent = base
                target = f"{parent}/{new}" if parent else new
                if target != old:
                    box.imap.rename_folder(old, target)
                    prefs = store.get_user_prefs(session["user_id"])
                    fvm = dict(prefs.get("folder_viewmodes") or {})
                    if old in fvm:
                        fvm[target] = fvm.pop(old)
                        store.set_user_pref(session["user_id"], "folder_viewmodes", fvm)
                save_viewmode(target)
                flash(i18n.gettext("folderupdated", g.lang, domain="messages"), "confirmation")
                if _framed_arg():
                    return redirect(url_for("views.folders_view", _edit=target, _framed="1", _saved="1"))
                return redirect(url_for("views.folders_view"))
        elif act == "delete":
            name = request.form.get("folder")
            if name:
                box.imap.delete_folder(name)
                flash(i18n.gettext("folderdeleted", g.lang, domain="messages"), "confirmation")
        elif act == "empty":
            name = request.form.get("folder")
            if name:
                box.empty_folder(name)
                # folder_purge.php:55 'folderpurged' confirmation
                flash(i18n.gettext("folderpurged", g.lang, domain="messages"), "confirmation")
        elif act in ("subscribe", "unsubscribe"):
            # reference: settings folder_subscribe/folder_unsubscribe actions
            name = request.form.get("folder")
            if name and name.upper() != "INBOX":
                if act == "subscribe":
                    box.imap.subscribe(name)
                else:
                    box.imap.unsubscribe(name)
                return redirect(url_for("views.folders_view", _edit=name, _framed=_framed_arg()))
    except MailError as e:
        flash(str(e), "error")
    return redirect(url_for("views.folders_view", _framed=_framed_arg()))


# ---------------------------------------------------------------- about


def _about_plugin_info():
    """rcmail_action_settings_about::plugins_list(): metadata of the active
    plugins (plus their required plugins), sorted by name; rows are only
    rendered when at least one plugin provides info."""
    api = get_api()
    plugin_info = {}
    for name in api.active_plugins:
        info = api.get_info(name)
        if info:
            plugin_info[name] = info
    # load info from required plugins, too
    for _name, info in list(plugin_info.items()):
        for req in info.get("require") or []:
            if req not in plugin_info:
                req_info = api.get_info(req)
                if req_info:
                    plugin_info[req] = req_info
    return [
        {
            "name": info.get("name") or name,
            "version": info.get("version") or "",
            "license": info.get("license") or "",
            "license_uri": info.get("license_uri") or "",
            "uri": info.get("src_uri") or info.get("uri") or "",
        }
        for name, info in sorted(plugin_info.items())  # ksort SORT_LOCALE
    ]


@bp.route("/about")
@login_required
def about():
    plugins = _about_plugin_info()
    if request.args.get("_framed") == "1":
        # reference: about dialog loads `?_task=settings&_action=about&_framed=1`
        return render_template("about_framed.html", task="settings", plugins=plugins)
    return render("settings", "about.html", plugins=plugins)
