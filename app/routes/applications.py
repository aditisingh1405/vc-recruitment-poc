from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApplicationDetail, ApplicationUpdate
from app.services import Conflict
from app.services import applications as application_service

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.post("", response_model=ApplicationDetail, status_code=status.HTTP_201_CREATED)
async def apply(
    job_id: int = Form(...),
    resume: UploadFile = File(..., description="PDF resume"),
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Apply to a job: upload a resume, get it parsed and screened in one call."""
    content = await resume.read()
    return application_service.apply_to_job(
        db,
        job_id,
        resume.filename or "resume.pdf",
        content,
        full_name=full_name,
        email=email,
    )


@router.get("", response_model=List[ApplicationDetail])
def list_applications(
    job_id: Optional[int] = Query(None),
    candidate_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    return application_service.list_applications(
        db, job_id=job_id, candidate_id=candidate_id
    )


@router.get("/{application_id}", response_model=ApplicationDetail)
def get_application(application_id: int, db: Session = Depends(get_db)):
    return application_service.get_application(db, application_id)


@router.post("/{application_id}/rescreen", response_model=ApplicationDetail)
def rescreen(application_id: int, db: Session = Depends(get_db)):
    """Re-run screening -- useful after adding a GROQ_API_KEY to a verdict that
    was produced by the keyword fallback."""
    return application_service.rescreen(db, application_id)


@router.patch("/{application_id}", response_model=ApplicationDetail)
def update_application(
    application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)
):
    if payload.status is None:
        raise Conflict("Nothing to update: provide a status.")
    return application_service.set_status(db, application_id, payload.status)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: int, db: Session = Depends(get_db)):
    application_service.delete_application(db, application_id)
