"""Resume file handling: validate the upload, store it, pull out the text."""

import re
import unicodedata
import uuid
from pathlib import Path
from typing import Optional

import fitz  # pymupdf

from app.config import settings

PDF_MAGIC = b"%PDF-"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}")
YEARS_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I)


class ResumeError(ValueError):
    """Raised for anything wrong with the uploaded file. Routes turn this into
    a 400 rather than letting it surface as a 500."""


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "resume").stem
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-").lower()
    return stem[:60] or "resume"


def save_resume(filename: str, data: bytes) -> Path:
    """Validate and write the upload under settings.upload_dir.

    The stored name is prefixed with a uuid: two candidates both uploading
    "resume.pdf" must not overwrite each other.
    """
    if not data:
        raise ResumeError("The uploaded file is empty.")
    if len(data) > settings.max_resume_bytes:
        limit_mb = settings.max_resume_bytes / (1024 * 1024)
        raise ResumeError(f"Resume is larger than the {limit_mb:.0f} MB limit.")
    if not data.startswith(PDF_MAGIC):
        raise ResumeError("Only PDF resumes are accepted.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{uuid.uuid4().hex}-{_safe_stem(filename)}.pdf"
    path.write_bytes(data)
    return path


def extract_text(path: Path) -> str:
    """Return the plain text of a PDF resume."""
    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ResumeError("The PDF is password protected.")
            pages = [page.get_text("text") for page in doc]
    except ResumeError:
        raise
    except Exception as exc:  # pymupdf raises a variety of types
        raise ResumeError(f"Could not read the PDF: {exc}") from exc

    text = "\n".join(pages)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) < 50:
        raise ResumeError(
            "No text found in the PDF. Scanned or image-only resumes aren't "
            "supported -- please upload a text-based PDF."
        )
    return text


def find_email(text: str) -> Optional[str]:
    match = EMAIL_RE.search(text)
    return match.group(0).lower() if match else None


def find_phone(text: str) -> Optional[str]:
    match = PHONE_RE.search(text)
    return match.group(0).strip() if match else None


def guess_years_experience(text: str) -> Optional[float]:
    """Largest "N years" figure anywhere in the resume. Crude, but it only
    feeds the no-API-key fallback path."""
    values = [float(m) for m in YEARS_RE.findall(text)]
    plausible = [v for v in values if 0 < v <= 60]
    return max(plausible) if plausible else None


def guess_name(text: str) -> Optional[str]:
    """Resumes almost always open with the candidate's name on its own line."""
    for line in text.splitlines()[:8]:
        line = line.strip()
        if not (2 <= len(line.split()) <= 5):
            continue
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue
        if any(ch.isdigit() for ch in line):
            continue
        if line.lower() in {"curriculum vitae", "resume", "cv"}:
            continue
        return line.title() if line.isupper() else line
    return None
