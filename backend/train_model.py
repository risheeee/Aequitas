import os
import pandas as pd
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier
import joblib

url = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
columns = [
    'age', 'workclass', 'fnlwgt', 'education', 'education_num', 'marital_status', 'occupation', 'relationship', 'race', 'sex', 'capital_gain', 'capital_loss', 'hours_per_week', 'native_country', 'income'
]

df = pd.read_csv(url, names = columns, na_values = '?', skipinitialspace = True)
df = df.dropna()

for col in df.select_dtypes(include = 'object').columns:        # set categorical to codes ()
    df[col] = df[col].astype('category').cat.codes

X = df.drop("income", axis = 1)
y = (df["income"] == 1).astype(int)

X_train, _, y_train, _ = train_test_split(X, y, test_size = 0.2, random_state = 37, stratify = y)

model = XGBClassifier(
    n_estimators=400,
    max_depth=9,
    learning_rate=0.1,
    subsample=0.9,
    colsample_bytree=0.9,
    random_state=42,
    n_jobs=-1,
    eval_metric="logloss"
)

print("Fitting xgb bmodel")
model.fit(X_train, y_train)

model_dir = os.path.join(os.path.dirname(__file__), "model")
os.makedirs(model_dir, exist_ok=True)
model_path = os.path.join(model_dir, "biased_loan_model.pkl")

joblib.dump(model, model_path)

print(f"XGBoost model trained and saved → {model_path}")
print(f"Model has {model.n_features_in_} features and {model.n_estimators} trees")