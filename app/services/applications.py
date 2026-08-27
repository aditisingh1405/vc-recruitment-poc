from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import STATUSES, Application, Candidate, Job
from app.services import Conflict, NotFound
from app.services import candidates as candidate_service
from app.services import jobs as job_service
from app.services import llm_service


def _with_relations(stmt):
    return stmt.options(
        selectinload(Application.job), selectinload(Application.candidate)
    )


def list_applications(
    db: Session, job_id: Optional[int] = None, candidate_id: Optional[int] = None
) -> List[Application]:
    stmt = _with_relations(select(Application))
    if job_id is not None:
        stmt = stmt.where(Application.job_id == job_id)
    if candidate_id is not None:
        stmt = stmt.where(Application.candidate_id == candidate_id)
    # Best candidates first; unscreened rows sort last.
    stmt = stmt.order_by(
        Application.score.desc().nullslast(), Application.created_at.desc()
    )
    return list(db.scalars(stmt))


def get_application(db: Session, application_id: int) -> Application:
    stmt = _with_relations(select(Application)).where(Application.id == application_id)
    application = db.scalar(stmt)
    if application is None:
        raise NotFound(f"Application {application_id} does not exist.")
    return application


def screen(db: Session, application: Application) -> Application:
    """Run (or re-run) the suitability screen and persist the verdict."""
    result, engine = llm_service.screen_candidate(
        application.job, application.candidate
    )

    application.score = result.score
    application.verdict = result.verdict
    application.reasoning = result.reasoning
    application.matched_skills = result.matched_skills
    application.missing_skills = result.missing_skills
    application.screened_by = engine
    if application.status == "new":
        application.status = "screened"

    db.commit()
    db.refresh(application)
    return application


def apply_to_job(
    db: Session,
    job_id: int,
    filename: str,
    content: bytes,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Application:
    """The candidate-facing flow: upload a resume against a job, get screened.

    Re-applying to the same job with the same email refreshes the resume and
    re-screens rather than failing on the unique constraint.
    """
    job = job_service.get_job(db, job_id)
    if not job.is_open:
        raise Conflict(f"'{job.title}' is no longer accepting applications.")

    candidate, _ = candidate_service.intake_resume(
        db, filename, content, full_name=full_name, email=email
    )

    application = db.scalar(
        select(Application).where(
            Application.job_id == job.id, Application.candidate_id == candidate.id
        )
    )
    if application is None:
        application = Application(job_id=job.id, candidate_id=candidate.id)
        db.add(application)
        db.commit()
        db.refresh(application)

    return screen(db, application)


def rescreen(db: Session, application_id: int) -> Application:
    return screen(db, get_application(db, application_id))


def set_status(db: Session, application_id: int, status: str) -> Application:
    if status not in STATUSES:
        raise Conflict(f"Status must be one of: {', '.join(STATUSES)}.")
    application = get_application(db, application_id)
    application.status = status
    db.commit()
    db.refresh(application)
    return application


def delete_application(db: Session, application_id: int) -> None:
    application = get_application(db, application_id)
    db.delete(application)
    db.commit()
