"""CraftCube configuration (env-overridable)."""
import os

class Config:
    SECRET_KEY = os.environ.get("CRAFTCUBE_SECRET", "craftcube-dev-secret-change-me")

    # SQLite database (roundcubemail-derived schema: users, contacts, identities, ...)
    DB_PATH = os.environ.get("CRAFTCUBE_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "craftcube.sqlite"))

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

    PAGE_SIZE = int(os.environ.get("CRAFTCUBE_PAGE_SIZE", "20"))
    PER_USER_PASSWORDS = os.environ.get("CRAFTCUBE_PER_USER_PASSWORDS", "1") == "1"
