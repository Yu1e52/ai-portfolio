# NutriVision 菜品识别评测

## 口径

- 样本：30 张公开食物图（Foodish 数据集），5 类，每类 6 张：pizza、burger、pasta、dessert、rice。
- 调用：部署后的 `POST /nutrivision/api/analyze`，逐张上传，记录 `food_name`、置信度与端到端耗时。
- 判定：以图片类别为 ground truth；模型输出包含该类别的中文/英文同义词即判为正确。例如 `果酱可丽饼` 计入 dessert，`番茄酱斜管面` 计入 pasta。
- 耗时：客户端到云服务的端到端耗时，包含图片上传与网络，未扣除服务冷启动；不包含人工标注时间。

## 结果

| 指标 | 结果 |
|---|---|
| 有效样本 | 30 / 30 |
| 识别正确 | 29 / 30（96.7%） |
| 平均响应 | 2.47 s |
| 中位响应 | 2.26 s |
| P95 响应 | 3.53 s |

分类明细：

| 类别 | 正确 / 总数 |
|---|---|
| pizza | 5 / 6 |
| burger | 6 / 6 |
| pasta | 6 / 6 |
| dessert | 6 / 6 |
| rice | 6 / 6 |

唯一错误：`pizza/04.jpg` 被识别为“意大利辣香肠奶酪椒盐卷饼”（pretzel），未命中 pizza 类别。

## 说明

- 这是 5 类、30 张图的小样本评测，不代表所有菜系或真实用户场景的准确率。
- 只评测“菜品识别”，没有评测营养表匹配、热量估算或建议质量。
- 评测脚本见 `scripts/`，逐条明细见 `results.json` 与 `results.txt`；原始图片不随仓库分发（`benchmark/images/` 已在 `.gitignore` 中），可按 `file` 字段用 `scripts/prepare_dataset.py` 从 Foodish 重新获取。
- 请求曾遇到上游限流，失败样本已间隔重试；最终 30 张均返回有效结果。

## 复现

1. 启动 NutriVision 服务（默认 `http://127.0.0.1:8000`）；若要打已部署实例，设置 `NUTRIVISION_ANALYZE_URL`。
2. `python scripts/prepare_dataset.py`：从 Foodish 拉 30 张图到 `benchmark/images/`，同时写出 `labels.json`。
3. `python scripts/resize_images.py`：统一缩放到长边 1000 px（需要 Pillow）。
4. `python scripts/run_test.py`：逐张调用 `/api/analyze`，写出 `results.json` 与 `summary.json`。
5. 遇到上游限流或 fallback 结果时跑 `python scripts/retry_failed.py` 间隔重试；`python scripts/rescore.py` 按上面的同义词口径重新判分并生成 `results.txt`。

脚本默认以 `benchmark/` 为数据目录，可用环境变量 `NUTRIVISION_BENCH_ROOT` 覆盖。`scripts/retry_one.py` 用于单张排查，`scripts/dump_results.py` 只负责把 `results.json` 导出成 `results.txt`。

用提交里的 `results.json` 跑 `rescore.py`，可复现出与仓库中完全一致的 `summary.json` 与 `results.txt`（已实测逐字节相同）。
