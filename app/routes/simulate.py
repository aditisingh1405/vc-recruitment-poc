from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import GeneratedResume
from app.services import jobs as job_service
from app.services import resume_generator

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


@router.post("/resume", response_model=GeneratedResume)
def simulate_resume(
    job_id: Optional[int] = Query(
        None,
        description=(
            "Aim the persona at this role. Roughly 70% are then built to meet "
            "it and the rest to miss it, so a demo mostly shows candidates "
            "worth discussing while still producing rejections. Without it the "
            "persona is random and fit is accidental."
        ),
    ),
    db: Session = Depends(get_db),
):
    """Invent a resume, render it to a PDF, and park it in the temp directory.

    Returns a token the form uses to fetch the file back and attach it, so the
    submitted application goes through exactly the same path as a real upload.
    Every filename carries the gen_ prefix.
    """
    job = job_service.get_job(db, job_id) if job_id is not None else None
    return resume_generator.generate(job)


@router.get("/resume/{token}", response_class=FileResponse)
def download_generated_resume(token: str):
    """Fetch a generated resume by token, so the browser can attach it."""
    path, filename = resume_generator.resolve(token)
    return FileResponse(path, media_type="application/pdf", filename=filename)
