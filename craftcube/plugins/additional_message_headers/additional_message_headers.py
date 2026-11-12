"""additional_message_headers - port of the Roundcube plugin.

Adds (or overrides) headers on outgoing messages via the
'message_before_send' hook.  Config, like the PHP original::

    config = {"additional_message_headers": {"User-Agent": "My-CraftCube"}}

%u / %l / %d expand to the user name / local part / domain; %%u etc.
escape to a literal %u.
"""

import re
from typing import ClassVar

from app.plugins import Plugin

# rcube-style preg_replace pairs: '(^|[^%])%X' -> '${1}<value>'
_USER_REFS = ("u", "l", "d")


class additional_message_headers(Plugin):
    CONFIG: ClassVar[dict] = {"additional_message_headers": {}}

    def init(self):
        self.add_hook("message_before_send", self.message_headers)

    def message_headers(self, args):
        self.load_config()
        headers = self.config.get("additional_message_headers") or {}
        if not headers:
            return args

        msg = args.get("message")
        if msg is None:
            return args

        from flask import session

        from app.views import get_store

        name = email = ""
        uid = session.get("user_id")
        if uid:
            ident = get_store().default_identity(uid)
            if ident:
                email = ident["email"] or ""
                name = ident["name"] or ""
        values = {"u": name or email,
                  "l": email.partition("@")[0],
                  "d": email.partition("@")[2]}

        def expand(value):
            for ref, repl in values.items():
                value = re.sub(f"(^|[^%])%{ref}",
                               lambda m, r=repl: m.group(1) + r, value)
            # replace %%<variable> with %<variable>
            return re.sub(r"%(%[uld])", r"\1", value)

        # rcube_message::headers($hash, true): override existing headers
        for key, value in headers.items():
            for k in list(msg.keys()):
                if k.lower() == key.lower():
                    del msg[k]
            msg[key] = expand(str(value))
        args["message"] = msg
        return args
