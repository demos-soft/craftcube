"""Roundcube-style plugin infrastructure (port of rcube_plugin_api + rcube_plugin).

Mirrors program/lib/Roundcube/rcube_plugin_api.php and rcube_plugin.php:
plugins live in ``plugins/<name>/<name>.py`` and define a class named
``<name>`` extending :class:`Plugin`.  Enabled plugins are listed in the
``plugins`` config option (env ``CRAFTCUBE_PLUGINS``, comma separated),
exactly like ``$config['plugins']`` in Roundcube.

Semantics kept faithful to the PHP original:

* ``exec_hook`` starts args with ``abort`` defaulting to False; handler
  return dicts override keys (PHP ``$args = $ret + $args``), handlers added
  while the hook runs are still executed, and ``break`` ends the chain.
* plugin init/filtering happens per request (Roundcube re-runs init() on
  every dispatch); registrations (hooks, actions, template objects,
  includes, containers) therefore live in per-request state on ``flask.g``
  while plugin instances are created once at app start.
* ``register_action`` prefixes names with ``plugin.`` unless a plugin task
  is registered (then ``<task>.<action>``); a name already owned by another
  plugin cannot be overwritten.
* plugin assets are served under ``/plugins/<name>/`` (Roundcube
  ``$api->url``), absolute and ``http(s)`` paths pass through unchanged.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

from flask import g, has_request_context

log = logging.getLogger("craftcube.plugins")

# rcmail::$main_tasks — plugin tasks may not shadow these
MAIN_TASKS = ("login", "mail", "addressbook", "settings", "utils")

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")          # load_plugin() guard
_TASK_RE = re.compile(r"^[a-z0-9_.-]+$")          # asciiwords()

# rcube_plugin_api::$license_uris — short license id -> license page
LICENSE_URIS = {
    "Apache": "https://www.apache.org/licenses/LICENSE-2.0.html",
    "Apache-2": "https://www.apache.org/licenses/LICENSE-2.0.html",
    "Apache-1": "https://www.apache.org/licenses/LICENSE-1.0",
    "Apache-1.1": "https://www.apache.org/licenses/LICENSE-1.1",
    "GPL": "https://www.gnu.org/licenses/gpl.html",
    "GPL-2.0": "https://www.gnu.org/licenses/gpl-2.0.html",
    "GPL-2.0+": "https://www.gnu.org/licenses/gpl.html",
    "GPL-3.0": "https://www.gnu.org/licenses/gpl-3.0.html",
    "GPL-3.0+": "https://www.gnu.org/licenses/gpl.html",
    "AGPL-3.0": "https://www.gnu.org/licenses/agpl.html",
    "AGPL-3.0+": "https://www.gnu.org/licenses/agpl.html",
    "LGPL": "https://www.gnu.org/licenses/lgpl.html",
    "LGPL-2.0": "https://www.gnu.org/licenses/lgpl-2.0.html",
    "LGPL-2.1": "https://www.gnu.org/licenses/lgpl-2.1.html",
    "LGPL-3.0": "https://www.gnu.org/licenses/lgpl.html",
    "LGPL-3.0+": "https://www.gnu.org/licenses/lgpl.html",
    "BSD": "https://opensource.org/licenses/bsd-license.html",
    "BSD-2-Clause": "https://opensource.org/licenses/BSD-2-Clause",
    "BSD-3-Clause": "https://opensource.org/licenses/BSD-3-Clause",
    "FreeBSD": "https://opensource.org/licenses/BSD-2-Clause",
    "MIT": "https://www.opensource.org/licenses/mit-license.php",
    "PHP": "https://opensource.org/licenses/PHP-3.0",
    "PHP-3": "https://www.php.net/license/3_01.txt",
    "PHP-3.0": "https://www.php.net/license/3_0.txt",
    "PHP-3.01": "https://www.php.net/license/3_01.txt",
}


class Plugin:
    """Base class for plugins — port of rcube_plugin."""

    #: regex of task names this plugin binds to ('' = all tasks)
    task: str | None = None
    #: skip the plugin on AJAX requests
    noajax = False
    #: skip the plugin on framed (_framed=1) requests
    noframe = False
    #: prefs a plugin may write via the client save-prefs command
    allowed_prefs: ClassVar[list[str]] = []
    #: bundled defaults (like config.inc.php.dist), overridden by
    #: plugins/<name>/config.inc.py through load_config()
    CONFIG: ClassVar[dict] = {}

    def __init__(self, api: PluginAPI, name: str):
        self.api: PluginAPI = api
        self.id = name                       # rcube_plugin::$ID
        self.home = api.dir / name           # filesystem location
        self.urlbase = api.url + name + "/"  # public URL base
        self.config: dict = dict(self.CONFIG)
        self._loaded_config: list[str] = []

    # subclasses must implement
    def init(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def onload(self):
        """Optional early-boot hook (method_exists('onload') in PHP)."""

    @staticmethod
    def info():
        return False

    # --- config -------------------------------------------------------
    def load_config(self, fname="config.inc.py"):
        """Merge plugins/<name>/config.inc.py over the bundled defaults.

        Roundcube loads the shipped config.inc.php first, then lets a
        <name>.inc.php in the global config path override it; both layers
        patch the global config.  Here: plugin-local file only, values land
        in the plugin's ``config`` dict and the app config namespace under
        their original (unprefixed) keys.
        """
        if fname in self._loaded_config:
            return True
        self._loaded_config.append(fname)
        fpath = self.home / fname
        if fpath.is_file():
            ns: dict = {}
            try:
                code = compile(fpath.read_text(encoding="utf-8"), str(fpath), "exec")
                exec(code, ns)  # noqa: S102 - trusted plugin config, like PHP include
            except Exception as exc:
                log.error("Failed to load config from %s: %s", fpath, exc)
                return False
            cfg = ns.get("config", ns)
            self.config.update(cfg)
            if self.api.app is not None:
                self.api.app.config.update(dict(cfg))
        return True

    # --- registration --------------------------------------------------
    def add_hook(self, hook, callback):
        self.api.register_hook(hook, callback)

    def remove_hook(self, hook, callback):
        self.api.unregister_hook(hook, callback)

    def register_action(self, action, callback):
        self.api.register_action(action, self.id, callback, self.mytask)

    def register_handler(self, name, callback):
        self.api.register_handler(name, self.id, callback)

    def register_task(self, task):
        if self.api.register_task(task, self.id):
            self.mytask = task

    mytask: str | None = None

    def require_plugin(self, name):
        return self.api.load_plugin(name, force=True)

    def include_plugin(self, name):
        return self.api.load_plugin(name, force=True, require=False)

    # --- client resources ----------------------------------------------
    def include_script(self, fn):
        self.api.include_script(self._resource_url(fn))

    def include_stylesheet(self, fn):
        self.api.include_stylesheet(self._resource_url(fn))

    def add_label(self, *keys):
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
            keys = keys[0]
        self.api.add_labels([k if k.startswith(self.id + ".") else f"{self.id}.{k}"
                             for k in keys])

    def gettext(self, key, vars=None, lang=None):
        from . import i18n
        text = i18n.gettext(f"{self.id}.{key}", lang, vars)
        return text if text != f"{self.id}.{key}" else i18n.gettext(key, lang, vars)

    def url(self, fn):
        return self.api.url + self._resource_url(fn)

    def _resource_url(self, fn):
        if fn.startswith("/") or fn.lower().startswith(("http://", "https://",
                                                        "skins/")):
            return fn
        return f"{self.id}/{fn}"


class PluginAPI:
    """Singleton plugin engine — port of rcube_plugin_api."""

    def __init__(self, app=None):
        self.app = app
        if app is not None:
            override = app.config.get("PLUGINS_DIR")
            self.dir = Path(override) if override \
                else Path(app.root_path).parent / "plugins"
        else:
            self.dir = Path("plugins")
        self.url = "/plugins/"
        self.plugins: dict[str, Plugin] = {}
        self.active_plugins: list[str] = []   # loaded (init may still be filtered)
        self.loaded_prefs: list[str] = []
        self._state: SimpleNamespace | None = None
        self.exec_stack: list[str] = []

    # --- request lifecycle ---------------------------------------------
    def open_request(self, task="", action="", html=True, framed=False):
        """Begin a per-request registration scope and init unfiltered plugins.

        Equivalent of Roundcube booting one PHP request: fresh hook/action/
        container registries, then load_plugins() with the request filter.
        """
        st = SimpleNamespace(task=task, action=action, html=html, framed=framed,
                             handlers=defaultdict(list), actions={}, actionmap={},
                             objects={}, objectsmap={}, tasks={}, contents={},
                             scripts=[], stylesheets=[], labels=set(),
                             initialized=set())
        self._state = st
        if has_request_context():
            g._cc_plugin_state = st
        for name in list(self.plugins):
            self._init_plugin(name)
        return st

    @property
    def state(self) -> SimpleNamespace:
        if self._state is None:
            if has_request_context() and hasattr(g, "_cc_plugin_state"):
                return g._cc_plugin_state
            raise RuntimeError("plugin API used outside of a request scope")
        return self._state

    @property
    def state_or_none(self):
        try:
            return self.state
        except RuntimeError:
            return None

    def close_request(self):
        self._state = None

    def _filter(self, plugin):
        """rcube_plugin_api::filter(): skip by noajax/task/noframe."""
        st = self.state
        return ((plugin.noajax and not st.html)
                or (plugin.task and not re.match(
                    "^(" + plugin.task + ")$", st.task or "", re.IGNORECASE))
                or (plugin.noframe and st.framed))

    def _init_plugin(self, name):
        st = self.state
        if name in st.initialized or self._filter(self.plugins[name]):
            return
        self.plugins[name].init()
        st.initialized.add(name)

    # --- loading ---------------------------------------------------------
    def load_plugin(self, name, force=False, require=True):
        """Import plugins/<name>/<name>.py once and instantiate the class."""
        if _NAME_RE.search(name):  # path traversal guard
            log.error("Invalid plugin name: %s", name)
            return False
        if name not in self.plugins:
            fn = self.dir / name / f"{name}.py"
            if not fn.is_file():
                if require:
                    log.error("Failed to load plugin file %s", fn)
                return False
            modname = f"cc_plugin_{name}"
            spec = importlib.util.spec_from_file_location(modname, fn)
            if spec is None or spec.loader is None:
                log.error("Failed to load plugin file %s", fn)
                return False
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            cls = getattr(mod, name, None)
            if not (isinstance(cls, type) and issubclass(cls, Plugin) and cls is not Plugin):
                log.error("No plugin class %s found in %s", name, fn)
                return False
            plugin = cls(self, name)
            self.active_plugins.append(name)
            # onload(): early boot hook, present when the subclass defines it
            if type(plugin).onload is not Plugin.onload:
                plugin.onload()
            self.loaded_prefs += plugin.allowed_prefs or []
            self.plugins[name] = plugin
        if force and has_request_context():
            st = self.state
            if name not in st.initialized and (force or not self._filter(self.plugins[name])):
                self.plugins[name].init()
                st.initialized.add(name)
        return True

    def load_plugins(self, names):
        for name in names:
            self.load_plugin(name)

    # --- plugin metadata ---------------------------------------------------
    def get_info(self, plugin_name):
        """rcube_plugin_api::get_info(): plugin class info() first, falling
        back to the plugin's composer.json metadata, then to a minimal
        name/version entry.  Returns False when nothing is known."""
        if _NAME_RE.search(plugin_name):  # path traversal guard
            log.error("Invalid plugin name: %s", plugin_name)
            return False
        plugin = self.plugins.get(plugin_name)
        info = type(plugin).info() if plugin else False
        if not info:
            info = {}
            composer = self.dir / plugin_name / "composer.json"
            if composer.is_file():
                try:
                    json_data = json.loads(composer.read_text())
                except ValueError:
                    json_data = None
                if isinstance(json_data, dict):
                    # list of plugins required (like the PHP require pass)
                    require = []
                    for dname in (json_data.get("require") or {}):
                        m = re.match(r"^([^/]+)/([a-zA-Z0-9_-]+)$", str(dname))
                        if not m:
                            continue
                        vendor, name = m.groups()
                        if name != "plugin-installer" and vendor not in ("pear", "pear-pear"):
                            if (self.dir / name / f"{name}.py").is_file():
                                require.append(name)
                    full = json_data.get("name")
                    if isinstance(full, str) and "/" in full:
                        info["vendor"], info["name"] = full.split("/", 1)
                    info["version"] = json_data.get("version")
                    info["license"] = json_data.get("license")
                    info["require"] = require
                    if json_data.get("homepage"):
                        info["uri"] = json_data["homepage"]
        if not info:
            if plugin is not None:
                info = {"name": plugin_name, "version": "--"}
            else:
                return False
        elif info.get("license"):
            # convert the composer SPDX identifier to something shorter
            license = str(info["license"])
            m = re.match(r"^([ALGP]+)[-v]([0-9.]+)(\+|-or-later)?", license)
            if m:
                info["license"] = (m.group(1) + "-"
                                   + "%.1f" % float(m.group(2))
                                   + ("+" if m.group(3) else ""))
            if not info.get("license_uri") and info["license"] in LICENSE_URIS:
                info["license_uri"] = LICENSE_URIS[info["license"]]
        return info

    # --- hooks -----------------------------------------------------------
    def register_hook(self, hook, callback):
        if callable(callback):
            self.state.handlers[hook].append(callback)
        else:
            log.error("Invalid callback function for %s", hook)

    def unregister_hook(self, hook, callback):
        handlers = self.state.handlers.get(hook)
        if handlers and callback in handlers:
            handlers.remove(callback)

    def exec_hook(self, hook, args=None):
        """rcube_plugin_api::exec_hook(): merge handler dicts (handler wins,
        like PHP ``$ret + $args``), honour ``break``, allow handlers added
        during the run to execute."""
        args = dict(args or {})
        args.setdefault("abort", False)
        handlers = self.state.handlers.get(hook, [])
        self.exec_stack.append(hook)
        i = 0
        while i < len(handlers):
            ret = handlers[i](args)
            if isinstance(ret, dict):
                merged = dict(ret)
                for k, v in args.items():
                    merged.setdefault(k, v)
                args = merged
            if args.get("break"):
                break
            i += 1
        self.exec_stack.pop()
        return args

    def is_processing(self, hook=None):
        return bool(self.exec_stack) and (not hook or hook in self.exec_stack)

    # --- actions ----------------------------------------------------------
    def register_action(self, action, owner, callback, task=None):
        if task:
            key = f"{task}.{action}"
        elif not action.startswith("plugin."):
            key = "plugin." + action
        else:
            key = action
        st = self.state
        if key not in st.actions or st.actionmap.get(key) == owner:
            st.actions[key] = callback
            st.actionmap[key] = owner
        else:
            log.error("Cannot register action %s; already taken by another plugin", key)

    def exec_action(self, action, task=None):
        """Dispatch _action=plugin.<x>; task-qualified keys win (rcmail.php)."""
        st = self.state
        if task and f"{task}.{action}" in st.actions:
            return st.actions[f"{task}.{action}"]()
        if action in st.actions:
            return st.actions[action]()
        if action != "refresh":
            log.error("No handler found for action %s", action)
        return None

    # --- template objects / containers -------------------------------------
    def register_handler(self, name, owner, callback):
        if not name.startswith("plugin."):
            name = "plugin." + name
        st = self.state
        if name not in st.objectsmap or st.objectsmap.get(name) == owner:
            st.objects[name] = callback
            st.objectsmap[name] = owner
        else:
            log.error("Cannot register template handler %s; already taken", name)

    def render_object(self, name, attrib=None):
        if not name.startswith("plugin."):
            name = "plugin." + name
        cb = self.state.objects.get(name)
        return cb(attrib or {}) if cb else ""

    def register_task(self, task, owner):
        st = self.state
        if not _TASK_RE.match(task or ""):
            log.error("Invalid task name: %s", task)
            return False
        if task in MAIN_TASKS or task in st.tasks:
            log.error("Cannot register task %s; already taken", task)
            return False
        st.tasks[task] = owner
        return True

    def is_plugin_task(self, task):
        return task in self.state.tasks

    def add_content(self, html, container):
        st = self.state
        st.contents[container] = st.contents.get(container, "") + html + "\n"

    def container(self, name):
        return self.state.contents.get(name, "")

    # --- client resource buffers --------------------------------------------
    def include_script(self, fn, tag_attributes=None):
        # api.resource_url(): prefix /plugins/ unless already a URL
        if self.state.html:
            self.state.scripts.append(self.resource_url(fn))

    def include_stylesheet(self, fn):
        if not self.state.html:
            return
        # plugin wrapper prefixed "<id>/<fn>"; resolved under plugins/
        local = not (fn.startswith("/")
                     or fn.lower().startswith(("http://", "https://")))
        if local and not (self.dir / fn).is_file():
            return
        self.state.stylesheets.append(self.resource_url(fn))

    def resource_url(self, fn):
        if fn.startswith("/") or fn.lower().startswith(("http://", "https://", "skins/")):
            return fn
        return self.url + fn

    def add_labels(self, keys):
        self.state.labels.update(keys)

    # --- introspection ----------------------------------------------------------
    def loaded_plugins(self):
        return list(self.plugins)

    def get_plugin(self, name):
        return self.plugins.get(name)


_api: PluginAPI | None = None


def get_api() -> PluginAPI:
    assert _api is not None, "plugin API not initialised"
    return _api


def init_api(app):
    """Create the singleton and load enabled plugins (config ``PLUGINS``)."""
    global _api
    _api = PluginAPI(app)
    names = app.config.get("PLUGINS") or []
    _api.load_plugins(names)
    return _api
