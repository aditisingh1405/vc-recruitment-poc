"""Resume understanding and candidate screening.

Both entry points work with or without a GROQ_API_KEY. With a key they call
Groq; without one -- or if the call fails -- they fall back to deterministic
rules so the POC stays demoable. Each returns the engine that produced the
result ("llm" or "rules") so the UI can be honest about where a verdict came
from.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from app.config import settings
from app.schemas import ResumeExtract, ScreeningResult
from app.services import pdf_service

logger = logging.getLogger(__name__)

# Groq bills by token and resumes have a long tail of very long PDFs.
MAX_RESUME_CHARS = 12_000

STRONG_FIT_AT = 70
POSSIBLE_FIT_AT = 40

EXTRACT_SYSTEM = """You extract structured data from resumes.
Return ONLY a JSON object with these keys:
  full_name       string or null
  email           string or null
  phone           string or null
  location        string or null (city, region)
  years_experience  number or null (total professional years, your best estimate)
  skills          array of strings (concrete skills, tools, domains; max 25)
  education       array of strings (one per degree, "Degree, Institution, Year")
  summary         string, at most 2 sentences, factual
Use null when the resume does not say. Never invent details."""

SCREEN_SYSTEM = """You screen candidates for venture capital roles.
Judge the candidate against the job and return ONLY a JSON object:
  score           integer 0-100, how well this candidate fits THIS job
  verdict         one of "strong_fit", "possible_fit", "not_a_fit"
  reasoning       2-4 sentences citing specifics from the resume
  matched_skills  array of required skills the candidate demonstrably has
  missing_skills  array of required skills you found no evidence for
Be strict and evidence-based. A candidate missing most required skills or
well short of the experience bar is not a fit. Keep score and verdict
consistent: >=70 strong_fit, 40-69 possible_fit, <40 not_a_fit."""


def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        timeout=60.0,
        max_retries=2,
    )


def _chat_json(system: str, user: str) -> Dict[str, Any]:
    response = _client().chat.completions.create(
        model=settings.groq_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _norm(skill: str) -> str:
    return re.sub(r"[^a-z0-9+#. ]+", " ", skill.lower()).strip()


def _clean_list(raw: Any, limit: int) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out[:limit]


# --------------------------------------------------------------------------
# Resume extraction
# --------------------------------------------------------------------------
def _extract_with_rules(text: str) -> ResumeExtract:
    return ResumeExtract(
        full_name=pdf_service.guess_name(text),
        email=pdf_service.find_email(text),
        phone=pdf_service.find_phone(text),
        location=None,
        years_experience=pdf_service.guess_years_experience(text),
        skills=[],
        education=[],
        summary=None,
    )


def extract_resume(text: str) -> Tuple[ResumeExtract, str]:
    """Pull structured fields out of resume text."""
    snippet = text[:MAX_RESUME_CHARS]

    if settings.llm_enabled:
        try:
            data = _chat_json(EXTRACT_SYSTEM, f"Resume:\n\n{snippet}")
            data["skills"] = _clean_list(data.get("skills"), 25)
            data["education"] = _clean_list(data.get("education"), 10)
            extracted = ResumeExtract.model_validate(data)
            # The regexes are more reliable than the model on contact details.
            extracted.email = pdf_service.find_email(text) or extracted.email
            extracted.phone = pdf_service.find_phone(text) or extracted.phone
            return extracted, "llm"
        except Exception as exc:
            logger.warning("Groq extraction failed, using rules: %s", exc)

    return _extract_with_rules(text), "rules"


# --------------------------------------------------------------------------
# Screening
# --------------------------------------------------------------------------
def _verdict_for(score: int) -> str:
    if score >= STRONG_FIT_AT:
        return "strong_fit"
    if score >= POSSIBLE_FIT_AT:
        return "possible_fit"
    return "not_a_fit"


def _screen_with_rules(job, candidate) -> ScreeningResult:
    """Skill overlap (70 points) plus experience (30 points).

    Skills are matched against the whole resume text, not just the extracted
    skills list -- without an LLM that list is empty.
    """
    haystack = " ".join(
        filter(None, [(candidate.resume_text or ""), " ".join(candidate.skills or [])])
    ).lower()

    required = [s for s in (job.required_skills or []) if s.strip()]
    matched = [s for s in required if _norm(s) and _norm(s) in haystack]
    missing = [s for s in required if s not in matched]

    if required:
        skill_score = 70.0 * len(matched) / len(required)
    else:
        skill_score = 45.0  # nothing specified, so nothing to fail on

    needed = job.min_years_experience or 0
    have = candidate.years_experience
    if not needed:
        exp_score = 25.0
        exp_note = "No minimum experience set for this role."
    elif have is None:
        exp_score = 10.0
        exp_note = "Years of experience could not be determined from the resume."
    elif have >= needed:
        exp_score = 30.0
        exp_note = f"{have:g} years of experience meets the {needed}-year minimum."
    else:
        exp_score = 30.0 * (have / needed)
        exp_note = f"{have:g} years of experience is short of the {needed}-year minimum."

    score = int(round(min(100.0, skill_score + exp_score)))

    if required:
        skill_note = (
            f"Matched {len(matched)} of {len(required)} required skills"
            + (f" ({', '.join(matched)})." if matched else ".")
        )
    else:
        skill_note = "The job lists no required skills, so only experience was weighed."

    return ScreeningResult(
        score=score,
        verdict=_verdict_for(score),
        reasoning=(
            f"Keyword screening (no LLM key configured). {skill_note} {exp_note}"
        ),
        matched_skills=matched,
        missing_skills=missing,
    )


def screen_candidate(job, candidate) -> Tuple[ScreeningResult, str]:
    """Score one candidate against one job."""
    if settings.llm_enabled:
        try:
            prompt = _build_screen_prompt(job, candidate)
            data = _chat_json(SCREEN_SYSTEM, prompt)

            score = int(round(float(data.get("score", 0))))
            score = max(0, min(100, score))
            verdict = str(data.get("verdict", "")).strip().lower()
            if verdict not in {"strong_fit", "possible_fit", "not_a_fit"}:
                verdict = _verdict_for(score)

            return (
                ScreeningResult(
                    score=score,
                    verdict=verdict,
                    reasoning=str(data.get("reasoning") or "").strip()
                    or "No reasoning returned.",
                    matched_skills=_clean_list(data.get("matched_skills"), 25),
                    missing_skills=_clean_list(data.get("missing_skills"), 25),
                ),
                "llm",
            )
        except Exception as exc:
            logger.warning("Groq screening failed, using rules: %s", exc)

    return _screen_with_rules(job, candidate), "rules"


def _build_screen_prompt(job, candidate) -> str:
    required = ", ".join(job.required_skills or []) or "(none listed)"
    skills = ", ".join(candidate.skills or []) or "(none extracted)"
    education = "; ".join(candidate.education or []) or "(none extracted)"
    years = candidate.years_experience
    resume = (candidate.resume_text or "")[:MAX_RESUME_CHARS]

    return f"""JOB
Title: {job.title}
Location: {job.location or 'unspecified'}
Employment type: {job.employment_type or 'unspecified'}
Required skills: {required}
Minimum years of experience: {job.min_years_experience or 0}

Description:
{job.description}

CANDIDATE
Name: {candidate.full_name}
Location: {candidate.location or 'unspecified'}
Years of experience: {years if years is not None else 'unknown'}
Skills: {skills}
Education: {education}

Resume text:
{resume}"""
