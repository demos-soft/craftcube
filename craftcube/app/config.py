"""CraftCube configuration (env-overridable)."""
import os
from typing import ClassVar


class Config:
    SECRET_KEY = os.environ.get("CRAFTCUBE_SECRET", "craftcube-dev-secret-change-me")

    # SQLite database (roundcubemail-derived schema: users, contacts, identities, ...)
    DB_PATH = os.environ.get(
        "CRAFTCUBE_DB",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "craftcube.sqlite"))

    # IMAP / SMTP
    IMAP_HOST = os.environ.get("CRAFTCUBE_IMAP_HOST", "localhost")
    IMAP_PORT = int(os.environ.get("CRAFTCUBE_IMAP_PORT", "143"))
    IMAP_SSL = os.environ.get("CRAFTCUBE_IMAP_SSL", "0") == "1"
    SMTP_HOST = os.environ.get("CRAFTCUBE_SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("CRAFTCUBE_SMTP_PORT", "1025"))
    SMTP_SSL = os.environ.get("CRAFTCUBE_SMTP_SSL", "0") == "1"

    # Special folders (empty = auto-detect via IMAP LIST)
    DRAFTS_FOLDER = os.environ.get("CRAFTCUBE_DRAFTS", "Drafts")
    SENT_FOLDER = os.environ.get("CRAFTCUBE_SENT", "Sent")
    TRASH_FOLDER = os.environ.get("CRAFTCUBE_TRASH", "Trash")

    PRODUCT_NAME = os.environ.get("CRAFTCUBE_PRODUCT_NAME", "CraftCube")
    VERSION = "1.0.0"

    # enabled plugins, like Roundcube $config['plugins']; the bundled
    # zipdownload port provides the message-export actions, so it ships on
    PLUGINS: ClassVar = [x for x in os.environ.get(
        "CRAFTCUBE_PLUGINS", "zipdownload").replace(" ", "").split(",") if x]

    # pages of the message/contact lists when the user has no preference;
    # matches the reference defaults (config/defaults.inc.php:
    # mail_pagesize = 50, addressbook_pagesize = 50)
    PAGE_SIZE = int(os.environ.get("CRAFTCUBE_PAGE_SIZE", "50"))
    PER_USER_PASSWORDS = os.environ.get("CRAFTCUBE_PER_USER_PASSWORDS", "1") == "1"
    # shared-mailbox mode (PER_USER_PASSWORDS=0): authenticate IMAP/SMTP with
    # these admin credentials instead of the user's own password
    IMAP_ADMIN_USER = os.environ.get("CRAFTCUBE_IMAP_ADMIN_USER", "")
    IMAP_ADMIN_PASS = os.environ.get("CRAFTCUBE_IMAP_ADMIN_PASS", "")
