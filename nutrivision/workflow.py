# workflow.py —— Day7 核心工作流（服务器版）
# 改造点：去掉 input() 人工介入，低置信自动重试一次，仍失败走 give_up 兜底
import base64, json, os, time
from pathlib import Path
from typing import TypedDict
import httpx
from dotenv import load_dotenv
from openai import OpenAI
from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import StateGraph, END

BASE_DIR = Path(__file__).resolve().parent          # 锚定脚本目录
load_dotenv(BASE_DIR / ".env")
RECORDS_DIR = BASE_DIR / "records"                  # 报告落盘目录
RECORDS_DIR.mkdir(exist_ok=True)

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    http_client=httpx.Client(trust_env=False),      # 直连绕系统代理
)
parser = JsonOutputParser()

# 营养表：每 100 克 热量/蛋白质/脂肪（Day3 数据）
NUTRITION_DATA = {
    "苹果": {"calories": 52, "protein": 0.3, "fat": 0.2},
    "香蕉": {"calories": 89, "protein": 1.1, "fat": 0.3},
    "牛排": {"calories": 200, "protein": 20, "fat": 13},
    "烤牛排": {"calories": 220, "protein": 25, "fat": 14},
    "玉米": {"calories": 112, "protein": 3.4, "fat": 1.5},
    "烤土豆": {"calories": 150, "protein": 2.8, "fat": 0.5},
    "圣女果": {"calories": 22, "protein": 0.9, "fat": 0.2},
    "生菜": {"calories": 15, "protein": 1.4, "fat": 0.2},
    "冬阴功": {"calories": 180, "protein": 15, "fat": 9},
    "米饭": {"calories": 116, "protein": 2.6, "fat": 0.3},      # 部署补充（与Day9换算表一致）
    "炒青菜": {"calories": 25, "protein": 2.0, "fat": 0.4},     # 部署补充（与Day9换算表一致）
}


class WorkflowState(TypedDict):
    image_path: str
    food_name: str
    confidence: float
    estimated_g: float
    nutrition: dict
    calories: float
    advice: str
    report: dict
    retry_count: int


def query_nutrition(food_name):
    """包含匹配：表里有这个词就算命中（Day3 逻辑）"""
    for key in sorted(NUTRITION_DATA, key=len, reverse=True):
        if key in food_name or food_name in key:
            return NUTRITION_DATA[key]
    return {"calories": 0, "protein": 0, "fat": 0}


def recognize(state):
    """识别节点：图片 -> base64 -> 模型输出 JSON"""
    try:
        with open(state["image_path"], "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        messages = [
            {"role": "system", "content": "你是食物识别助手，只输出json。格式：{\"food_name\":\"菜名\",\"estimated_g\":克数,\"confidence\":0到1小数}"},
            {"role": "user", "content": [{"type": "text", "text": "识别图中的食物，按格式输出json"},
                                          {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]},
        ]
        resp = client.chat.completions.create(model="deepseek-flash", messages=messages)
        data = parser.invoke(resp.choices[0].message.content)
        print(f"[识别] -> {data}")
        return {"food_name": data.get("food_name", "未知食物"),
                "confidence": float(data.get("confidence", 0)),
                "estimated_g": float(data.get("estimated_g", 0))}
    except Exception as e:
        print(f"[识别]失败，兜底: {e}")
        return {"food_name": "未知食物", "confidence": 0.0, "estimated_g": 0.0}


def ask_human(state):
    """服务器版：不再等真人输入，自动重试一次（提示模型重新判断）"""
    print(f"[重试]第{state['retry_count']+1}次，自动重新识别")
    return {"retry_count": state["retry_count"] + 1}


def give_up(state):
    """放弃：输出兜底报告"""
    print("[放弃]仍无法识别，输出兜底报告")
    return {"report": {"image_path": state["image_path"], "food_name": "无法识别",
                       "confidence": state["confidence"], "estimated_g": 0,
                       "nutrition": {}, "calories": 0,
                       "advice": "图片无法识别，请换一张清晰的实物图片"}}


def match(state):
    """匹配节点：查营养表"""
    nutrition = query_nutrition(state["food_name"])
    print(f"[匹配] {state['food_name']} -> {nutrition}")
    return {"nutrition": nutrition}


def calc(state):
    """计算节点：热量 = 每100克热量 × 克数 / 100"""
    g = state["estimated_g"]
    if g < 1 or g > 500:
        print(f"[计算]克数不合理({g}g)，按0处理")
        return {"calories": 0.0}
    calories = state["nutrition"]["calories"] * g / 100
    print(f"[计算] {g}g x {state['nutrition']['calories']}kcal/100g = {calories:.1f}kcal")
    return {"calories": calories}


def advice(state):
    """建议节点：数据异常跳过模型，否则生成建议"""
    if state["calories"] <= 0:
        print("[建议]数据异常，跳过模型")
        return {"advice": "营养数据缺失，请核对食物信息后再评估"}
    messages = [
        {"role": "system", "content": "你是营养师，只输出json。格式：{\"summary\":\"一句话总结\",\"advice\":\"2-3条建议,分号分隔\"}"},
        {"role": "user", "content": f"食物:{state['food_name']},{state['estimated_g']}克,总热量{state['calories']:.0f}kcal,每100g蛋白质{state['nutrition'].get('protein',0)}g脂肪{state['nutrition'].get('fat',0)}g,给饮食建议"},
    ]
    try:
        resp = client.chat.completions.create(model="deepseek-flash", messages=messages)
        data = parser.invoke(resp.choices[0].message.content)
        print(f"[建议] -> {data}")
        return {"advice": data.get("advice", "数据不足，无法给出建议")}
    except Exception as e:
        print(f"[建议]解析失败，兜底: {e}")
        return {"advice": "数据不足，无法给出建议"}


def store(state):
    """存储节点：报告落盘 records/report_时间戳.json"""
    report = {"image_path": state["image_path"], "food_name": state["food_name"],
              "confidence": state["confidence"], "estimated_g": state["estimated_g"],
              "nutrition": state["nutrition"], "calories": state["calories"],
              "advice": state["advice"]}
    ts = time.strftime("%Y%m%d_%H%M%S")
    with open(RECORDS_DIR / f"report_{ts}.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[存储]报告已写入 records/report_{ts}.json")
    return {"report": report}


LOW_CONF_FOODS = {"无食物", "未识别到食物", "未知食物"}


def route_after_recognize(state):
    """条件路由：高置信->match；重试<2->ask_human(自动重试)；否则放弃"""
    if state["confidence"] >= 0.7 and state["food_name"] not in LOW_CONF_FOODS:
        return "match"
    if state["retry_count"] < 2:
        return "ask_human"
    return "give_up"


# 建图（Day5/6 五连招）
# 注意：LangGraph 新版要求节点名不能与 State 字段重名，故 advice 节点叫 advice_node
graph = StateGraph(WorkflowState)
graph.add_node("recognize", recognize)
graph.add_node("ask_human", ask_human)
graph.add_node("give_up", give_up)
graph.add_node("match", match)
graph.add_node("calc", calc)
graph.add_node("advice_node", advice)
graph.add_node("store", store)
graph.set_entry_point("recognize")
graph.add_conditional_edges("recognize", route_after_recognize,
                            {"match": "match", "ask_human": "ask_human", "give_up": "give_up"})
graph.add_edge("ask_human", "recognize")
graph.add_edge("give_up", END)
graph.add_edge("match", "calc")
graph.add_edge("calc", "advice_node")
graph.add_edge("advice_node", "store")
graph.add_edge("store", END)
app = graph.compile()


def run_workflow(image_path: str) -> dict:
    """对外唯一入口：传图片路径，返回报告 dict"""
    result = app.invoke({"image_path": image_path, "food_name": "", "confidence": 0.0,
                         "estimated_g": 0.0, "nutrition": {}, "calories": 0.0,
                         "advice": "", "report": {}, "retry_count": 0})
    return result["report"]
