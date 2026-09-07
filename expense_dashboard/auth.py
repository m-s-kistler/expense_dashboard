"""Fail-closed Google sign-in for the private financial dashboard."""

import time
from collections.abc import Mapping

import streamlit as st


def authorized_user(claims: Mapping, allowed_email: str, now: float | None = None) -> bool:
    """Only a verified, unexpired Google identity matching the owner is allowed."""
    try:
        expires = float(claims.get("exp", 0))
    except (TypeError, ValueError):
        return False
    return bool(
        allowed_email
        and claims.get("is_logged_in") is True
        and claims.get("iss") in {"https://accounts.google.com", "accounts.google.com"}
        and claims.get("email_verified") is True
        and str(claims.get("email", "")).casefold() == allowed_email.casefold()
        and expires > (time.time() if now is None else now)
    )


def require_login() -> None:
    """Stop before opening the database or rendering any financial content."""
    try:
        auth = st.secrets.get("auth", {})
        allowed_email = str(st.secrets.get("access", {}).get("allowed_email", "")).strip()
        ready = (
            allowed_email
            and all(auth.get(field) for field in ("client_id", "client_secret", "cookie_secret", "redirect_uri"))
            and auth.get("server_metadata_url") == "https://accounts.google.com/.well-known/openid-configuration"
        )
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        ready = False
    if not ready:
        st.title("Finance Dashboard")
        st.info("Sign-in setup is not complete. Contact the dashboard owner.")
        st.stop()
    if not st.user.get("is_logged_in", False):
        st.title("Finance Dashboard")
        st.write("Sign in to access your dashboard.")
        st.button("Sign in with Google", on_click=st.login, type="primary")
        st.stop()
    if not authorized_user(dict(st.user), allowed_email):
        st.error("Access denied or your session has expired. Sign in with the authorized account.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    st.sidebar.button("Sign out", on_click=st.logout)
