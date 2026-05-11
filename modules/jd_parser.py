"""
jd_parser.py
============
Parses the Job Description (JD) using Gemini.
Extracts: required skills, experience level, education, and key responsibilities.

The output is a structured dict — not raw LLM text — to reduce hallucination risk.

Interview talking point:
  "The JD parser always returns a consistent JSON structure.
   This prevents hallucinations from propagating downstream —
   if the LLM returns garbage, the JSON parser catches it early."
"""

import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure the Gemini client once at module load
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


# ─── Prompt for JD Parsing ────────────────────────────────────────────────────
JD_PARSE_PROMPT = """You are an expert HR analyst. Analyze the job description below and extract structured information.

Return ONLY a valid JSON object — no markdown, no explanation, no code fences.

Required JSON format:
{{
  "job_title": "string",
  "required_skills": ["skill1", "skill2"],
  "preferred_skills": ["skill1", "skill2"],
  "experience_years": "string (e.g. '3-5 years' or 'not specified')",
  "experience_level": "string (Junior/Mid/Senior/Lead/Not specified)",
  "education_requirement": "string (e.g. 'Bachelor in CS or equivalent')",
  "certifications": ["cert1", "cert2"],
  "key_responsibilities": ["resp1", "resp2"],
  "domain": "string (e.g. 'Software Engineering', 'Data Science')",
  "summary": "string (2 sentences max describing the ideal candidate)"
}}

Job Description:
{jd_text}

Return ONLY the JSON object. No other text."""


def parse_jd(jd_text: str) -> dict:
    """
    Sends the JD to Gemini and returns a structured dict.

    Args:
        jd_text : Raw job description text (already sanitized by validator).

    Returns:
        A dict with keys: job_title, required_skills, preferred_skills,
        experience_years, experience_level, education_requirement,
        certifications, key_responsibilities, domain, summary.
        On failure, returns a dict with an 'error' key.
    """
    if not jd_text or not jd_text.strip():
        return {"error": "Empty job description provided."}

    prompt = JD_PARSE_PROMPT.format(jd_text=jd_text)

    raw_text = ""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")

        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=1,          # gemini-2.5-flash requires temperature=1
                max_output_tokens=2000,
            ),
        )

        # Safely extract text — thinking models sometimes use candidates[] instead of .text
        raw_text = ""
        if hasattr(response, "text") and response.text:
            raw_text = response.text.strip()
        elif response.candidates:
            for cand in response.candidates:
                for part in cand.content.parts:
                    if hasattr(part, "text") and part.text:
                        raw_text += part.text

        raw_text = raw_text.strip()

        if not raw_text:
            return {"error": "Gemini returned empty response for JD parsing."}

        # ── Robustly extract JSON ─────────────────────────────────────────────
        # Handles: markdown fences, thinking text before JSON, trailing text

        text = raw_text

        # Step 1: if there are ``` fences, extract content inside them
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    text = part
                    break

        # Step 2: find the first { and last } to isolate the JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]

        parsed = json.loads(text)
        return parsed

    except json.JSONDecodeError as e:
        return {
            "error": f"LLM returned invalid JSON: {str(e)}",
            "raw_response": raw_text[:300] if raw_text else "N/A",
        }
    except Exception as e:
        return {"error": f"JD parsing failed: {str(e)}"}


def format_jd_summary(parsed_jd: dict) -> str:
    """
    Converts the parsed JD dict into a human-readable summary string.
    Used for display in the Streamlit UI.
    """
    if "error" in parsed_jd:
        return f"⚠️ Parse error: {parsed_jd['error']}"

    lines = [
        f"**Role:** {parsed_jd.get('job_title', 'N/A')}",
        f"**Domain:** {parsed_jd.get('domain', 'N/A')}",
        f"**Experience:** {parsed_jd.get('experience_years', 'N/A')} "
        f"({parsed_jd.get('experience_level', 'N/A')})",
        f"**Education:** {parsed_jd.get('education_requirement', 'N/A')}",
        f"**Required Skills:** {', '.join(parsed_jd.get('required_skills', []))}",
        f"**Summary:** {parsed_jd.get('summary', 'N/A')}",
    ]
    return "\n\n".join(lines)