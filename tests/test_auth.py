"""Login security: hashing, password rules, lockout, roles and the sign-in UI."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.auth import passwords
from src.auth.user_store import GENERIC_LOGIN_ERROR, MAX_FAILED_ATTEMPTS, AuthError, UserStore

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """Fewer PBKDF2 iterations keep the tests fast; the algorithm is unchanged."""
    monkeypatch.setattr(passwords, "ITERATIONS", 1_000)


@pytest.fixture
def store(tmp_path):
    s = UserStore(tmp_path / "users.json")
    s.create_user("admin", "Admin12345", "admin", "Admin User")
    return s


def test_hash_is_salted_and_verifiable():
    h1, h2 = passwords.hash_password("Secret123"), passwords.hash_password("Secret123")
    assert h1 != h2                                   # different random salts
    assert passwords.verify_password("Secret123", h1)
    assert not passwords.verify_password("secret123", h1)
    assert not passwords.verify_password("Secret123", "garbage")


@pytest.mark.parametrize("password, ok", [("short1", False), ("lettersonly", False),
                                          ("12345678", False), ("goodpass1", True)])
def test_password_rules(password, ok):
    assert (passwords.password_problems(password) == []) is ok


def test_password_cannot_equal_username():
    assert passwords.password_problems("analyst01", "analyst01")


def test_file_never_contains_plain_password(store):
    text = store.path.read_text(encoding="utf-8")
    assert "Admin12345" not in text
    assert json.loads(text)["users"]["admin"]["password_hash"].startswith("pbkdf2_sha256$")


def test_first_account_must_be_admin(tmp_path):
    with pytest.raises(AuthError):
        UserStore(tmp_path / "u.json").create_user("bob", "Password1", "analyst")


def test_create_validates_and_rejects_duplicates(store):
    with pytest.raises(AuthError):
        store.create_user("Admin", "Another123", "analyst")      # usernames are case-insensitive
    with pytest.raises(AuthError):
        store.create_user("a", "Another123", "analyst")          # too short
    with pytest.raises(AuthError):
        store.create_user("bob", "Another123", "superuser")      # unknown role
    assert store.create_user("Bob", "Another123", "analyst").username == "bob"


def test_authenticate_success_records_last_login(store):
    user = store.authenticate("ADMIN", "Admin12345")
    assert user.is_admin and store.get("admin").last_login is not None
    assert "password_hash" not in user.public()


def test_wrong_password_and_unknown_user_give_same_message(store):
    for username, password in (("admin", "wrong-pass1"), ("nobody", "whatever1")):
        with pytest.raises(AuthError, match=GENERIC_LOGIN_ERROR):
            store.authenticate(username, password)


def test_lockout_after_repeated_failures_and_unlock_after_timeout(store):
    now = datetime(2026, 1, 1, 12, 0)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError):
            store.authenticate("admin", "wrong-pass1", now)
    with pytest.raises(AuthError, match="locked"):
        store.authenticate("admin", "Admin12345", now)            # correct password, still locked
    assert store.authenticate("admin", "Admin12345", now + timedelta(minutes=6)).is_admin


def test_change_and_reset_password(store):
    with pytest.raises(AuthError):
        store.change_password("admin", "not-current1", "NewPass123")
    store.change_password("admin", "Admin12345", "NewPass123")
    assert store.authenticate("admin", "NewPass123")
    store.reset_password("admin", "Reset12345")
    assert store.authenticate("admin", "Reset12345")


def test_last_admin_is_protected(store):
    with pytest.raises(AuthError):
        store.delete_user("admin")
    with pytest.raises(AuthError):
        store.set_role("admin", "analyst")
    store.create_user("second", "Second123", "admin")
    store.set_role("admin", "analyst")
    store.delete_user("admin")
    assert [u.username for u in store.list_users()] == ["second"]


def test_register_and_reset_with_recovery_code(store):
    user, code = store.register("meena", "Original123", "Meena")
    assert user.role == "analyst"                     # admin already exists
    raw = store.path.read_text(encoding="utf-8")
    assert code not in raw and "Original123" not in raw
    assert "recovery_hash" not in user.public()
    new_code = store.reset_with_recovery_code("Meena", code.lower(), "Brandnew123")
    assert store.authenticate("meena", "Brandnew123")
    with pytest.raises(AuthError):                    # the old code is used up
        store.reset_with_recovery_code("meena", code, "Another123")
    store.reset_with_recovery_code("meena", new_code, "Another123")
    assert store.authenticate("meena", "Another123")


def test_wrong_recovery_code_is_generic_and_locks(store):
    from src.auth.user_store import GENERIC_RECOVERY_ERROR

    store.register("meena", "Original123")
    now = datetime(2026, 1, 1, 12, 0)
    with pytest.raises(AuthError, match=GENERIC_RECOVERY_ERROR):
        store.reset_with_recovery_code("nobody", "AAAA-BBBB-CCCC-DDDD", "Brandnew123", now)
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError, match=GENERIC_RECOVERY_ERROR):
            store.reset_with_recovery_code("meena", "AAAA-BBBB-CCCC-DDDD", "Brandnew123", now)
    with pytest.raises(AuthError, match="locked"):
        store.authenticate("meena", "Original123", now)


def test_users_without_recovery_code_and_regeneration(store):
    with pytest.raises(AuthError):                    # admin-created account has no code
        store.reset_with_recovery_code("admin", "AAAA-BBBB-CCCC-DDDD", "Brandnew123")
    with pytest.raises(AuthError):
        store.regenerate_recovery_code("admin", "wrong-pass1")
    code = store.regenerate_recovery_code("admin", "Admin12345")
    assert store.get("admin").has_recovery_code
    store.reset_with_recovery_code("admin", code, "Brandnew123")


def test_old_user_file_without_recovery_field_still_loads(tmp_path):
    from src.auth.passwords import hash_password

    legacy = {"users": {"old": {"username": "old", "display_name": "Old", "role": "admin",
                                "password_hash": hash_password("Legacy123"),
                                "created_at": "2026-01-01T00:00:00"}}}
    path = tmp_path / "users.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert UserStore(path).authenticate("old", "Legacy123").has_recovery_code is False


# --- Sign-in user interface -------------------------------------------------
def _app(monkeypatch, users_file: Path) -> AppTest:
    monkeypatch.setenv("AUTH_USERS_FILE", str(users_file))
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)


def _submit(at: AppTest, label: str) -> None:
    next(b for b in at.button if b.label == label).click().run()


def _register(at: AppTest, username: str, password: str, name: str = "") -> str:
    """Fill the Register tab; returns the recovery code shown on screen."""
    at.text_input(key="reg_name").set_value(name or username)
    at.text_input(key="reg_username").set_value(username)
    at.text_input(key="reg_password").set_value(password)
    at.text_input(key="reg_confirm").set_value(password)
    _submit(at, "Create account")
    assert not at.exception, [e.value for e in at.exception]
    return at.code[0].value


def test_first_registration_creates_admin_and_shows_recovery_code(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path / "users.json").run()
    assert any("first account you register becomes the administrator" in i.value for i in at.info)
    code = _register(at, "priya", "Dashboard1", "Priya")
    assert len(code) == 19 and code.count("-") == 3
    _submit(at, "I saved it - continue to the dashboard")
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["auth_user"]["role"] == "admin"
    stored = UserStore(tmp_path / "users.json").get("priya")
    assert stored.is_admin and stored.last_login is not None
    assert code not in (tmp_path / "users.json").read_text(encoding="utf-8")


def test_later_registrations_are_analysts(monkeypatch, tmp_path, store):
    at = _app(monkeypatch, store.path).run()
    _register(at, "ravi", "Analyst123")
    assert store.get("ravi").role == "analyst"


def test_registration_rejects_mismatch_and_duplicates(monkeypatch, tmp_path, store):
    at = _app(monkeypatch, store.path).run()
    at.text_input(key="reg_username").set_value("ravi")
    at.text_input(key="reg_password").set_value("Analyst123")
    at.text_input(key="reg_confirm").set_value("Different123")
    _submit(at, "Create account")
    assert any("do not match" in e.value for e in at.error)
    at.text_input(key="reg_username").set_value("admin")
    at.text_input(key="reg_confirm").set_value("Analyst123")
    _submit(at, "Create account")
    assert any("already taken" in e.value for e in at.error)


def test_forgot_password_flow_in_ui(monkeypatch, tmp_path, store):
    _, code = store.register("meena", "Original123")
    at = _app(monkeypatch, store.path).run()
    at.text_input(key="fp_username").set_value("meena")
    at.text_input(key="fp_code").set_value(code.lower().replace("-", " "))   # typing is forgiving
    at.text_input(key="fp_password").set_value("Brandnew123")
    at.text_input(key="fp_confirm").set_value("Brandnew123")
    _submit(at, "Reset password")
    assert not at.exception, [e.value for e in at.exception]
    new_code = at.code[0].value
    assert new_code != code
    _submit(at, "I saved it - go to sign in")
    assert any("Sign in with your new password" in i.value for i in at.info)
    assert store.authenticate("meena", "Brandnew123")


def test_sign_in_rejects_wrong_password_then_accepts_correct(monkeypatch, tmp_path, store):
    at = _app(monkeypatch, store.path).run()
    at.text_input(key="login_username").set_value("admin")
    at.text_input(key="login_password").set_value("wrong-pass1")
    _submit(at, "Sign in")
    assert any(GENERIC_LOGIN_ERROR in e.value for e in at.error)
    assert "auth_user" not in at.session_state
    at.text_input(key="login_password").set_value("Admin12345")
    _submit(at, "Sign in")
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["auth_user"]["username"] == "admin"
    assert "password_hash" not in at.session_state["auth_user"]


def test_sign_out_clears_session(monkeypatch, tmp_path, store):
    at = _app(monkeypatch, store.path).run()
    at.text_input(key="login_username").set_value("admin")
    at.text_input(key="login_password").set_value("Admin12345")
    _submit(at, "Sign in")
    at.session_state["private_marker"] = "data from this session"
    at.run()
    _submit(at, "Sign out")
    assert "auth_user" not in at.session_state and "private_marker" not in at.session_state


def test_session_timeout_signs_user_out(monkeypatch, tmp_path, store):
    at = _app(monkeypatch, store.path)
    at.session_state["auth_user"] = store.get("admin").public()
    at.session_state["auth_last_seen"] = 0          # long ago
    at.run()
    assert "auth_user" not in at.session_state
    assert any("inactivity" in i.value for i in at.info)


def test_analyst_cannot_manage_users(monkeypatch, tmp_path, store):
    store.create_user("ana", "Analyst123", "analyst")
    page = AppTest.from_file(str(ROOT / "app_pages/8_Account.py"), default_timeout=60)
    monkeypatch.setenv("AUTH_USERS_FILE", str(store.path))
    page.session_state["auth_user"] = store.get("ana").public()
    page.run()
    assert not page.exception
    assert not any(b.label == "Create user" for b in page.button)


def test_admin_can_create_user_from_account_page(monkeypatch, tmp_path, store):
    monkeypatch.setenv("AUTH_USERS_FILE", str(store.path))
    page = AppTest.from_file(str(ROOT / "app_pages/8_Account.py"), default_timeout=60)
    page.session_state["auth_user"] = store.get("admin").public()
    page.run()
    form_inputs = [t for t in page.text_input if t.label in ("Username", "Display name", "Initial password")]
    values = {"Username": "newbie", "Display name": "New Person", "Initial password": "Welcome123"}
    for widget in form_inputs:
        widget.set_value(values[widget.label])
    _submit(page, "Create user")
    assert not page.exception, [e.value for e in page.exception]
    assert store.get("newbie").role == "analyst"


# --- Stale-session security fixes (Fix #3) ----------------------------------

def test_deleted_user_is_logged_out_on_next_page_load(monkeypatch, tmp_path, store):
    """A user deleted while their session is active must be evicted on the next
    Streamlit rerun, not allowed to keep browsing."""
    store.create_user("second", "Second123", "admin")  # need 2 admins to delete admin
    stale_user = store.get("admin").public()
    store.delete_user("admin")                          # delete account mid-session
    at = _app(monkeypatch, store.path)
    at.session_state["auth_user"] = stale_user
    at.session_state["auth_last_seen"] = __import__("time").time()
    at.run()
    assert "auth_user" not in at.session_state, "Deleted user must be signed out"
    # The user sees an informative message, not a silent redirect
    from itertools import chain
    all_messages = [m.value for m in chain(at.info, at.warning, at.error)]
    assert any("removed" in m or "account" in m.lower() for m in all_messages)


def test_demoted_admin_loses_powers_on_next_page_load(monkeypatch, tmp_path, store):
    """An admin demoted to analyst while signed in must lose admin rights on the
    next page load — without needing to sign out and back in."""
    store.create_user("second", "Second123", "admin")  # keep at least one admin
    # Session still holds old role=admin snapshot
    stale_user = store.get("admin").public()
    assert stale_user["role"] == "admin"
    store.set_role("admin", "analyst")                  # demote while session is live

    at = _app(monkeypatch, store.path)
    at.session_state["auth_user"] = stale_user
    at.session_state["auth_last_seen"] = __import__("time").time()
    at.run()
    # Session must still exist (user was not deleted) but with the updated role
    assert "auth_user" in at.session_state
    assert at.session_state["auth_user"]["role"] == "analyst", (
        "Role in session must reflect the updated value from the users file")

