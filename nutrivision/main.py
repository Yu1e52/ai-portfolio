# main.py —— NutriVision FastAPI 服务入口（部署版）
# 接口：/api/hello、/api/analyze(传图识别)、/api/chat(顾问对话)、/api/history(记录)
import json, shutil, time
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from workflow import run_workflow
from agent import chat

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RECORDS_DIR = BASE_DIR / "records"
UPLOAD_DIR.mkdir(exist_ok=True)
RECORDS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="NutriVision 服务")


class ChatRequest(BaseModel):
    """聊天请求体：消息 + 会话ID（同一个ID=同一场对话，记忆隔离）"""
    message: str
    thread_id: str = "default"


@app.get("/api/hello")
def hello():
    """健康检查接口，浏览器直接访问验证服务是否在跑"""
    return {"message": "你好，NutriVision 服务已上线！"}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    """上传食物图片 -> 跑 Day7 工作流 -> 返回识别报告"""
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="只支持 png/jpg/jpeg 图片")
    # 保存上传的图片到临时目录（文件名带时间戳防冲突）
    ext = Path(file.filename).suffix
    tmp = UPLOAD_DIR / f"upload_{int(time.time())}{ext}"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    print(f"[API] 收到图片 {file.filename}，保存为 {tmp.name}")

    report = run_workflow(str(tmp))
    return {"code": 0, "report": report}


@app.post("/api/chat")
def chat_api(req: ChatRequest):
    """顾问对话：同 thread_id 自动记忆上下文"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    answer = chat(req.thread_id, req.message)
    return {"code": 0, "thread_id": req.thread_id, "answer": answer}


@app.get("/api/history")
def history():
    """返回历史识别报告列表（按时间倒序）"""
    reports = []
    for p in sorted(RECORDS_DIR.glob("report_*.json"), reverse=True):
        with open(p, encoding="utf-8") as f:
            reports.append(json.load(f))
    return {"code": 0, "count": len(reports), "history": reports}


@app.get("/")
def index():
    """根路径：返回前端页面"""
    return FileResponse(BASE_DIR / "static" / "index.html")
