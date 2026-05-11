"""
ranker.py
=========
Sorts scored candidates into a ranked shortlist.

Takes the list of score dicts from scorer.py and returns:
  - A sorted list (highest score first)
  - A pandas DataFrame for display
  - Separate hire / no-hire lists


  "The ranker is intentionally kept separate from the scorer.
   This makes it easy to change the ranking logic — for example,
   adding tie-breaking rules or filtering by minimum dimension
   scores — without touching the scoring code."
"""

import pandas as pd
from modules.scorer import RUBRIC_WEIGHTS


def rank_candidates(scored_candidates: list) -> list:
    """
    Sorts candidates by weighted_total score (descending).
    Candidates with errors are pushed to the bottom.

    Args:
        scored_candidates : List of score dicts from scorer.score_all_candidates()

    Returns:
        Sorted list with a 'rank' field added to each dict.
    """
    # A valid candidate must have weighted_total AND a real scores dict
    valid = [
        c for c in scored_candidates
        if "weighted_total" in c
        and "scores" in c
        and isinstance(c.get("scores"), dict)
        and len(c["scores"]) == 5
    ]
    errors = [c for c in scored_candidates if c not in valid]

    # Sort valid candidates by weighted total, descending
    valid_sorted = sorted(valid, key=lambda x: x.get("weighted_total", 0), reverse=True)

    # Add rank field
    for i, candidate in enumerate(valid_sorted, start=1):
        candidate["rank"] = i

    # Errors get no rank
    for candidate in errors:
        candidate["rank"] = None

    return valid_sorted + errors


def build_summary_dataframe(ranked_candidates: list) -> pd.DataFrame:
    """
    Builds a clean DataFrame for display in Streamlit.

    Columns:
        Rank, Candidate, Skills, Experience, Education,
        Projects, Communication, Total Score, Recommendation
    """
    rows = []

    for c in ranked_candidates:
        if "error" in c and "weighted_total" not in c:
            rows.append({
                "Rank": "—",
                "Candidate": c.get("filename", "Unknown"),
                "Skills (30%)": "—",
                "Experience (25%)": "—",
                "Education (15%)": "—",
                "Projects (20%)": "—",
                "Communication (10%)": "—",
                "Total /100": "Error",
                "Recommendation": "⚠️ Parse Error",
            })
            continue

        scores = c.get("scores", {})
        rows.append({
            "Rank": c.get("rank", "—"),
            "Candidate": c.get("candidate_name", "Unknown"),
            "Skills (30%)": f"{scores.get('skills_match', 0)}/10",
            "Experience (25%)": f"{scores.get('experience_relevance', 0)}/10",
            "Education (15%)": f"{scores.get('education_certifications', 0)}/10",
            "Projects (20%)": f"{scores.get('projects_portfolio', 0)}/10",
            "Communication (10%)": f"{scores.get('communication_quality', 0)}/10",
            "Total /100": c.get("weighted_total", 0),
            "Recommendation": (
                "✅ HIRE" if c.get("recommendation") == "HIRE" else "❌ NO HIRE"
            ),
        })

    return pd.DataFrame(rows)


def apply_override(candidate: dict, overrides: dict, reason: str) -> dict:
    """
    Applies human-in-the-loop score overrides.

    Args:
        candidate : The candidate score dict.
        overrides : Dict of {dimension: new_score} pairs.
        reason    : Text reason for the override (required by the brief).

    Returns:
        Updated candidate dict with override log appended.

    Interview talking point:
      "Human-in-the-loop is a first-class feature. HR can override
       any dimension score, and every change is logged with a timestamp
       and reason — creating an audit trail."
    """
    from modules.scorer import compute_weighted_total
    import datetime

    # Log the original scores before override
    if "override_log" not in candidate:
        candidate["override_log"] = []

    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "reason": reason,
        "original_scores": dict(candidate["scores"]),
        "changes": overrides,
    }

    # Apply overrides
    for dim, new_score in overrides.items():
        if dim in candidate["scores"]:
            clamped = max(0, min(10, int(new_score)))
            candidate["scores"][dim] = clamped

    # Recompute total
    candidate["weighted_total"] = compute_weighted_total(candidate["scores"])
    candidate["recommendation"] = (
        "HIRE" if candidate["weighted_total"] >= 60.0 else "NO HIRE"
    )
    candidate["override_log"].append(log_entry)
    candidate["manually_overridden"] = True

    return candidate


def get_shortlist(ranked_candidates: list, top_n: int = None) -> list:
    """
    Returns only HIRE-recommended candidates.
    Optionally limits to top_n candidates.
    """
    shortlist = [c for c in ranked_candidates if c.get("recommendation") == "HIRE"]
    if top_n:
        shortlist = shortlist[:top_n]
    return shortlist