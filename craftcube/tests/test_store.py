"""app.store: the SQLite-backed user data (users, prefs, identities,
responses, contacts, groups, collected addresses, sessions)."""
from app.store import _lock


class TestUsers:
    def test_create_get_roundtrip(self, store):
        uid = store.create_user("a@example.org", "hash")
        row = store.get_user("a@example.org")
        assert row["user_id"] == uid
        assert row["username"] == "a@example.org"
        assert row["password"] == "hash"

    def test_get_unknown_user_is_none(self, store):
        assert store.get_user("nope@example.org") is None

    def test_touch_login_resets_failures(self, store, user):
        store.touch_login(user, failed=True)
        row = store._conn().execute(
            "SELECT failed_login_counter FROM users WHERE user_id = ?", (user,)).fetchone()
        assert row["failed_login_counter"] == 1
        store.touch_login(user)
        row = store._conn().execute(
            "SELECT failed_login_counter, last_login FROM users WHERE user_id = ?", (user,)).fetchone()
        assert row["failed_login_counter"] is None
        assert row["last_login"]


class TestPrefs:
    def test_default_is_empty(self, store, user):
        assert store.get_user_prefs(user) == {}

    def test_set_get(self, store, user):
        store.set_user_pref(user, "pagesize", 20)
        store.set_user_pref(user, "theme", "dark")
        assert store.get_user_prefs(user) == {"pagesize": 20, "theme": "dark"}

    def test_corrupt_json_falls_back(self, store, user):
        with _lock:
            c = store._conn()
            c.execute("UPDATE users SET preferences = 'not json' WHERE user_id = ?", (user,))
            c.commit()
        assert store.get_user_prefs(user) == {}


class TestSessions:
    def test_create_get_set_delete(self, store):
        sid = store.session_create("127.0.0.1", {"user_id": 7})
        assert store.session_get(sid) == {"user_id": 7}
        store.session_set(sid, {"user_id": 7, "tz": "Europe/Berlin"})
        assert store.session_get(sid)["tz"] == "Europe/Berlin"
        store.session_delete(sid)
        assert store.session_get(sid) is None

    def test_unknown_sid(self, store):
        assert store.session_get("nope") is None


class TestIdentities:
    def _data(self, **kw):
        d = {"name": "Test User", "organization": "", "email": "test@example.org",
             "reply_to": "", "bcc": "", "signature": "--\nbye", "html_signature": 0,
             "standard": 1}
        d.update(kw)
        return d

    def test_save_and_list(self, store, user):
        iid = store.identity_save(user, self._data())
        rows = store.identities(user)
        assert len(rows) == 1
        assert rows[0]["identity_id"] == iid
        assert rows[0]["email"] == "test@example.org"

    def test_standard_is_unique(self, store, user):
        first = store.identity_save(user, self._data())
        store.identity_save(user, self._data(name="Second", email="two@example.org", standard=1))
        rows = store.identities(user)
        standards = [r["identity_id"] for r in rows if r["standard"]]
        assert standards == [first] or len(standards) == 1

    def test_update_in_place(self, store, user):
        iid = store.identity_save(user, self._data())
        store.identity_save(user, self._data(name="Renamed"), identity_id=iid)
        assert store.identity(user, iid)["name"] == "Renamed"
        assert len(store.identities(user)) == 1

    def test_delete_is_soft(self, store, user):
        iid = store.identity_save(user, self._data())
        store.identity_delete(user, iid)
        assert store.identities(user) == []
        raw = store._conn().execute(
            "SELECT del FROM identities WHERE identity_id = ?", (iid,)).fetchone()
        assert raw["del"] == 1

    def test_default_identity(self, store, user):
        iid = store.identity_save(user, self._data(standard=0))
        assert store.default_identity(user)["identity_id"] == iid


class TestResponses:
    def test_crud(self, store, user):
        rid = store.response_save(user, "Thanks", "Thanks a lot!")
        assert store.response(user, rid)["name"] == "Thanks"
        store.response_save(user, "Thanks", "Thanks!", html=1, rid=rid)
        row = store.response(user, rid)
        assert row["body"] == "Thanks!" and row["html"] == 1
        store.response_delete(user, rid)
        assert store.responses(user) == []

    def test_sorted_by_name(self, store, user):
        store.response_save(user, "Zeta", "z")
        store.response_save(user, "Alpha", "a")
        assert [r["name"] for r in store.responses(user)] == ["Alpha", "Zeta"]


class TestContacts:
    def _data(self, **kw):
        d = {"name": "Ada Lovelace", "email": "ada@example.org",
             "firstname": "Ada", "surname": "Lovelace", "vcard": ""}
        d.update(kw)
        return d

    def test_save_get(self, store, user):
        cid = store.contact_save(user, self._data())
        row = store.contact(user, cid)
        assert row["name"] == "Ada Lovelace"
        assert "ada" in row["words"]  # search index built from all name fields

    def test_query_matches_any_name_field(self, store, user):
        store.contact_save(user, self._data())
        for q in ("Ada", "Lovelace", "ada@example.org"):
            assert len(store.contacts(user, query=q)) == 1, q
        assert store.contacts(user, query="nobody") == []

    def test_delete_is_soft(self, store, user):
        cid = store.contact_save(user, self._data())
        store.contact_delete(user, [cid])
        assert store.contact(user, cid) is None
        assert store.contacts(user) == []

    def test_groups_membership(self, store, user):
        cid = store.contact_save(user, self._data())
        store.contactgroup_save(user, "Friends")
        gid = store.contactgroups(user)[0]["contactgroup_id"]
        store.contactgroup_add(gid, [cid, cid])  # idempotent
        assert [r["contact_id"] for r in store.contactgroup_members(gid)] == [cid]
        assert len(store.contacts(user, group=gid)) == 1
        store.contactgroup_remove(gid, [cid])
        assert store.contacts(user, group=gid) == []

    def test_group_delete_is_soft(self, store, user):
        store.contactgroup_save(user, "Gone")
        gid = store.contactgroups(user)[0]["contactgroup_id"]
        store.contactgroup_delete(user, gid)
        assert store.contactgroups(user) == []

    def test_contacts_are_per_user(self, store):
        from app.auth import hash_password
        u1 = store.create_user("one@example.org", hash_password("x"))
        u2 = store.create_user("two@example.org", hash_password("x"))
        store.contact_save(u1, self._data())
        assert store.contacts(u2) == []


class TestCollected:
    def test_upsert_updates_name(self, store, user):
        store.collected_upsert(user, 1, "", "x@example.org")
        store.collected_upsert(user, 1, "Xavier", "x@example.org")
        rows = store.collected_list(user, 1)
        assert len(rows) == 1 and rows[0]["name"] == "Xavier"

    def test_types_are_separate(self, store, user):
        store.collected_upsert(user, 1, "A", "a@example.org")
        store.collected_upsert(user, 2, "B", "b@example.org")
        assert len(store.collected_list(user, 1)) == 1
        assert len(store.collected_list(user, 2)) == 1

    def test_delete(self, store, user):
        store.collected_upsert(user, 1, "A", "a@example.org")
        store.collected_delete(user, 1, ["a@example.org"])
        assert store.collected_list(user, 1) == []
