from fastapi import APIRouter, Query

from app.schemas import DriveCandidateDetail, DriveDocumentList, DriveStatus
from app.services import drive_service

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.get("/status", response_model=DriveStatus)
def drive_status():
    """Whether Drive browsing is configured, and how warm the caches are.

    Never contacts Drive or the LLM, so the page can render a useful message
    instead of hanging when the feature is switched off.
    """
    return drive_service.status()


@router.get("/documents", response_model=DriveDocumentList)
def list_documents():
    """Every resume in the shared folder, parsed to text. No LLM involved.

    Files are streamed into memory and parsed there -- nothing is downloaded to
    uploads/ and nothing is written to the database. Unchanged files come from
    the per-file cache, so this is fast after the first read.
    """
    return drive_service.load_documents()


@router.post("/refresh", response_model=DriveDocumentList)
def refresh_documents(
    full: bool = Query(
        False,
        description=(
            "Re-download and re-parse every resume, including unchanged ones, "
            "and discard the cached LLM details. Without this, only files "
            "whose modifiedTime has changed are read again."
        ),
    ),
):
    """Re-walk the Drive folder.

    Metadata only unless something changed, so this is cheap when nothing in
    Drive has moved.
    """
    return drive_service.load_documents(force=True, full=full)


@router.get("/documents/{file_id}/details", response_model=DriveCandidateDetail)
def document_details(
    file_id: str,
    force: bool = Query(False, description="Re-run the model even if cached."),
):
    """The candidate details for one resume -- the only endpoint that uses the LLM.

    Runs against text already parsed and cached, so no Drive call is made. The
    result is cached against that resume version, so the model runs once per
    version rather than once per view.
    """
    return drive_service.get_details(file_id, force=force)
