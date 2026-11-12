"""Password hashing (PBKDF2-HMAC-SHA256, like roundcube's 'pbkdf2_sha256' scheme)."""
import base64
import hashlib
import hmac
import os

SCHEME = "pbkdf2.sha256"
ITERATIONS = 100_000


def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{SCHEME}${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password, stored):
    if not stored:
        return False
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$")
        if scheme != SCHEME:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False
