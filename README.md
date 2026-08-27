# vc-recruitment-poc

AI-assisted candidate screening for VC roles. Recruiters post jobs, candidates
upload a PDF resume, an LLM extracts structured data and a suitability verdict.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill in GROQ_API_KEY
```

Postgres via Docker:

```bash
docker run --name pg -e POSTGRES_USER=aditi -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=vc_recruitment -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data -d postgres:17
```

## Migrations

```bash
alembic init migrations
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

## Run

```bash
uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs
