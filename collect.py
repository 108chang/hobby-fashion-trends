"""NAVER API HUB 검색어/쇼핑 클릭 수집. 검증용 probe는 기존 데이터에 손대지 않습니다.

.env에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET을 저장하세요(절대 Git에 올리지 마세요).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
BASE_URL = "https://naverapihub.apigw.ntruss.com"
START_DATE = "2022-01-01"
END_DATE = "2025-12-31"
TIME_UNIT = "week"


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_products():
    return read_csv(ROOT / "config/products.csv")


def read_activities():
    return json.loads((ROOT / "config/activities.json").read_text(encoding="utf-8"))


def credentials():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not secret or client_id.startswith("YOUR_") or secret.startswith("YOUR_"):
        raise ValueError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 필요합니다. .env 파일을 확인하세요.")
    return client_id, secret


def post_api(path, payload, client_id, secret, session=None):
    ses = session if session is not None else requests.Session()
    headers = {"X-NCP-APIGW-API-KEY-ID": client_id,
               "X-NCP-APIGW-API-KEY": secret,
               "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            resp = ses.post(BASE_URL + path, json=payload, headers=headers, timeout=25)
        except requests.RequestException as exc:
            if attempt == 2:
                raise RuntimeError(f"네트워크 오류: {type(exc).__name__}") from exc
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(2 ** attempt + 2)
            continue
        if not resp.ok:
            # API 응답 전문은 인증정보가 노출될 수 있어 출력하지 않음
            raise RuntimeError(f"API HTTP {resp.status_code} / 경로 {path}. API 권한과 파라미터 확인 필요")
        result = resp.json()
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise ValueError(f"예상하지 못한 응답 구조: {path}")
        return result
    raise RuntimeError(f"API 호출 실패: {path}")


def activity_payload():
    groups = [{"groupName": name, "keywords": kws} for name, kws in read_activities().items()]
    if not 1 <= len(groups) <= 5:
        raise ValueError("검색어 그룹은 최대 5개입니다.")
    if any(not 1 <= len(g["keywords"]) <= 20 for g in groups):
        raise ValueError("그룹당 검색어는 1~20개입니다.")
    return {"startDate": START_DATE, "endDate": END_DATE,
            "timeUnit": TIME_UNIT, "keywordGroups": groups}


def shopping_payload(product, *, time_unit=TIME_UNIT):
    code = str(product["category_id"]).strip()
    if not re.fullmatch(r"\d{8}", code):
        raise ValueError(f"카테고리 코드 확인 필요: {product['product_id']}")
    if time_unit not in ("week", "month", "date"):
        raise ValueError("timeUnit은 date/week/month만 가능합니다.")
    return {"startDate": START_DATE, "endDate": END_DATE,
            "timeUnit": time_unit, "category": code,
            "keyword": [{"name": product["product_id"], "param": [product["keyword"]]}]}


def selected_products(mode):
    products = read_products()
    if mode == "pilot":
        return [p for p in products if p["pilot_enabled"].strip().lower() == "yes"]
    if mode == "full":
        pending = [p["product_id"] for p in products if
                   not p["category_id"] or p["category_status"].strip().lower() != "verified"]
        if pending:
            raise ValueError("전체 수집은 카테고리 수동 검증 후 실행하세요. 미검증: " + ", ".join(pending))
        return products
    raise ValueError("mode는 pilot/full이어야 합니다.")


def write_rows(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_activity(result):
    rows = []
    for item in result["results"]:
        for entry in item.get("data", []):
            rows.append({"week": entry["period"], "activity": item["title"],
                         "search_index": entry["ratio"]})
    return rows


def parse_shopping(result, product):
    rows = []
    for item in result["results"]:
        for entry in item.get("data", []):
            rows.append({"week": entry["period"], "product_id": product["product_id"],
                         "keyword": product["keyword"], "activity": product["activity"],
                         "usage_type": product["usage_type"],
                         "category_id": product["category_id"], "click_index": entry["ratio"]})
    return rows


def expected_periods(time_unit):
    start, end = date.fromisoformat(START_DATE), date.fromisoformat(END_DATE)
    if time_unit == "week":
        first = start - timedelta(days=start.weekday())
        return [(first + timedelta(days=7 * n)).isoformat()
                for n in range(((end - first).days // 7) + 1)]
    if time_unit == "month":
        n = (end.year - start.year) * 12 + end.month - start.month + 1
        return [date(start.year + (start.month - 1 + i) // 12,
                     (start.month - 1 + i) % 12 + 1, 1).isoformat() for i in range(n)]
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def summarize_probe(result, time_unit):
    observed = {}
    for group in result.get("results", []):
        for entry in group.get("data", []):
            observed[str(entry["period"])] = float(entry["ratio"])
    expected = set(expected_periods(time_unit))
    present = expected.intersection(observed)
    vals = list(observed.values())
    return {"observed_periods": len(present), "expected_periods": len(expected),
            "coverage_pct": round(100 * len(present) / len(expected), 2),
            "missing_periods": len(expected - present),
            "nonzero_periods": sum(v > 0 for v in vals),
            "distinct_values": len(set(vals))}


def run_probe(limit):
    """별도 폴더에 시험 결과 기록. 원래 원본/가공 데이터는 변경하지 않음."""
    rows = read_csv(ROOT / "config/probe_candidates.csv")
    if not 1 <= limit <= len(rows):
        raise ValueError(f"--limit는 1~{len(rows)} 사이로 지정하세요.")
    client_id, secret = credentials()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    probe_dir = ROOT / "data/probes" / stamp
    summary = []
    for probe in rows[:limit]:
        probe_id = probe["probe_id"]
        payload = shopping_payload(probe, time_unit=probe["time_unit"])
        row = {key: probe[key] for key in
               ("probe_id", "product_id", "keyword", "category_id", "time_unit", "purpose")}
        print("시험:", probe_id, probe["keyword"], probe["category_id"], probe["time_unit"])
        try:
            result = post_api("/shopping/v1/category/keywords", payload, client_id, secret)
            probe_dir.mkdir(parents=True, exist_ok=True)
            (probe_dir / f"{probe_id}.json").write_text(
                json.dumps({"payload": payload, "response": result}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            row.update({"api_status": "ok", **summarize_probe(result, probe["time_unit"]), "error": ""})
        except (RuntimeError, ValueError, requests.RequestException) as exc:
            row.update({"api_status": "error", "observed_periods": "", "expected_periods": "",
                        "coverage_pct": "", "missing_periods": "", "nonzero_periods": "",
                        "distinct_values": "", "error": str(exc)})
        summary.append(row)
    out = ROOT / "outputs/probe_summary.csv"
    if out.exists():
        backup = ROOT / "outputs/probe_history" / f"probe_summary_{stamp}.csv"
        backup.parent.mkdir(parents=True, exist_ok=True)
        out.replace(backup)
    write_rows(out, list(summary[0].keys()), summary)
    ok = sum(row["api_status"] == "ok" for row in summary)
    print(f"시험 완료: {ok}/{len(summary)}건 정상 응답")
    print("결과:", out)
    print("원본 수집 파일은 변경하지 않았습니다. 커버리지는 카테고리 적합성의 증명이 아닙니다.")
    if not ok:
        raise RuntimeError("정상 응답이 없습니다. probe_summary.csv의 error를 확인하세요.")


def run_collection(mode):
    products = selected_products(mode)
    client_id, secret = credentials()
    processed = ROOT / "data/processed"
    raw = ROOT / "data/raw"
    # 이전 처리 파일이 있다면 백업 후 저장: 기존 분석 결과 소실 방지
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "data/backups" / stamp
    for target in (raw / "activity.json", processed / "activity_trends.csv",
                   processed / "shopping_trends.csv", processed / "collection_manifest.json"):
        if target.exists():
            copy_target = backup / target.relative_to(ROOT)
            copy_target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(target, copy_target)
    for p in products:
        target = raw / f"shopping_{p['product_id']}.json"
        if target.exists():
            copy_target = backup / target.relative_to(ROOT)
            copy_target.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(target, copy_target)
    if backup.exists():
        print("기존 파일 백업:", backup)
    print("기간:", START_DATE, "~", END_DATE, "/", TIME_UNIT)
    print("상품 수:", len(products), "(키워드별 개별 정규화)")
    response = post_api("/search-trend/v1/search", activity_payload(), client_id, secret)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "activity.json").write_text(json.dumps(
        {"payload": activity_payload(), "response": response}, ensure_ascii=False, indent=2), encoding="utf-8")
    activity_rows = parse_activity(response)
    if not activity_rows:
        raise RuntimeError("검색어 트렌드 응답 관측치 0개")
    write_rows(processed / "activity_trends.csv", ["week", "activity", "search_index"], activity_rows)
    shop_rows = []
    for p in products:
        print("수집:", p["product_id"], p["keyword"], "category_id=" + p["category_id"])
        payload = shopping_payload(p)
        result = post_api("/shopping/v1/category/keywords", payload, client_id, secret)
        (raw / f"shopping_{p['product_id']}.json").write_text(
            json.dumps({"payload": payload, "response": result}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        parsed = parse_shopping(result, p)
        if not parsed:
            print("주의: 관측치 0개:", p["product_id"], "누락을 0으로 채우지 않습니다.")
        shop_rows.extend(parsed)
    if not shop_rows:
        raise RuntimeError("쇼핑 데이터 관측치 0개. 카테고리와 키워드를 확인하세요.")
    write_rows(processed / "shopping_trends.csv",
               ["week", "product_id", "keyword", "activity", "usage_type", "category_id", "click_index"],
               shop_rows)
    manifest = {"collected_at_utc": datetime.now(timezone.utc).isoformat(), "mode": mode,
                "period": [START_DATE, END_DATE], "timeUnit": TIME_UNIT,
                "activity_series": len({r["activity"] for r in activity_rows}),
                "product_series": len({r["product_id"] for r in shop_rows}),
                "product_requested": len(products),
                "caution": "상대지수이며 매출/절대 클릭량 아님. 카테고리 코드는 상품별 검증 필요."}
    (processed / "collection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("수집 완료. python analyze.py 실행 권장")


def main():
    parser = argparse.ArgumentParser(description="NAVER 데이터랩 검색 및 쇼핑 지수 수집")
    parser.add_argument("--mode", choices=["dry-run", "probe", "pilot", "full"], default="dry-run")
    parser.add_argument("--limit", type=int, default=6, help="probe 모드에서 시험할 요청 수(기본 6)")
    args = parser.parse_args()
    if args.mode == "dry-run":
        print("인증 없이 실행하는 요청 계획(실제 API 호출 없음)")
        print("활동:", list(read_activities()))
        for p in selected_products("pilot"):
            print(p["product_id"], p["keyword"], p["category_id"], p["category_status"])
        print("probe 후보 요청:", len(read_csv(ROOT / "config/probe_candidates.csv")))
    elif args.mode == "probe":
        run_probe(args.limit)
    else:
        run_collection(args.mode)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError, KeyError, requests.RequestException) as exc:
        print("오류:", exc, file=sys.stderr)
        sys.exit(1)
