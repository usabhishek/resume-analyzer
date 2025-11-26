import os
import tempfile
import json
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  
POPPLER_PATH = os.getenv("POPPLER_PATH")     # optional
TESSERACT_CMD = os.getenv("TESSERACT_CMD")   # optional

# Configure Gemini if available
if GENAI_AVAILABLE and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print("Warning: genai.configure failed:", e)
        GENAI_AVAILABLE = False

app = Flask(__name__)
CORS(app)


def extract_text_from_pdf(pdf_path):
    text_parts = []

    # Try direct text extraction first
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

    # OCR fallback
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

    return "\n".join(text_parts).strip()


def analyze_resume_with_gemini(resume_text, job_description=None):
    if not GENAI_AVAILABLE:
        raise RuntimeError("Gemini client not available or GEMINI_API_KEY missing")

    prompt = f"""
    You are an ATS simulator and HR expert. Evaluate the resume against the job description.

    Resume:
    {resume_text}

    Job Description:
    {job_description or "Not provided"}

    Provide output in JSON format:
    {{
      "ats_score": <0-100>,
      "section_scores": {{
        "Skills": <0-100>,
        "Experience": <0-100>,
        "Education": <0-100>
      }},
      "missing_keywords": [],
      "suggestions": []
    }}
    """

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        ai_text = getattr(response, "text", None) or str(response)
        return ai_text
    except Exception as e:
        raise RuntimeError(f"Gemini call failed: {e}")


def make_fallback_analysis():
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
            "Quantify achievements with numbers.",
            "Include relevant keywords from the JD."
        ]
    }



@app.route("/api/analyze", methods=["POST"])
def analyze_resume_endpoint():
    try:
        if "resume" not in request.files:
            return jsonify({"error": "Resume file is required"}), 400

        resume_file = request.files["resume"]
        jd_text = request.form.get("jd", "") or ""

        # Save temp file
        suffix = ".pdf" if resume_file.filename.lower().endswith(".pdf") else ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp_path = tmp.name
        tmp.close()
        resume_file.save(tmp_path)

        resume_text = extract_text_from_pdf(tmp_path) or ""

        # Try Gemini
        ai_data = None
        if GENAI_AVAILABLE and GEMINI_API_KEY:
            try:
                ai_output_text = analyze_resume_with_gemini(resume_text, jd_text)

                try:
                    ai_data = json.loads(ai_output_text)
                except Exception:
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

        if not ai_data:
            api_failed = True
            ai_data = make_fallback_analysis()
        else:
            api_failed = False

        warning = "Gemini API failed — showing limited fallback results." if api_failed else ""
        ai_data["warning"] = warning

        try:
            ai_data["ats_score"] = float(ai_data.get("ats_score", 0))
            for k in ["Skills", "Experience", "Education"]:
                val = ai_data.get("section_scores", {}).get(k, 0)
                if isinstance(val, str):
                    val = "".join(ch for ch in val if (ch.isdigit() or ch == "."))
                ai_data["section_scores"][k] = float(val or 0)
        except Exception:
            pass

        # Attach debug info
        ai_data["debug"] = {
            "resume_text": (resume_text[:2000] + "...") if len(resume_text) > 2000 else resume_text,
            "jd_text": (jd_text[:2000] + "...") if len(jd_text) > 2000 else jd_text
        }

        return jsonify(ai_data), 200

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("Unhandled error in /api/analyze:", tb)
        return jsonify({
            "error": "Internal server error",
            "detail": str(e),
            "trace": tb
        }), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
