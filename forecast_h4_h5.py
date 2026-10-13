r"""NAVER DataLab hobby/fashion: H4/H5 leakage-aware expanding-window evaluation.

Place beside collect.py/analyze.py, then run:
    .\.venv\Scripts\python.exe -m pip install scikit-learn
    .\.venv\Scripts\python.exe forecast_h4_h5.py

Requires data/processed/activity_trends.csv and shopping_trends.csv.
No API requests, credentials, or edits to original collected data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
MIN_TRAIN_ROWS = 40
ALPHA = 10.0
HORIZONS = (1, 4)
EVAL_YEARS = (2024, 2025)
TRAIN_TARGET_START = pd.Timestamp("2023-01-01")
LAST_COMPLETE_WEEK = pd.Timestamp("2025-12-22")


def load_inputs(activity_path: Path, shopping_path: Path):
    a = pd.read_csv(activity_path, parse_dates=["week"], encoding="utf-8-sig")
    s = pd.read_csv(shopping_path, parse_dates=["week"], encoding="utf-8-sig")
    if a.duplicated(["week", "activity"]).any() or s.duplicated(["week", "product_id"]).any():
        raise ValueError("중복된 (week, activity) 또는 (week, product_id)가 존재합니다.")
    if a.search_index.isna().any() or s.click_index.isna().any():
        raise ValueError("관측된 API 지수에 결측값이 존재합니다.")
    meta = s[["product_id", "keyword", "activity", "usage_type"]].drop_duplicates()
    if meta.product_id.duplicated().any():
        raise ValueError("상품 코드마다 일관된 메타데이터가 필요합니다.")
    meta = meta.set_index("product_id")
    idx = pd.date_range(a.week.min(), a.week.max(), freq="W-MON")
    search = a.pivot(index="week", columns="activity", values="search_index").reindex(idx)
    shopping = s.pivot(index="week", columns="product_id", values="click_index").reindex(idx)
    return search, shopping, meta


def make_features(product_id, horizon, activities, search, shopping):
    """All features are observed at origin t; outcome is y(t+horizon)."""
    y = shopping[product_id]
    d = pd.DataFrame(index=shopping.index)
    for lag in (0, 1, 4, 13, 52):
        d[f"click_lag_{lag}"] = y.shift(lag)
    d["click_rolling_4"] = y.rolling(4, min_periods=4).mean()
    d["click_rolling_13"] = y.rolling(13, min_periods=13).mean()
    d["target_week"] = d.index + pd.Timedelta(weeks=horizon)
    week_number = d.target_week.dt.isocalendar().week.astype(float).to_numpy()
    d["week_sin"] = np.sin(2 * np.pi * week_number / 52.1775)
    d["week_cos"] = np.cos(2 * np.pi * week_number / 52.1775)
    for activity in activities:
        x = search[activity]
        for lag in (0, 1, 4):
            d[f"search_{activity}_lag_{lag}"] = x.shift(lag)
        d[f"search_{activity}_mean_4"] = x.rolling(4, min_periods=4).mean()
    d["target"] = y.shift(-horizon)
    d["origin_week"] = d.index
    return d.loc[(d.target_week >= TRAIN_TARGET_START) &
                 (d.target_week <= LAST_COMPLETE_WEEK)].dropna()


def walk_forward(product_id, horizon, feature_activities, search, shopping, year):
    """Re-estimate every week, training only rows whose outcome was known by origin week."""
    base = make_features(product_id, horizon, [], search, shopping)
    expanded = make_features(product_id, horizon, feature_activities, search, shopping)
    common_origins = base.index.intersection(expanded.index)
    base, expanded = base.loc[common_origins], expanded.loc[common_origins]
    no_features = {"origin_week", "target_week", "target"}
    base_cols = [c for c in base if c not in no_features]
    expanded_cols = [c for c in expanded if c not in no_features]
    test = base[base.target_week.dt.year == year]
    out = []
    for origin, test_row in test.iterrows():
        train = base.loc[base.target_week <= test_row.origin_week]
        if len(train) < MIN_TRAIN_ROWS:
            continue
        train_aug = expanded.loc[train.index]

        def estimate(data, cols, training):
            model = make_pipeline(StandardScaler(), Ridge(alpha=ALPHA))
            model.fit(training[cols], training.target)
            return max(0, float(model.predict(data.loc[[origin], cols])[0]))

        forecast_target = test_row.target_week
        seasonal_week = forecast_target - pd.Timedelta(weeks=52)
        seasonal_naive = shopping.at[seasonal_week, product_id] if seasonal_week in shopping.index else np.nan
        out.append({
            "product_id": product_id,
            "horizon_weeks": horizon,
            "evaluation_year": year,
            "origin_week": origin,
            "target_week": forecast_target,
            "observed": float(test_row.target),
            "baseline_pred": estimate(base, base_cols, train),
            "interest_pred": estimate(expanded, expanded_cols, train_aug),
            "seasonal_naive_pred": seasonal_naive,
            "persistence_pred": float(shopping.at[origin, product_id]),
            "train_samples": len(train),
        })
    return pd.DataFrame(out)


def metrics(df, actual="observed", predicted="interest_pred"):
    r = df[[actual, predicted]].dropna()
    if len(r) == 0:
        return {"mae": np.nan, "rmse": np.nan}
    return {
        "mae": float(mean_absolute_error(r[actual], r[predicted])),
        "rmse": float(np.sqrt(mean_squared_error(r[actual], r[predicted]))),
    }


def main():
    parser = argparse.ArgumentParser(description="H4/H5 확장시점 적합성 검증 (2024~2025)")
    parser.add_argument("--activity", type=Path, default=ROOT / "data/processed/activity_trends.csv")
    parser.add_argument("--shopping", type=Path, default=ROOT / "data/processed/shopping_trends.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/modeling")
    args = parser.parse_args()
    search, shopping, meta = load_inputs(args.activity, args.shopping)
    args.out.mkdir(parents=True, exist_ok=True)
    summary_rows, prediction_frames = [], []

    for horizon in HORIZONS:
        for product_id, m in meta.iterrows():
            for year in EVAL_YEARS:
                d = walk_forward(product_id, horizon, [m.activity], search, shopping, year)
                if d.empty:
                    continue
                d["keyword"] = m.keyword
                d["activity"] = m.activity
                d["usage_type"] = m.usage_type
                prediction_frames.append(d)
                b = metrics(d, predicted="baseline_pred")
                x = metrics(d, predicted="interest_pred")
                naive = metrics(d, predicted="seasonal_naive_pred")
                persistence = metrics(d, predicted="persistence_pred")
                summary_rows.append({
                    "product_id": product_id,
                    "keyword": m.keyword,
                    "activity": m.activity,
                    "usage_type": m.usage_type,
                    "horizon_weeks": horizon,
                    "evaluation_year": year,
                    "n_test": len(d),
                    "mae_baseline": b["mae"],
                    "mae_with_interest": x["mae"],
                    "mae_seasonal_naive": naive["mae"],
                    "mae_persistence": persistence["mae"],
                    "rmse_baseline": b["rmse"],
                    "rmse_with_interest": x["rmse"],
                    "rmse_persistence": persistence["rmse"],
                    "mae_improvement_pct": (b["mae"] - x["mae"]) / b["mae"] * 100 if b["mae"] > 0 else np.nan,
                })

    if not summary_rows:
        raise ValueError("결과를 계산할 만큼 충분한 과거 지수가 없습니다.")
    s = pd.DataFrame(summary_rows)
    p = pd.concat(prediction_frames, ignore_index=True)
    s.to_csv(args.out / "h5_model_comparison.csv", index=False, encoding="utf-8-sig")
    p.to_csv(args.out / "h5_weekly_predictions.csv", index=False, encoding="utf-8-sig")

    # H4: Can gym search help *beyond* pilates search on overlapping apparel proxies?
    h4 = []
    shared_candidates = ["PIL_F01", "PIL_F02", "PIL_L01", "PIL_L02"]
    for product_id in shared_candidates:
        if product_id not in meta.index or "필라테스" not in search or "헬스" not in search:
            continue
        for horizon in HORIZONS:
            for year in EVAL_YEARS:
                pil = walk_forward(product_id, horizon, ["필라테스"], search, shopping, year)
                gym = walk_forward(product_id, horizon, ["필라테스", "헬스"], search, shopping, year)
                if pil.empty or gym.empty:
                    continue
                both = pil.merge(gym[["target_week", "interest_pred"]].rename(columns={"interest_pred": "gym_added_pred"}), on="target_week")
                pil_mae = metrics(both, predicted="interest_pred")["mae"]
                plus_mae = metrics(both, predicted="gym_added_pred")["mae"]
                h4.append({
                    "product_id": product_id,
                    "keyword": meta.loc[product_id, "keyword"],
                    "evaluation_year": year,
                    "horizon_weeks": horizon,
                    "n_test": len(both),
                    "mae_pilates_only": pil_mae,
                    "mae_pilates_plus_gym": plus_mae,
                    "gym_incremental_improvement_pct": (pil_mae - plus_mae) / pil_mae * 100 if pil_mae else np.nan,
                })
    pd.DataFrame(h4).to_csv(args.out / "h4_cross_activity.csv", index=False, encoding="utf-8-sig")

    # Reference notes: API ratios are relative, not comparable absolute volumes.
    methodology = {
        "data": "NAVER DataLab weekly relative interest/click indices, not sales",
        "prediction_target": "click ratio in week (origin + horizon)",
        "evaluation_years": EVAL_YEARS,
        "horizons_weeks": HORIZONS,
        "train_start_target": "2023-01-01",
        "train_cutoff_rule": "training label target_week <= current forecast origin_week",
        "rolling_validation": "expanding origin-by-origin model refit",
        "regressor": "StandardScaler + Ridge(alpha=10), fixed a priori",
        "baseline_variables": "product clicks at origin/lag1/4/13/52, trailing rolling 4/13, known target-week sine/cosine seasonality",
        "simple_benchmark": "persistence: assume future click index equals the index observed at prediction origin; seasonal naive: prior-year target-week index",
        "added_variables": "activity search ratio at origin, lag1, lag4, trailing 4-week mean",
        "no_forward_imputation": True,
        "missingness": "rows with missing required lagged features/labels are excluded, report n_test",
        "cautions": [
            "observational index series; no causal interpretation",
            "relative API indices normalized over requested historical range; prospective index scaling may differ",
            "category fit and keyword meaning still provisional",
            "only 51 or fewer evaluated observations per product for 2025; multiple comparisons are exploratory",
            "forecast target observed only after target week closes; origin-week index assumed finalized before prediction",
        ],
    }
    (args.out / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2), encoding="utf-8")
    for h in HORIZONS:
        d = s[(s.evaluation_year == 2025) & (s.horizon_weeks == h)]
        print(f"{h}주 후: 2025년 {int((d.mae_improvement_pct > 0).sum())}/{len(d)}개 상품 개선; "
              f"중앙값 {d.mae_improvement_pct.median():+.1f}% / 지속성 예측보다 우수한 상품 "
              f"{int((d.mae_with_interest < d.mae_persistence).sum())}/{len(d)}개")
    print("결과 폴더:", args.out.resolve())


if __name__ == "__main__":
    main()
