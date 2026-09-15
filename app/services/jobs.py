from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Job
from app.schemas import JobCreate, JobUpdate
from app.services import Forbidden, NotFound


def create_job(db: Session, data: JobCreate, created_by_id: Optional[int] = None) -> Job:
    """Create a role, owned by whoever posted it."""
    job = Job(**data.model_dump(), created_by_id=created_by_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs(
    db: Session,
    open_only: bool = False,
    created_by_id: Optional[int] = None,
) -> List[Job]:
    """Roles, newest first.

    created_by_id narrows the list to one recruiter's own postings. The public
    listing never passes it -- a candidate has to be able to see every open
    role, whoever posted it.
    """
    stmt = (
        select(Job)
        .options(selectinload(Job.created_by))
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    if open_only:
        stmt = stmt.where(Job.is_open.is_(True))
    if created_by_id is not None:
        stmt = stmt.where(Job.created_by_id == created_by_id)
    return list(db.scalars(stmt))


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFound(f"Job {job_id} does not exist.")
    return job


def _require_owner(job: Job, user_id: int) -> None:
    """A role may only be changed by the recruiter who posted it.

    A role with no owner -- one created before accounts existed -- belongs to
    nobody, so nobody may change it. That deliberately leaves such roles
    read-only rather than making them fair game for whoever is signed in;
    assign one to an account if it needs managing.
    """
    if job.created_by_id is None:
        raise Forbidden(
            "That role has no owner and cannot be changed. Assign it to an "
            "account first."
        )
    if job.created_by_id != user_id:
        raise Forbidden("That role was posted by someone else.")


def update_job(db: Session, job_id: int, data: JobUpdate, user_id: int) -> Job:
    job = get_job(db, job_id)
    _require_owner(job, user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job_id: int, user_id: int) -> None:
    """Remove a role. Its applications and applicant rows cascade away with it,
    so the caller is expected to have warned about that first."""
    job = get_job(db, job_id)
    _require_owner(job, user_id)
    db.delete(job)
    db.commit()
