# -*- coding: utf-8 -*-
import json
import os

ROOT = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

rows = json.load(open(os.path.join(ROOT, "results.json"), encoding="utf-8"))
with open(os.path.join(ROOT, "results.txt"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(f"{r['file']}\t{r['label']}\t{r['food_name']}\t{r['confidence']}\t{r['elapsed_sec']}\t{r['match']}\n")
print("ok")
