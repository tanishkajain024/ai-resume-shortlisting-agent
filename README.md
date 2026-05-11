# 🤖 AI Resume & LinkedIn Shortlisting Agent
### AI Enablement Internship — Task 1

An AI-powered HR screening assistant that ingests a Job Description and multiple
candidate resumes, scores each candidate across a transparent 5-dimension rubric
using Google Gemini, and produces a ranked shortlist report.

---

## 📸 Demo

> Upload your JD → Upload resumes → Click Analyze → Get ranked shortlist with
> scores, justifications, and a downloadable HTML/JSON report.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Streamlit UI                     │
│                      app.py                         │
└──────────┬──────────────────────┬───────────────────┘
           │                      │
    ┌──────▼──────┐        ┌──────▼──────┐
    │  JD Parser  │        │Resume Parser│
    │ jd_parser.py│        │resume_parser│
    └──────┬──────┘        └──────┬──────┘
           │                      │
           └──────────┬───────────┘
                      │
               ┌──────▼──────┐        ┌──────────────┐
               │   Scorer    │◄───────│  Validator   │
               │  scorer.py  │        │ validator.py │
               └──────┬──────┘        └──────────────┘
                      │
               ┌──────▼──────┐
               │   Ranker    │
               │  ranker.py  │
               └──────┬──────┘
                      │
           ┌──────────▼───────────┐
           │   Report Generator   │
           │ report_generator.py  │
           └──────────────────────┘
                   │         │
             HTML Report  JSON Report
```

### Agent Flow (matches internship brief)
1. **Input** — HR uploads JD (text/PDF) + resume files (PDF/DOCX)
2. **Parse** — Gemini extracts structured requirements from JD
3. **Profile** — pdfplumber/python-docx extracts resume text
4. **Score** — Gemini computes 5-dimension rubric score per candidate
5. **Rank** — Candidates sorted by weighted total score
6. **Report** — HTML + JSON shortlist report generated
7. **Override** — HR can adjust any score; change logged with reason

---

## 📋 Scoring Rubric

| Dimension | Weight | 0 — Poor | 5 — Average | 10 — Excellent |
|---|---|---|---|---|
| Skills Match | 30% | <30% match | 50–70% match | >85% match |
| Experience Relevance | 25% | Unrelated domain | Adjacent domain | Exact domain & seniority |
| Education & Certs | 15% | Doesn't meet minimum | Meets minimum | Exceeds + extra certs |
| Projects / Portfolio | 20% | No evidence | 1–2 generic | Strong relevant portfolio |
| Communication Quality | 10% | Poor grammar | Adequate clarity | Crisp and impactful |

**Hire threshold:** Total weighted score ≥ 60/100

---

## 🛠️ Tech Stack & Decision Log

### LLM
**Model:** `gemini-1.5-flash` (Google Generative AI)

**Why Gemini 1.5 Flash over alternatives:**
- Free tier: ~60 requests/minute — sufficient for a student project
- 1M token context window — can handle long resumes without chunking
- JSON mode support — reduces hallucination risk
- No credit card required for free tier (unlike GPT-4o)
- Gemini 1.5 Pro is available as a drop-in upgrade for production

### Agent Framework
**Framework:** LangChain + google-generativeai (direct)

**Architecture pattern:** Sequential chain (not ReAct/multi-agent)
- JD Parse → Resume Extract → Score → Rank → Report
- Each step is a separate module function — easy to test and replace
- LangChain used for prompt templating and output parsing structure
- Direct Gemini SDK used for the scoring calls (simpler for students)

**Why not CrewAI/AutoGen:** Overkill for a sequential pipeline; harder to debug.

### Embeddings
`sentence-transformers` (all-MiniLM-L6-v2) — available for semantic similarity
enhancement. Currently, scoring is LLM-based; embeddings can be added as a
similarity pre-filter to reduce LLM calls.

### Resume Parsing
`pdfplumber` over PyPDF2:
- Better handling of multi-column PDF layouts (common in resumes)
- Preserves table structure
- More reliable text extraction from modern PDF generators

### Output
- HTML report (Jinja2-style Python f-strings)
- JSON report (structured, machine-readable)
- Streamlit UI with downloadable reports

---

## 🛡️ Security Mitigations

### 1. Prompt Injection Prevention
**Risk:** Malicious resume content overrides LLM scoring instructions.

**Mitigation:**
- `validator.py` scans all input text for 10+ known injection patterns
  (e.g. "ignore previous instructions", "you are now", "jailbreak")
- Resume text is clearly delimited from instructions in the prompt
  using `=== CANDIDATE RESUME ===` markers
- Scoring prompt uses a strict JSON schema — even if injection succeeds,
  the output validator rejects any response not matching the schema
- Text truncated to 8000 chars before sending to LLM

### 2. API Key Protection
**Risk:** API key leaked in source code or version control.

**Mitigation:**
- API key stored exclusively in `.env` file
- `.env` added to `.gitignore` — never committed
- `.env.example` provided as a safe template
- `python-dotenv` loads key at runtime
- Key never appears in any log, output, or UI element

### 3. Data Privacy / PII Handling
**Risk:** Candidate PII (email, phone, ID numbers) logged or stored.

**Mitigation:**
- `redact_pii_for_logs()` in `validator.py` strips emails, phones,
  and Aadhaar-like numbers before any logging
- Resume text processed in memory only — not written to disk
- No database or persistent storage of candidate data
- User is warned that uploaded files may contain PII

### 4. Hallucination Mitigation
**Risk:** LLM returns false scores or fabricated justifications.

**Mitigation:**
- Strict JSON output schema defined in every prompt
- `validate_scores()` in `scorer.py` checks every returned score:
  - All 5 dimensions must be present
  - All scores must be integers in range 0–10
  - Out-of-range scores are clamped, not passed through
- Temperature set to 0.1–0.2 for factual extraction tasks
- Human-in-the-loop override allows HR to correct AI errors

### 5. File Upload Security
**Risk:** Malicious files uploaded (wrong type, oversized, path traversal).

**Mitigation:**
- `validate_file()` checks MIME type against allowlist (PDF, DOCX only)
- Maximum file size: 5 MB per file
- Files read into memory only — no disk write, no path traversal risk
- Streamlit's built-in sandboxing provides additional isolation

---

## 📁 Project Structure

```
ai_resume_agent/
├── app.py                    ← Streamlit UI entry point
├── requirements.txt          ← All Python dependencies
├── .env.example              ← API key template (safe to commit)
├── .gitignore                ← Prevents .env from being committed
├── README.md                 ← This file
│
├── modules/
│   ├── __init__.py
│   ├── validator.py          ← Security: injection prevention, file validation
│   ├── resume_parser.py      ← PDF/DOCX text extraction
│   ├── jd_parser.py          ← JD structured extraction via Gemini
│   ├── scorer.py             ← 5-dimension rubric scoring via Gemini
│   ├── ranker.py             ← Sorting, ranking, human override
│   └── report_generator.py  ← HTML + JSON report generation
│
├── prompts/
│   └── __init__.py           ← Prompt templates (centralized)
│
└── sample_data/
    ├── sample_jd.txt         ← Sample Python Developer JD
    ├── sample_resume_1_strong.txt   ← Strong match candidate
    ├── sample_resume_2_partial.txt  ← Partial match candidate
    └── sample_resume_3_poor.txt     ← Poor match candidate
```

---

## 🚀 Setup & Running Locally

### Prerequisites
- Python 3.9 or higher
- A free [Google Gemini API key](https://makersuite.google.com/app/apikey)

### Step 1 — Clone and enter the project
```bash
git clone https://github.com/YOUR_USERNAME/ai-resume-agent.git
cd ai-resume-agent
```

### Step 2 — Create and activate virtual environment
```bash
python -m venv venv

# Mac / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### Step 3 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 4 — Set up API key
```bash
cp .env.example .env
# Now open .env and replace the placeholder with your actual Gemini API key
```

### Step 5 — Run the app
```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## 🧪 Testing with Sample Data

1. Click **"Load Sample JD"** in the UI to load the Python Developer JD
2. Convert the `.txt` files in `sample_data/` to PDF (or copy-paste into any
   online PDF converter)
3. Upload 3+ resumes and click **Analyze**

For automated testing, paste the sample resume text directly as a `.txt` file
(the app accepts PDF/DOCX — convert with any free tool).

---

## 📊 Sample Output

```json
{
  "report_metadata": {
    "job_title": "Python Backend Developer",
    "total_candidates": 3,
    "shortlisted": 1
  },
  "candidates": [
    {
      "rank": 1,
      "candidate_name": "Priya Sharma",
      "weighted_total": 87.5,
      "recommendation": "HIRE",
      "scores": {
        "skills_match": 9,
        "experience_relevance": 9,
        "education_certifications": 8,
        "projects_portfolio": 9,
        "communication_quality": 8
      }
    }
  ]
}
```

---

## 🎤 Interview Explanation

**"What does your project do?"**
> "It's an AI HR screening assistant. You upload a job description and multiple
> resumes, and it uses Google Gemini to score each candidate on a 5-dimension
> rubric — skills, experience, education, projects, and communication quality.
> It ranks candidates, generates a downloadable report, and includes a
> human-in-the-loop override so HR can adjust AI scores with a logged reason."

**"What was the hardest part?"**
> "Preventing hallucinations. The LLM sometimes returns scores outside the
> valid range or skips dimensions. I solved this with a validation layer
> that checks every returned score before it's used — clamping values to
> 0–10 and rejecting responses with missing fields."

**"How did you handle security?"**
> "Three ways: API keys are in a .env file that's gitignored. All inputs
> are scanned for prompt injection patterns before reaching the LLM.
> And PII is redacted before any logging, so candidate data stays
> in memory only."

---

## 📋 Prompt Design

### JD Parsing Prompt
- Temperature: 0.1 (factual extraction)
- Output: Strict JSON schema with 10 fields
- Guardrail: JSON parse failure returns error dict, not crash

### Scoring Prompt
- Temperature: 0.2 (consistent scoring)
- Output: JSON with scores (0–10), justifications, strengths, gaps
- Guardrail: `validate_scores()` checks every field before use
- Resume text capped at 8000 chars to control token cost

---

## 👨‍💻 Author

Student Internship Project — AI Enablement Program  
Task 1: HR Resume & LinkedIn Shortlisting Agent
