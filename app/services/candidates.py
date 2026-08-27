from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate
from app.services import NotFound
from app.services import llm_service, pdf_service
from app.services.pdf_service import ResumeError


def list_candidates(db: Session) -> List[Candidate]:
    stmt = select(Candidate).order_by(Candidate.created_at.desc(), Candidate.id.desc())
    return list(db.scalars(stmt))


def get_candidate(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFound(f"Candidate {candidate_id} does not exist.")
    return candidate


def intake_resume(
    db: Session,
    filename: str,
    content: bytes,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Tuple[Candidate, str]:
    """Store a resume, extract its fields, and create or refresh the candidate.

    Email is the identity key: re-uploading under the same address updates that
    candidate rather than creating a duplicate. Returns the candidate and the
    engine that did the extraction ("llm" or "rules").
    """
    path = pdf_service.save_resume(filename, content)
    text = pdf_service.extract_text(path)
    extracted, engine = llm_service.extract_resume(text)

    resolved_email = (email or "").strip().lower() or (
        str(extracted.email).lower() if extracted.email else None
    )
    if not resolved_email:
        path.unlink(missing_ok=True)
        raise ResumeError(
            "No email address could be found in the resume. Please enter one "
            "on the form."
        )

    resolved_name = (full_name or "").strip() or extracted.full_name
    if not resolved_name:
        path.unlink(missing_ok=True)
        raise ResumeError(
            "No name could be found in the resume. Please enter one on the form."
        )

    candidate = db.scalar(select(Candidate).where(Candidate.email == resolved_email))
    if candidate is None:
        candidate = Candidate(email=resolved_email)
        db.add(candidate)

    candidate.full_name = resolved_name
    candidate.phone = extracted.phone or candidate.phone
    candidate.location = extracted.location or candidate.location
    candidate.years_experience = extracted.years_experience
    candidate.skills = extracted.skills
    candidate.education = extracted.education
    candidate.summary = extracted.summary
    candidate.resume_filename = filename
    candidate.resume_path = str(path)
    candidate.resume_text = text

    db.commit()
    db.refresh(candidate)
    return candidate, engine
