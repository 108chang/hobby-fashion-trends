"""실제 수집 CSV를 210주 전체 기준으로 검증하고, 완전한 208주에 한해 시차 탐색."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import collect

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/processed"
OUT = ROOT / "outputs"


def all_weeks():
    return pd.DatetimeIndex(pd.to_datetime(collect.expected_periods("week")))


def complete_weeks():
    """2022-01-01~2025-12-31 범위 안에 월~일이 모두 포함되는 주차만 분석."""
    idx = all_weeks()
    start = pd.Timestamp(collect.START_DATE)
    end = pd.Timestamp(collect.END_DATE)
    return idx[(idx >= start) & (idx + pd.Timedelta(days=6) <= end)]


def quality(df, group_col, metric, expected_weeks=None):
    expected_weeks = all_weeks() if expected_weeks is None else pd.DatetimeIndex(expected_weeks)
    records, missing = [], []
    for name, group in df.groupby(group_col, sort=True):
        index = pd.DatetimeIndex(group["week"].dropna().unique())
        measures = pd.to_numeric(group[metric], errors="coerce")
        absent = expected_weeks.difference(index)
        records.append({
            "series": name, "rows": len(group), "unique_weeks": len(index),
            "expected_weeks": len(expected_weeks),
            "missing_week_rows": len(absent),
            "coverage_pct": round(100 * (len(expected_weeks) - len(absent)) / len(expected_weeks), 2),
            "missing_values": int(measures.isna().sum()),
            "out_of_range": int(((measures < 0) | (measures > 100)).fillna(False).sum()),
            "zero_values": int((measures == 0).sum()),
            "distinct_values": int(measures.dropna().nunique()),
            "first_week": str(index.min().date()) if len(index) else "",
            "last_week": str(index.max().date()) if len(index) else "",
        })
        missing += [{"series": name, "week": str(dt.date()),
                     "missing_reason": "API 응답에 주차 없음 (0과 다름)"} for dt in absent]
    return records, missing


def lag_corr(activity, shopping, max_lag=8, min_pairs=52, timeline=None):
    """lag=k는 Corr(activity[t-k], shopping[t]). 미래 정보를 사용하지 않음."""
    a, b = activity.copy(), shopping.copy()
    a.index = pd.to_datetime(a.index)
    b.index = pd.to_datetime(b.index)
    if timeline is None:
        idx = a.index.union(b.index)
        grid = pd.date_range(idx.min(), idx.max(), freq="7D") if len(idx) else pd.DatetimeIndex([])
    else:
        grid = pd.DatetimeIndex(timeline)
    aligned = pd.concat([a.rename("search"), b.rename("click")], axis=1).reindex(grid)
    records = []
    for transform in ("raw", "diff_52weeks"):
        frame = aligned if transform == "raw" else aligned.diff(52)
        for lag in range(max_lag + 1):
            pair = pd.concat([frame["search"].shift(lag), frame["click"]], axis=1).dropna()
            row = {"transform": transform, "lag_weeks": lag, "n_pairs": len(pair),
                   "pearson_r": np.nan, "spearman_r": np.nan}
            if len(pair) >= min_pairs and pair.iloc[:, 0].nunique() > 1 and pair.iloc[:, 1].nunique() > 1:
                row["pearson_r"] = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="pearson")
                row["spearman_r"] = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
            records.append(row)
    return records


def category_audit(shop, product_map, quality_rows):
    """코드/상품 키워드 매칭은 연구자 수동 확인이 필요: 관측치만으로 verified로 변경하지 않음."""
    products = {p["product_id"]: p for p in product_map}
    quality_by_id = {q["series"]: q for q in quality_rows if q["source"] == "shopping"}
    output = []
    for product_id in sorted(products):
        p = products[product_id]
        subset = shop.loc[shop["product_id"] == product_id]
        observed = sorted({str(x) for x in subset["category_id"].dropna()})
        q = quality_by_id.get(product_id, {})
        output.append({
            "product_id": product_id, "activity": p["activity"],
            "usage_type": p["usage_type"], "keyword": p["keyword"],
            "configured_category_id": p["category_id"],
            "observed_category_id": ";".join(observed),
            "category_status": p["category_status"],
            "pilot_enabled": p["pilot_enabled"],
            "rows": len(subset), "missing_week_rows": q.get("missing_week_rows", ""),
            "coverage_pct": q.get("coverage_pct", ""),
            "category_code_match": ("yes" if observed == [p["category_id"]] else "not_checked" if not observed else "no"),
            "manual_review_required": "yes" if p["category_status"] != "verified" else "no",
            "note": p["note"],
        })
    return output


def main():
    actpath, shoppath = DATA / "activity_trends.csv", DATA / "shopping_trends.csv"
    if not actpath.exists() or not shoppath.exists():
        raise FileNotFoundError("기존 수집 데이터가 필요합니다: data/processed/*.csv")
    act = pd.read_csv(actpath, encoding="utf-8-sig", dtype={"activity": "string"})
    shop = pd.read_csv(shoppath, encoding="utf-8-sig", dtype={"product_id": "string", "category_id": "string"})
    for frame in (act, shop):
        frame["week"] = pd.to_datetime(frame["week"], errors="raise")
    if act.duplicated(["week", "activity"]).any():
        raise ValueError("운동 검색 데이터에 주차·운동 중복이 있습니다.")
    if shop.duplicated(["week", "product_id"]).any():
        raise ValueError("쇼핑 데이터에 주차·상품 중복이 있습니다.")
    expected, core = all_weeks(), complete_weeks()
    if act.loc[~act["week"].isin(expected)].shape[0] or shop.loc[~shop["week"].isin(expected)].shape[0]:
        raise ValueError("요청 기간을 벗어난 주차가 존재합니다.")
    aq, am = quality(act, "activity", "search_index", expected)
    sq, sm = quality(shop, "product_id", "click_index", expected)
    quality_rows = [{"source": "search", **q} for q in aq] + [{"source": "shopping", **q} for q in sq]
    missing_rows = ([{"source": "search", **m} for m in am] +
                    [{"source": "shopping", **m} for m in sm])
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(quality_rows).to_csv(OUT / "data_quality.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(missing_rows, columns=["source", "series", "week", "missing_reason"]).to_csv(
        OUT / "missing_weeks.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(category_audit(shop, collect.read_products(), quality_rows)).to_csv(
        OUT / "category_audit.csv", index=False, encoding="utf-8-sig")
    act = act[act["week"].isin(core)]
    shop = shop[shop["week"].isin(core)]
    records = []
    for pid, group in shop.groupby("product_id"):
        activity_name = str(group["activity"].iloc[0])
        a = act.loc[act["activity"] == activity_name].set_index("week")["search_index"]
        b = group.set_index("week")["click_index"]
        for row in lag_corr(a, b, timeline=core):
            records.append({"activity": activity_name, "product_id": pid,
                            "keyword": group["keyword"].iloc[0],
                            "usage_type": group["usage_type"].iloc[0], **row})
    pd.DataFrame(records).to_csv(OUT / "lag_correlations.csv", index=False, encoding="utf-8-sig")
    print(f"품질검사 대상: 전체 {len(expected)}주, 완전 주차 상관분석 {len(core)}주")
    print("전체 누락 주차:", len(missing_rows), "(누락 ≠ 클릭수 0)")
    for fname in ("data_quality.csv", "missing_weeks.csv", "category_audit.csv", "lag_correlations.csv"):
        print("저장:", OUT / fname)
    print("주의: 시차 상관은 탐색적 지표이며 인과·예측력이 검증된 결과가 아닙니다.")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print("오류:", exc, file=sys.stderr)
        sys.exit(1)
