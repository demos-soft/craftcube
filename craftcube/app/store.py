"""SQLite storage layer — schema mirrors roundcubemail/SQL/sqlite.initial.sql."""
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta

from .util import format_address  # noqa: F401 (kept symmetric)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id integer NOT NULL PRIMARY KEY,
  username varchar(128) NOT NULL default '',
  mail_host varchar(128) NOT NULL default '',
  created datetime NOT NULL default '0000-00-00 00:00:00',
  last_login datetime DEFAULT NULL,
  failed_login datetime DEFAULT NULL,
  failed_login_counter integer DEFAULT NULL,
  language varchar(16),
  preferences text DEFAULT NULL,
  password text DEFAULT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username, mail_host);

CREATE TABLE IF NOT EXISTS contacts (
  contact_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  del tinyint NOT NULL default '0',
  name varchar(128) NOT NULL default '',
  email text NOT NULL default '',
  firstname varchar(128) NOT NULL default '',
  surname varchar(128) NOT NULL default '',
  vcard text NOT NULL default '',
  words text NOT NULL default ''
);
CREATE INDEX IF NOT EXISTS ix_contacts_user_id ON contacts(user_id, del);

CREATE TABLE IF NOT EXISTS contactgroups (
  contactgroup_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  del tinyint NOT NULL default '0',
  name varchar(128) NOT NULL default ''
);
CREATE INDEX IF NOT EXISTS ix_contactgroups_user_id ON contactgroups(user_id, del);

CREATE TABLE IF NOT EXISTS contactgroupmembers (
  contactgroup_id integer NOT NULL
    REFERENCES contactgroups(contactgroup_id) ON DELETE CASCADE ON UPDATE CASCADE,
  contact_id integer NOT NULL
    REFERENCES contacts(contact_id) ON DELETE CASCADE ON UPDATE CASCADE,
  created datetime NOT NULL default '0000-00-00 00:00:00',
  PRIMARY KEY (contactgroup_id, contact_id)
);
CREATE INDEX IF NOT EXISTS ix_contactgroupmembers_contact_id ON contactgroupmembers (contact_id);

CREATE TABLE IF NOT EXISTS identities (
  identity_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  del tinyint NOT NULL default '0',
  standard tinyint NOT NULL default '0',
  name varchar(128) NOT NULL default '',
  organization varchar(128) default '',
  email varchar(128) NOT NULL default '',
  "reply-to" varchar(128) NOT NULL default '',
  bcc varchar(128) NOT NULL default '',
  signature text NOT NULL default '',
  html_signature tinyint NOT NULL default '0'
);
CREATE INDEX IF NOT EXISTS ix_identities_user_id ON identities(user_id, del);

CREATE TABLE IF NOT EXISTS searches (
  search_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  "type" smallint NOT NULL DEFAULT '0',
  name varchar(128) NOT NULL,
  data text NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
  sess_id varchar(128) NOT NULL PRIMARY KEY,
  expires_at datetime NOT NULL default '0000-00-00 00:00:00',
  ip varchar(40) NOT NULL default '',
  vars text NOT NULL
);

CREATE TABLE IF NOT EXISTS collected_addresses (
  address_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  name varchar(255) NOT NULL default '',
  email varchar(255) NOT NULL,
  "type" integer NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_collected_addresses_user_id ON collected_addresses(user_id, "type", email);

CREATE TABLE IF NOT EXISTS responses (
  response_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  name varchar(100) NOT NULL,
  body text NOT NULL,
  html tinyint NOT NULL default '0'
);
"""

_lock = threading.Lock()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
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
            'SELECT * FROM identities WHERE user_id = ? AND del = 0 ORDER BY standard DESC, identity_id',
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
            like = f"%{query}%"
            sql += " AND (name LIKE ? OR email LIKE ? OR firstname LIKE ? OR surname LIKE ?)"
            args += [like] * 4
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

    def contact_save(self, user_id, data, contact_id=None):
        words = " ".join(filter(None, [data["name"], data["email"], data["firstname"], data["surname"]])).lower()
        with _lock:
            c = self._conn()
            if contact_id:
                c.execute(
                    """UPDATE contacts SET name=?, email=?, firstname=?, surname=?, vcard=?, words=?, changed=?
                       WHERE user_id=? AND contact_id=?""",
                    (data["name"], data["email"], data["firstname"], data["surname"],
                     data.get("vcard", ""), words, now(), user_id, contact_id),
                )
                c.commit()
                return contact_id
            cur = c.execute(
                """INSERT INTO contacts (user_id, name, email, firstname, surname, vcard, words, changed)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (user_id, data["name"], data["email"], data["firstname"], data["surname"],
                 data.get("vcard", ""), words, now()),
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
            if group_id:
                c.execute("UPDATE contactgroups SET name = ?, changed = ? WHERE user_id = ? AND contactgroup_id = ?",
                          (name, now(), user_id, group_id))
            else:
                c.execute("INSERT INTO contactgroups (user_id, name, changed) VALUES (?,?,?)", (user_id, name, now()))
            c.commit()

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
