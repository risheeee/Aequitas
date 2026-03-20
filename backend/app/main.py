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
from pathlib import Path

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
ACTIVE_MODEL_POINTER_PATH = os.path.join(os.path.dirname(__file__), "../model/active_model.json")


def _load_model_from_path(model_path: str):
    return joblib.load(model_path)


def _load_active_model_info() -> dict[str, Any]:
    if os.path.exists(ACTIVE_MODEL_POINTER_PATH):
        try:
            with open(ACTIVE_MODEL_POINTER_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
            selected_path = payload.get("path")
            if selected_path and os.path.exists(selected_path):
                return payload
        except Exception:
            pass

    return {
        "name": "xgboost-default",
        "path": os.path.abspath(MODEL_PATH),
        "run_id": None,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


active_model_info = _load_active_model_info()
model = _load_model_from_path(active_model_info["path"])

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


class ActivateModelRequest(BaseModel):
    model_name: str
    run_id: str | None = None

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
    def _format_factors(contributions: list[float]) -> list[dict[str, Any]]:
        factors: list[dict[str, Any]] = []
        for idx, feature in enumerate(FEATURE_ORDER):
            factors.append(
                {
                    "feature": feature,
                    "label": FEATURE_LABELS.get(feature, feature),
                    "value": float(df.iloc[0][feature]),
                    "contribution": float(contributions[idx]),
                }
            )
        return factors

    # Preferred path for XGBoost models with SHAP-style local contributions.
    try:
        dmatrix = xgb.DMatrix(df, feature_names=FEATURE_ORDER)
        contributions = model.get_booster().predict(dmatrix, pred_contribs=True)[0]
        return _format_factors([float(c) for c in contributions[: len(FEATURE_ORDER)]])
    except Exception:
        pass

    # Model-agnostic fallback: estimate local feature effect via one-feature perturbation.
    try:
        baseline_prob = float(model.predict_proba(df)[0][1])
        local_effects: list[float] = []
        for feature in FEATURE_ORDER:
            perturbed = df.copy()
            perturbed.loc[:, feature] = 0.0
            perturbed_prob = float(model.predict_proba(perturbed)[0][1])
            local_effects.append(baseline_prob - perturbed_prob)

        return _format_factors(local_effects)
    except Exception:
        return []


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


def _load_latest_benchmark_from_csv() -> dict[str, Any] | None:
    csv_path = os.path.join(os.path.dirname(__file__), "../model/benchmark_results.csv")
    if not os.path.exists(csv_path):
        return None

    try:
        benchmark_df = pd.read_csv(csv_path)
        if benchmark_df.empty:
            return None

        top = benchmark_df.sort_values(by=["roc_auc", "pr_auc"], ascending=False).iloc[0].to_dict()
        return {
            "source": "csv",
            "run_id": top.get("run_id"),
            "created_at": top.get("created_at"),
            "best_model": top,
            "models": benchmark_df.to_dict(orient="records"),
        }
    except Exception:
        return None


def _load_latest_benchmark_from_supabase() -> dict[str, Any] | None:
    try:
        latest_run = (
            supabase
            .table("model_benchmarks")
            .select("run_id,created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not latest_run.data:
            return None

        run_id = latest_run.data[0]["run_id"]
        created_at = latest_run.data[0].get("created_at")

        run_rows = (
            supabase
            .table("model_benchmarks")
            .select("*")
            .eq("run_id", run_id)
            .execute()
        )

        if not run_rows.data:
            return None

        rows = sorted(run_rows.data, key=lambda row: (row.get("roc_auc", 0), row.get("pr_auc", 0)), reverse=True)
        return {
            "source": "supabase",
            "run_id": run_id,
            "created_at": created_at,
            "best_model": rows[0],
            "models": rows,
        }
    except Exception:
        return None


def _load_benchmark_for_run_id(run_id: str) -> dict[str, Any] | None:
    if not run_id:
        return None
    try:
        run_rows = (
            supabase
            .table("model_benchmarks")
            .select("*")
            .eq("run_id", run_id)
            .execute()
        )
        if run_rows.data:
            rows = sorted(run_rows.data, key=lambda row: (row.get("roc_auc", 0), row.get("pr_auc", 0)), reverse=True)
            return {
                "source": "supabase",
                "run_id": run_id,
                "created_at": rows[0].get("created_at"),
                "best_model": rows[0],
                "models": rows,
            }
    except Exception:
        pass

    csv_result = _load_latest_benchmark_from_csv()
    if csv_result and str(csv_result.get("run_id")) == str(run_id):
        return csv_result
    return None


def _persist_active_model_info(payload: dict[str, Any]) -> None:
    model_dir = os.path.dirname(ACTIVE_MODEL_POINTER_PATH)
    os.makedirs(model_dir, exist_ok=True)
    with open(ACTIVE_MODEL_POINTER_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f)

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


@app.get("/model-benchmarks/latest")
def get_latest_model_benchmarks():
    result = _load_latest_benchmark_from_supabase() or _load_latest_benchmark_from_csv()
    if not result:
        return {
            "status": "missing",
            "message": "No benchmark data found. Run backend/benchmark_models.py first.",
        }
    return {
        "status": "ok",
        "active_model": active_model_info,
        **result,
    }


@app.get("/models/active")
def get_active_model():
    return {
        "status": "ok",
        "active_model": active_model_info,
    }


@app.get("/models/available")
def get_available_models(run_id: str | None = None):
    snapshot = _load_benchmark_for_run_id(run_id) if run_id else (_load_latest_benchmark_from_supabase() or _load_latest_benchmark_from_csv())
    if not snapshot:
        return {
            "status": "missing",
            "message": "No benchmark data found. Run backend/benchmark_models.py first.",
        }
    return {
        "status": "ok",
        "run_id": snapshot.get("run_id"),
        "created_at": snapshot.get("created_at"),
        "models": snapshot.get("models", []),
        "active_model": active_model_info,
    }


@app.post("/models/activate")
def activate_model(request: ActivateModelRequest, user: dict = Depends(get_current_user)):
    del user
    snapshot = _load_benchmark_for_run_id(request.run_id) if request.run_id else (_load_latest_benchmark_from_supabase() or _load_latest_benchmark_from_csv())
    if not snapshot:
        raise HTTPException(status_code=404, detail="No benchmark snapshot found")

    matches = [row for row in snapshot.get("models", []) if row.get("model_name") == request.model_name]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Model '{request.model_name}' not found in benchmark snapshot")

    model_row = matches[0]
    artifact_path = model_row.get("model_artifact_path")
    if not artifact_path:
        raise HTTPException(status_code=400, detail="Selected model row has no artifact path")
    if not Path(artifact_path).exists():
        raise HTTPException(status_code=404, detail=f"Model artifact not found: {artifact_path}")

    global model, active_model_info
    try:
        model = _load_model_from_path(artifact_path)
        active_model_info = {
            "name": request.model_name,
            "path": str(artifact_path),
            "run_id": snapshot.get("run_id"),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        _persist_active_model_info(active_model_info)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to activate model: {exc}") from exc

    return {
        "status": "ok",
        "message": f"Activated model '{request.model_name}'",
        "active_model": active_model_info,
    }