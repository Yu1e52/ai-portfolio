# -*- coding: utf-8 -*-
import json
import os
import ssl
import time
import urllib.request
import uuid

ROOT = os.environ.get("NUTRIVISION_BENCH_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
URL = os.environ.get("NUTRIVISION_ANALYZE_URL", "http://127.0.0.1:8000/api/analyze")


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
    with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=180) as r:
        return time.time() - t0, json.loads(r.read().decode("utf-8"))


if __name__ == "__main__":
    for rel in ["pizza/01.jpg", "pizza/02.jpg", "rice/01.jpg"]:
        path = os.path.join(ROOT, "images", rel)
        try:
            dt, data = post(path)
            rep = data.get("report", {})
            print(rel, repr(rep.get("food_name")), rep.get("confidence"), round(dt, 2))
        except Exception as e:
            print(rel, "ERR", repr(e))
        time.sleep(15)
