from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.schemas import GeneratedResume
from app.services import resume_generator

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


@router.post("/resume", response_model=GeneratedResume)
def simulate_resume():
    """Invent a resume, render it to a PDF, and park it in the temp directory.

    Returns a token the form uses to fetch the file back and attach it, so the
    submitted application goes through exactly the same path as a real upload.
    Every filename carries the gen_ prefix.
    """
    return resume_generator.generate()


@router.get("/resume/{token}", response_class=FileResponse)
def download_generated_resume(token: str):
    """Fetch a generated resume by token, so the browser can attach it."""
    path, filename = resume_generator.resolve(token)
    return FileResponse(path, media_type="application/pdf", filename=filename)
