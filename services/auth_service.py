"""User accounts for the GhostWork UI.

Backend:
  - supabase: Supabase Auth (users live in auth.users; Supabase hashes passwords).
    Accounts are created with the server-side admin API, so no email
    confirmation step is needed. Sign-in uses a separate short-lived client so
    the shared database client keeps using the server key.
  - memory: in-process users with Werkzeug password hashes (tests / offline demo).

Registration requires REGISTRATION_CODE; without it nobody can register.
"""

import hmac
import logging
import re
import threading
from typing import Dict, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from config import Config

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_memory_users: Dict[str, dict] = {}
_memory_lock = threading.Lock()


class AuthError(Exception):
    """Registration or sign-in failed; the message is safe to show to the user."""


def _clean_email(email: str) -> str:
    return (email or "").strip().lower()


def _public_user(user_id, email, name) -> dict:
    return {"id": str(user_id), "email": email, "name": name or email.split("@")[0]}


def registration_open() -> bool:
    return bool(Config.REGISTRATION_CODE)


def register(name: str, email: str, password: str, invite_code: str) -> dict:
    """Create an account. Raises AuthError with a user-safe message."""
    email = _clean_email(email)
    name = (name or "").strip()[:80]

    if not registration_open():
        raise AuthError("Registration is closed. Ask an administrator for an account.")
    if not hmac.compare_digest((invite_code or "").strip().encode(), Config.REGISTRATION_CODE.encode()):
        raise AuthError("Invalid invite code.")
    if not EMAIL_PATTERN.match(email):
        raise AuthError("Enter a valid email address.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    if Config.DB_BACKEND == "memory":
        with _memory_lock:
            if email in _memory_users:
                raise AuthError("An account with this email already exists.")
            user_id = len(_memory_users) + 1
            _memory_users[email] = {"id": user_id, "name": name,
                                    "password_hash": generate_password_hash(password)}
        return _public_user(user_id, email, name)

    from services.supabase_service import get_service

    try:
        response = get_service()._supabase_client.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"name": name},
        })
    except Exception as e:
        message = str(e).lower()
        if "already" in message and ("registered" in message or "exists" in message):
            raise AuthError("An account with this email already exists.") from e
        if "password" in message:
            raise AuthError("Password was rejected. Use a longer, less common password.") from e
        logger.error(f"Supabase user creation failed: {str(e)[:150]}")
        raise AuthError("Could not create the account. Try again later.") from e

    user = response.user
    logger.info("Registered new user", extra={"user_id": user.id})
    return _public_user(user.id, user.email, name)


def authenticate(email: str, password: str) -> Optional[dict]:
    """Return the user for valid credentials, else None."""
    email = _clean_email(email)
    if not email or not password:
        return None

    if Config.DB_BACKEND == "memory":
        record = _memory_users.get(email)
        if record and check_password_hash(record["password_hash"], password):
            return _public_user(record["id"], email, record["name"])
        return None

    from supabase import create_client

    try:
        # Separate client: signing in changes a client's session, and the shared
        # database client must keep using the server key.
        client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        response = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        logger.info(f"Sign-in rejected: {type(e).__name__}")
        return None

    user = response.user
    if not user:
        return None
    name = (user.user_metadata or {}).get("name")
    return _public_user(user.id, user.email, name)


def clear_memory_users() -> None:
    """Test helper."""
    with _memory_lock:
        _memory_users.clear()
