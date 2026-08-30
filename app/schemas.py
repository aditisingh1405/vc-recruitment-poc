from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ORM = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
class JobBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    location: Optional[str] = Field(default=None, max_length=120)
    employment_type: Optional[str] = Field(default=None, max_length=50)
    required_skills: List[str] = Field(default_factory=list)
    min_years_experience: int = Field(default=0, ge=0, le=60)


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1)
    location: Optional[str] = Field(default=None, max_length=120)
    employment_type: Optional[str] = Field(default=None, max_length=50)
    required_skills: Optional[List[str]] = None
    min_years_experience: Optional[int] = Field(default=None, ge=0, le=60)
    is_open: Optional[bool] = None


class JobRead(JobBase):
    model_config = ORM

    id: int
    is_open: bool
    created_at: datetime


class JobSummary(BaseModel):
    """Job fields embedded in an application row."""

    model_config = ORM

    id: int
    title: str
    location: Optional[str] = None


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------
class CandidateRead(BaseModel):
    model_config = ORM

    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    location: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    resume_filename: Optional[str] = None
    created_at: datetime


class CandidateSummary(BaseModel):
    """Candidate fields embedded in an application row."""

    model_config = ORM

    id: int
    full_name: str
    email: EmailStr
    years_experience: Optional[float] = None
    skills: List[str] = Field(default_factory=list)


class ResumeExtract(BaseModel):
    """What llm_service pulls out of resume text. Every field is optional --
    resumes are messy and a missing phone number shouldn't fail the upload."""

    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    years_experience: Optional[float] = Field(default=None, ge=0, le=60)
    skills: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    summary: Optional[str] = None


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
class ScreeningResult(BaseModel):
    """The suitability verdict for one candidate against one job."""

    score: int = Field(ge=0, le=100)
    verdict: str
    reasoning: str
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)


class ApplicationUpdate(BaseModel):
    status: Optional[str] = None


class ApplicationRead(BaseModel):
    model_config = ORM

    id: int
    job_id: int
    candidate_id: int
    status: str
    score: Optional[int] = None
    verdict: Optional[str] = None
    reasoning: Optional[str] = None
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    screened_by: Optional[str] = None
    created_at: datetime


class ApplicationDetail(ApplicationRead):
    """An application with its job and candidate inlined -- what the recruiter
    dashboard renders."""

    job: JobSummary
    candidate: CandidateSummary

    # Set when the application saved but a follow-on step (the Drive upload)
    # did not. The application is still valid.
    warning: Optional[str] = None


class GeneratedResume(BaseModel):
    """A simulated resume waiting in temp for the form to pick up."""

    token: str
    filename: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    headline: Optional[str] = None
    size_bytes: int
    generated_by: str


# --------------------------------------------------------------------------
# Google Drive browsing
#
# Two stages. A DriveDocument is the cheap, LLM-free parse of one file; a
# DriveCandidateDetail is what the model makes of it, fetched only when a
# candidate is actually displayed. Neither has an ORM counterpart -- nothing
# here is stored in the database.
# --------------------------------------------------------------------------
class DriveDocument(BaseModel):
    file_id: str
    filename: str
    domain: str = ""
    mime_type: str
    modified: Optional[str] = None
    web_view_link: Optional[str] = None

    state: str  # parsed | skipped | failed
    reason: Optional[str] = None
    chars: int = 0
    display_name: Optional[str] = None
    from_cache: bool = False


class DriveCandidateDetail(BaseModel):
    """Produced by the LLM at display time, then cached per resume version."""

    file_id: str
    filename: str
    domain: str = ""
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    extracted_by: Optional[str] = None
    from_cache: bool = False


class DriveCounts(BaseModel):
    parsed: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    reused: int = 0
    reparsed: int = 0
    detailed: int = 0


class DriveDocumentList(BaseModel):
    documents: List[DriveDocument] = Field(default_factory=list)
    counts: DriveCounts
    fetched_at: float
    cached: bool = False
    age_seconds: int = 0


class DriveStatus(BaseModel):
    configured: bool
    folder_id_set: bool
    key_file_set: bool
    cache_ttl_seconds: int
    cached: bool
    age_seconds: Optional[int] = None
    counts: Optional[DriveCounts] = None
    files_cached: int = 0
    details_cached: int = 0
