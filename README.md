# AI 应用开发作品集

两个独立完成的 AI 应用项目，覆盖多模态识别、LangGraph 工作流、RAG、Agent 工具调用、FastAPI 服务化与本地部署。

## 项目

### 1. NutriVision · AI 食物识别与营养分析 Agent

拍照识别食物 → 匹配营养表 → 估算热量 → 生成饮食建议 → 保存报告；支持带记忆的饮食顾问对话。

- DeepSeek 多模态 API + LangGraph StateGraph
- BGE 嵌入 + 营养知识库 RAG
- FastAPI 四个接口 + 原生 HTML 前端
- [进入项目](nutrivision/)

### 2. 招聘协作平台 · AI 简历分拣

多角色招聘协作平台：简历入库 → AI 逐条打分 → HR 复核 → 部门推荐 → 反馈验证；AI 只辅助，不自动淘汰。

- Python 标准库 HTTP 服务 + SQLite
- DeepSeek Chat Completions + 原文引用校验
- DOCX / PDF / TXT 简历解析、多角色权限与操作留痕
- [进入项目](recruitment-platform/)

## 技术栈

Python · FastAPI · LangGraph · LangChain · DeepSeek API · RAG（BGE）· SQLite · HTML / CSS / JavaScript · pytest · systemd / Caddy

## 目录结构

```text
ai-portfolio/
├── nutrivision/            # 多模态识别 + 营养分析 Agent
│   ├── main.py             # FastAPI 入口
│   ├── workflow.py         # 识别 → 匹配 → 计算 → 建议 → 存储
│   ├── agent.py            # 饮食顾问 Agent（工具调用 + 会话记忆）
│   ├── rag.py              # BGE 嵌入 + 知识库检索
│   ├── static/             # 单页前端与界面截图
│   └── README.md
├── recruitment-platform/   # AI 简历分拣与招聘协作
│   ├── deepseek_server.py  # 本地 HTTP 服务与模型调用
│   ├── recruitment_store.py# SQLite 存储、账号与权限
│   ├── test_*.py           # pytest 测试
│   ├── screenshots/        # 界面截图
│   └── README.md
└── README.md
```

## 说明

- 两个项目均为个人独立完成。
- 仓库不包含 API Key、`.env`、SQLite 数据库、真实简历或服务器凭据；示例数据均为虚构数据。
- 项目仍在持续迭代，评分口径与功能边界以各项目 README 为准。
