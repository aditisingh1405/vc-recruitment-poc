# vc-recruitment-poc

AI-assisted candidate screening for VC roles. Recruiters post jobs, candidates
upload a PDF resume, an LLM extracts structured data and a suitability verdict.

## How it works

1. A recruiter posts a role with required skills and a minimum experience bar.
2. A candidate uploads a PDF resume against that role.
3. `pdf_service` extracts the text; `llm_service` turns it into structured
   fields (name, contact, skills, education, years of experience).
4. The same service scores the candidate against the role and returns a
   0–100 score, a verdict (`strong_fit` / `possible_fit` / `not_a_fit`), and
   written reasoning citing matched and missing skills.
5. The recruiter view lists applicants ranked by score.

**Screening works without an API key.** If `GROQ_API_KEY` is unset, the app
falls back to deterministic keyword matching (skill overlap for 70 points,
experience for 30) so the POC is demoable out of the box. Every application
records which engine produced its verdict in `screened_by`, and the recruiter
page shows a banner when the fallback is active. Add a key and use the
**Re-screen** button to upgrade an existing verdict.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill in DATABASE_URL and GROQ_API_KEY
```

Postgres via Docker — the user, password and database must match the
`DATABASE_URL` you put in `.env`:

```bash
docker run --name pg -e POSTGRES_USER=aditi -e POSTGRES_PASSWORD=CHANGEME \
  -e POSTGRES_DB=vc_recruitment -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data -d postgres:17
```

Note: `requirements.txt` pins **psycopg 3**, so SQLAlchemy needs the driver
named explicitly. `app/config.py` rewrites a plain `postgresql://` URL to
`postgresql+psycopg://` for you — keep the plain form in `.env`.

## Migrations

Alembic is already initialised and the initial revision is committed, so a
fresh database only needs:

```bash
alembic upgrade head
```

After changing `app/models.py`:

```bash
alembic revision --autogenerate -m "what changed"
alembic upgrade head
```

## Run

```bash
uvicorn app.main:app --reload
```

- App: http://localhost:8000 — open roles, apply, recruiter dashboard
- API docs: http://localhost:8000/docs

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status plus the active screening engine |
| `POST` | `/api/jobs` | Post a role |
| `GET` | `/api/jobs?open_only=` | List roles |
| `GET` | `/api/jobs/{id}` | One role |
| `PATCH` | `/api/jobs/{id}` | Edit a role, or close it with `is_open: false` |
| `DELETE` | `/api/jobs/{id}` | Delete a role and its applications |
| `GET` | `/api/jobs/{id}/applications` | Applicants for a role, best score first |
| `POST` | `/api/candidates` | Parse a resume without applying (multipart) |
| `GET` | `/api/candidates` | List candidates |
| `GET` | `/api/candidates/{id}` | One candidate |
| `POST` | `/api/applications` | Apply: `job_id` + `resume` PDF, screened on submit |
| `GET` | `/api/applications?job_id=&candidate_id=` | List applications |
| `GET` | `/api/applications/{id}` | One application |
| `POST` | `/api/applications/{id}/rescreen` | Re-run screening |
| `PATCH` | `/api/applications/{id}` | Set status: `new`/`screened`/`shortlisted`/`rejected` |
| `DELETE` | `/api/applications/{id}` | Delete an application |
| `GET` | `/api/drive/status` | Whether Drive browsing is configured, and cache state |
| `GET` | `/api/drive/documents` | Resumes parsed to text. No LLM |
| `POST` | `/api/drive/refresh?full=` | Re-walk Drive; `full=true` rebuilds everything |
| `GET` | `/api/drive/documents/{id}/details` | LLM-extracted candidate details for one resume |

Candidates are keyed by email: re-uploading under the same address updates that
candidate, and re-applying to the same role re-screens rather than duplicating.

## Resumes (Google Drive)

A read-only browser for resumes that live in a shared Drive folder, reached
from the **Resumes** tab. It is deliberately stateless:

- resumes are streamed into memory, parsed and discarded -- nothing is written
  to `uploads/`;
- nothing is written to the database. There is no Drive table and no migration.
  Both caches live in process memory and are cleared by a restart.

Setup mirrors the `resume_parser` POC: enable the Drive API, create a service
account, download its JSON key, and share the Drive folder with the service
account's email as **Viewer**. Then point `.env` at both:

```
DRIVE_ROOT_FOLDER_ID=<trailing segment of the Drive folder URL>
DRIVE_SERVICE_ACCOUNT_FILE=/absolute/path/to/sa.json
```

Leave them blank and the tab reports the feature as unconfigured instead of
failing. Keep the key file outside the repo, or in `credentials/` which is
gitignored.

| Format | Handling |
| --- | --- |
| PDF | Parsed with pymupdf. Scans with no text layer are listed as skipped. |
| Google Doc | Exported to PDF by Drive, then parsed as a PDF. |
| `.docx` | Parsed with python-docx, including table contents. |
| `.doc` | Listed as skipped -- the legacy binary format needs LibreOffice. |

### Two stages

Reading and understanding are separate, because they cost very different things.

**Stage 1 -- read and parse.** `GET /api/drive/documents` walks the folder,
streams each file into memory, and turns it into a JSON record: metadata plus
plain text. **No LLM is involved**, so it is fast, free, and never rate
limited. Roughly three seconds for ten resumes on a cold cache, milliseconds
once warm.

**Stage 2 -- display.** `GET /api/drive/documents/{file_id}/details` is the
only endpoint that calls the model, and only for a candidate actually being
shown. It runs against text already cached, so it makes no Drive call. The page
renders the list immediately and fills each card in as its details arrive,
one request at a time.

### Caching

Both stages cache per file, keyed on `file_id` + the Drive `modifiedTime`:

| Cache | Holds | Invalidated by |
| --- | --- | --- |
| Whole listing | the last document list | 15-minute TTL, or either button |
| Per file (stage 1) | metadata + parsed text | the file changing in Drive, or **Rebuild all** |
| Per file (stage 2) | the LLM extraction | the same, so an edited resume is re-read |

**Check Drive for changes** re-walks the folder -- metadata only, one API call
per folder. Unchanged files are reused and never downloaded again; only new or
edited ones are parsed. A file that is re-parsed has its cached details dropped
too, since they describe the old version. Files that leave the folder are
evicted from both caches. Failures are deliberately *not* cached, since they are
usually transient and should be retried. **Rebuild all**
(`POST /api/drive/refresh?full=true`) discards everything and starts over.

The net effect: the model runs once per resume version, not once per page load.

### Rate limits

Groq's free tier allows 8000 tokens per minute and a resume costs roughly
2,500, so details are fetched one at a time rather than in parallel. Extraction
that still fails falls back to regex, visible as `rules` in the "read by" line
on each card.

## Layout

```
app/
  config.py            settings from .env, psycopg driver fix
  database.py          engine, session, Base, get_db
  models.py            Job, Candidate, Application
  schemas.py           request/response models
  main.py              app, error handlers, static frontend mount
  routes/              HTTP layer, one module per resource
  services/            business logic; pdf_service + llm_service do the work
                       drive_service parses Drive files in memory (no LLM),
                       then extracts details on display; stores nothing
frontend/              vanilla HTML/CSS/JS, served by FastAPI
migrations/            Alembic
uploads/               stored resumes (gitignored)
```

## Limitations

- Resumes must be text-based PDFs; scanned/image-only files are rejected
  rather than OCR'd.
- No authentication — the recruiter view is open to anyone who can reach it.
- Uploaded resumes are stored on local disk, not object storage.
