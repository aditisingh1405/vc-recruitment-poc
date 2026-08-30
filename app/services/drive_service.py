"""Browse resumes that live in a shared Google Drive folder.

Deliberately stateless. Files are streamed into memory, parsed, and discarded:
nothing is written to uploads/, and nothing is written to the database. The
only thing that outlives a request is a short-lived in-process cache, so
opening the page twice doesn't refetch and re-bill every resume.

Auth mirrors the resume_parser POC: a read-only service account key, with the
Drive folder shared to that account's address.
"""

import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterator, List, Optional, Tuple

import fitz  # pymupdf, already used for uploaded resumes

from app.config import settings
from app.services import Unavailable
from app.services import llm_service, pdf_service

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"
GDOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_MIME = "application/msword"

# Legacy .doc is walked so it can be reported as skipped rather than vanishing.
DOCUMENT_MIMES = frozenset({PDF_MIME, GDOC_MIME, DOCX_MIME, DOC_MIME})

# Below this, a PDF has no text layer -- it's a scan and needs OCR.
MIN_CHARS = 100

_local = threading.local()
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"fetched_at": 0.0, "payload": None}


# --------------------------------------------------------------------------
# Drive client
# --------------------------------------------------------------------------
def _client():
    """One client per thread.

    googleapiclient's underlying http object is not thread-safe, and the
    listing below runs across a thread pool.
    """
    client = getattr(_local, "drive", None)
    if client is not None:
        return client

    if not settings.drive_enabled:
        raise Unavailable(
            "Google Drive is not configured. Set DRIVE_ROOT_FOLDER_ID and "
            "DRIVE_SERVICE_ACCOUNT_FILE in .env, then restart the server."
        )

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise Unavailable(
            "The Google Drive libraries are not installed. Run "
            "`pip install -r requirements.txt`."
        ) from exc

    try:
        creds = service_account.Credentials.from_service_account_file(
            settings.drive_service_account_file, scopes=SCOPES
        )
    except FileNotFoundError as exc:
        raise Unavailable(
            f"Service account key not found at "
            f"{settings.drive_service_account_file}."
        ) from exc
    except ValueError as exc:
        raise Unavailable(f"Service account key is not valid JSON: {exc}") from exc

    client = build("drive", "v3", credentials=creds, cache_discovery=False)
    _local.drive = client
    return client


def _list_children(drive, folder_id: str) -> Iterator[Dict[str, Any]]:
    """Yield every direct child of a folder, following pagination."""
    token = None
    while True:
        response = (
            drive.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink)",
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for item in response.get("files", []):
            yield item

        token = response.get("nextPageToken")
        if not token:
            return


def _walk(drive, folder_id: str, label: str = "") -> Iterator[Tuple[Dict[str, Any], str]]:
    """Recursively yield (file metadata, folder label) for every document.

    Folder names become the label, matching the resume_parser convention where
    the tree encodes a domain -- manager/, developer/, and so on.
    """
    for item in _list_children(drive, folder_id):
        if item["mimeType"] == FOLDER_MIME:
            child = f"{label}/{item['name']}".lstrip("/")
            for pair in _walk(drive, item["id"], child):
                yield pair
        elif item["mimeType"] in DOCUMENT_MIMES:
            yield item, label


# --------------------------------------------------------------------------
# Fetch + parse, entirely in memory
# --------------------------------------------------------------------------
def _drain(request) -> io.BytesIO:
    """Run a media request to completion into a BytesIO. Never touches disk."""
    from googleapiclient.http import MediaIoBaseDownload

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def _fetch(drive, meta: Dict[str, Any]) -> Tuple[io.BytesIO, str]:
    """Return (bytes, kind) for a supported document.

    Google Docs carry no binary content -- get_media() rejects them with
    403 fileNotDownloadable -- so they are exported to PDF instead.
    """
    mime = meta["mimeType"]
    file_id = meta["id"]

    if mime == PDF_MIME:
        return _drain(drive.files().get_media(fileId=file_id)), "pdf"
    if mime == GDOC_MIME:
        return (
            _drain(
                drive.files().export_media(fileId=file_id, mimeType=PDF_MIME)
            ),
            "pdf",
        )
    if mime == DOCX_MIME:
        return _drain(drive.files().get_media(fileId=file_id)), "docx"

    raise ValueError(f"unsupported mimeType: {mime}")


def _text_from_pdf(buf: io.BytesIO) -> str:
    """Parse from the byte stream, so no temporary file is ever created."""
    with fitz.open(stream=buf.getvalue(), filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError("password protected")
        return "\n".join(page.get_text("text") for page in doc).strip()


def _text_from_docx(buf: io.BytesIO) -> str:
    import docx

    document = docx.Document(buf)
    parts = [p.text for p in document.paragraphs]
    # Resumes are often laid out in tables, whose text is not in .paragraphs.
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts).strip()


def _process(meta: Dict[str, Any], domain: str) -> Dict[str, Any]:
    """Fetch and parse one Drive document into a candidate row.

    Returns a dict with a "state" of parsed or skipped. One unreadable file
    must not abandon the whole listing, so every failure is captured as a row
    rather than raised.
    """
    name = meta["name"]
    base = {
        "file_id": meta["id"],
        "filename": name,
        "domain": domain,
        "mime_type": meta["mimeType"],
        "modified": meta.get("modifiedTime"),
        "web_view_link": meta.get("webViewLink"),
        "state": "skipped",
        "reason": None,
        "full_name": None,
        "email": None,
        "phone": None,
        "location": None,
        "years_experience": None,
        "skills": [],
        "education": [],
        "summary": None,
        "chars": 0,
        "extracted_by": None,
    }

    if meta["mimeType"] == DOC_MIME:
        base["reason"] = "Legacy .doc format is not supported."
        return base

    try:
        drive = _client()
        buf, kind = _fetch(drive, meta)
        text = _text_from_pdf(buf) if kind == "pdf" else _text_from_docx(buf)
    except Exception as exc:
        logger.warning("Drive: failed to read %s: %s", name, exc)
        base["state"] = "failed"
        base["reason"] = f"Could not read this file: {exc}"
        return base

    if kind == "pdf" and len(text) < MIN_CHARS:
        base["reason"] = "No text layer -- this looks like a scan and needs OCR."
        return base

    base["chars"] = len(text)

    try:
        extracted, engine = llm_service.extract_resume(text)
    except Exception as exc:  # extraction already falls back internally
        logger.warning("Drive: extraction failed for %s: %s", name, exc)
        base["state"] = "failed"
        base["reason"] = f"Could not extract details: {exc}"
        return base

    base.update(
        {
            "state": "parsed",
            "full_name": extracted.full_name or pdf_service.guess_name(text),
            "email": str(extracted.email) if extracted.email else None,
            "phone": extracted.phone,
            "location": extracted.location,
            "years_experience": extracted.years_experience,
            "skills": extracted.skills,
            "education": extracted.education,
            "summary": extracted.summary,
            "extracted_by": engine,
        }
    )
    return base


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def _build_payload() -> Dict[str, Any]:
    drive = _client()
    documents = list(_walk(drive, settings.drive_root_folder_id.strip()))

    if not documents:
        return {
            "candidates": [],
            "counts": {"parsed": 0, "skipped": 0, "failed": 0, "total": 0},
            "fetched_at": time.time(),
        }

    workers = max(1, min(settings.drive_max_workers, len(documents)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda pair: _process(*pair), documents))

    # Parsed first, then by name -- failures and scans sink to the bottom.
    order = {"parsed": 0, "skipped": 1, "failed": 2}
    rows.sort(key=lambda r: (order.get(r["state"], 3), (r["filename"] or "").lower()))

    counts = {"parsed": 0, "skipped": 0, "failed": 0, "total": len(rows)}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1

    return {"candidates": rows, "counts": counts, "fetched_at": time.time()}


def load_candidates(force: bool = False) -> Dict[str, Any]:
    """Return the Drive listing, using the in-process cache unless forced.

    The cache exists because every refresh re-downloads and re-extracts every
    resume, which costs both Drive quota and LLM tokens. It is memory only --
    a restart clears it, and nothing is persisted anywhere.
    """
    if not settings.drive_enabled:
        raise Unavailable(
            "Google Drive is not configured. Set DRIVE_ROOT_FOLDER_ID and "
            "DRIVE_SERVICE_ACCOUNT_FILE in .env, then restart the server."
        )

    with _cache_lock:
        age = time.time() - _cache["fetched_at"]
        cached = _cache["payload"]
        if not force and cached is not None and age < settings.drive_cache_ttl_seconds:
            return {**cached, "cached": True, "age_seconds": int(age)}

        payload = _build_payload()
        _cache["payload"] = payload
        _cache["fetched_at"] = payload["fetched_at"]
        return {**payload, "cached": False, "age_seconds": 0}


def status() -> Dict[str, Any]:
    """Configuration and cache state, without touching Drive."""
    with _cache_lock:
        payload = _cache["payload"]
        age = time.time() - _cache["fetched_at"] if payload else None

    return {
        "configured": settings.drive_enabled,
        "folder_id_set": bool(settings.drive_root_folder_id.strip()),
        "key_file_set": bool(settings.drive_service_account_file.strip()),
        "cache_ttl_seconds": settings.drive_cache_ttl_seconds,
        "cached": payload is not None,
        "age_seconds": int(age) if age is not None else None,
        "counts": payload["counts"] if payload else None,
    }
