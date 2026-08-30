from fastapi import APIRouter

from app.schemas import DriveListing, DriveStatus
from app.services import drive_service

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.get("/status", response_model=DriveStatus)
def drive_status():
    """Whether Drive browsing is configured, and how old the cache is.

    Never contacts Drive, so the page can render a useful message instead of
    hanging when the feature is switched off.
    """
    return drive_service.status()


@router.get("/candidates", response_model=DriveListing)
def list_drive_candidates():
    """Candidates read live from the shared Drive folder.

    Resumes are parsed in memory and discarded -- nothing is downloaded to
    uploads/ and nothing is written to the database. Served from a short-lived
    in-process cache; use /refresh to bypass it.
    """
    return drive_service.load_candidates()


@router.post("/refresh", response_model=DriveListing)
def refresh_drive_candidates():
    """Re-read every resume from Drive, ignoring the cache."""
    return drive_service.load_candidates(force=True)
