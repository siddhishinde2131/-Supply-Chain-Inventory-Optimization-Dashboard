"""Page 8 - Account & Users: change your password; administrators manage users."""
import pandas as pd
import streamlit as st

from src.auth.user_store import ROLES, AuthError
from src.ui import auth
from src.ui.theme import hero

user = st.session_state.get(auth.SESSION_KEY)
if user is None:
    st.warning("Please sign in first.")
    st.stop()
store = auth.get_store()

hero("Account & Users" if user["role"] == "admin" else "My Account",
     "Manage your password" + (" and the people who can use this dashboard." if user["role"] == "admin"
                               else "."),
     [(f"Signed in as {user['username']}", ""), (user["role"].capitalize(), "user")])

st.subheader("Change my password")
with st.form("change_password", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    current = c1.text_input("Current password", type="password", autocomplete="current-password")
    new = c2.text_input("New password", type="password", autocomplete="new-password",
                        help="At least 8 characters with a letter and a number.")
    confirm = c3.text_input("Confirm new password", type="password", autocomplete="new-password")
    if st.form_submit_button("Update password", icon=":material/key:"):
        if new != confirm:
            st.error("The new passwords do not match.")
        else:
            try:
                store.change_password(user["username"], current, new)
                st.success("Password updated.")
            except AuthError as exc:
                st.error(str(exc))

st.divider()
auth.recovery_code_section(user["username"])

if user["role"] != "admin":
    st.stop()

st.divider()
st.subheader("Users")
if "account_msg" in st.session_state:
    st.success(st.session_state.pop("account_msg"), icon=":material/check_circle:")
users = store.list_users()
table = pd.DataFrame([{**u.public(), "locked": bool(u.locked_until)} for u in users])
st.dataframe(table[["username", "display_name", "role", "created_at", "last_login", "locked"]],
             hide_index=True, width="stretch")

left, right = st.columns(2)
with left, st.form("add_user", clear_on_submit=True, border=True):
    st.markdown("**Add a user**")
    name = st.text_input("Username", help="3-32 characters: letters, numbers, '.', '_' or '-'.")
    display = st.text_input("Display name")
    role = st.selectbox("Role", ROLES, index=1,
                        help="Admin: manage users and write data to PostgreSQL. "
                             "Analyst: load data and use all analysis pages.")
    temp = st.text_input("Initial password", type="password",
                         help="Share it securely; the user can change it on this page.")
    if st.form_submit_button("Create user", type="primary", icon=":material/person_add:"):
        try:
            store.create_user(name, temp, role, display)
            st.session_state["account_msg"] = f"User '{name.strip().lower()}' created."
            st.rerun()
        except AuthError as exc:
            st.error(str(exc))

with right, st.container(border=True):
    st.markdown("**Manage an existing user**")
    others = [u.username for u in users]
    target = st.selectbox("User", others, key="manage_user")
    selected = next(u for u in users if u.username == target)
    tab_reset, tab_role, tab_delete = st.tabs(["Reset password", "Change role", "Delete"])
    with tab_reset:
        with st.form("reset_pw", clear_on_submit=True):
            pw = st.text_input("New password", type="password")
            if st.form_submit_button("Reset password and unlock", icon=":material/lock_reset:"):
                try:
                    store.reset_password(target, pw)
                    st.success(f"Password reset for '{target}'.")
                except AuthError as exc:
                    st.error(str(exc))
    with tab_role:
        new_role = st.selectbox("Role", ROLES, index=ROLES.index(selected.role), key="new_role")
        if st.button("Save role", icon=":material/badge:"):
            try:
                store.set_role(target, new_role)
                st.success(f"'{target}' is now {new_role}.")
                if target == user["username"]:
                    st.info("You changed your own role; it applies after you sign in again.")
            except AuthError as exc:
                st.error(str(exc))
    with tab_delete:
        if target == user["username"]:
            st.info("You cannot delete the account you are signed in with.")
        else:
            confirm_delete = st.checkbox(f"Yes, permanently delete '{target}'", key="confirm_delete")
            if st.button("Delete user", type="primary", disabled=not confirm_delete,
                         icon=":material/person_remove:"):
                try:
                    store.delete_user(target)
                    st.session_state["account_msg"] = f"User '{target}' deleted."
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))

st.caption(f"Accounts file: `{store.path}` (passwords are stored only as salted PBKDF2 hashes; "
           "the file is excluded from Git). Accounts are locked for 5 minutes after 5 failed "
           "sign-ins.")
