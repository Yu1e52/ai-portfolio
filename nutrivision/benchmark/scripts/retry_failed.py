# -*- coding: utf-8 -*-
import json
import os
import ssl
import statistics
import time
import urllib.request
import uuid

ROOT = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
URL = os.environ.get("NUTRIVISION_ANALYZE_URL", "http://127.0.0.1:8000/api/analyze")
CTX = ssl._create_unverified_context()

with open(os.path.join(ROOT, "labels.json"), encoding="utf-8") as f:
    labels = json.load(f)
with open(os.path.join(ROOT, "results.json"), encoding="utf-8") as f:
    results = json.load(f)

KEYWORDS = {
    "pizza": ["披萨", "比萨", "匹萨", "pizza"],
    "burger": ["汉堡", "burger", "堡"],
    "pasta": ["意大利面", "意面", "通心粉", "pasta", "意粉", "螺丝面", "蝴蝶面"],
    "dessert": ["蛋糕", "甜点", "甜品", "冰淇淋", "巧克力", "dessert", "布朗尼", "派",
                "可丽饼", "慕斯", "布丁", "圣代", "甜甜圈", "曲奇", "马卡龙", "提拉米苏", "泡芙", "奶昔"],
    "rice": ["米饭", "炒饭", "咖喱饭", "盖饭", "rice", "饭"],
}


def post(path):
    boundary = "----dsh" + uuid.uuid4().hex
    data = open(path, "rb").read()
    body = (
        ("--" + boundary + "\r\n").encode()
        + b'Content-Disposition: form-data; name="file"; filename="test.jpg"\r\n'
        + b"Content-Type: image/jpeg\r\n\r\n" + data
        + ("\r\n--" + boundary + "--\r\n").encode()
    )
    req = urllib.request.Request(URL, data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    t0 = time.time()
    with urllib.request.urlopen(req, context=CTX, timeout=180) as r:
        return time.time() - t0, json.loads(r.read().decode("utf-8"))


def matched(cat, food):
    food = food or ""
    return any(k.lower() in food.lower() for k in KEYWORDS[cat])


# Retry only fallback/error rows. Pace requests so the upstream model is not rate-limited.
for i, row in enumerate(results, 1):
    bad = row.get("error") or not row.get("food_name") or row.get("food_name") in ("无法识别", "未知食物")
    if not bad:
        continue
    rel = row["file"]
    path = os.path.join(ROOT, "images", rel)
    print(f"retry {rel}", flush=True)
    for attempt in range(2):
        try:
            dt, data = post(path)
            rep = data.get("report", {})
            food = rep.get("food_name", "")
            if food and food not in ("无法识别", "未知食物"):
                row.update({
                    "food_name": food, "confidence": rep.get("confidence"),
                    "calories": rep.get("calories"), "elapsed_sec": round(dt, 3),
                    "match": matched(row["label"], food),
                })
                row.pop("error", None)
                print(f"  ok -> {food} {row['match']}", flush=True)
                break
            print("  still fallback", flush=True)
        except Exception as e:
            row["error"] = repr(e)
            print("  error", repr(e), flush=True)
        time.sleep(8)
    time.sleep(12)

with open(os.path.join(ROOT, "results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

valid = [r for r in results if not r.get("error") and r.get("food_name") not in ("", "无法识别", "未知食物")]
correct = sum(1 for r in valid if r.get("match"))
latencies = [r["elapsed_sec"] for r in valid if r.get("elapsed_sec") is not None]
summary = {
    "total": len(results),
    "valid": len(valid),
    "correct": correct,
    "accuracy": round(correct / len(valid), 4) if valid else None,
    "avg_latency_sec": round(statistics.mean(latencies), 2) if latencies else None,
    "median_latency_sec": round(statistics.median(latencies), 2) if latencies else None,
    "p95_latency_sec": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
    "per_category": {},
}
for cat in KEYWORDS:
    rows = [r for r in valid if r["label"] == cat]
    summary["per_category"][cat] = {
        "total": len(rows),
        "correct": sum(1 for r in rows if r.get("match")),
    }
with open(os.path.join(ROOT, "summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
