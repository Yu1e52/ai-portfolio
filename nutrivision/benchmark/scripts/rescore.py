# -*- coding: utf-8 -*-
import json
import os
import statistics

ROOT = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
with open(os.path.join(ROOT, "results.json"), encoding="utf-8") as f:
    rows = json.load(f)

KEYWORDS = {
    "pizza": ["披萨", "比萨", "匹萨", "pizza"],
    "burger": ["汉堡", "burger", "堡"],
    "pasta": ["意大利面", "意面", "通心粉", "pasta", "意粉", "斜管面", "管面",
              "肉酱面", "螺旋面", "蝴蝶面", "宽面", "细面", "拌面", "炒面"],
    "dessert": ["蛋糕", "甜点", "甜品", "冰淇淋", "巧克力", "dessert", "布朗尼", "派",
                "可丽饼", "慕斯", "布丁", "圣代", "甜甜圈", "曲奇", "马卡龙",
                "提拉米苏", "泡芙", "奶昔"],
    "rice": ["米饭", "炒饭", "咖喱饭", "盖饭", "rice", "饭"],
}


def matched(cat, food):
    food = food or ""
    return any(k.lower() in food.lower() for k in KEYWORDS[cat])


for r in rows:
    r["food_name"] = r.get("food_name") or ""
    r["match"] = matched(r["label"], r["food_name"]) if r["food_name"] not in ("", "无法识别", "未知食物") else False

with open(os.path.join(ROOT, "results.json"), "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)

valid = [r for r in rows if r["food_name"] not in ("", "无法识别", "未知食物") and not r.get("error")]
correct = sum(1 for r in valid if r["match"])
latencies = [r["elapsed_sec"] for r in valid if r.get("elapsed_sec") is not None]
summary = {
    "total": len(rows),
    "valid": len(valid),
    "correct": correct,
    "accuracy": round(correct / len(valid), 4) if valid else None,
    "avg_latency_sec": round(statistics.mean(latencies), 2) if latencies else None,
    "median_latency_sec": round(statistics.median(latencies), 2) if latencies else None,
    "p95_latency_sec": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
    "per_category": {},
}
for cat in KEYWORDS:
    catrows = [r for r in valid if r["label"] == cat]
    summary["per_category"][cat] = {
        "total": len(catrows),
        "correct": sum(1 for r in catrows if r["match"]),
    }
with open(os.path.join(ROOT, "summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

with open(os.path.join(ROOT, "results.txt"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(f"{r['file']}\t{r['label']}\t{r['food_name']}\t{r['confidence']}\t{r['elapsed_sec']}\t{r['match']}\n")

print(json.dumps(summary, ensure_ascii=False, indent=2))
