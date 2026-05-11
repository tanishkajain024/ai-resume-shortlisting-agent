"""
app.py
======
AI Resume & LinkedIn Shortlisting Agent
Main Streamlit entry point.

Run with: streamlit run app.py

Architecture:
  app.py (UI only)
    → modules/validator.py     (security)
    → modules/resume_parser.py (file parsing)
    → modules/jd_parser.py     (JD extraction via Gemini)
    → modules/scorer.py        (rubric scoring via Gemini)
    → modules/ranker.py        (sorting + override)
    → modules/report_generator.py (HTML + JSON output)
"""

import streamlit as st
import os
import json
from dotenv import load_dotenv
import pandas as pd

# Load .env FIRST — before any module that needs the API key
load_dotenv()

# ── Module imports ─────────────────────────────────────────────────────────────
from modules.validator import (
    validate_file,
    validate_jd_text,
    sanitize_text,
    contains_injection,
)
from modules.resume_parser import parse_multiple_resumes
from modules.jd_parser import parse_jd, format_jd_summary
from modules.scorer import score_all_candidates, RUBRIC_WEIGHTS
from modules.ranker import rank_candidates, build_summary_dataframe, apply_override, get_shortlist
from modules.report_generator import generate_html_report, generate_json_report


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Resume Screening Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state initialization ───────────────────────────────────────────────
# Streamlit re-runs the whole script on every interaction.
# session_state persists data between re-runs.
if "ranked_candidates" not in st.session_state:
    st.session_state.ranked_candidates = []
if "parsed_jd" not in st.session_state:
    st.session_state.parsed_jd = {}
if "analysis_done" not in st.session_state:
    st.session_state.analysis_done = False


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Configuration")
    st.markdown("---")

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        st.error("⚠️ GOOGLE_API_KEY not found in .env")
        st.code("GOOGLE_API_KEY=your_key_here", language="bash")
        st.markdown(
            "[Get a free Gemini API key →](https://makersuite.google.com/app/apikey)"
        )
    else:
        st.success("✅ Gemini API key loaded")

    st.markdown("---")
    st.markdown("### 📊 Scoring Rubric")
    rubric_data = {
        "Dimension": [
            "Skills Match",
            "Experience",
            "Education & Certs",
            "Projects",
            "Communication",
        ],
        "Weight": ["30%", "25%", "15%", "20%", "10%"],
    }
    st.table(pd.DataFrame(rubric_data))

    st.markdown("---")
    hire_threshold = st.slider(
        "Hire threshold (total /100)",
        min_value=40,
        max_value=80,
        value=60,
        step=5,
        help="Candidates scoring above this are recommended for hire.",
    )

    st.markdown("---")
    st.markdown("### 🛡️ Security Status")
    st.markdown("""
    - ✅ API key via `.env`
    - ✅ Prompt injection scan
    - ✅ File type validation
    - ✅ PII redaction in logs
    - ✅ Structured JSON output
    """)

    st.markdown("---")
    st.markdown("### ℹ️ About")
    st.markdown("""
    **Model:** Gemini 1.5 Flash  
    **Framework:** LangChain + google-generativeai  
    **Internship Task 1** — AI Enablement Brief
    """)


# ── Main Header ────────────────────────────────────────────────────────────────
st.title("🤖 AI Resume Shortlisting Agent")
st.markdown(
    "*Upload a Job Description and candidate resumes. "
    "Get an AI-powered ranked shortlist with transparent scoring.*"
)
st.markdown("---")


# ── STEP 1 & 2: Inputs ────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("📋 Step 1 — Job Description")

    jd_tab1, jd_tab2 = st.tabs(["📝 Paste Text", "📁 Upload File"])

    jd_text = ""
    jd_file = None

    with jd_tab1:
        jd_text_input = st.text_area(
            "Paste the job description:",
            height=280,
            placeholder="We are looking for a Python Backend Developer with experience in FastAPI...",
            key="jd_text_area",
        )
        if jd_text_input:
            jd_text = jd_text_input

    with jd_tab2:
        jd_file = st.file_uploader(
            "Upload JD as PDF",
            type=["pdf"],
            key="jd_file_upload",
        )
        if jd_file:
            st.success(f"✅ {jd_file.name} ({jd_file.size // 1024} KB)")

    # ── Sample Data button ────────────────────────────────────────────────────
    if st.button("📄 Load Sample JD", use_container_width=True):
        try:
            with open("sample_data/sample_jd.txt", "r") as f:
                st.session_state["sample_jd"] = f.read()
            st.info("Sample JD loaded. Switch to 'Paste Text' tab — it's pre-filled below.")
        except FileNotFoundError:
            st.warning("sample_data/sample_jd.txt not found.")

    if "sample_jd" in st.session_state and not jd_text:
        jd_text = st.session_state["sample_jd"]
        st.text_area(
            "Sample JD (read-only preview):",
            value=jd_text[:500] + "...",
            height=100,
            disabled=True,
        )

with col2:
    st.subheader("📄 Step 2 — Upload Resumes")
    resume_files = st.file_uploader(
        "Upload candidate resumes (PDF or DOCX):",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        key="resume_upload",
    )

    if resume_files:
        st.markdown(f"**{len(resume_files)} resume(s) ready:**")
        for f in resume_files:
            # Validate each file
            valid, msg = validate_file(f)
            if valid:
                st.markdown(f"- ✅ {f.name} ({f.size // 1024} KB)")
            else:
                st.markdown(f"- ❌ {f.name} — {msg}")

    st.markdown("---")
    st.markdown("**No resumes to upload? Use sample data:**")
    st.info(
        "Place `.txt` files with resume text in `sample_data/` folder. "
        "The app reads `.pdf` and `.docx` — for testing, "
        "convert the provided `.txt` samples to PDF."
    )


# ── STEP 3: Analyze button ────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🚀 Step 3 — Run Analysis")

btn_col, warn_col = st.columns([1, 3])

with btn_col:
    analyze_clicked = st.button(
        "🚀 Analyze Candidates",
        type="primary",
        use_container_width=True,
        disabled=(not api_key),
    )

with warn_col:
    if not api_key:
        st.error("Add GOOGLE_API_KEY to your .env file first.")
    elif not jd_text and not jd_file:
        st.warning("Add a Job Description in Step 1.")
    elif not resume_files:
        st.warning("Upload at least one resume in Step 2.")
    else:
        st.success(f"✅ Ready to analyze {len(resume_files)} candidate(s).")


# ── Analysis Logic ─────────────────────────────────────────────────────────────
if analyze_clicked:
    errors_found = []

    # ── Validate JD ──────────────────────────────────────────────────────────
    if jd_file:
        # Parse JD from uploaded PDF
        from modules.resume_parser import extract_text_from_pdf
        jd_text = extract_text_from_pdf(jd_file.read())

    jd_valid, jd_err = validate_jd_text(jd_text)
    if not jd_valid:
        st.error(f"❌ JD Error: {jd_err}")
        st.stop()

    # Sanitize JD
    jd_text_clean = sanitize_text(jd_text)

    # ── Validate resumes ──────────────────────────────────────────────────────
    if not resume_files:
        st.error("❌ Please upload at least one resume.")
        st.stop()

    valid_resume_files = []
    for f in resume_files:
        ok, msg = validate_file(f)
        if ok:
            valid_resume_files.append(f)
        else:
            errors_found.append(f"⚠️ Skipped {f.name}: {msg}")

    if not valid_resume_files:
        st.error("❌ No valid resume files to process.")
        st.stop()

    if errors_found:
        for e in errors_found:
            st.warning(e)

    # ── Run the pipeline ──────────────────────────────────────────────────────
    progress = st.progress(0, text="Starting analysis...")

    # Step A: Parse JD
    progress.progress(10, text="🔍 Parsing Job Description with Gemini...")
    parsed_jd = parse_jd(jd_text_clean)

    if "error" in parsed_jd:
        st.error(f"❌ JD Parsing failed: {parsed_jd['error']}")
        st.stop()

    progress.progress(30, text="📄 Extracting text from resumes...")

    # Step B: Parse resumes
    parsed_resumes = parse_multiple_resumes(valid_resume_files)

    progress.progress(50, text="🤖 Scoring candidates with AI rubric...")

    # Step C: Score all candidates
    scored = score_all_candidates(parsed_resumes, parsed_jd)

    progress.progress(80, text="📊 Ranking and building report...")

    # Step D: Rank
    ranked = rank_candidates(scored)

    # Save to session state
    st.session_state.ranked_candidates = ranked
    st.session_state.parsed_jd = parsed_jd
    st.session_state.analysis_done = True

    progress.progress(100, text="✅ Analysis complete!")
    st.success(f"✅ Analyzed {len(valid_resume_files)} candidate(s) successfully!")


# ── RESULTS ───────────────────────────────────────────────────────────────────
if st.session_state.analysis_done and st.session_state.ranked_candidates:
    ranked = st.session_state.ranked_candidates
    parsed_jd = st.session_state.parsed_jd

    st.markdown("---")
    st.header("📊 Results")

    # ── JD Summary ────────────────────────────────────────────────────────────
    with st.expander("📋 Parsed Job Description", expanded=False):
        st.markdown(format_jd_summary(parsed_jd))
        st.json(parsed_jd)

    # ── Summary stats ─────────────────────────────────────────────────────────
    valid_results = [c for c in ranked if "weighted_total" in c]
    hire_count = sum(1 for c in valid_results if c.get("recommendation") == "HIRE")
    nohire_count = len(valid_results) - hire_count

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Analyzed", len(valid_results))
    m2.metric("✅ Hire", hire_count)
    m3.metric("❌ No Hire", nohire_count)
    top_score = max((c.get("weighted_total", 0) for c in valid_results), default=0)
    m4.metric("Top Score", f"{top_score}/100")

    # ── Ranked Table ─────────────────────────────────────────────────────────
    st.markdown("### 🏆 Ranked Shortlist")
    df = build_summary_dataframe(ranked)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Individual Candidate Cards ────────────────────────────────────────────
    st.markdown("### 👤 Candidate Details")

    for candidate in valid_results:
        rec = candidate.get("recommendation", "NO HIRE")
        total = candidate.get("weighted_total", 0)
        name = candidate.get("candidate_name", "Unknown")
        icon = "✅" if rec == "HIRE" else "❌"

        with st.expander(
            f"{icon} Rank #{candidate.get('rank')} — {name} — {total}/100",
            expanded=(candidate.get("rank") == 1),
        ):
            scores = candidate.get("scores", {})
            justifications = candidate.get("justifications", {})

            # Score bars
            score_cols = st.columns(5)
            dim_names = [
                ("skills_match", "Skills\n(30%)"),
                ("experience_relevance", "Experience\n(25%)"),
                ("education_certifications", "Education\n(15%)"),
                ("projects_portfolio", "Projects\n(20%)"),
                ("communication_quality", "Communication\n(10%)"),
            ]
            for col, (dim, label) in zip(score_cols, dim_names):
                col.metric(label, f"{scores.get(dim, 0)}/10")

            # Justifications table
            st.markdown("**📝 Score Justifications:**")
            just_data = {
                "Dimension": [],
                "Score": [],
                "Justification": [],
            }
            for dim, label in dim_names:
                just_data["Dimension"].append(label.replace("\n", " "))
                just_data["Score"].append(f"{scores.get(dim, 0)}/10")
                just_data["Justification"].append(justifications.get(dim, "N/A"))
            st.table(pd.DataFrame(just_data))

            # Strengths and gaps
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**💪 Key Strengths:**")
                for s in candidate.get("key_strengths", []):
                    st.markdown(f"- ✓ {s}")
            with c2:
                st.markdown("**⚠️ Key Gaps:**")
                for g in candidate.get("key_gaps", []):
                    st.markdown(f"- ✗ {g}")

            st.markdown(f"**💬 Summary:** {candidate.get('overall_summary', 'N/A')}")

            # ── Human-in-the-loop Override ────────────────────────────────────
            st.markdown("---")
            st.markdown("**🧑‍⚖️ Human Override** *(optional — adjust AI scores)*")

            if candidate.get("manually_overridden"):
                log = candidate["override_log"][-1]
                st.warning(
                    f"⚠️ Override applied on {log['timestamp'][:10]}: {log['reason']}"
                )

            with st.form(key=f"override_form_{candidate.get('filename', name)}"):
                ov_cols = st.columns(5)
                overrides = {}
                dim_keys = [d[0] for d in dim_names]
                for col, dim in zip(ov_cols, dim_keys):
                    current = scores.get(dim, 0)
                    short = dim.replace("_", " ").title().split(" ")[0]
                    new_val = col.number_input(
                        short,
                        min_value=0,
                        max_value=10,
                        value=current,
                        step=1,
                        key=f"{dim}_{name}",
                    )
                    if new_val != current:
                        overrides[dim] = new_val

                override_reason = st.text_input(
                    "Reason for override (required if changing scores):",
                    placeholder="e.g. Candidate has relevant unpublished experience",
                )

                submitted = st.form_submit_button("💾 Apply Override")
                if submitted and overrides:
                    if not override_reason.strip():
                        st.error("Please provide a reason for the override.")
                    else:
                        # Find and update this candidate in session state
                        for i, c in enumerate(st.session_state.ranked_candidates):
                            if c.get("filename") == candidate.get("filename"):
                                st.session_state.ranked_candidates[i] = apply_override(
                                    c, overrides, override_reason
                                )
                                st.success("✅ Override applied. Re-ranking...")
                                # Re-rank after override
                                st.session_state.ranked_candidates = rank_candidates(
                                    st.session_state.ranked_candidates
                                )
                                st.rerun()

    # ── Download Reports ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📥 Download Reports")

    dl1, dl2 = st.columns(2)

    with dl1:
        html_report = generate_html_report(ranked, parsed_jd)
        st.download_button(
            label="📄 Download HTML Report",
            data=html_report,
            file_name="shortlist_report.html",
            mime="text/html",
            use_container_width=True,
        )

    with dl2:
        json_report = generate_json_report(ranked, parsed_jd)
        st.download_button(
            label="📋 Download JSON Report",
            data=json_report,
            file_name="shortlist_report.json",
            mime="application/json",
            use_container_width=True,
        )

    # ── Raw JSON preview ─────────────────────────────────────────────────────
    with st.expander("🔍 View Raw JSON Output"):
        st.json(json.loads(json_report))

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<p style='text-align:center; color:gray; font-size:12px;'>"
    "AI Resume Shortlisting Agent · Student Internship Project · "
    "Powered by Gemini 1.5 Flash + LangChain · "
    "Scores are AI-generated — human review recommended before final decisions."
    "</p>",
    unsafe_allow_html=True,
)
