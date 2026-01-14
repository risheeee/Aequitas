from fastapi import FastAPI, Depends, BackgroundTasks
from pydantic import BaseModel
import joblib
import pandas as pd
import os
from fastapi.middleware.cors import CORSMiddleware
from .auth import get_current_user
from dotenv import load_dotenv
import sys
from transformers import pipeline
from supabase import create_client, Client
import datetime
import torch

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, "../.env")

load_dotenv(dotenv_path = env_path)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../model/biased_loan_model.pkl")
model = joblib.load(MODEL_PATH)

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Supabase credentials not found :-(")
    sys.exit(1)

supabase: Client = create_client(url, key)

print("loading flan...")
genai_pipe = pipeline("text2text-generation", model = "google/flan-t5-small")

app = FastAPI(title="Aequitas – Biased Decision System", version="1.0")

# CORS config
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

def generate_explaination(decision: int, data: dict):
    if decision == 1:
        return "Application Approved"
    
    prompt = (
        "Explain why the loan was denied for a person with: "
        f"Capital Gain: {data['capital_gain']}, "
        f"Capital Loss: {data['capital_loss']}, "
        f"Hours worked per week: {data['hours_per_week']}."
        "Write a short, but professional rejection sentence."
    )

    output = genai_pipe(prompt, max_length = 50, do_sample= False)
    return output[0]['generated_text']

def log_to_supabase(record: dict):
    try:
        response = supabase.table('decisions').insert(record).execute()
        print("🥵 saved ")
    except Exception as e:
        print(f"🍒 error: {e}")

@app.get("/")
def root():
    return {"status": "Aequitas API running"}

@app.post("/predict")
async def predict(applicant: Applicant, background_tasks: BackgroundTasks):
    
    data = applicant.model_dump()  
    df = pd.DataFrame([data])
    
    df = df[[
        'age', 'workclass', 'fnlwgt', 'education', 'education_num',
        'marital_status', 'occupation', 'relationship', 'race', 'sex',
        'capital_gain', 'capital_loss', 'hours_per_week', 'native_country'
    ]].astype('float64')  

    prob = float(model.predict_proba(df)[0][1])
    decision = int(prob > 0.55)

    explanation_text = generate_explaination(decision, data)

    db_record = {
        "applicant_id": "SYSTEM_PRODUCER",
        "age": data["age"],
        "race": data["race"],
        "sex": data["sex"],
        "decision": decision,
        "probability": round(prob, 4),
        "explanation": explanation_text,
        "created_at": datetime.datetime.now().isoformat()
    }

    background_tasks.add_task(log_to_supabase, db_record)

    return {
        "decision": decision,
        "approval_probability": round(prob, 6),
        "explanation": explanation_text
    }

# protected route
@app.get("/secure-test")
def secure_endpoint(user: dict = Depends(get_current_user)):
    return {
        "message": f"Verified User: {user.get('preferred_username')}",
        "roles": user.get("realm_access", {}).get("roles", []),
        "status": "Authenticated "
    }