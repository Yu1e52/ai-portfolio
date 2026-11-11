# -*- coding: utf-8 -*-
import json
import os
import ssl
import time
import urllib.request

# 数据与结果默认落在 benchmark/ 目录下；可用 NUTRIVISION_BENCH_ROOT 覆盖
ROOT = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
CATEGORIES = ["pizza", "burger", "pasta", "dessert", "rice"]
PER_CATEGORY = 6
CTX = ssl._create_unverified_context()


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.read()


labels = {}
for cat in CATEGORIES:
    outdir = os.path.join(ROOT, "images", cat)
    os.makedirs(outdir, exist_ok=True)
    seen = set()
    n = 0
    attempts = 0
    while n < PER_CATEGORY and attempts < 40:
        attempts += 1
        try:
            meta = json.loads(get(f"https://foodish-api.com/api/images/{cat}").decode("utf-8"))
            img_url = meta["image"]
        except Exception as e:
            print("api error", cat, attempts, repr(e))
            time.sleep(1)
            continue
        if img_url in seen:
            continue
        seen.add(img_url)
        try:
            blob = get(img_url, timeout=60)
            if len(blob) < 5000:
                continue
            n += 1
            name = f"{n:02d}.jpg"
            path = os.path.join(outdir, name)
            with open(path, "wb") as f:
                f.write(blob)
            labels[f"{cat}/{name}"] = cat
            print("saved", cat, name, len(blob))
        except Exception as e:
            print("download error", img_url, repr(e))
        time.sleep(0.5)

with open(os.path.join(ROOT, "labels.json"), "w", encoding="utf-8") as f:
    json.dump(labels, f, ensure_ascii=False, indent=2)
print("total", len(labels))
