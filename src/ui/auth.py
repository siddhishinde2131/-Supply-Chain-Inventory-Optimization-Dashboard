"""Login, registration, forgot password, logout, session timeout and role checks.

The signed-in user is kept in Streamlit's server-side session state (never the
password or its hash). Reloading the browser tab starts a new session, so the
user signs in again.
"""
import html
import os
import time

import streamlit as st

from src.auth.user_store import AuthError, UserStore

SESSION_KEY = "auth_user"
LAST_SEEN_KEY = "auth_last_seen"
FLASH_KEY = "auth_flash"
NEW_CODE_KEY = "auth_new_code"      # (username, code, reason) shown once after register / reset
PASSWORD_HELP = "At least 8 characters with a letter and a number."
USERNAME_HELP = "3-32 characters: letters, numbers, '.', '_' or '-'."


def session_timeout_minutes() -> int:
    try:
        return max(1, int(os.getenv("AUTH_SESSION_MINUTES", "30")))
    except ValueError:
        return 30


def get_store() -> UserStore:
    return UserStore()


def _refresh_session(user: dict) -> dict | None:
    """Re-read the users file and sync the live session.

    * If the account no longer exists (admin deleted it) -> log out.
    * If the role changed (e.g. admin demoted to analyst) -> update the
      session dict so the new role takes effect on this very page load.

    Returns the (possibly updated) user dict, or None if the user was
    deleted and has been logged out.
    """
    try:
        store = get_store()
        fresh = store.get(user["username"])
    except Exception:  # store unreadable - don't crash every page
        return user
    if fresh is None:
        logout("Your account has been removed. Please contact an administrator.")
        return None
    # Sync mutable fields from the authoritative file into the session dict.
    user["role"] = fresh.role
    user["display_name"] = fresh.display_name
    st.session_state[SESSION_KEY] = user
    return user


def current_user() -> dict | None:
    """The signed-in user, or None. Ends the session after the inactivity timeout.

    Also refreshes the session against the users file on every call so that
    deleted accounts are logged out and role changes take effect immediately.
    """
    user = st.session_state.get(SESSION_KEY)
    if user is None:
        return None
    now = time.time()
    last_seen = st.session_state.get(LAST_SEEN_KEY, now)
    if now - last_seen > session_timeout_minutes() * 60:
        logout(f"Your session ended after {session_timeout_minutes()} minutes of inactivity. "
               "Please sign in again.")
        return None
    st.session_state[LAST_SEEN_KEY] = now
    return _refresh_session(user)


def is_admin() -> bool:
    user = st.session_state.get(SESSION_KEY)
    return bool(user and user["role"] == "admin")


def sign_in(user) -> None:
    """Start a fresh session for ``user`` (clears anything left from before)."""
    st.session_state.clear()
    st.session_state[SESSION_KEY] = user.public()
    st.session_state[LAST_SEEN_KEY] = time.time()


def logout(message: str | None = None) -> None:
    """Remove the user AND all loaded data from the session."""
    st.session_state.clear()
    if message:
        st.session_state[FLASH_KEY] = message


# ---------------------------------------------------------------------------
# Sign-in screen: Sign in | Register | Forgot password
# ---------------------------------------------------------------------------
def login_page() -> None:
    store = get_store()
    # No navigation exists before sign-in, so hide the (otherwise empty) sidebar.
    st.markdown("<style>section[data-testid='stSidebar']{display:none;}</style>",
                unsafe_allow_html=True)
    _, middle, _ = st.columns([1, 1.15, 1])
    with middle:
        st.markdown("""<div class="login-head"><div class="logo">IO</div>
            <h2>Inventory Optimization</h2><p>Supply chain &amp; inventory analytics dashboard</p>
            </div>""", unsafe_allow_html=True)
        flash = st.session_state.pop(FLASH_KEY, None)
        if flash:
            st.info(flash, icon=":material/info:")
        if NEW_CODE_KEY in st.session_state:
            _show_recovery_code(store)
            return
        try:
            first_run = not store.has_users()
        except AuthError as exc:
            st.error(str(exc))
            return
        if first_run:
            st.info("No accounts exist yet. The **first account you register becomes the "
                    "administrator**.", icon=":material/admin_panel_settings:")
            tab_register, tab_sign_in, tab_forgot = st.tabs(["Register", "Sign in", "Forgot password"])
        else:
            tab_sign_in, tab_register, tab_forgot = st.tabs(["Sign in", "Register", "Forgot password"])
        with tab_sign_in:
            _sign_in_form(store)
        with tab_register:
            _register_form(store)
        with tab_forgot:
            _forgot_form(store)


def _sign_in_form(store: UserStore) -> None:
    with st.form("login_form", border=True):
        username = st.text_input("Username", key="login_username", autocomplete="username")
        password = st.text_input("Password", type="password", key="login_password",
                                 autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch",
                                          icon=":material/login:")
    if submitted:
        if not username or not password:
            st.error("Enter your username and password.")
            return
        try:
            user = store.authenticate(username, password)
        except AuthError as exc:
            st.error(str(exc), icon=":material/lock:")
            return
        sign_in(user)
        st.rerun()
    st.caption("Forgot your password? Use the **Forgot password** tab with your recovery code.")


def _register_form(store: UserStore) -> None:
    with st.form("register_form", border=True):
        display_name = st.text_input("Your name", key="reg_name")
        username = st.text_input("Username", key="reg_username", help=USERNAME_HELP,
                                 autocomplete="username")
        password = st.text_input("Password", type="password", key="reg_password",
                                 help=PASSWORD_HELP, autocomplete="new-password")
        confirm = st.text_input("Confirm password", type="password", key="reg_confirm",
                                autocomplete="new-password")
        submitted = st.form_submit_button("Create account", type="primary", width="stretch",
                                          icon=":material/person_add:")
    if submitted:
        if password != confirm:
            st.error("The passwords do not match.")
            return
        try:
            user, code = store.register(username, password, display_name)
        except AuthError as exc:
            st.error(str(exc))
            return
        st.session_state[NEW_CODE_KEY] = (user.username, code, "registered")
        st.rerun()
    st.caption("New accounts get the analyst role. An administrator can change roles later.")


def _forgot_form(store: UserStore) -> None:
    with st.form("forgot_form", border=True):
        st.caption("Enter the recovery code you saved when you registered.")
        username = st.text_input("Username", key="fp_username", autocomplete="username")
        code = st.text_input("Recovery code", key="fp_code", placeholder="XXXX-XXXX-XXXX-XXXX")
        password = st.text_input("New password", type="password", key="fp_password",
                                 help=PASSWORD_HELP, autocomplete="new-password")
        confirm = st.text_input("Confirm new password", type="password", key="fp_confirm",
                                autocomplete="new-password")
        submitted = st.form_submit_button("Reset password", type="primary", width="stretch",
                                          icon=":material/lock_reset:")
    if submitted:
        if password != confirm:
            st.error("The new passwords do not match.")
            return
        try:
            new_code = store.reset_with_recovery_code(username, code, password)
        except AuthError as exc:
            st.error(str(exc), icon=":material/lock:")
            return
        st.session_state[NEW_CODE_KEY] = (username.strip().lower(), new_code, "reset")
        st.rerun()
    st.caption("No recovery code? Ask an administrator to reset your password.")


def _show_recovery_code(store: UserStore) -> None:
    """Show a new recovery code ONCE, then continue."""
    username, code, reason = st.session_state[NEW_CODE_KEY]
    with st.container(border=True):
        if reason == "registered":
            st.success(f"Account **{username}** created.", icon=":material/check_circle:")
        else:
            st.success("Your password has been reset. Your old recovery code no longer works.",
                       icon=":material/check_circle:")
        st.markdown("**Save your recovery code.** You need it if you forget your password. "
                    "It is shown only now.")
        st.code(code, language=None)
        st.download_button("Download code as a text file",
                           f"Inventory Optimization - recovery code for {username}: {code}\n",
                           file_name=f"recovery_code_{username}.txt", icon=":material/download:",
                           width="stretch")
        label = ("I saved it - continue to the dashboard" if reason == "registered"
                 else "I saved it - go to sign in")
        if st.button(label, type="primary", width="stretch", key="code_saved"):
            del st.session_state[NEW_CODE_KEY]
            if reason == "registered":
                store.record_login(username)
                sign_in(store.get(username))
            else:
                st.session_state[FLASH_KEY] = "Sign in with your new password."
            st.rerun()


def recovery_code_section(username: str) -> None:
    """Account page: create a new recovery code (needs the current password)."""
    store = get_store()
    user = store.get(username)
    st.subheader("Recovery code")
    if user is not None and not user.has_recovery_code:
        st.warning("You have no recovery code yet, so you cannot use **Forgot password**. "
                   "Create one below.", icon=":material/warning:")
    else:
        st.caption("Lost your recovery code? Create a new one; the old code stops working.")
    with st.form("new_code_form", clear_on_submit=True):
        current = st.text_input("Current password", type="password", key="rc_password")
        if st.form_submit_button("Create new recovery code", icon=":material/key:"):
            try:
                code = store.regenerate_recovery_code(username, current)
                st.success("New recovery code - save it now, it is shown only once:")
                st.code(code, language=None)
            except AuthError as exc:
                st.error(str(exc))


def user_card() -> None:
    """Signed-in user summary and sign-out button for the sidebar."""
    user = st.session_state.get(SESSION_KEY)
    if not user:
        return
    st.markdown(f"""<div class="user-card"><div class="role">{html.escape(user['role'])}</div>
        <b>{html.escape(user['display_name'])}</b><br><span style="opacity:.7">@{html.escape(user['username'])}</span>
        </div>""", unsafe_allow_html=True)
    if st.button("Sign out", icon=":material/logout:", width="stretch", key="sign_out"):
        logout("You have signed out.")
        st.rerun()
