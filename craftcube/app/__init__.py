"""CraftCube — a Python re-implementation of the Roundcube Webmail UI."""
import functools
import os

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)

from .auth import hash_password, verify_password
from .config import Config
from .mail import Imap, MailError, Mailbox
from .store import Store
from . import util


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

    @app.template_filter("datetime")
    def _datetime(dt):
        return util.fmt_datetime(dt)

    @app.template_filter("size")
    def _size(n):
        return util.human_size(n)

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
