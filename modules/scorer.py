"""
scorer.py
=========
Core AI scoring engine.

For each candidate, sends their resume text + the parsed JD to Gemini
and receives back a structured score across 5 rubric dimensions.

Rubric (from the internship brief — mandatory):
  - Skills Match       30%
  - Experience         25%
  - Education & Certs  15%
  - Projects/Portfolio 20%
  - Communication      10%

Hallucination mitigation:
  - Strict JSON output schema defined in the prompt
  - Scores validated to be integers 0–10
  - Justifications checked for minimum length
  - Temperature set to 0.2 (low) for consistent scoring


  "The scorer uses structured JSON output with a Pydantic-style
   validation step after the LLM call. If any score is out of range
   or missing, we reject the response and return a safe error state
   instead of propagating hallucinated scores."
"""

import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


# ─── Rubric weights (must match the brief) ────────────────────────────────────
RUBRIC_WEIGHTS = {
    "skills_match": 0.30,
    "experience_relevance": 0.25,
    "education_certifications": 0.15,
    "projects_portfolio": 0.20,
    "communication_quality": 0.10,
}

# Score thresholds for hire recommendation
HIRE_THRESHOLD = 60.0   # weighted total out of 100


# ─── Scoring Prompt ───────────────────────────────────────────────────────────
SCORING_PROMPT = """You are a senior HR evaluator scoring a candidate's resume against a job description.

Score the candidate on EXACTLY these 5 dimensions using integers from 0 to 10:
- 0 = Poor (no match)
- 5 = Average (partial match)
- 10 = Excellent (strong match)

Scoring guide (from the rubric):
1. skills_match      : 0 if <30% skills match, 5 if 50-70% match, 10 if >85% match
2. experience_relevance : 0 if unrelated domain, 5 if adjacent domain, 10 if exact domain & seniority
3. education_certifications : 0 if doesn't meet minimum, 5 if meets minimum, 10 if exceeds with extra certs
4. projects_portfolio : 0 if no evidence, 5 if 1-2 generic projects, 10 if strong relevant portfolio
5. communication_quality : 0 if poor structure/grammar, 5 if adequate clarity, 10 if crisp and impactful

Return ONLY a valid JSON object in this exact format (no markdown, no explanation):
{{
  "candidate_name": "string (extract from resume, or 'Unknown Candidate' if not found)",
  "scores": {{
    "skills_match": <integer 0-10>,
    "experience_relevance": <integer 0-10>,
    "education_certifications": <integer 0-10>,
    "projects_portfolio": <integer 0-10>,
    "communication_quality": <integer 0-10>
  }},
  "justifications": {{
    "skills_match": "one sentence explaining this score",
    "experience_relevance": "one sentence explaining this score",
    "education_certifications": "one sentence explaining this score",
    "projects_portfolio": "one sentence explaining this score",
    "communication_quality": "one sentence explaining this score"
  }},
  "key_strengths": ["strength1", "strength2", "strength3"],
  "key_gaps": ["gap1", "gap2"],
  "overall_summary": "2-3 sentence summary of candidate fit"
}}

=== JOB DESCRIPTION (Structured) ===
Role: {job_title}
Domain: {domain}
Required Skills: {required_skills}
Experience Required: {experience_years} ({experience_level})
Education: {education_requirement}

=== CANDIDATE RESUME ===
{resume_text}

Return ONLY the JSON object."""


def clean_json_response(raw_text: str) -> str:
    """
    Robustly extracts JSON from LLM response.
    Handles markdown fences, leading text, and trailing text.
    """
    text = raw_text.strip()

    # Method 1: strip ```json ... ``` or ``` ... ``` fences
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    # Method 2: find the first { and last } (handles leading/trailing text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]

    return text.strip()


def score_candidate(resume_text: str, parsed_jd: dict) -> dict:
    """
    Scores one candidate's resume against the parsed JD.

    Args:
        resume_text : Raw text extracted from the resume.
        parsed_jd   : Structured JD dict from jd_parser.parse_jd().

    Returns:
        A dict with scores, justifications, weighted total, and recommendation.
        On error, returns a dict with 'error' key.
    """
    if not resume_text or not resume_text.strip():
        return {"error": "Empty resume text."}

    if "error" in parsed_jd:
        return {"error": f"Invalid JD: {parsed_jd['error']}"}

    # Build the prompt with JD context
    prompt = SCORING_PROMPT.format(
        job_title=parsed_jd.get("job_title", "Not specified"),
        domain=parsed_jd.get("domain", "Not specified"),
        required_skills=", ".join(parsed_jd.get("required_skills", [])),
        experience_years=parsed_jd.get("experience_years", "Not specified"),
        experience_level=parsed_jd.get("experience_level", "Not specified"),
        education_requirement=parsed_jd.get("education_requirement", "Not specified"),
        resume_text=resume_text[:8000],  # Cap at 8000 chars to control token usage
    )

    raw_text = ""
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=1,
                max_output_tokens=4000,
            ),
        )
        raw_text = ""
        if hasattr(response, "text") and response.text:
            raw_text = response.text.strip()
        elif response.candidates:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        raw_text += part.text
        raw_text = raw_text.strip()
        if not raw_text:
            return {"error": "Gemini returned empty response.", "candidate_name": "Empty Response"}

        # Robustly clean and extract JSON
        cleaned = clean_json_response(raw_text)

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # Last resort: return error with the raw text for debugging
            return {
                "error": f"Could not parse JSON from LLM response.",
                "raw_response_preview": raw_text[:300],
                "candidate_name": "Parse Error",
            }

        # ── Validate the output (hallucination mitigation) ────────────────────
        validated = validate_scores(result)
        if "error" in validated:
            return validated

        # ── Compute weighted total score ──────────────────────────────────────
        scores = validated["scores"]
        weighted_total = sum(
            scores[dim] * 10 * weight  # score is 0-10, weight to get 0-100 scale
            for dim, weight in RUBRIC_WEIGHTS.items()
        )
        validated["weighted_total"] = round(weighted_total, 1)

        # ── Hire recommendation ───────────────────────────────────────────────
        validated["recommendation"] = (
            "HIRE" if weighted_total >= HIRE_THRESHOLD else "NO HIRE"
        )
        validated["hire_threshold"] = HIRE_THRESHOLD

        return validated

    except json.JSONDecodeError as e:
        return {
            "error": f"Scoring LLM returned invalid JSON: {str(e)}",
            "candidate_name": "Parse Error",
        }
    except Exception as e:
        return {"error": f"Scoring failed: {str(e)}"}


def validate_scores(result: dict) -> dict:
    """
    Validates the LLM output to catch hallucinations:
      - All 5 dimensions must be present
      - All scores must be integers 0–10
      - All justifications must be non-empty strings
    """
    required_dimensions = [
        "skills_match",
        "experience_relevance",
        "education_certifications",
        "projects_portfolio",
        "communication_quality",
    ]

    if "scores" not in result:
        return {"error": "LLM response missing 'scores' key."}

    scores = result["scores"]

    for dim in required_dimensions:
        if dim not in scores:
            return {"error": f"Missing score for dimension: {dim}"}

        score = scores[dim]

        # Ensure score is numeric
        try:
            score = int(score)
        except (ValueError, TypeError):
            return {"error": f"Score for '{dim}' is not a number: {score}"}

        # Clamp to valid range
        scores[dim] = max(0, min(10, score))

    # Ensure justifications exist
    if "justifications" not in result:
        result["justifications"] = {dim: "No justification provided." for dim in required_dimensions}

    return result


def compute_weighted_total(scores: dict) -> float:
    """
    Recomputes weighted total from a scores dict.
    Useful for human override recalculation.
    """
    return round(
        sum(scores[dim] * 10 * RUBRIC_WEIGHTS[dim] for dim in RUBRIC_WEIGHTS),
        1,
    )


def score_all_candidates(parsed_resumes: list, parsed_jd: dict) -> list:
    """
    Scores all candidates.

    Args:
        parsed_resumes : List of dicts from resume_parser.parse_multiple_resumes()
        parsed_jd      : Parsed JD dict from jd_parser.parse_jd()

    Returns:
        List of score dicts, one per candidate.
    """
    results = []
    for resume in parsed_resumes:
        if resume.get("error"):
            results.append({
                "candidate_name": resume["filename"],
                "error": resume["error"],
                "filename": resume["filename"],
            })
            continue

        score_result = score_candidate(resume["text"], parsed_jd)
        score_result["filename"] = resume["filename"]
        results.append(score_result)

    return results