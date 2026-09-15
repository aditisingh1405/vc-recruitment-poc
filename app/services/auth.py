"""Recruiter accounts: sign up, sign in, and the session behind each request.

Passwords are hashed with Argon2id and never stored or logged in the clear.
Sessions are rows rather than signed cookies, so signing out revokes access
for real and a password change can drop every other session.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models import User, UserSession
from app.services import Conflict, NotFound, Unauthorized

logger = logging.getLogger(__name__)

SESSION_COOKIE = "vcr_session"
SESSION_DAYS = 14
MIN_PASSWORD_LENGTH = 8

_hasher = PasswordHasher()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(token: str) -> str:
    """What actually goes in the database. The token itself never does."""
    return hashlib.sha256(token.encode()).hexdigest()


def _normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _check_password_strength(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise Conflict(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )


def sign_up(db: Session, email: str, password: str, full_name: str) -> User:
    """Create a recruiter account.

    Sign-up is open: this is a proof of concept with no invite flow, so anyone
    who can reach the app can create an account. Put it behind something real
    before exposing it beyond a demo.
    """
    address = _normalise_email(email)
    if not address:
        raise Conflict("An email address is required.")
    name = (full_name or "").strip()
    if not name:
        raise Conflict("A name is required.")
    _check_password_strength(password)

    existing = db.scalar(select(User).where(User.email == address))
    if existing is not None:
        # Deliberately explicit: this is a recruiter tool, not a consumer
        # signup, so telling someone the address is taken is more useful than
        # hiding it.
        raise Conflict("An account with that email address already exists.")

    user = User(email=address, full_name=name, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Created account for %s", address)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the user for these credentials, or raise Unauthorized.

    The same message is used whether the address is unknown or the password is
    wrong, so the response cannot be used to enumerate accounts.
    """
    address = _normalise_email(email)
    user = db.scalar(select(User).where(User.email == address))
    wrong = Unauthorized("That email address and password do not match.")

    if user is None:
        # Hash anyway so a missing account does not answer measurably faster
        # than a wrong password.
        _hasher.hash(password or "x")
        raise wrong
    if not user.is_active:
        raise Unauthorized("That account has been deactivated.")

    try:
        _hasher.verify(user.password_hash, password or "")
    except (VerifyMismatchError, InvalidHashError):
        raise wrong

    # Argon2 parameters change between releases; refresh the stored hash when
    # the library says this one is out of date.
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login_at = _now()
    db.commit()
    db.refresh(user)
    return user


def start_session(db: Session, user: User) -> str:
    """Open a session and return the token to put in the cookie.

    The token is returned once and never recoverable afterwards -- only its
    digest is kept.
    """
    _sweep_expired(db)
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=_digest(token),
            expires_at=_now() + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def end_session(db: Session, token: Optional[str]) -> None:
    """Sign out. Silent when the token is unknown -- there is nothing to tell."""
    if not token:
        return
    db.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))
    db.commit()


def user_for_token(db: Session, token: Optional[str]) -> Optional[User]:
    """The signed-in user, or None. Never raises -- callers decide what a
    missing session means for them."""
    if not token:
        return None
    stmt = (
        select(UserSession)
        .options(selectinload(UserSession.user))
        .where(UserSession.token_hash == _digest(token))
    )
    session = db.scalar(stmt)
    if session is None:
        return None
    if session.expires_at <= _now():
        db.delete(session)
        db.commit()
        return None
    if session.user is None or not session.user.is_active:
        return None
    return session.user


def change_password(db: Session, user: User, current: str, new: str) -> None:
    """Change a password and drop every other session for that account."""
    try:
        _hasher.verify(user.password_hash, current or "")
    except (VerifyMismatchError, InvalidHashError):
        raise Unauthorized("The current password is not correct.")
    _check_password_strength(new)
    user.password_hash = hash_password(new)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound(f"User {user_id} does not exist.")
    return user


def _sweep_expired(db: Session) -> None:
    """Drop sessions that have lapsed. Cheap, and keeps the table from growing
    without bound over a long-running demo."""
    db.execute(delete(UserSession).where(UserSession.expires_at <= _now()))
