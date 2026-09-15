from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import current_user, require_user
from app.models import User
from app.schemas import (
    LoginRequest,
    PasswordChange,
    SessionRead,
    SignUpRequest,
    UserRead,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    """HTTP-only so script on the page cannot read it, SameSite=Lax so it is
    not sent on cross-site requests. Secure follows the deployment: on plain
    http://localhost a Secure cookie would never be stored at all."""
    response.set_cookie(
        auth_service.SESSION_COOKIE,
        token,
        max_age=auth_service.SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def sign_up(payload: SignUpRequest, response: Response, db: Session = Depends(get_db)):
    """Create a recruiter account and sign in with it.

    Sign-up is open -- there is no invite flow -- so anyone who can reach the
    app can create an account. That is a proof-of-concept decision, not a
    deployment-ready one.
    """
    user = auth_service.sign_up(
        db, email=payload.email, password=payload.password, full_name=payload.full_name
    )
    _set_session_cookie(response, auth_service.start_session(db, user))
    return user


@router.post("/login", response_model=UserRead)
def log_in(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, payload.email, payload.password)
    _set_session_cookie(response, auth_service.start_session(db, user))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def log_out(
    response: Response,
    vcr_session: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Revoke this session. Succeeds even when there was nothing to revoke."""
    auth_service.end_session(db, vcr_session)
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")


@router.get("/me", response_model=SessionRead)
def whoami(user: Optional[User] = Depends(current_user)):
    """Who is signed in, or null. Deliberately never 401s: every page calls
    this on load to decide what to show."""
    return SessionRead(user=user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    response: Response,
    user: User = Depends(require_user),
    vcr_session: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Change the password, which signs out every session including this one."""
    auth_service.change_password(
        db, user, payload.current_password, payload.new_password
    )
    response.delete_cookie(auth_service.SESSION_COOKIE, path="/")
