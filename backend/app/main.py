from fastapi import FastAPI, Depends, Header, HTTPException, status
from pydantic import BaseModel
import joblib
import pandas as pd
import os
from fastapi.middleware.cors import CORSMiddleware
from .auth import get_current_user
from dotenv import load_dotenv
import sys
from supabase import create_client, Client
import datetime
import redis
import json
import uuid
import xgboost as xgb
from typing import Any
import google.generativeai as genai

EVIDENCE_MARKER = "[EVIDENCE_JSON]"

FEATURE_ORDER = [
    'age', 'workclass', 'fnlwgt', 'education', 'education_num',
    'marital_status', 'occupation', 'relationship', 'race', 'sex',
    'capital_gain', 'capital_loss', 'hours_per_week', 'native_country'
]

FEATURE_LABELS = {
    'age': 'Age',
    'workclass': 'Work Class',
    'fnlwgt': 'Population Weight Proxy',
    'education': 'Education Category',
    'education_num': 'Education Level',
    'marital_status': 'Marital Status',
    'occupation': 'Occupation Category',
    'relationship': 'Relationship Category',
    'race': 'Race Group',
    'sex': 'Sex',
    'capital_gain': 'Capital Gain',
    'capital_loss': 'Capital Loss',
    'hours_per_week': 'Hours Per Week',
    'native_country': 'Native Country Category',
}

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, "../.env")

load_dotenv(dotenv_path = env_path)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../model/biased_loan_model.pkl")
model = joblib.load(MODEL_PATH)

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Supabase credentials not found :-(")
    sys.exit(1)

supabase: Client = create_client(url, key)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
gemini_model = None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL)
        print(f"Gemini explanation model enabled: {GEMINI_MODEL}")
    except Exception as exc:
        gemini_model = None
        print(f"Gemini initialization failed. Falling back to deterministic summary: {exc}")
else:
    print("GEMINI_API_KEY not set. Using deterministic explanation fallback.")

app = FastAPI(title="Aequitas - Biased Decision System", version="1.0")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins = origins,
    allow_credentials = True, 
    allow_methods = ["*"],    
    allow_headers = ["*"],    
)

class Applicant(BaseModel):
    model_config = {"extra": "forbid"}  

    applicant_id: str | None = None

    age: int
    workclass: int
    fnlwgt: int
    education: int
    education_num: int
    marital_status: int = 0
    occupation: int = 0
    relationship: int = 0
    race: int = 0
    sex: int = 0
    capital_gain: int = 0
    capital_loss: int = 0
    hours_per_week: int = 0
    native_country: int = 0

def verify_internal_api_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    required_key = os.getenv("INTERNAL_API_KEY")
    if required_key and required_key.strip().lower() in {"change_me", ""}:
        required_key = None
    if required_key and x_internal_api_key != required_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )


def _compute_feature_contributions(df: pd.DataFrame) -> list[dict[str, Any]]:
    try:
        dmatrix = xgb.DMatrix(df, feature_names=FEATURE_ORDER)
        contributions = model.get_booster().predict(dmatrix, pred_contribs=True)[0]
    except Exception:
        return []

    factors: list[dict[str, Any]] = []
    for idx, feature in enumerate(FEATURE_ORDER):
        factors.append({
            "feature": feature,
            "label": FEATURE_LABELS.get(feature, feature),
            "value": float(df.iloc[0][feature]),
            "contribution": float(contributions[idx]),
        })

    return factors


def _build_grounded_summary(decision: int, prob: float, factors: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if decision == 1:
        ranked = sorted(factors, key=lambda item: item["contribution"], reverse=True)
        selected = [item for item in ranked if item["contribution"] > 0][:3]
        prefix = "The application was approved because the strongest signals supported approval"
    else:
        ranked = sorted(factors, key=lambda item: item["contribution"])
        selected = [item for item in ranked if item["contribution"] < 0][:3]
        prefix = "The application was denied because the strongest signals increased estimated repayment risk"

    if not selected:
        selected = sorted(factors, key=lambda item: abs(item["contribution"]), reverse=True)[:3]

    reasons = [f"{item['label']}={item['value']:.0f}" for item in selected]
    reason_text = "; ".join(reasons) if reasons else "overall feature profile"
    confidence = "high" if abs(prob - 0.55) >= 0.20 else "moderate"

    summary = (
        f"{prefix}: {reason_text}. "
        f"Model probability={prob:.3f} with {confidence} confidence relative to threshold 0.55."
    )
    return summary, selected


def _compose_short_fallback(decision: int, prob: float, selected: list[dict[str, Any]], threshold: float) -> str:
    if not selected:
        return f"{'Approved' if decision == 1 else 'Rejected'} at probability {prob:.3f} against threshold {threshold:.2f}, based on overall feature risk profile."

    short_reasons = ", ".join([f"{item['label']} ({item['value']:.0f})" for item in selected[:2]])
    verdict = "approved" if decision == 1 else "rejected"
    return f"Application {verdict} at probability {prob:.3f} vs threshold {threshold:.2f}, mainly influenced by {short_reasons}."


def _generate_with_gemini(decision: int, prob: float, selected: list[dict[str, Any]], threshold: float) -> str | None:
    if gemini_model is None:
        return None

    evidence_lines = "\n".join(
        [f"- {item['label']}: value={item['value']:.0f}, contribution={item['contribution']:.4f}" for item in selected]
    )
    expected_outcome = "approved" if decision == 1 else "rejected"
    prompt = (
        "Return ONLY valid JSON in one line with this schema: "
        "{\"summary\":\"...\",\"outcome\":\"approved|rejected\"}.\n"
        "Rules for summary: exactly one sentence, 14-26 words, plain English, no markdown, no bullets, "
        "no repeated fragments, no invented factors, and no mention of protected attributes.\n"
        "The outcome field MUST exactly match the decision provided.\n\n"
        f"Decision: {expected_outcome}\n"
        f"Probability: {prob:.3f}\n"
        f"Threshold: {threshold:.2f}\n"
        f"Top factors:\n{evidence_lines if evidence_lines else '- overall feature profile'}"
    )

    try:
        response = gemini_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=80,
            ),
        )
        raw_text = (response.text or "").strip()
        if not raw_text:
            return None

        # Strip optional markdown fences if model adds them.
        candidate = raw_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(candidate)
        outcome = str(parsed.get("outcome", "")).strip().lower()
        summary = str(parsed.get("summary", "")).strip()
        if outcome != expected_outcome:
            return None
        if len(summary) < 40 or len(summary) > 220:
            return None
        words = summary.split()
        if len(words) < 10 or len(words) > 35:
            return None

        # Final sanitization to avoid duplicate punctuation fragments.
        summary = " ".join(summary.split())
        if not summary.endswith((".", "!", "?")):
            summary = f"{summary}."
        return summary
    except Exception:
        return None


def generate_explanation(decision: int, prob: float, data: dict, df: pd.DataFrame) -> tuple[str, list[dict[str, Any]]]:
    factors = _compute_feature_contributions(df)
    _, selected = _build_grounded_summary(decision, prob, factors)
    threshold = 0.55

    candidate = _generate_with_gemini(decision, prob, selected, threshold)
    if candidate:
        return candidate, selected

    return _compose_short_fallback(decision, prob, selected, threshold), selected

def log_to_supabase(record: dict):
    try:
        supabase.table('decisions').insert(record).execute()
        print("🥵 saved ")
    except Exception as e:
        print(f"🍒 error: {e}")


def _serialize_explanation_for_storage(explanation_text: str, selected_factors: list[dict[str, Any]], threshold: float) -> str:
    active_model = GEMINI_MODEL if gemini_model else "deterministic-fallback"
    payload = {
        "top_factors": selected_factors,
        "threshold": threshold,
        "model": active_model,
        "version": "grounded-v1",
    }
    return f"{explanation_text}\n\n{EVIDENCE_MARKER}{json.dumps(payload, separators=(',', ':'))}"

@app.get("/")
def root():
    return {"status": "Aequitas API running"}

@app.post("/predict")
async def predict(applicant: Applicant, _: None = Depends(verify_internal_api_key)):
    
    data = applicant.model_dump()  
    applicant_id = data.get("applicant_id") or str(uuid.uuid4())
    df = pd.DataFrame([data])
    
    df = df[FEATURE_ORDER].astype('float64')

    prob = float(model.predict_proba(df)[0][1])
    decision = int(prob > 0.55)

    explanation_text, selected_factors = generate_explanation(decision, prob, data, df)
    threshold = 0.55
    stored_explanation = _serialize_explanation_for_storage(explanation_text, selected_factors, threshold)

    db_record = {
        "applicant_id": applicant_id,
        "age": data["age"],
        "race": data["race"],
        "sex": data["sex"],
        "decision": decision,
        "probability": round(prob, 4),
        "explanation": stored_explanation,
        "created_at": datetime.datetime.now().isoformat()
    }

    log_to_supabase(db_record)

    return {
        "applicant_id": applicant_id,
        "decision": decision,
        "approval_probability": round(prob, 6),
        "explanation": explanation_text,
        "top_factors": selected_factors,
        "threshold": threshold,
    }

# protected route
@app.get("/secure-test")
def secure_endpoint(user: dict = Depends(get_current_user)):
    return {
        "message": f"Verified User: {user.get('preferred_username')}",
        "roles": user.get("realm_access", {}).get("roles", []),
        "status": "Authenticated "
    }

@app.get("/metrics")
def get_metrics():
    try:
        data = redis_client.get("live_metrics")
        if not data:
            return {"status": "waiting", "message": "No data in Redis yet"}
        
        return json.loads(data)
    except Exception as e:
        return {"error": str(e)}