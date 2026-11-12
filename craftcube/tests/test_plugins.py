"""Plugin engine (rcube_plugin_api port) semantics and integration."""
import textwrap

import pytest

from app.plugins import get_api

DEMO_PLUGIN = textwrap.dedent('''
    from flask import Response

    from app.plugins import Plugin


    class demo(Plugin):
        CONFIG = {"demo_opt": "default"}

        def init(self):
            self.load_config()
            self.add_hook("loginform_content", self.login_marker)
            self.register_action("plugin.demo.hello", self.hello)
            self.api.add_content('<span id="demo-ct">C</span>', "listcontrols")
            self.add_label("hello_world")
            self.include_script("demo.js")

        def login_marker(self, args):
            args["content"] = args.get("content", "") + "<!--demo-hook-->" + self.config["demo_opt"]
            return args

        def hello(self):
            return Response("hello world", mimetype="text/plain")
''')

SETONLY_PLUGIN = textwrap.dedent('''
    from app.plugins import Plugin


    class setonly(Plugin):
        task = "settings"

        def init(self):
            self.add_hook("loginform_content", self.mark)

        def mark(self, args):
            args["content"] = args.get("content", "") + "<!--setonly-->"
            return args
''')


@pytest.fixture()
def plugin_env(tmp_path):
    """A dedicated app: plugins load inside create_app (its before_request
    closure holds the API instance), against a temp plugins dir."""
    from app import create_app
    pdir = tmp_path / "plugins"
    (pdir / "demo").mkdir(parents=True)
    (pdir / "setonly").mkdir(parents=True)
    (pdir / "demo" / "demo.py").write_text(DEMO_PLUGIN)
    (pdir / "demo" / "config.inc.py").write_text('config = {"demo_opt": "layered"}\n')
    (pdir / "demo" / "demo.js").write_text("// demo plugin script\n")
    (pdir / "setonly" / "setonly.py").write_text(SETONLY_PLUGIN)
    return create_app({
        "TESTING": True,
        "DB_PATH": str(tmp_path / "t.sqlite"),
        "SECRET_KEY": "test-secret",
        "IMAP_HOST": "127.0.0.1", "IMAP_PORT": 1,
        "SMTP_HOST": "127.0.0.1", "SMTP_PORT": 1,
        "PLUGINS_DIR": str(pdir),
        "PLUGINS": ["demo", "setonly"],
    })


def _open_api():
    api = get_api()
    api.open_request()
    return api


def test_load_and_list(plugin_env):
    assert get_api().loaded_plugins() == ["demo", "setonly"]


def test_load_missing_plugin_not_required(plugin_env):
    assert get_api().load_plugin("ghost", require=False) is False


def test_invalid_name_rejected(plugin_env):
    assert get_api().load_plugin("../evil") is False


def test_hook_merge_break_and_dynamic_handlers(plugin_env):
    """exec_hook: handler dict wins per key ($ret + $args), break stops the
    chain, handlers added during the run still execute."""
    api = _open_api()
    seen = []
    api.register_hook("h", lambda a: {"a": 1, "added": True})
    api.register_hook("h", lambda a: {"a": 2})

    def third(args):
        seen.append(args)
        assert api.is_processing()
        args["break"] = True
    api.register_hook("h", third)

    def never(args):  # must not run: previous handler set break
        raise AssertionError("ran after break")
    api.register_hook("h", never)

    out = api.exec_hook("h", {"a": 0, "keep": 1})
    assert out == {"a": 2, "keep": 1, "added": True, "break": True, "abort": False}
    assert seen[0]["a"] == 2  # earlier handler output visible in args

    # a handler added while the hook runs is executed too
    api2 = _open_api()
    order = []

    def first(args):
        order.append("first")
        api2.register_hook("dyn", lambda a: order.append("late"))
    api2.register_hook("dyn", first)
    api2.exec_hook("dyn")
    assert order == ["first", "late"]


def test_action_owner_conflict_keeps_first(plugin_env):
    api = _open_api()
    api.register_action("x", "owner1", lambda: "one")
    api.register_action("x", "owner2", lambda: "two")
    assert api.state.actions["plugin.x"]() == "one"
    api.register_action("x", "owner1", lambda: "one-b")  # same owner may replace
    assert api.state.actions["plugin.x"]() == "one-b"


def test_task_qualified_action_wins(plugin_env):
    api = _open_api()
    api.register_action("go", "p1", lambda: "global")
    api.register_action("go", "p2", lambda: "mailed", task="mail")
    # plugin-task dispatch (rcmail.php:277) passes '<task>.<action>'
    assert api.exec_action("mail.go") == "mailed"
    # plain _action=plugin.go still resolves the global key
    assert api.exec_action("plugin.go", task="mail") == "global"


def test_task_and_frame_filters(plugin_env):
    api = get_api()
    st = api.open_request(task="login")
    assert "setonly" not in st.initialized  # task mismatch
    st = api.open_request(task="settings")
    assert "setonly" in st.initialized


def test_login_page_hook_container_and_assets(plugin_env):
    client = plugin_env.test_client()
    html = client.get("/login").get_data(as_text=True)
    assert "<!--demo-hook-->layered" in html      # hook ran, config layered
    assert "<!--setonly-->" not in html           # task-filtered out
    js = client.get("/plugins/demo/demo.js")
    assert js.status_code == 200
    assert "// demo plugin script" in js.get_data(as_text=True)
    # the include_script() declaration reaches the page head/footer
    assert "/plugins/demo/demo.js" in html
    # plugin label reached the client label map
    assert "demo.hello_world" in html
    # path traversal blocked
    assert client.get("/plugins/demo/..%2f..%2fconfig.py").status_code == 404


def test_plugin_action_dispatch(plugin_env, user):
    client = plugin_env.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user
    r = client.get("/mail?_action=plugin.demo.hello")
    assert r.status_code == 200
    assert r.get_data() == b"hello world"


def test_plugin_action_requires_login(plugin_env):
    client = plugin_env.test_client()
    r = client.get("/mail?_action=plugin.demo.hello")
    # not dispatched anonymously: falls through to the normal mail redirect
    assert r.status_code == 302


def test_register_task_guard(plugin_env):
    api = _open_api()
    assert api.register_task("help", "p") is True
    assert api.register_task("help", "q") is False   # duplicate
    assert api.register_task("mail", "q") is False   # reserved
    assert api.register_task("Bad Name", "q") is False


def test_headers_plugin_via_client(monkeypatch, plugin_env):
    """The bundled additional_message_headers expands %u/%l/%d like the PHP
    preg_replace pairs and overrides existing headers."""
    import importlib.util
    from email.message import EmailMessage
    from pathlib import Path

    import app.views as views
    from app import plugins as P

    path = Path(views.__file__).parent.parent / "plugins" / \
        "additional_message_headers" / "additional_message_headers.py"
    spec = importlib.util.spec_from_file_location("amh", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    api = P.get_api()

    class FakeStore:
        def default_identity(self, uid):
            return {"name": "Test User", "email": "tu@example.org"}

    monkeypatch.setattr(views, "get_store", lambda: FakeStore())
    plugin = mod.additional_message_headers(api, "additional_message_headers")
    plugin.config = {"additional_message_headers": {
        "X-App": "%u <%l@%d>", "X-Esc": "%%u stays", "X-Over": "new"}}
    msg = EmailMessage()
    msg["X-Over"] = "old"
    with plugin_env.test_request_context("/"):
        from flask import session
        session["user_id"] = 1
        out = plugin.message_headers({"message": msg})
    m = out["message"]
    assert m["X-App"] == "Test User <tu@example.org>"
    assert m["X-Esc"] == "%u stays"
    assert m["X-Over"] == "new"       # override semantics (headers(..., true))


def test_export_delegates_to_zipdownload(app, user):
    """The product default ships zipdownload; /message/export is its action."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user
        sess["username"] = "unit@example.org"
        sess["imap_password"] = "secret"
    assert get_api().get_plugin("zipdownload") is not None
    # no uids -> 404 (same as the reference plugin action)
    assert client.get("/message/export").status_code == 404


# ---------------------------------------------------------------------------
# zipdownload port: reference selection parsing + entry-name helpers
# ---------------------------------------------------------------------------

def _load_zipdownload():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(__file__), os.pardir,
                        "plugins", "zipdownload", "zipdownload.py")
    spec = importlib.util.spec_from_file_location("zd_port", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_zipdownload_uid_selection_multifolder(plugin_env):
    mod = _load_zipdownload()
    zd = mod.zipdownload.__new__(mod.zipdownload)
    with plugin_env.test_request_context(
            "/x", method="POST",
            data={"_mbox": "INBOX", "_uid[]": ["5", "9-Sent Mail", "7"]}):
        groups = zd._uid_selection()
    # get_uids(): uid or uid-MBOX tokens, first-seen order
    assert groups == {"INBOX": ["5", "7"], "Sent Mail": ["9"]}
    with plugin_env.test_request_context("/x?_mbox=INBOX&_uid=3,4-Drafts"):
        groups = zd._uid_selection()
    assert groups == {"INBOX": ["3"], "Drafts": ["4"]}


def test_zipdownload_entry_names_from_subject(plugin_env):
    mod = _load_zipdownload()
    zd = mod.zipdownload.__new__(mod.zipdownload)
    zd.charset = "ISO-8859-1"
    # _filename_from_subject: collapse control whitespace, trim " ./_"
    assert zd._filename_from_subject("  Re: hi\n\tthere  ") == "Re: hi there"
    # _convert_filename: backslash->'-' first, then basename, ctrl chars out
    assert zd._convert_filename("a/b" + chr(92) + "c") == "b-c"
    # latin-1 encodes cleanly; unconvertible chars become '?' (like iconv)
    assert zd._convert_filename("caf\u00e9 \u4e2d") == "caf\u00e9 ?"
    # mbox stamp: PHP 'D M d H:i:s Y' in UTC with C-locale month names
    from datetime import UTC, datetime
    stamp = zd._mbox_stamp(datetime(2026, 11, 3, 7, 5, 9, tzinfo=UTC))
    assert stamp == "Tue Nov 03 07:05:09 2026"


def test_plugin_action_route_dispatch_and_404(plugin_env):
    client = plugin_env.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "unit@example.org"
    # demo plugin registers plugin.demo.hello in the fixture source
    r = client.get("/plugin/demo/hello")
    assert r.status_code == 200 and b"hello world" in r.data
    assert client.get("/plugin/demo/nosuch").status_code == 404
    assert client.get("/plugin/ghost/hello").status_code == 404
    # anonymous: login required
    anon = plugin_env.test_client()
    assert anon.get("/plugin/demo/hello").status_code == 302
