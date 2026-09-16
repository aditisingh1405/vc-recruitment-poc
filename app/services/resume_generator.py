"""Make up a plausible resume, render it to a PDF, and park it in temp.

Used by the "Simulate resume" button on the apply form, so the flow can be
demonstrated without hunting for a real PDF. Every generated file is named
with a gen_ prefix so it is obvious -- in temp, in Drive, and in the database
-- that a person did not write it.

Works without a Groq key: the fallback builds a resume from the same persona
data, just without the model's prose.
"""

import json
import logging
import random
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import fitz  # pymupdf

from app.config import settings
from app.services import NotFound
from app.services import llm_service

logger = logging.getLogger(__name__)

GENERATED_PREFIX = "gen_"

# Scratch files are disposable; anything older than this is swept on the next
# generate so temp doesn't fill up over a long-running session.
MAX_AGE_SECONDS = 6 * 60 * 60

# Generation is capped so one click cannot turn into a long wait. Both are
# deliberately tight: the template fallback is instant and good enough.
GENERATE_TIMEOUT_SECONDS = 10.0
GENERATE_MAX_TOKENS = 900

# How often a resume aimed at a job is built to meet it rather than miss it.
# Weighted towards fits so a demo mostly shows candidates worth discussing,
# while still producing rejections without having to contrive one.
FIT_PROBABILITY = 0.7

FIRST = [
    "Aarti", "Rohan", "Meera", "Devika", "Karan", "Sana", "Vikram", "Nisha",
    "Arjun", "Priyanka", "Imran", "Leela", "Tanvi", "Rahul", "Sneha", "Kabir",
]
LAST = [
    "Iyer", "Bakshi", "Menon", "Chaudhary", "Rao", "Sethi", "Nair", "Kulkarni",
    "Bose", "Trivedi", "Ahuja", "Pillai", "Ganguly", "Verma", "Shetty",
]
CITIES = [
    "Bengaluru, India", "Mumbai, India", "Pune, India", "Gurugram, India",
    "London, UK", "Singapore", "New York, NY", "San Francisco, CA",
]
ROLES = [
    ("Investment Analyst", 2, 4, ["financial modeling", "market research", "Excel", "valuation"]),
    ("Senior Investment Associate", 5, 9, ["financial modeling", "due diligence", "valuation", "deal sourcing", "Python"]),
    ("Principal, Growth Equity", 8, 14, ["portfolio management", "due diligence", "valuation", "board reporting"]),
    ("Data Analyst", 2, 5, ["SQL", "Python", "dashboards", "market research"]),
    ("Backend Engineer", 3, 8, ["Python", "PostgreSQL", "FastAPI", "AWS", "Docker"]),
    ("Product Manager", 4, 9, ["roadmapping", "user research", "SQL", "stakeholder management"]),
]
SECTORS = ["enterprise SaaS", "fintech", "healthtech", "climate tech", "consumer marketplaces"]
FIRMS = ["Meridian Ventures", "Kestrel Growth", "Northgate Partners", "Bluecrest Capital",
         "Vantage Point Advisors", "Harbourline Capital"]
SCHOOLS = ["Indian Institute of Management, Ahmedabad", "London Business School",
           "Wharton School", "Indian Institute of Technology, Bombay",
           "UC Berkeley", "National University of Singapore"]

SYSTEM = """You write realistic but entirely fictional resumes for software demos.
Return ONLY a JSON object:
  full_name        string
  email            string
  phone            string
  location         string
  headline         string, one line
  summary          string, 2 sentences
  experience       array of exactly 2 objects: {title, company, dates, bullets: array of 2 strings}
  skills           array of strings, exactly as given in the brief
  education        array of 1 string, "Degree, Institution, Year"
Write concrete, quantified bullets. Invent every detail; never use a real person."""


# Every skill the personas know about, used to build a candidate who is
# plausibly employable but deliberately wrong for a particular role.
ALL_SKILLS = sorted({skill for _, _, _, skills in ROLES for skill in skills})


def _norm_skill(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _persona_for(job, fit: bool) -> Dict[str, Any]:
    """A brief aimed at one job, either meeting its bar or missing it.

    The caller decides which. "Fit" means the resume carries every required
    skill and clears the experience bar; "miss" means a plausible candidate
    from a different discipline who does neither. Screening still has the
    final say -- this loads the dice, it does not decide the verdict.
    """
    base = _persona()
    required = [s for s in (job.required_skills or []) if str(s).strip()]
    needed = job.min_years_experience or 0

    if fit:
        # Lead with what the role asks for, then pad with neighbouring skills
        # so the resume does not read as a checklist.
        extras = [s for s in base["skills"] if _norm_skill(s) not in
                  {_norm_skill(r) for r in required}]
        base["skills"] = required + extras[:3]
        base["years"] = random.randint(max(needed, 1), max(needed, 1) + 4)
        base["title"] = job.title
    else:
        off_limits = {_norm_skill(r) for r in required}
        pool = [s for s in ALL_SKILLS if _norm_skill(s) not in off_limits]
        base["skills"] = random.sample(pool, min(6, len(pool))) if pool else []
        # Short of the bar when there is one, junior when there is not.
        base["years"] = random.randint(0, needed - 1) if needed else random.randint(1, 3)
        others = [r for r in ROLES if r[0] != job.title]
        base["title"] = random.choice(others or ROLES)[0]

    base["aimed_at"] = job.title
    base["intended_fit"] = fit
    return base


def _persona() -> Dict[str, Any]:
    """A random brief, so two clicks never produce the same resume."""
    title, low, high, skills = random.choice(ROLES)
    years = random.randint(low, high)
    first, last = random.choice(FIRST), random.choice(LAST)
    return {
        "full_name": f"{first} {last}",
        "email": f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@example.com",
        "phone": f"+91 {random.randint(70000, 99999)} {random.randint(10000, 99999)}",
        "location": random.choice(CITIES),
        "title": title,
        "years": years,
        "sector": random.choice(SECTORS),
        "firm": random.choice(FIRMS),
        "prior_firm": random.choice(FIRMS),
        "school": random.choice(SCHOOLS),
        "skills": skills,
    }


def _fallback(persona: Dict[str, Any]) -> Dict[str, Any]:
    """A resume built from the persona alone, for when the LLM is unavailable."""
    year = time.gmtime().tm_year
    return {
        "full_name": persona["full_name"],
        "email": persona["email"],
        "phone": persona["phone"],
        "location": persona["location"],
        "headline": f"{persona['title']} · {persona['sector']}",
        "summary": (
            f"{persona['title']} with {persona['years']} years of experience "
            f"across {persona['sector']}. Focused on diligence, analysis and "
            f"working closely with operating teams."
        ),
        "experience": [
            {
                "title": persona["title"],
                "company": persona["firm"],
                "dates": f"{year - persona['years'] // 2}–Present",
                "bullets": [
                    f"Led analysis on {random.randint(8, 40)} opportunities in {persona['sector']}.",
                    "Built and maintained the models used for investment committee review.",
                ],
            },
            {
                "title": "Associate",
                "company": persona["prior_firm"],
                "dates": f"{year - persona['years']}–{year - persona['years'] // 2}",
                "bullets": [
                    "Ran market mapping and sourcing across early-stage companies.",
                ],
            },
        ],
        "skills": persona["skills"],
        "education": [f"MBA, {persona['school']}, {year - persona['years'] - 1}"],
    }


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value[:40] or "candidate"


def _render_pdf(data: Dict[str, Any]) -> bytes:
    """Lay the resume out as a single-page PDF. Returns bytes, writes nothing."""
    doc = fitz.open()
    page = doc.new_page()
    left, right, y = 56, 556, 64

    def write(text: str, size: int, bold: bool = False, gap: int = 6, indent: int = 0):
        nonlocal y
        font = "hebo" if bold else "helv"
        box = fitz.Rect(left + indent, y, right, y + 400)
        used = page.insert_textbox(box, text, fontsize=size, fontname=font, align=0)
        # insert_textbox returns the unused height of the box it was given.
        y += (400 - used) + gap

    write(data.get("full_name", "Candidate"), 19, bold=True, gap=2)
    contact = " · ".join(
        str(v) for v in (data.get("email"), data.get("phone"), data.get("location")) if v
    )
    write(contact, 9, gap=3)
    if data.get("headline"):
        write(str(data["headline"]), 10, gap=12)

    if data.get("summary"):
        write("SUMMARY", 9, bold=True, gap=3)
        write(str(data["summary"]), 10, gap=12)

    if data.get("experience"):
        write("EXPERIENCE", 9, bold=True, gap=4)
        for job in data["experience"][:3]:
            header = f"{job.get('title', '')} — {job.get('company', '')}"
            if job.get("dates"):
                header += f"  ({job['dates']})"
            write(header, 10, bold=True, gap=2)
            for bullet in (job.get("bullets") or [])[:3]:
                write(f"•  {bullet}", 9.5, gap=2, indent=10)
            y += 5

    if data.get("skills"):
        write("SKILLS", 9, bold=True, gap=3)
        write(", ".join(str(s) for s in data["skills"]), 9.5, gap=12)

    if data.get("education"):
        write("EDUCATION", 9, bold=True, gap=3)
        for line in data["education"][:2]:
            write(str(line), 9.5, gap=2)

    out = doc.tobytes()
    doc.close()
    return out


def _sweep() -> None:
    """Delete generated files older than MAX_AGE_SECONDS."""
    cutoff = time.time() - MAX_AGE_SECONDS
    try:
        for path in settings.generated_dir.glob(f"{GENERATED_PREFIX}*.pdf"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError as exc:  # a swept temp dir is not worth failing a request
        logger.warning("Could not sweep generated resumes: %s", exc)


def generate(job=None) -> Dict[str, Any]:
    """Create one resume and save it under the temp directory.

    Given a job, FIT_PROBABILITY of the resumes are built to meet it and the
    rest to miss it, so a demo shows both outcomes instead of a run of
    rejections. Without a job the persona is random, as before.

    Returns the token used to fetch it back, plus enough detail for the form to
    show what was made.
    """
    _sweep()
    if job is not None:
        persona = _persona_for(job, fit=random.random() < FIT_PROBABILITY)
    else:
        persona = _persona()
    engine = "rules"

    if settings.llm_enabled:
        # The skills have to be in the brief, not just the persona: without
        # them the model invents its own and any targeting is lost.
        wanted = ", ".join(persona["skills"]) or "general commercial skills"
        brief = (
            f"Write a resume for a fictional {persona['title']} with about "
            f"{persona['years']} years of experience in {persona['sector']}. "
            f"Name: {persona['full_name']}. Email: {persona['email']}. "
            f"Phone: {persona['phone']}. Location: {persona['location']}. "
            f"Most recent employer: {persona['firm']}. "
            f"Earlier employer: {persona['prior_firm']}. "
            f"Education at {persona['school']}. "
            f"The skills list must be exactly these, in this order: {wanted}. "
            f"Demonstrate them in the experience bullets, and do not add "
            f"skills beyond this list."
        )
        try:
            # Temperature is high on purpose: two clicks should not produce the
            # same resume, which is the opposite of what extraction wants.
            # A simulated resume is a convenience, not the product. The shared
            # client retries a rate limit five times with backoff, which turned
            # one click into a 40-second wait; here it is better to give up
            # quickly and render the template instead.
            response = llm_service._client().with_options(
                timeout=GENERATE_TIMEOUT_SECONDS, max_retries=1
            ).chat.completions.create(
                model=settings.groq_model,
                temperature=1.0,
                max_tokens=GENERATE_MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": brief},
                ],
            )
            data = json.loads(response.choices[0].message.content or "{}")
            # The model is free with the details but must not invent contact
            # information that could belong to a real person.
            data.update(
                {
                    "full_name": data.get("full_name") or persona["full_name"],
                    "email": persona["email"],
                    "phone": persona["phone"],
                    "location": persona["location"],
                }
            )
            engine = "llm"
        except Exception as exc:
            logger.warning("Resume generation fell back to the template: %s", exc)
            data = _fallback(persona)
    else:
        data = _fallback(persona)

    if not data.get("experience"):
        data = {**_fallback(persona), **{k: v for k, v in data.items() if v}}

    pdf = _render_pdf(data)

    token = uuid.uuid4().hex
    filename = f"{GENERATED_PREFIX}{_slug(data['full_name'])}_{token[:8]}.pdf"
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    path = settings.generated_dir / f"{token}__{filename}"
    path.write_bytes(pdf)

    return {
        "token": token,
        "filename": filename,
        "full_name": data.get("full_name"),
        "email": data.get("email"),
        "headline": data.get("headline"),
        "size_bytes": len(pdf),
        "generated_by": engine,
        "aimed_at": persona.get("aimed_at"),
        "intended_fit": persona.get("intended_fit"),
    }


def resolve(token: str) -> Tuple[Path, str]:
    """Return (path, filename) for a token, or raise NotFound."""
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        raise NotFound("That is not a valid generated-resume reference.")
    matches = sorted(settings.generated_dir.glob(f"{token}__*.pdf"))
    if not matches:
        raise NotFound(
            "That generated resume has expired. Press Simulate resume again."
        )
    path = matches[0]
    return path, path.name.split("__", 1)[1]
