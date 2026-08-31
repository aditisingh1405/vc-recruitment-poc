from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApplicantList
from app.services import applications as application_service

router = APIRouter(prefix="/api/applicants", tags=["applicants"])


@router.get("", response_model=ApplicantList)
def list_applicants(
    job_id: Optional[int] = Query(None, description="Only one job posting."),
    db: Session = Depends(get_db),
):
    """Resumes that arrived through an application, with the job each one
    was submitted against.

    This is the durable half of the Resumes tab. The Candidates view reads
    Drive directly and stays stateless; this view needs the database, because
    only it records which posting a file belongs to.
    """
    return ApplicantList(applicants=application_service.list_applicants(db, job_id=job_id))
