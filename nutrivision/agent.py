# agent.py —— Day9 饮食顾问 Agent（服务器版）
# 改造点：去掉顶层执行代码（while 循环/演示调用），只暴露 chat(thread_id, message)
import os, httpx, operator
from pathlib import Path
from typing import TypedDict, Annotated
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import ToolMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from rag import rag_answer

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# 假数据：今日摄入 / 历史记录
today_intake = [{"食物": "米饭", "克": 200}, {"食物": "炒青菜", "克": 150}]


@tool
def query_intake():
    """查询用户今天吃了什么，返回食物清单。"""
    print("[工具] query_intake 被调用")
    return today_intake


@tool
def query_nutrition_kb(question: str):
    """查询营养知识库，只依据资料回答饮食禁忌/误区问题。"""
    print(f"[工具] query_nutrition_kb 被调用，参数={question}")
    return rag_answer(question)


@tool
def calc_calories(food: str, grams: float):
    """计算某食物按克数摄入的热量。"""
    table = {"米饭": 1.16, "炒青菜": 0.25}   # 千卡/克，假数据
    cal = table.get(food, 1.0) * grams
    print(f"[工具] calc_calories 被调用，参数={food},{grams}，返回={cal:.0f}千卡")
    return cal


@tool
def query_history():
    """查询用户过往的饮食记录。"""
    print("[工具] query_history 被调用")
    return [{"日期": "昨天", "食物": "面条"}, {"日期": "前天", "食物": "饺子"}]


tools = [query_intake, query_nutrition_kb, calc_calories, query_history]

model = ChatOpenAI(
    base_url="https://api.deepseek.com",
    model="deepseek-flash",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    http_client=httpx.Client(trust_env=False),   # 直连绕代理
).bind_tools(tools)


class State(TypedDict):
    messages: Annotated[list, operator.add]


def call_model(state):
    """agent 节点：模型思考，决定调哪个工具"""
    print("[agent] 模型思考中...")
    return {"messages": [model.invoke(state["messages"])]}


def call_tools(state):
    """tools 节点：真正执行工具，结果放回对话"""
    last = state["messages"][-1]
    out = []
    for tc in last.tool_calls:
        t = {x.name: x for x in tools}[tc["name"]]
        out.append(ToolMessage(str(t.invoke(tc["args"])), tool_call_id=tc["id"]))
    return {"messages": out}


def route(state):
    """条件边：还有工具调用就回 agent 继续，否则结束"""
    return "tools" if state["messages"][-1].tool_calls else END


def build_graph():
    """建图 + 编译（挂 checkpointer 存档机，thread_id 隔离记忆）"""
    g = StateGraph(State)
    g.add_node("agent", call_model).add_node("tools", call_tools)
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    return g.compile(checkpointer=MemorySaver())


app = build_graph()


def chat(thread_id: str, message: str) -> str:
    """对外唯一入口：同一 thread_id 自动恢复历史记忆"""
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke({"messages": [HumanMessage(content=message)]}, config)
    return result["messages"][-1].content
