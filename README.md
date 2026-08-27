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

Candidates are keyed by email: re-uploading under the same address updates that
candidate, and re-applying to the same role re-screens rather than duplicating.

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
frontend/              vanilla HTML/CSS/JS, served by FastAPI
migrations/            Alembic
uploads/               stored resumes (gitignored)
```

## Limitations

- Resumes must be text-based PDFs; scanned/image-only files are rejected
  rather than OCR'd.
- No authentication — the recruiter view is open to anyone who can reach it.
- Uploaded resumes are stored on local disk, not object storage.
