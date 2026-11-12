"""CraftCube — a Python re-implementation of the Roundcube Webmail UI."""
import os
import re

from flask import Flask, g, render_template

from . import util
from .config import Config
from .store import Store


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
    app.store = Store(app.config["DB_PATH"])

    from .views import bp as views_bp
    app.register_blueprint(views_bp)

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

    @app.context_processor
    def inject_globals():
        return {
            "product_name": app.config["PRODUCT_NAME"],
            "version": app.config["VERSION"],
            "current_user": g.get("user"),
            "task": g.get("task", ""),
            "action": g.get("action", ""),
        }

    @app.errorhandler(404)
    @app.errorhandler(500)
    def error_page(err):
        code = getattr(err, "code", 500)
        return render_template("error.html", code=code,
                               message=getattr(err, "description", "Server error")), code

    return app
