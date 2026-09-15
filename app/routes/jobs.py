from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, require_user
from app.models import User
from app.schemas import ApplicationDetail, JobCreate, JobRead, JobUpdate
from app.services import Unauthorized
from app.services import applications as application_service
from app.services import jobs as job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Posting a role is a recruiter action and needs a session. Reading roles
    does not -- candidates have to be able to browse and apply.

    The role is recorded against the account that posted it.
    """
    return job_service.create_job(db, payload, created_by_id=user.id)


@router.get("", response_model=List[JobRead])
def list_jobs(
    open_only: bool = Query(False, description="Only roles still accepting applicants"),
    mine: bool = Query(
        False,
        description=(
            "Only roles posted by the signed-in account. Requires a session; "
            "without one there is no 'mine' to filter by."
        ),
    ),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(current_user),
):
    """Open to everyone: a candidate must be able to browse roles without an
    account. Narrowing to your own postings is the part that needs a session."""
    if mine:
        if user is None:
            raise Unauthorized("Sign in to see your own roles.")
        return job_service.list_jobs(db, open_only=open_only, created_by_id=user.id)
    return job_service.list_jobs(db, open_only=open_only)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return job_service.get_job(db, job_id)


@router.patch("/{job_id}", response_model=JobRead)
def update_job(
    job_id: int,
    payload: JobUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return job_service.update_job(db, job_id, payload, user_id=user.id)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Delete a role and everything hanging off it: its applications, and the
    applicant rows linking uploaded resumes to it. Only the recruiter who
    posted it may do this."""
    job_service.delete_job(db, job_id, user_id=user.id)


@router.get("/{job_id}/applications", response_model=List[ApplicationDetail])
def list_job_applications(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    job_service.get_job(db, job_id)  # 404 for an unknown job, rather than []
    return application_service.list_applications(db, job_id=job_id)
