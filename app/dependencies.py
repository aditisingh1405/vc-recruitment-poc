"""Request-scoped dependencies shared by the route modules."""

from typing import Optional

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services import Unauthorized
from app.services import auth as auth_service


def current_user(
    vcr_session: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Whoever is signed in, or None. Use this where a page works either way."""
    return auth_service.user_for_token(db, vcr_session)


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    """Guard a route. Raises 401 when there is no valid session.

    Applied at router level for everything that exposes candidate data or
    changes state; posting an application stays open so candidates can still
    apply without an account.
    """
    if user is None:
        raise Unauthorized("Sign in to continue.")
    return user
