"""User accounts stored in a local JSON file (works without PostgreSQL).

Default location: data/users.json (excluded from Git). Override with the
AUTH_USERS_FILE environment variable. Only password hashes are stored.

Security rules
--------------
* Failed sign-ins are counted per user; after ``MAX_FAILED_ATTEMPTS`` the account
  is locked for ``LOCKOUT_MINUTES``.
* Sign-in errors never reveal whether the username exists, and an unknown user
  costs the same hashing time as a wrong password.
* The last administrator cannot be deleted or demoted.

Forgot password (no e-mail needed)
----------------------------------
At registration the user receives a one-time **recovery code**. Only its hash is
stored. With username + recovery code a new password can be set; the old code
then stops working and a new one is issued. Wrong codes count as failed
attempts, so the same lockout applies.
"""
import json
import os
import secrets
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.auth.passwords import (hash_password, normalise_username, password_problems,
                                username_problems, verify_password)
from src.config import DATA_DIR

ROLES = ("admin", "analyst")
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 5
GENERIC_LOGIN_ERROR = "Invalid username or password."
_LOCK = threading.Lock()
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


class AuthError(Exception):
    """A problem that can be shown to the user."""


@dataclass
class User:
    username: str
    display_name: str
    role: str
    password_hash: str
    created_at: str
    last_login: str | None = None
    failed_attempts: int = 0
    locked_until: str | None = None
    recovery_hash: str | None = None

    @property
    def has_recovery_code(self) -> bool:
        return self.recovery_hash is not None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict:
        """User details WITHOUT the password hash (safe to show or keep in session)."""
        data = asdict(self)
        data.pop("password_hash")
        data.pop("recovery_hash")
        return data


RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I to avoid confusion
GENERIC_RECOVERY_ERROR = "Username or recovery code is incorrect."


def new_recovery_code() -> str:
    """16 random characters in 4 groups, e.g. K7QM-2XPA-9RTD-HV4C."""
    chars = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(16))
    return "-".join(chars[i:i + 4] for i in range(0, 16, 4))


def normalise_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def default_users_file() -> Path:
    return Path(os.getenv("AUTH_USERS_FILE", DATA_DIR / "users.json"))


class UserStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_users_file()

    # --- file handling --------------------------------------------------------
    def _load(self) -> dict[str, User]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise AuthError(f"The user file {self.path} cannot be read ({exc}).") from exc
        return {name: User(**data) for name, data in raw.get("users", {}).items()}

    def _save(self, users: dict[str, User]) -> None:
        """Write atomically: a crash never leaves a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"users": {n: asdict(u) for n, u in users.items()}}, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".users_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, self.path)

    # --- queries ---------------------------------------------------------------
    def has_users(self) -> bool:
        return bool(self._load())

    def get(self, username: str) -> User | None:
        return self._load().get(normalise_username(username))

    def list_users(self) -> list[User]:
        return sorted(self._load().values(), key=lambda u: u.username)

    # --- changes ---------------------------------------------------------------
    def create_user(self, username: str, password: str, role: str = "analyst",
                    display_name: str = "") -> User:
        name = normalise_username(username)
        problems = username_problems(name) + password_problems(password, name)
        if role not in ROLES:
            problems.append(f"Role must be one of: {', '.join(ROLES)}.")
        if problems:
            raise AuthError(" ".join(problems))
        with _LOCK:
            users = self._load()
            if name in users:
                raise AuthError(f"The username '{name}' is already taken.")
            if not users and role != "admin":
                raise AuthError("The first account must be an administrator.")
            user = User(username=name, display_name=display_name.strip() or name, role=role,
                        password_hash=hash_password(password),
                        created_at=datetime.now().isoformat(timespec="seconds"))
            users[name] = user
            self._save(users)
        return user

    def register(self, username: str, password: str, display_name: str = "") -> tuple[User, str]:
        """Self-registration. The first account becomes admin, later ones analyst.

        Returns (user, recovery code). The code is shown once and never stored in clear.
        """
        role = "admin" if not self.has_users() else "analyst"
        user = self.create_user(username, password, role, display_name)
        return user, self._issue_recovery_code(user.username)

    def _issue_recovery_code(self, username: str) -> str:
        code = new_recovery_code()
        with _LOCK:
            users = self._load()
            users[username].recovery_hash = hash_password(normalise_recovery_code(code))
            self._save(users)
        return code

    def regenerate_recovery_code(self, username: str, current_password: str) -> str:
        """Signed-in user: replace the recovery code (needs the current password)."""
        user = self.get(username)
        if user is None or not verify_password(current_password, user.password_hash):
            raise AuthError("The current password is incorrect.")
        return self._issue_recovery_code(user.username)

    def reset_with_recovery_code(self, username: str, code: str, new_password: str,
                                 now: datetime | None = None) -> str:
        """Forgot password: set a new password with the recovery code.

        Returns the NEW recovery code (the old one is used up).
        """
        now = now or datetime.now()
        name = normalise_username(username)
        problems = password_problems(new_password, name)
        if problems:
            raise AuthError(" ".join(problems))
        with _LOCK:
            users = self._load()
            user = users.get(name)
            if user is None or user.recovery_hash is None:
                verify_password(code, _DUMMY_HASH)          # same cost as a real check
                raise AuthError(GENERIC_RECOVERY_ERROR)
            if user.locked_until and now < datetime.fromisoformat(user.locked_until):
                raise AuthError("Too many failed attempts. This account is locked for a few "
                                "minutes - try again later.")
            if not verify_password(normalise_recovery_code(code), user.recovery_hash):
                self._register_failure(user, now)
                self._save(users)
                raise AuthError(GENERIC_RECOVERY_ERROR)
            user.password_hash = hash_password(new_password)
            user.failed_attempts = 0
            user.locked_until = None
            self._save(users)
        return self._issue_recovery_code(name)

    @staticmethod
    def _register_failure(user: User, now: datetime) -> None:
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
            user.failed_attempts = 0

    def record_login(self, username: str) -> None:
        with _LOCK:
            users = self._load()
            users[normalise_username(username)].last_login = datetime.now().isoformat(timespec="seconds")
            self._save(users)

    def authenticate(self, username: str, password: str, now: datetime | None = None) -> User:
        now = now or datetime.now()
        name = normalise_username(username)
        with _LOCK:
            users = self._load()
            user = users.get(name)
            if user is None:
                verify_password(password, _DUMMY_HASH)   # same cost as a real check
                raise AuthError(GENERIC_LOGIN_ERROR)
            if user.locked_until and now < datetime.fromisoformat(user.locked_until):
                raise AuthError("Too many failed attempts. This account is locked for a few "
                                "minutes - try again later or ask an administrator.")
            if not verify_password(password, user.password_hash):
                self._register_failure(user, now)
                self._save(users)
                raise AuthError(GENERIC_LOGIN_ERROR)
            user.failed_attempts = 0
            user.locked_until = None
            user.last_login = now.isoformat(timespec="seconds")
            self._save(users)
            return user

    def change_password(self, username: str, current_password: str, new_password: str) -> None:
        name = normalise_username(username)
        problems = password_problems(new_password, name)
        if problems:
            raise AuthError(" ".join(problems))
        with _LOCK:
            users = self._load()
            user = users.get(name)
            if user is None or not verify_password(current_password, user.password_hash):
                raise AuthError("The current password is incorrect.")
            user.password_hash = hash_password(new_password)
            self._save(users)

    def reset_password(self, username: str, new_password: str) -> None:
        """Administrator action: set a new password and unlock the account."""
        name = normalise_username(username)
        problems = password_problems(new_password, name)
        if problems:
            raise AuthError(" ".join(problems))
        with _LOCK:
            users = self._load()
            if name not in users:
                raise AuthError(f"User '{name}' does not exist.")
            users[name].password_hash = hash_password(new_password)
            users[name].failed_attempts = 0
            users[name].locked_until = None
            self._save(users)

    def set_role(self, username: str, role: str) -> None:
        if role not in ROLES:
            raise AuthError(f"Role must be one of: {', '.join(ROLES)}.")
        name = normalise_username(username)
        with _LOCK:
            users = self._load()
            if name not in users:
                raise AuthError(f"User '{name}' does not exist.")
            if users[name].is_admin and role != "admin" and self._admin_count(users) == 1:
                raise AuthError("You cannot remove the last administrator.")
            users[name].role = role
            self._save(users)

    def delete_user(self, username: str) -> None:
        name = normalise_username(username)
        with _LOCK:
            users = self._load()
            if name not in users:
                raise AuthError(f"User '{name}' does not exist.")
            if users[name].is_admin and self._admin_count(users) == 1:
                raise AuthError("You cannot delete the last administrator.")
            del users[name]
            self._save(users)

    @staticmethod
    def _admin_count(users: dict[str, User]) -> int:
        return sum(u.is_admin for u in users.values())
