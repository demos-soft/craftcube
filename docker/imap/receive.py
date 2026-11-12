#!/usr/bin/env python3
"""Minimal SMTP receiver that appends every message into Dovecot's Maildir.

Runs beside dovecot in the development mail container. All recipients go to
the single development mailbox (/var/mail/test/Maildir). Stdlib only."""
import os
import socket
import socketserver
import sys
import mailbox

MAILDIR = "/var/mail/test/Maildir"


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.reply("220 craftcube-dev ESMTP ready")
        data_mode = False
        body = []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if data_mode:
                if line in (b".\r\n", b".\n"):
                    data_mode = False
                    self.deliver(b"".join(body))
                    body = []
                    self.reply("250 2.0.0 Ok: queued")
                    continue
                if line.startswith(b".."):
                    line = line[1:]
                body.append(line)
                continue
            cmd = line.strip().upper()
            if cmd.startswith(b"EHLO") or cmd.startswith(b"HELO"):
                self.reply("250-craftcube-dev")
                self.reply("250 SIZE")
            elif cmd == b"MAIL FROM:<>" or cmd.startswith(b"MAIL FROM:"):
                self.reply("250 2.1.0 Ok")
            elif cmd.startswith(b"RCPT TO:"):
                self.reply("250 2.1.5 Ok")
            elif cmd == b"DATA":
                data_mode = True
                self.reply("354 End data with <CR><LF>.<CR><LF>")
            elif cmd in (b"RSET", b"NOOP"):
                self.reply("250 Ok")
            elif cmd == b"QUIT":
                self.reply("221 Bye")
                break
            else:
                self.reply("250 Ok")

    def deliver(self, raw):
        os.makedirs(MAILDIR, exist_ok=True)
        mb = mailbox.Maildir(MAILDIR, create=True)
        try:
            mb.add(mailbox.MaildirMessage(raw))
            mb.flush()
        finally:
            mb.close()
        sys.stderr.write("delivered %d bytes to %s\n" % (len(raw), MAILDIR))
        sys.stderr.flush()

    def reply(self, text):
        self.wfile.write((text + "\r\n").encode())
        self.wfile.flush()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    Server(("0.0.0.0", port), Handler).serve_forever()
