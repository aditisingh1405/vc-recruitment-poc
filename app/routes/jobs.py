from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApplicationDetail, JobCreate, JobRead, JobUpdate
from app.services import applications as application_service
from app.services import jobs as job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    return job_service.create_job(db, payload)


@router.get("", response_model=List[JobRead])
def list_jobs(
    open_only: bool = Query(False, description="Only roles still accepting applicants"),
    db: Session = Depends(get_db),
):
    return job_service.list_jobs(db, open_only=open_only)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return job_service.get_job(db, job_id)


@router.patch("/{job_id}", response_model=JobRead)
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    return job_service.update_job(db, job_id, payload)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job_service.delete_job(db, job_id)


@router.get("/{job_id}/applications", response_model=List[ApplicationDetail])
def list_job_applications(job_id: int, db: Session = Depends(get_db)):
    job_service.get_job(db, job_id)  # 404 for an unknown job, rather than []
    return application_service.list_applications(db, job_id=job_id)
