"""CraftCube — a Python re-implementation of the Roundcube Webmail UI."""
import os
import re

from flask import Flask, g, render_template, request, send_from_directory
from markupsafe import Markup

from . import i18n, util
from .config import Config
from .plugins import init_api
from .store import Store

# plugin API path conventions (Roundcube derives _task from the request)
_TASK_PATHS = {"mail": "mail", "message": "mail", "compose": "mail",
               "attachment": "mail", "contacts": "addressbook",
               "settings": "settings", "login": "login", "logout": "login"}


def _request_task_action():
    task = request.args.get("_task") or ""
    if not task:
        seg = (request.path.split("/")[1] if len(request.path) > 2 else "")
        task = _TASK_PATHS.get(seg, "")
    return task, request.args.get("_action") or ""


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
    app.store = Store(app.config["DB_PATH"])

    from .views import bp as views_bp
    app.register_blueprint(views_bp)

    # ---- plugin engine (rcube_plugin_api equivalent) --------------------
    api = init_api(app)

    @app.before_request
    def _plugin_request_open():
        task, action = _request_task_action()
        html = (not request.path.startswith(("/json", "/attachment"))
                and request.headers.get("X-Requested-With") != "XMLHttpRequest"
                and not request.path.endswith(".json"))
        framed = request.args.get("_framed") not in (None, "", "0")
        api.open_request(task=task, action=action, html=html, framed=framed)
        # rcmail.php:227 — the 'ready' hook fires with task/action context
        api.exec_hook("ready", {"task": task, "action": action})
        # allow 5 "redirects" to another action (rcmail.php dispatch loop):
        # a plugin callback may return another _action as a string
        for _ in range(5):
            if not action.startswith("plugin."):
                break
            from flask import session as fsession
            if not fsession.get("user_id"):
                break  # plugin actions run authenticated, like Roundcube
            result = api.exec_action(action, task=task)
            if result is None:
                break
            if not isinstance(result, (str, bytes)):
                return result
            action = str(result)  # a plugin redirected to another action
        g._cc_plugin_action_handled = action
        return None

    @app.teardown_appcontext
    def _plugin_request_close(_exc):
        api.close_request()

    @app.route("/plugins/<name>/<path:fn>")
    def plugin_resource(name, fn):
        # $api->url . resource_url($fn): /plugins/<id>/<file>
        return send_from_directory(str(api.dir / name), fn)

    def _container(name):
        st = api.state_or_none
        # plugin-provided HTML, same trust level as Roundcube add_content()
        return Markup(st.contents.get(name, "")) if st else Markup("")  # noqa: S704

    def _object(name, **a):
        st = api.state_or_none
        if not st:
            return ""
        cb = st.objects.get(name if name.startswith("plugin.") else "plugin." + name)
        return cb(a) if cb else ""

    app.jinja_env.globals["plugin_container"] = _container
    app.jinja_env.globals["plugin_enabled"] = lambda name: name in api.plugins
    app.jinja_env.globals["plugin_object"] = _object

    @app.template_filter("rcdate")
    def _rcdate(dt):
        return util.fmt_date(dt)

    @app.template_filter("listdate")
    def _listdate(dt):
        prefs = getattr(g, "prefs", None)
        return util.list_pref_date(dt, prefs) if prefs else util.fmt_list_date(dt)

    @app.template_filter("summarydate")
    def _summarydate(dt):
        prefs = getattr(g, "prefs", None)
        return util.fmt_pref_date(dt, prefs) if prefs else util.fmt_summary_date(dt)

    @app.template_filter("datetime")
    def _datetime(dt):
        return util.fmt_datetime(dt)

    @app.template_filter("size")
    def _size(n):
        return util.human_size(n)

    @app.template_filter("rc_recipient")
    def _rc_recipient(ident):
        # rcube format_email_recipient(email, name)
        def field(key):
            try:
                return ident[key]
            except (KeyError, IndexError, TypeError):
                return getattr(ident, key, "") or ""
        email = (field("email") or "").strip()
        name = field("name") or ""
        if name and name != email:
            if re.search(r'[()<>\.\[\]@,;:"]', name):
                name = '"' + re.sub(r'(["\\])', r"\\\1", name) + '"'
            return f"{name} <{email}>"
        return email

    @app.template_filter("lc")
    def _lc(text):
        # translate an English UI literal through its catalogue key
        return i18n.translate_en(text, g.get("lang", "en_US"))

    # rcube-style UI gettext usable in templates and includes alike
    app.jinja_env.globals["_"] = lambda key, **vars: i18n.gettext(
        key, g.get("lang", "en_US"), vars or None)

    @app.context_processor
    def inject_globals():
        return {
            "product_name": app.config["PRODUCT_NAME"],
            "version": app.config["VERSION"],
            "current_user": g.get("user"),
            "task": g.get("task", ""),
            "action": g.get("action", ""),
            "lang": g.get("lang", "en_US"),
            # rcube app.env.labels: the catalogue slice client JS needs
            "js_labels": i18n.js_labels(g.get("lang", "en_US")),
            # plugin-declared client resources (include_script/-stylesheet)
            "plugin_scripts": list(api.state.scripts) if api.state_or_none else [],
            "plugin_stylesheets": list(api.state.stylesheets) if api.state_or_none else [],
            "plugin_labels": sorted(api.state.labels) if api.state_or_none else [],
            # rcmail labels from plugins: key -> human suffix fallback
            "plugin_label_map": {
                k: k.partition(".")[2].replace("_", " ").capitalize()
                for k in (sorted(api.state.labels) if api.state_or_none else [])},
        }

    @app.errorhandler(404)
    @app.errorhandler(500)
    def error_page(err):
        code = getattr(err, "code", 500)
        return render_template("error.html", code=code,
                               message=getattr(err, "description", "Server error")), code

    return app
