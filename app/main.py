import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.routes import applications, candidates, drive, jobs
from app.services import Conflict, NotFound, Unavailable
from app.services.pdf_service import ResumeError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="VC Recruitment POC",
    description=(
        "AI-assisted candidate screening. Recruiters post jobs, candidates "
        "upload a PDF resume, and each application is scored against the role."
    ),
    version="0.1.0",
)

# The frontend is served from this same origin, but keep CORS open so the pages
# can also be opened straight off disk during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Service errors -> HTTP status codes
# --------------------------------------------------------------------------
@app.exception_handler(NotFound)
def handle_not_found(request: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Conflict)
def handle_conflict(request: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ResumeError)
def handle_resume_error(request: Request, exc: ResumeError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Unavailable)
def handle_unavailable(request: Request, exc: Unavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(applications.router)
app.include_router(drive.router)


@app.get("/api/health", tags=["meta"])
def health():
    """Also reports which screening engine is active, so the UI can warn when
    verdicts are coming from the keyword fallback."""
    return {
        "status": "ok",
        "screening_engine": "llm" if settings.llm_enabled else "rules",
        "model": settings.groq_model if settings.llm_enabled else None,
    }


if FRONTEND_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "jobs.html")

    # Mounted last: this catches every path the API routes above didn't claim.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
