# test_api.py —— 服务器端接口验收脚本（验证 4 个接口）
import json, urllib.request

BASE = "http://127.0.0.1:8000"


def req(method, path, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(BASE + path, data=body, method=method,
                               headers=headers or {"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


print("1) GET /api/hello ->", req("GET", "/api/hello"))

print("2) POST /api/chat 第一次 ->", req("POST", "/api/chat",
      {"message": "我今天吃了啥", "thread_id": "test-1"})["answer"][:60])

print("3) POST /api/chat 第二次(同thread_id,测记忆) ->",
      req("POST", "/api/chat", {"message": "那我晚饭能吃什么", "thread_id": "test-1"})["answer"][:60])

print("4) GET /api/history ->", req("GET", "/api/history")["count"], "条记录")

# 错误输入验收：空消息应返回 400 JSON 错误
try:
    req("POST", "/api/chat", {"message": "", "thread_id": "test-1"})
    print("5) 空消息: 未按预期报错!")
except urllib.error.HTTPError as e:
    print("5) 空消息 -> HTTP", e.code, "错误JSON:", e.read().decode()[:100])
