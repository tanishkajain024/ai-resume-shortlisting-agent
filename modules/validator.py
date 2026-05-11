"""
validator.py
============
Security-first module: validates all inputs before they touch the LLM.

Security mitigations implemented here (as required by the internship brief):
  - Prompt injection prevention (pattern matching)
  - File type and size validation
  - PII redaction for logs
  - Text sanitization

Interview talking point:
  "I built security in from day one — a dedicated validator module
   runs before any input reaches the LLM, blocking injection attempts
   and enforcing file type/size limits."
"""

import re


# ─── Prompt Injection Patterns ────────────────────────────────────────────────
# These are known attack patterns that try to override LLM instructions
INJECTION_PATTERNS = [
    r"ignore (all )?(previous|above|prior) instructions",
    r"disregard (your )?(system prompt|instructions|rules)",
    r"you are now",
    r"act as (a )?(different|new|another|evil)",
    r"forget (everything|all instructions|your instructions)",
    r"jailbreak",
    r"override (your )?(safety|guidelines|instructions)",
    r"new persona",
    r"pretend (you are|to be)",
    r"<\|.*?\|>",          # Special tokens like <|endoftext|>
    r"\[\[.*?\]\]",        # Double-bracket injection
    r"system:\s",          # Fake system message injection
    r"human:\s",           # Fake human message injection
]

# Allowed file MIME types
ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]

MAX_FILE_SIZE_MB = 5
MAX_TEXT_LENGTH = 50_000  # chars — prevents token flooding


def contains_injection(text: str) -> bool:
    """
    Scans text for known prompt injection patterns.
    Returns True if an attack pattern is found.

    Usage: reject any input where this returns True.
    """
    if not text:
        return False
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def sanitize_text(text: str) -> str:
    """
    Cleans raw text before sending to the LLM:
      - Removes control characters
      - Collapses excessive whitespace
      - Truncates to MAX_TEXT_LENGTH to prevent token flooding
    """
    if not text:
        return ""
    # Strip non-printable control characters (keep newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    # Truncate if too long
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "\n\n[... content truncated for safety ...]"
    return text


def validate_file(uploaded_file) -> tuple:
    """
    Validates an uploaded Streamlit file object.
    Returns (is_valid: bool, error_message: str).

    Checks:
      - File is not None
      - MIME type is PDF or DOCX
      - File size <= MAX_FILE_SIZE_MB
    """
    if uploaded_file is None:
        return False, "No file provided."

    if uploaded_file.type not in ALLOWED_MIME_TYPES:
        return False, (
            f"File type '{uploaded_file.type}' is not allowed. "
            "Please upload a PDF or DOCX file."
        )

    size_mb = uploaded_file.size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return False, (
            f"File '{uploaded_file.name}' is {size_mb:.1f} MB. "
            f"Maximum allowed is {MAX_FILE_SIZE_MB} MB."
        )

    return True, ""


def redact_pii_for_logs(text: str) -> str:
    """
    Redacts obvious PII before writing to any log or console output.
    NOTE: The full text IS used for scoring — redaction is only for logs.

    Redacts: email addresses, phone numbers, Aadhaar-like numbers.

    Interview talking point:
      "We keep the full resume data in memory for scoring but redact
       PII before writing to logs, so candidate data isn't accidentally
       persisted in plaintext."
    """
    # Email addresses
    text = re.sub(r"[\w.\-+]+@[\w.\-]+\.\w{2,}", "[EMAIL REDACTED]", text)
    # Phone numbers (Indian and international formats)
    text = re.sub(r"(\+?\d[\d\s\-().]{7,}\d)", "[PHONE REDACTED]", text)
    # Aadhaar (12-digit number blocks)
    text = re.sub(r"\b\d{4}\s?\d{4}\s?\d{4}\b", "[ID REDACTED]", text)
    return text


def validate_jd_text(jd_text: str) -> tuple:
    """
    Validates the job description text input.
    Returns (is_valid: bool, error_message: str).
    """
    if not jd_text or not jd_text.strip():
        return False, "Job description cannot be empty."

    if len(jd_text.strip()) < 50:
        return False, "Job description is too short (minimum 50 characters)."

    if contains_injection(jd_text):
        return False, (
            "The job description contains disallowed content. "
            "Please remove any instruction-like text and try again."
        )

    return True, ""
