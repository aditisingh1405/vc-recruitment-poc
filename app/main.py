import logging
from typing import Optional
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.database import get_db
from app.routes import (
    applicants,
    auth,
    applications,
    candidates,
    drive,
    jobs,
    simulate,
)
from app.services import Conflict, Forbidden, NotFound, Unauthorized, Unavailable
from app.services import auth as auth_service
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


# The pages and the script that drives them ship as one unit: a cached page
# running against a newer app.js is how a missing element silently disabled a
# form. no-cache still allows ETag revalidation, so this costs a 304, not a
# re-download.
@app.middleware("http")
async def revalidate_frontend(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".html", ".js", ".css")) or path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


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


@app.exception_handler(Unauthorized)
def handle_unauthorized(request: Request, exc: Unauthorized):
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(Forbidden)
def handle_forbidden(request: Request, exc: Forbidden):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(Unavailable)
def handle_unavailable(request: Request, exc: Unavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(applications.router)
app.include_router(applicants.router)
app.include_router(drive.router)
app.include_router(simulate.router)


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
    # Pages that only make sense signed in. The JavaScript redirects too, but
    # gating here means the page is never served at all without a session --
    # the guard does not depend on the browser running our script.
    #
    # Registered as explicit paths rather than a catch-all: a wildcard here
    # would shadow every other static file, including app.js.
    def _guarded_page(page: str):
        def handler(
            vcr_session: Optional[str] = Cookie(default=None),
            db: Session = Depends(get_db),
        ):
            if auth_service.user_for_token(db, vcr_session) is None:
                return RedirectResponse(
                    f"/login.html?next={quote(page)}", status_code=303
                )
            return FileResponse(FRONTEND_DIR / page)

        return handler

    for _page in ("recruiter.html", "drive.html"):
        app.get(f"/{_page}", include_in_schema=False)(_guarded_page(_page))

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "jobs.html")

    # Mounted last: this catches every path the API routes above didn't claim.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
