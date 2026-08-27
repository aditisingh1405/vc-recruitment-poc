from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import CandidateRead
from app.services import candidates as candidate_service

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    resume: UploadFile = File(..., description="PDF resume"),
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Parse a resume into a candidate record, without applying to a job.

    Uploading again with the same email updates that candidate.
    """
    content = await resume.read()
    candidate, _ = candidate_service.intake_resume(
        db, resume.filename or "resume.pdf", content, full_name=full_name, email=email
    )
    return candidate


@router.get("", response_model=List[CandidateRead])
def list_candidates(db: Session = Depends(get_db)):
    return candidate_service.list_candidates(db)


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    return candidate_service.get_candidate(db, candidate_id)
