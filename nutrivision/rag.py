# rag.py —— Day8 RAG 封装（服务器版）
# 模型只加载一次（模块级），之后所有问答复用
import os, httpx
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

BASE_DIR = Path(__file__).resolve().parent   # 锚定脚本目录
load_dotenv(BASE_DIR / ".env")              # 读取服务器上的 .env

# 模块级加载：嵌入模型 + 知识库 + 库向量（服务启动时执行一次）
embed_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

with open(BASE_DIR / "nutrition_kb.txt", encoding="utf-8") as f:
    blocks = [b.strip() for b in f.read().split("\n\n") if b.strip()]
block_vecs = embed_model.encode(blocks)


def rag_answer(question):
    """四步链路：检索 top2 -> 拼 prompt -> 只依据资料回答"""
    q_vec = embed_model.encode(question)
    scores = cos_sim(q_vec, block_vecs)[0]
    order = sorted(range(len(blocks)), key=lambda i: scores[i], reverse=True)
    top2 = [blocks[i] for i in order[:2]]

    prompt = f"""你是营养学助手。请只依据下面的【知识资料】回答问题，不要使用资料之外的知识；如果资料里没有相关内容，直接说明“资料里没有这个信息”。

[知识资料]
{"\n----\n".join(top2)}

[问题]
{question}"""

    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        http_client=httpx.Client(trust_env=False),   # 直连，绕开系统代理
    )
    resp = client.chat.completions.create(
        model="deepseek-flash", messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content
