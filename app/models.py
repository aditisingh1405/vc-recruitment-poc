from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Application.verdict values, worst to best.
VERDICTS = ("not_a_fit", "possible_fit", "strong_fit")

# Application.status values -- the recruiter's pipeline, independent of the
# LLM's verdict.
STATUSES = ("new", "screened", "shortlisted", "rejected")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(120))
    employment_type: Mapped[Optional[str]] = mapped_column(String(50))
    required_skills: Mapped[List[str]] = mapped_column(JSON, default=list)
    min_years_experience: Mapped[int] = mapped_column(Integer, default=0)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    applications: Mapped[List["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    location: Mapped[Optional[str]] = mapped_column(String(120))

    # Filled by pdf_service + llm_service from the uploaded resume.
    years_experience: Mapped[Optional[float]] = mapped_column(Float)
    skills: Mapped[List[str]] = mapped_column(JSON, default=list)
    education: Mapped[List[str]] = mapped_column(JSON, default=list)
    summary: Mapped[Optional[str]] = mapped_column(Text)

    resume_filename: Mapped[Optional[str]] = mapped_column(String(255))
    resume_path: Mapped[Optional[str]] = mapped_column(String(512))
    resume_text: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    applications: Mapped[List["Application"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(20), default="new")

    # Screening result. Null until the screening pass has run.
    score: Mapped[Optional[int]] = mapped_column(Integer)
    verdict: Mapped[Optional[str]] = mapped_column(String(20))
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    matched_skills: Mapped[List[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[List[str]] = mapped_column(JSON, default=list)
    screened_by: Mapped[Optional[str]] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(back_populates="applications")
    candidate: Mapped["Candidate"] = relationship(back_populates="applications")
