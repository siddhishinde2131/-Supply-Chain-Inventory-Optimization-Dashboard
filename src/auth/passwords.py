"""Password hashing and password rules (Python standard library only).

Passwords are never stored. We store a salted PBKDF2-HMAC-SHA256 hash:
    pbkdf2_sha256$<iterations>$<salt>$<hash>
Verification recomputes the hash and compares in constant time.
"""
import base64
import hashlib
import hmac
import os
import re

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 310_000          # OWASP recommendation for PBKDF2-HMAC-SHA256
MIN_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,32}$")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or ITERATIONS
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     base64.b64decode(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, base64.b64decode(expected))


def password_problems(password: str, username: str = "") -> list[str]:
    """Rules a new password must satisfy (empty list = acceptable)."""
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        problems.append("Include at least one letter and one number.")
    if username and password.lower() == username.lower():
        problems.append("The password must not be the same as the username.")
    return problems


def normalise_username(username: str) -> str:
    return username.strip().lower()


def username_problems(username: str) -> list[str]:
    if not USERNAME_PATTERN.match(normalise_username(username)):
        return ["Username must be 3-32 characters: letters, numbers, '.', '_' or '-'."]
    return []
