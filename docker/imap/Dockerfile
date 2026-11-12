FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      dovecot-imapd dovecot-lmtpd ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 5000 -d /var/mail vmail
COPY dovecot.conf /etc/dovecot/dovecot.conf
COPY users /etc/dovecot/users
COPY receive.py /usr/local/bin/receive.py
RUN chown vmail:vmail /var/mail && mkdir -p /var/mail/test && chown -R vmail:vmail /var/mail/test
EXPOSE 143 2525
# receive.py accepts SMTP on :2525 and appends to the Maildir (as vmail); dovecot serves IMAP
CMD ["sh", "-c", "su vmail -s /bin/sh -c 'python3 /usr/local/bin/receive.py 2525' & exec dovecot -F"]
