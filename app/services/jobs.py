from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job
from app.schemas import JobCreate, JobUpdate
from app.services import NotFound


def create_job(db: Session, data: JobCreate) -> Job:
    job = Job(**data.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs(db: Session, open_only: bool = False) -> List[Job]:
    stmt = select(Job).order_by(Job.created_at.desc(), Job.id.desc())
    if open_only:
        stmt = stmt.where(Job.is_open.is_(True))
    return list(db.scalars(stmt))


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFound(f"Job {job_id} does not exist.")
    return job


def update_job(db: Session, job_id: int, data: JobUpdate) -> Job:
    job = get_job(db, job_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job_id: int) -> None:
    job = get_job(db, job_id)
    db.delete(job)
    db.commit()
