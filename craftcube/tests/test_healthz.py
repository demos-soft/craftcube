"""Liveness endpoint: must answer without sessions, templates or IMAP."""


class TestHealthz:
    def test_healthz_anonymous_and_imap_free(self, client, monkeypatch):
        # a probe that touches IMAP can starve behind stalled mailbox reads,
        # which the kubelet misreads as a dead pod (restart loop observed on
        # staging); /healthz must therefore never enumerate folders
        from app import views

        def _boom():
            raise AssertionError("healthz touched IMAP")
        monkeypatch.setattr(views, "folders_for_menu", _boom)
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.get_data(as_text=True) == "ok"
