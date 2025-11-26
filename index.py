import os
import tempfile
import json
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# optional AI client; keep in try/except so server still runs if library missing
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except Exception:
    GENAI_AVAILABLE = False

# PDF / OCR libs
try:
    import pdfplumber
except Exception:
    pdfplumber = None
try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None
try:
    import pytesseract
except Exception:
    pytesseract = None

load_dotenv()

# Read environment variables (do NOT hardcode keys in source)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # your Gemini API key (if present)
POPPLER_PATH = os.getenv("POPPLER_PATH")     # optional, for pdf2image on Windows
TESSERACT_CMD = os.getenv("TESSERACT_CMD")   # optional, e.g. "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

if GENAI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print("Warning: genai.configure failed:", e)
        GENAI_AVAILABLE = False

app = Flask(__name__)
CORS(app)  # allow all origins (for dev). Lock this down in production.

# -------------------------------
# Helpers: PDF text extraction (pdfplumber fallback -> OCR)
# -------------------------------
def extract_text_from_pdf(pdf_path):
    text_parts = []

    # try direct text extraction first (pdfplumber)
    if pdfplumber:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            combined = "\n".join(text_parts).strip()
            if combined:
                return combined
        except Exception as e:
            print("Direct text extraction failed:", e)

    # fallback OCR using pdf2image + pytesseract
    if convert_from_path and pytesseract:
        if TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

        try:
            images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH) \
                     if POPPLER_PATH else convert_from_path(pdf_path)
            for img in images:
                try:
                    page_text = pytesseract.image_to_string(img)
                    if page_text:
                        text_parts.append(page_text)
                except Exception as e:
                    print("pytesseract page OCR failed:", e)
        except Exception as e:
            print("convert_from_path (OCR) failed:", e)

    return ("\n".join(text_parts)).strip()


# -------------------------------
# Analyze resume - call Gemini if available, otherwise fallback
# -------------------------------
def analyze_resume_with_gemini(resume_text, job_description=None):
    """
    Try to call Gemini (google.generativeai). If anything fails, raise exception
    so caller can fallback to a local dummy response.
    """
    if not GENAI_AVAILABLE:
        raise RuntimeError("Gemini client not available or GEMINI_API_KEY missing")

    # Build prompt
    prompt = f"""
    You are an ATS (Applicant Tracking System) simulator and HR expert.
    Evaluate the resume against the given job description (if any).

    Resume:
    {resume_text}

    Job Description:
    {job_description or "Not provided"}

    Provide output in this JSON format only (valid JSON):
    {{
      "ats_score": <overall match score out of 100>,
      "section_scores": {{
        "Skills": <score out of 100>,
        "Experience": <score out of 100>,
        "Education": <score out of 100>
      }},
      "missing_keywords": [<list of important missing keywords>],
      "suggestions": [<list of actionable suggestions>]
    }}
    """

    # The google generative client API surface can vary.
    # We'll try the pattern used in older libs and be tolerant to returned object shapes.
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)  # may raise if API differs
        # response may be an object with .text or __str__
        ai_text = getattr(response, "text", None) or str(response)
        return ai_text
    except Exception as e:
        # bubble up so caller can fall back gracefully
        raise RuntimeError(f"Gemini call failed: {e}")


def make_fallback_analysis():
    # deterministic-ish dummy structure (numbers)
    return {
        "ats_score": random.randint(50, 90),
        "section_scores": {
            "Skills": float(random.randint(50, 90)),
            "Experience": float(random.randint(50, 90)),
            "Education": float(random.randint(50, 90))
        },
        "missing_keywords": ["Python", "SQL", "AWS"],
        "suggestions": [
            "Add cloud skills (AWS/GCP/Azure).",
            "Quantify achievements in Experience (use numbers).",
            "Add relevant keywords from JD to Skills section."
        ]
    }


# -------------------------------
# API endpoint
# -------------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze_resume_endpoint():
    try:
        if "resume" not in request.files:
            return jsonify({"error": "Resume file is required"}), 400

        resume_file = request.files["resume"]
        jd_text = request.form.get("jd", "") or ""

        # Save uploaded file to a temp file (safer than fixed filename)
        suffix = ".pdf" if resume_file.filename.lower().endswith(".pdf") else ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp_path = tmp.name
        tmp.close()
        resume_file.save(tmp_path)

        resume_text = extract_text_from_pdf(tmp_path) or ""

        ai_data = None
        # Try Gemini if available
        if GENAI_AVAILABLE and GEMINI_API_KEY:
            try:
                ai_output_text = analyze_resume_with_gemini(resume_text, jd_text)
                # parse JSON if model returned JSON text
                try:
                    ai_data = json.loads(ai_output_text)
                except Exception:
                    # model may have returned extraneous text -> try to extract JSON substring
                    import re
                    m = re.search(r"(\{[\s\S]*\})", ai_output_text)
                    if m:
                        try:
                            ai_data = json.loads(m.group(1))
                        except Exception:
                            ai_data = None
                    else:
                        ai_data = None
            except Exception as e:
                print("Gemini analysis failed:", e)
                ai_data = None

        # fallback if AI failed or not configured
        if not ai_data:
            ai_data = make_fallback_analysis()

        # Normalize numeric types (ensure floats)
        try:
            ai_data["ats_score"] = float(ai_data.get("ats_score", 0))
            for k in ["Skills", "Experience", "Education"]:
                val = ai_data.get("section_scores", {}).get(k, 0)
                if isinstance(val, str):
                    # try to parse numbers out of strings like "85%"
                    val = "".join(ch for ch in val if (ch.isdigit() or ch == "."))
                ai_data["section_scores"][k] = float(val or 0)
        except Exception:
            pass

        # add debug info, but trim large text
        ai_data["debug"] = {
            "resume_text": (resume_text[:2000] + "...") if len(resume_text) > 2000 else resume_text,
            "jd_text": (jd_text[:2000] + "...") if len(jd_text) > 2000 else jd_text
        }

        return jsonify(ai_data), 200

    except Exception as e:
        # return JSON error with stack info (in dev only)
        import traceback
        tb = traceback.format_exc()
        print("Unhandled error in /api/analyze:", tb)
        return jsonify({"error": "Internal server error", "detail": str(e), "trace": tb}), 500


if __name__ == "__main__":
    # debug True is convenient for development; set to False in production
    app.run(debug=True, host="0.0.0.0", port=5000)
