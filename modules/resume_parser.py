"""
resume_parser.py
================
Extracts raw text from uploaded PDF and DOCX resume files.

Libraries used:
  - pdfplumber : More accurate PDF text extraction than PyPDF2;
                 handles tables and multi-column layouts better.
  - python-docx : Reads .docx files paragraph by paragraph.

Interview talking point:
  "I used pdfplumber over PyPDF2 because it handles complex resume
   layouts — multi-column PDFs, embedded tables — much more reliably.
   The parser returns a dict with filename, raw text, and any errors,
   so downstream modules always get a consistent structure."
"""

import io
import pdfplumber
from docx import Document


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extracts all text from a PDF file given its raw bytes.
    Joins pages with a separator so page context is preserved.
    """
    text_pages = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text()
                if page_text:
                    text_pages.append(page_text)
    except Exception as e:
        return f"[PDF PARSE ERROR: {str(e)}]"

    if not text_pages:
        return "[No text found in PDF — may be a scanned image]"

    return "\n\n--- PAGE BREAK ---\n\n".join(text_pages)


def extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Extracts all text from a DOCX file given its raw bytes.
    Reads each paragraph and joins them with newlines.
    """
    try:
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        return f"[DOCX PARSE ERROR: {str(e)}]"


def parse_resume(uploaded_file) -> dict:
    """
    Master parser — detects file type and routes to the correct extractor.

    Args:
        uploaded_file : A Streamlit UploadedFile object.

    Returns a dict:
        {
            "filename"  : str,
            "text"      : str,   # Raw extracted text
            "error"     : str,   # Empty string if successful
            "char_count": int
        }
    """
    result = {
        "filename": uploaded_file.name,
        "text": "",
        "error": "",
        "char_count": 0,
    }

    file_bytes = uploaded_file.read()
    file_type = uploaded_file.type

    if file_type == "application/pdf":
        result["text"] = extract_text_from_pdf(file_bytes)
    elif file_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        result["text"] = extract_text_from_docx(file_bytes)
    else:
        result["error"] = f"Unsupported file type: {file_type}"
        return result

    # Check for parse errors embedded in the text
    if result["text"].startswith("[") and "ERROR" in result["text"]:
        result["error"] = result["text"]
        result["text"] = ""
    else:
        result["char_count"] = len(result["text"])

    return result


def parse_multiple_resumes(uploaded_files: list) -> list:
    """
    Parses a list of uploaded resume files.
    Returns a list of result dicts (one per file).

    Skips files that fail validation — errors are logged in the dict.
    """
    results = []
    for f in uploaded_files:
        parsed = parse_resume(f)
        results.append(parsed)
    return results
