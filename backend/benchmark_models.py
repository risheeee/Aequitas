import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
import joblib
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from supabase import create_client
from xgboost import XGBClassifier


load_dotenv()


ADULT_DATA_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data"
COLUMNS = [
    "age",
    "workclass",
    "fnlwgt",
    "education",
    "education_num",
    "marital_status",
    "occupation",
    "relationship",
    "race",
    "sex",
    "capital_gain",
    "capital_loss",
    "hours_per_week",
    "native_country",
    "income",
]


@dataclass
class BenchmarkResult:
    model_name: str
    roc_auc: float
    pr_auc: float
    brier_score: float
    disparate_impact_sex: float
    disparate_impact_race: float
    equal_opportunity_gap_sex: float
    equal_opportunity_gap_race: float
    train_seconds: float
    inference_ms_per_1000: float
    model_artifact_path: str


def _disparate_impact(y_pred: pd.Series, privileged_mask: pd.Series) -> float:
    unpriv_mask = ~privileged_mask

    privileged_rate = float(y_pred[privileged_mask].mean()) if privileged_mask.any() else 0.0
    unpriv_rate = float(y_pred[unpriv_mask].mean()) if unpriv_mask.any() else 0.0

    if privileged_rate <= 1e-9:
        return 1.0
    return unpriv_rate / privileged_rate


def _equal_opportunity_gap(y_true: pd.Series, y_pred: pd.Series, privileged_mask: pd.Series) -> float:
    positive_mask = y_true == 1

    priv_pos = privileged_mask & positive_mask
    unpriv_pos = (~privileged_mask) & positive_mask

    priv_tpr = float(y_pred[priv_pos].mean()) if priv_pos.any() else 0.0
    unpriv_tpr = float(y_pred[unpriv_pos].mean()) if unpriv_pos.any() else 0.0

    return unpriv_tpr - priv_tpr


def _load_dataset() -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    df = pd.read_csv(ADULT_DATA_URL, names=COLUMNS, na_values="?", skipinitialspace=True)
    df = df.dropna().reset_index(drop=True)

    y = df["income"].astype(str).str.strip().isin([">50K", ">50K."]).astype(int)

    sex_privileged = df["sex"].astype(str).str.strip().eq("Male")
    race_privileged = df["race"].astype(str).str.strip().eq("White")

    X = df.drop(columns=["income"]).copy()
    for col in X.select_dtypes(include="object").columns:
        X[col] = X[col].astype("category").cat.codes

    return X, y, sex_privileged, race_privileged


def _measure_inference_ms_per_1000(model, X_test: pd.DataFrame) -> float:
    runs = 10
    t0 = time.perf_counter()
    for _ in range(runs):
        model.predict_proba(X_test)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    per_run_ms = elapsed_ms / runs
    scale = 1000 / max(len(X_test), 1)
    return per_run_ms * scale


def run_benchmark() -> pd.DataFrame:
    X, y, sex_privileged, race_privileged = _load_dataset()

    (
        X_train,
        X_test,
        y_train,
        y_test,
        sex_train,
        sex_test,
        race_train,
        race_test,
    ) = train_test_split(
        X,
        y,
        sex_privileged,
        race_privileged,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    run_id = f"bench-{uuid4()}"
    model_output_dir = os.path.join(os.path.dirname(__file__), "model", "candidates", run_id)
    os.makedirs(model_output_dir, exist_ok=True)

    models = {
        "logistic_regression": LogisticRegression(max_iter=1000, random_state=42),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=14,
            random_state=42,
            n_jobs=-1,
        ),
        "gradient_boosting": GradientBoostingClassifier(random_state=42),
        "xgboost": XGBClassifier(
            n_estimators=400,
            max_depth=9,
            learning_rate=0.1,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=-1,
            eval_metric="logloss",
        ),
    }

    results: list[BenchmarkResult] = []

    for model_name, model in models.items():
        print(f"Training {model_name}...")
        train_start = time.perf_counter()
        model.fit(X_train, y_train)
        train_seconds = time.perf_counter() - train_start

        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        artifact_path = os.path.join(model_output_dir, f"{model_name}.pkl")
        joblib.dump(model, artifact_path)

        result = BenchmarkResult(
            model_name=model_name,
            roc_auc=float(roc_auc_score(y_test, y_prob)),
            pr_auc=float(average_precision_score(y_test, y_prob)),
            brier_score=float(brier_score_loss(y_test, y_prob)),
            disparate_impact_sex=float(_disparate_impact(pd.Series(y_pred), sex_test.reset_index(drop=True))),
            disparate_impact_race=float(_disparate_impact(pd.Series(y_pred), race_test.reset_index(drop=True))),
            equal_opportunity_gap_sex=float(
                _equal_opportunity_gap(
                    y_test.reset_index(drop=True),
                    pd.Series(y_pred),
                    sex_test.reset_index(drop=True),
                )
            ),
            equal_opportunity_gap_race=float(
                _equal_opportunity_gap(
                    y_test.reset_index(drop=True),
                    pd.Series(y_pred),
                    race_test.reset_index(drop=True),
                )
            ),
            train_seconds=float(train_seconds),
            inference_ms_per_1000=float(_measure_inference_ms_per_1000(model, X_test)),
            model_artifact_path=os.path.abspath(artifact_path),
        )
        results.append(result)

    leaderboard = pd.DataFrame([vars(r) for r in results]).sort_values(
        by=["roc_auc", "pr_auc"], ascending=False
    )
    leaderboard.insert(0, "run_id", run_id)
    leaderboard.insert(1, "created_at", datetime.now(timezone.utc).isoformat())
    return leaderboard


def persist_benchmark_to_supabase(leaderboard: pd.DataFrame, run_id: str, created_at: str) -> None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_KEY", "").strip()
    if not supabase_url or not supabase_key:
        print("Skipping Supabase benchmark persistence: missing SUPABASE_URL/SUPABASE_KEY")
        return

    try:
        supabase = create_client(supabase_url, supabase_key)
        records = []
        for row in leaderboard.to_dict(orient="records"):
            records.append(
                {
                    **row,
                }
            )

        supabase.table("model_benchmarks").insert(records).execute()
        print(f"Persisted {len(records)} benchmark rows to Supabase table 'model_benchmarks'")
    except Exception as exc:
        print(
            "Could not persist benchmark rows to Supabase table 'model_benchmarks'. "
            f"Create the table first if needed. Error: {exc}"
        )


def main() -> None:
    leaderboard = run_benchmark()
    run_id = str(leaderboard.iloc[0]["run_id"])
    created_at = str(leaderboard.iloc[0]["created_at"])

    output_dir = os.path.join(os.path.dirname(__file__), "model")
    os.makedirs(output_dir, exist_ok=True)

    csv_path = os.path.join(output_dir, "benchmark_results.csv")
    md_path = os.path.join(output_dir, "benchmark_results.md")

    leaderboard.to_csv(csv_path, index=False)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Model Benchmark Leaderboard\n\n")
        f.write(leaderboard.to_markdown(index=False))
        f.write("\n")

    print("\nBenchmark complete. Leaderboard:\n")
    print(leaderboard.to_string(index=False))
    print(f"\nSaved CSV: {csv_path}")
    print(f"Saved Markdown: {md_path}")

    persist_benchmark_to_supabase(leaderboard, run_id=run_id, created_at=created_at)


if __name__ == "__main__":
    main()
