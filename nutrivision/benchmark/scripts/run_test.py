# -*- coding: utf-8 -*-
import json
import os
import ssl
import statistics
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
# 指向已部署或本地启动的服务；本地默认就用 README 里的 8000 端口
URL = os.environ.get("NUTRIVISION_ANALYZE_URL", "http://127.0.0.1:8000/api/analyze")
CTX = ssl._create_unverified_context()

with open(os.path.join(ROOT, "labels.json"), encoding="utf-8") as f:
    labels = json.load(f)

KEYWORDS = {
    "pizza": ["披萨", "比萨", "pizza"],
    "burger": ["汉堡", "burger", "堡"],
    "pasta": ["意大利面", "意面", "通心粉", "pasta", "意粉"],
    "dessert": ["蛋糕", "甜点", "甜品", "冰淇淋", "巧克力", "dessert", "布朗尼", "派"],
    "rice": ["米饭", "炒饭", "咖喱饭", "盖饭", "rice", "饭"],
}


def post_image(path):
    boundary = "----dsh" + uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = (
        ("--" + boundary + "\r\n").encode()
        + b'Content-Disposition: form-data; name="file"; filename="test.jpg"\r\n'
        + b"Content-Type: image/jpeg\r\n\r\n"
        + data
        + ("\r\n--" + boundary + "--\r\n").encode()
    )
    req = urllib.request.Request(
        URL, data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, context=CTX, timeout=180) as r:
        raw = r.read().decode("utf-8")
    return time.time() - t0, json.loads(raw)


def matched(cat, food):
    food = food or ""
    return any(k.lower() in food.lower() for k in KEYWORDS[cat])


results = []
for i, (rel, cat) in enumerate(sorted(labels.items()), 1):
    path = os.path.join(ROOT, "images", rel)
    try:
        elapsed, data = post_image(path)
        report = data.get("report", {})
        food = report.get("food_name", "")
        conf = report.get("confidence")
        calories = report.get("calories")
        ok = matched(cat, food)
        row = {
            "file": rel, "label": cat, "food_name": food,
            "confidence": conf, "calories": calories,
            "elapsed_sec": round(elapsed, 3), "match": ok,
        }
        print(f"[{i:02d}/{len(labels)}] {rel} -> {food} conf={conf} {elapsed:.1f}s match={ok}", flush=True)
    except Exception as e:
        row = {
            "file": rel, "label": cat, "food_name": "",
            "confidence": None, "calories": None,
            "elapsed_sec": None, "match": False, "error": repr(e),
        }
        print(f"[{i:02d}/{len(labels)}] {rel} -> ERROR {e!r}", flush=True)
    results.append(row)

with open(os.path.join(ROOT, "results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

valid = [r for r in results if not r.get("error")]
correct = sum(1 for r in valid if r["match"])
latencies = [r["elapsed_sec"] for r in valid if r["elapsed_sec"] is not None]
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
        "correct": sum(1 for r in rows if r["match"]),
    }
with open(os.path.join(ROOT, "summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(json.dumps(summary, ensure_ascii=False, indent=2))
