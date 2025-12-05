from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import pandas as pd
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../model/biased_loan_model.pkl")
model = joblib.load(MODEL_PATH)

app = FastAPI(title = "Aequitas - Bias Detection System")

class Applicant(BaseModel):
    age: int
    workclass: int
    fnlwgt: int
    education: int
    education_num: int
    marital_status: int
    occupation: int
    relationship: int
    race: int
    sex: int 
    capital_gain: int
    capital_loss: int 
    hours_per_week: int
    native_country: int 
    income: int

@app.get("/")
def root():
    return {"message": "Aequitas - Bias Detection System"}

@app.post("/predict")
async def predict(applicant: Applicant):
    df = pd.DataFrame([applicant.model_dump()])
    prob = float(model.predict_proba(df)[0][1])
    decision = int(prob > 0.55)
    return {
        "decision": decision,
        "approved_probability": round(prob, 4)
    }
