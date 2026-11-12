"""SQLite storage layer.

The schema is NOT defined here: it lives in versioned SQL files under
``sql/migrations/`` and is applied/upgraded by ``app.db_migrations``
(see docs/DATABASE.md).
"""
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta

from . import db_migrations, util
from .util import format_address  # noqa: F401 (kept symmetric)

_lock = threading.Lock()


_UNSET = object()  # "field absent from form" sentinel (vs explicit clear)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._local = threading.local()
        with self._conn() as c:
            # create/upgrade the schema to the version shipped with the code
            # (sql/migrations/*.sql via app.db_migrations; docs/DATABASE.md)
            db_migrations.migrate(c)

    def schema_version(self):
        return db_migrations.current_version(self._conn())

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            # WAL: readers (incl. k8s liveness probes on /) never block
            # behind a preferences write; NORMAL keeps it crash-safe enough
            # for a cache-class DB.
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = c
        return c

    # ------------------------------------------------------------ users

    def get_user(self, username):
        return self._conn().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    def create_user(self, username, password_hash, mail_host="localhost"):
        with _lock:
            c = self._conn()
            cur = c.execute(
                "INSERT INTO users (username, mail_host, created, password) VALUES (?,?,?,?)",
                (username, mail_host, now(), password_hash),
            )
            c.commit()
            return cur.lastrowid

    def set_user_password(self, user_id, password_hash):
        with _lock:
            c = self._conn()
            c.execute("UPDATE users SET password = ? WHERE user_id = ?", (password_hash, user_id))
            c.commit()

    def touch_login(self, user_id, failed=False):
        with _lock:
            c = self._conn()
            if failed:
                c.execute(
                    "UPDATE users SET failed_login = ?, failed_login_counter ="
                    " COALESCE(failed_login_counter,0)+1 WHERE user_id = ?",
                    (now(), user_id),
                )
            else:
                c.execute(
                    "UPDATE users SET last_login = ?, failed_login = NULL,"
                    " failed_login_counter = NULL WHERE user_id = ?",
                    (now(), user_id),
                )
            c.commit()

    def get_user_prefs(self, user_id):
        row = self._conn().execute("SELECT preferences FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["preferences"]:
            try:
                prefs = json.loads(row["preferences"])
            except ValueError:
                return {}
            # a checkbox stored as the string "0" must not be truthy: coerce
            # known boolean keys to int (legacy/externally written values)
            if isinstance(prefs, dict):
                from .prefs_sections import CHECKBOXES
                for key in list(prefs):
                    if key in CHECKBOXES and isinstance(prefs[key], str):
                        prefs[key] = 1 if prefs[key] == "1" else 0
                return prefs
        return {}

    def set_user_pref(self, user_id, key, value):
        prefs = self.get_user_prefs(user_id)
        prefs[key] = value
        with _lock:
            c = self._conn()
            c.execute("UPDATE users SET preferences = ? WHERE user_id = ?", (json.dumps(prefs), user_id))
            c.commit()

    def set_user_prefs(self, user_id, mapping):
        """Bulk variant: one read + one write + one commit for a whole form
        save. The per-key loop was O(n) transactions per preferences page
        save and starved sqlite readers (liveness probe timeouts)."""
        prefs = self.get_user_prefs(user_id)
        prefs.update(mapping)
        with _lock:
            c = self._conn()
            c.execute("UPDATE users SET preferences = ? WHERE user_id = ?", (json.dumps(prefs), user_id))
            c.commit()

    # ------------------------------------------------------------ sessions (DB, like roundcube)

    def session_create(self, ip, vars_dict):
        sid = secrets.token_urlsafe(32)
        with _lock:
            c = self._conn()
            c.execute(
                "INSERT INTO session (sess_id, expires_at, ip, vars) VALUES (?,?,?,?)",
                (sid, (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"), ip, json.dumps(vars_dict)),
            )
            c.commit()
        return sid

    def session_get(self, sid):
        row = self._conn().execute("SELECT * FROM session WHERE sess_id = ?", (sid,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["vars"])
        except ValueError:
            return None

    def session_set(self, sid, vars_dict):
        with _lock:
            c = self._conn()
            c.execute("UPDATE session SET vars = ? WHERE sess_id = ?", (json.dumps(vars_dict), sid))
            c.commit()

    def session_delete(self, sid):
        with _lock:
            c = self._conn()
            c.execute("DELETE FROM session WHERE sess_id = ?", (sid,))
            c.commit()

    # ------------------------------------------------------------ identities

    def identities(self, user_id):
        return self._conn().execute(
            'SELECT * FROM identities WHERE user_id = ? AND del = 0'
            ' ORDER BY standard DESC, name ASC, email ASC, identity_id ASC',
            (user_id,),
        ).fetchall()

    def identity(self, user_id, identity_id):
        return self._conn().execute(
            "SELECT * FROM identities WHERE user_id = ? AND identity_id = ? AND del = 0",
            (user_id, identity_id),
        ).fetchone()

    def default_identity(self, user_id):
        row = self._conn().execute(
            "SELECT * FROM identities WHERE user_id = ? AND del = 0 AND standard = 1 LIMIT 1", (user_id,)
        ).fetchone()
        return row or (self.identities(user_id) or [None])[0]

    def identity_save(self, user_id, data, identity_id=None):
        with _lock:
            c = self._conn()
            if identity_id:
                c.execute(
                    """UPDATE identities SET name=?, organization=?, email=?, "reply-to"=?, bcc=?,
                       signature=?, html_signature=?, standard=?, changed=? WHERE user_id=? AND identity_id=?""",
                    (data["name"], data["organization"], data["email"], data["reply_to"], data["bcc"],
                     data["signature"], int(data["html_signature"]), int(data["standard"]),
                     now(), user_id, identity_id),
                )
            else:
                c.execute(
                    """INSERT INTO identities (user_id, name, organization, email, "reply-to", bcc,
                       signature, html_signature, standard, changed)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, data["name"], data["organization"], data["email"], data["reply_to"],
                     data["bcc"], data["signature"], int(data["html_signature"]), int(data["standard"]), now()),
                )
            if int(data.get("standard", 0)):
                # keep exactly one standard identity (rcmail_identity_save);
                # compare on identity_id — evaluating last_insert_rowid() in
                # the WHERE clause would be a constant equal to the bound id
                iid = identity_id or c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.execute(
                    "UPDATE identities SET standard = 0 WHERE user_id = ? AND del = 0 AND identity_id != ?",
                    (user_id, iid),
                )
            c.commit()
            return identity_id or c.execute("SELECT last_insert_rowid()").fetchone()[0]

    def identity_delete(self, user_id, identity_id):
        with _lock:
            c = self._conn()
            c.execute("UPDATE identities SET del = 1, changed = ? WHERE user_id = ? AND identity_id = ?",
                      (now(), user_id, identity_id))
            c.commit()

    # ------------------------------------------------------------ responses

    def responses(self, user_id):
        return self._conn().execute(
            "SELECT * FROM responses WHERE user_id = ? ORDER BY name", (user_id,)
        ).fetchall()

    def response(self, user_id, rid):
        return self._conn().execute(
            "SELECT * FROM responses WHERE user_id = ? AND response_id = ?",
            (user_id, rid)).fetchone()

    def response_save(self, user_id, name, body, html=0, rid=None):
        with _lock:
            c = self._conn()
            if rid:
                c.execute("UPDATE responses SET name = ?, body = ?, html = ? "
                          "WHERE user_id = ? AND response_id = ?",
                          (name, body, html, user_id, rid))
            else:
                cur = c.execute(
                    "INSERT INTO responses (user_id, name, body, html) VALUES (?,?,?,?)",
                    (user_id, name, body, html))
                rid = cur.lastrowid
            c.commit()
            return rid

    def response_delete(self, user_id, rid):
        with _lock:
            c = self._conn()
            c.execute("DELETE FROM responses WHERE user_id = ? AND response_id = ?",
                      (user_id, rid))
            c.commit()

    # ------------------------------------------------------------ contacts

    def contacts(self, user_id, query=None, group=None, offset=0, limit=0):
        sql = "SELECT * FROM contacts WHERE user_id = ? AND del = 0"
        args = [user_id]
        if query:
            # rcube_contacts::search() quick '*' mode: every normalized query
            # token must be present as a substring of the words column
            for tok in util.normalize_string(query, as_array=True, minlen=1):
                sql += " AND words LIKE ?"
                args.append(f"%{tok}%")
        if group:
            sql += " AND contact_id IN (SELECT contact_id FROM contactgroupmembers WHERE contactgroup_id = ?)"
            args.append(group)
        sql += " ORDER BY COALESCE(NULLIF(name,''), surname, firstname, email) COLLATE NOCASE"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            args += [limit, offset]
        return self._conn().execute(sql, args).fetchall()

    def contact(self, user_id, contact_id):
        return self._conn().execute(
            "SELECT * FROM contacts WHERE user_id = ? AND contact_id = ? AND del = 0", (user_id, contact_id)
        ).fetchone()

    def email_to_contact(self, user_id, email):
        """Address-book lookup by e-mail (RC photo/add-contact resolution).
        Returns contact_id of the first contact whose record contains the
        address, else None."""
        if not email:
            return None
        needle = email.lower()
        for r in self.contacts(user_id):
            vcard = (r["vcard"] if "vcard" in r.keys() else "") or ""  # noqa: SIM118 (sqlite3.Row)
            if needle in vcard.lower() or needle in (r["email"] or "").lower():
                return r["contact_id"]
        return None

    def contact_photo(self, user_id, contact_id):
        """Raw photo bytes or None (RC stores photo as a separate blob column)."""
        row = self._conn().execute(
            "SELECT photo FROM contacts WHERE user_id = ? AND contact_id = ? AND del = 0",
            (user_id, contact_id),
        ).fetchone()
        return row["photo"] if row and row["photo"] else None

    def contact_save(self, user_id, data, contact_id=None, photo=_UNSET):
        words = data.get("words") or " ".join(
            filter(None, [data["name"], data["email"], data["firstname"], data["surname"]])).lower()
        with _lock:
            c = self._conn()
            if contact_id:
                c.execute(
                    """UPDATE contacts SET name=?, email=?, firstname=?, surname=?, vcard=?, words=?, changed=?
                       WHERE user_id=? AND contact_id=?""",
                    (data["name"], data["email"], data["firstname"], data["surname"],
                     data.get("vcard", ""), words, now(), user_id, contact_id),
                )
                if photo is not _UNSET:
                    # RC save.php: photo '' means delete (form '-del-' marker)
                    c.execute("UPDATE contacts SET photo=? WHERE user_id=? AND contact_id=?",
                              (photo or None, user_id, contact_id))
                c.commit()
                return contact_id
            cur = c.execute(
                """INSERT INTO contacts (user_id, name, email, firstname, surname, vcard, words, changed, photo)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (user_id, data["name"], data["email"], data["firstname"], data["surname"],
                 data.get("vcard", ""), words, now(),
                 photo if photo is not _UNSET else None),
            )
            c.commit()
            return cur.lastrowid

    def contact_delete(self, user_id, contact_ids):
        with _lock:
            c = self._conn()
            q = ",".join("?" * len(contact_ids))
            c.execute(f"UPDATE contacts SET del = 1, changed = ? WHERE user_id = ? AND contact_id IN ({q})",  # noqa: S608 - q is a sequence of '?' bind placeholders
                      [now(), user_id, *list(contact_ids)])
            c.commit()

    def contactgroups(self, user_id):
        return self._conn().execute(
            "SELECT * FROM contactgroups WHERE user_id = ? AND del = 0 ORDER BY name COLLATE NOCASE", (user_id,)
        ).fetchall()

    def contactgroup_save(self, user_id, name, group_id=None):
        with _lock:
            c = self._conn()
            # rcube_contacts::unique_groupname() — append ' 2', ' 3', ... on
            # collision (used by both create_group and rename_group, and like
            # the original it counts a group's own name as a collision)
            check, num = name, 2
            while c.execute(
                    "SELECT 1 FROM contactgroups WHERE del = 0 AND user_id = ? AND name = ?",
                    (user_id, check)).fetchone():
                check = f"{name} {num}"
                num += 1
            name = check
            if group_id:
                c.execute("UPDATE contactgroups SET name = ?, changed = ? WHERE user_id = ? AND contactgroup_id = ?",
                          (name, now(), user_id, group_id))
            else:
                c.execute("INSERT INTO contactgroups (user_id, name, changed) VALUES (?,?,?)", (user_id, name, now()))
            c.commit()
            return name

    def contactgroup_delete(self, user_id, group_id):
        with _lock:
            c = self._conn()
            c.execute("UPDATE contactgroups SET del = 1, changed = ? WHERE user_id = ? AND contactgroup_id = ?",
                      (now(), user_id, group_id))
            c.commit()

    def contactgroup_members(self, group_id):
        return self._conn().execute(
            "SELECT contact_id FROM contactgroupmembers WHERE contactgroup_id = ?", (group_id,)
        ).fetchall()

    def contactgroup_add(self, group_id, contact_ids):
        with _lock:
            c = self._conn()
            for cid in contact_ids:
                c.execute(
                    "INSERT OR IGNORE INTO contactgroupmembers (contactgroup_id, contact_id, created) VALUES (?,?,?)",
                    (group_id, cid, now()))
            c.commit()

    def contactgroup_remove(self, group_id, contact_ids):
        with _lock:
            c = self._conn()
            for cid in contact_ids:
                c.execute("DELETE FROM contactgroupmembers WHERE contactgroup_id = ? AND contact_id = ?",
                          (group_id, cid))
            c.commit()

    # ------------------------------------------------- collected / trusted
    # Roundcube addressbook types: 1 = Collected Recipients, 2 = Trusted Senders

    def collected_list(self, user_id, atype, query=None):
        sql = 'SELECT * FROM collected_addresses WHERE user_id = ? AND "type" = ?'
        args = [user_id, atype]
        if query:
            like = f"%{query}%"
            sql += " AND (name LIKE ? OR email LIKE ?)"
            args += [like, like]
        sql += " ORDER BY COALESCE(NULLIF(name,''), email) COLLATE NOCASE"
        return self._conn().execute(sql, args).fetchall()

    def contact_email_known(self, user_id, email, kind="contacts"):
        """True when the address is known to the user.

        kind='contacts' matches address-book entries (reference
        contact_exists with TYPE_RECIPIENT|TYPE_WRITEABLE, show_images=1);
        kind='trusted' matches the collected trusted-sender table (type 2,
        TYPE_TRUSTED_SENDER, show_images=3)."""
        if not email:
            return False
        email = email.lower()
        c = self._conn()
        if kind == "trusted":
            row = c.execute(
                'SELECT 1 FROM collected_addresses WHERE user_id = ? AND "type" = 2 '
                "AND lower(email) = ? LIMIT 1", (user_id, email)).fetchone()
        else:
            row = c.execute(
                "SELECT 1 FROM contacts WHERE user_id = ? AND del = 0 "
                "AND lower(email) = ? LIMIT 1", (user_id, email)).fetchone()
            if row is None:
                # contacts can carry several addresses in the email column
                row = c.execute(
                    "SELECT 1 FROM contacts WHERE user_id = ? AND del = 0 "
                    "AND lower(email) LIKE ? LIMIT 1",
                    (user_id, f"%{email}%")).fetchone()
        return row is not None

    def collected_upsert(self, user_id, atype, name, email):
        with _lock:
            c = self._conn()
            c.execute(
                'INSERT INTO collected_addresses (user_id, "type", name, email, changed) VALUES (?,?,?,?,?) '
                'ON CONFLICT (user_id, "type", email) DO UPDATE SET name=excluded.name, changed=excluded.changed',
                (user_id, atype, name, email, now()))
            c.commit()

    def collected_delete(self, user_id, atype, emails):
        with _lock:
            c = self._conn()
            q = ",".join("?" * len(emails))
            c.execute(f'DELETE FROM collected_addresses WHERE user_id = ? AND "type" = ? AND email IN ({q})',  # noqa: S608 - q is a sequence of '?' bind placeholders
                      [user_id, atype, *list(emails)])
            c.commit()
