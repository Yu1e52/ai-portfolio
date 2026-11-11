# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageOps

# 目标目录为 benchmark/images；可用 NUTRIVISION_BENCH_ROOT 覆盖
BENCH = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
ROOT = os.path.join(BENCH, "images")
for dirpath, _, filenames in os.walk(ROOT):
    for name in filenames:
        if not name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        path = os.path.join(dirpath, name)
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1000, 1000), Image.LANCZOS)
            im.save(path, "JPEG", quality=85, optimize=True)
        print("resized", path, os.path.getsize(path))
