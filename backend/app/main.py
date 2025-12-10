from fastapi import FastAPI, Depends
from pydantic import BaseModel
import joblib
import pandas as pd
import os
from fastapi.middleware.cors import CORSMiddleware
from .auth import get_current_user

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../model/biased_loan_model.pkl")
model = joblib.load(MODEL_PATH)

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

@app.get("/")
def root():
    return {"status": "Aequitas API running"}

@app.post("/predict")
async def predict(applicant: Applicant):
    
    data = applicant.model_dump()  
    df = pd.DataFrame([data])
    
    df = df[[
        'age', 'workclass', 'fnlwgt', 'education', 'education_num',
        'marital_status', 'occupation', 'relationship', 'race', 'sex',
        'capital_gain', 'capital_loss', 'hours_per_week', 'native_country'
    ]].astype('float64')  

    prob = float(model.predict_proba(df)[0][1])
    decision = int(prob > 0.55)

    return {
        "decision": decision,
        "approval_probability": round(prob, 6)
    }

# protected route
@app.get("/secure-test")
def secure_endpoint(user: dict = Depends(get_current_user)):
    return {
        "message": f"Verified User: {user.get('preferred_username')}",
        "roles": user.get("realm_access", {}).get("roles", []),
        "status": "Authenticated "
    }