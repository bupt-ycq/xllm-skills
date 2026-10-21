# EvalScope 性能指标与输出约定

本 Skill 的指标名称和主要计算口径依据 EvalScope 官方中文文档与源码：

- [EvalScope 中文文档](https://evalscope.readthedocs.io/zh-cn/latest/)
- [性能压测快速开始](https://evalscope.readthedocs.io/zh-cn/latest/user_guides/stress_test/quick_start.html)
- [性能压测参数](https://evalscope.readthedocs.io/zh-cn/latest/user_guides/stress_test/parameters.html)
- 工作区源码参考：`evalscope/docs/zh/user_guides/stress_test/`、`evalscope/evalscope/perf/`

## 汇总指标

| 输出键 | 单位 | 含义或公式 |
| --- | --- | --- |
| `Test Duration (s)` | 秒 | 最早正式请求开始到最晚正式请求结束的墙钟时间；不含预热 |
| `Concurrency` | 请求 | 最大并发请求数 |
| `Total Requests` / `Success Requests` / `Failed Requests` | 请求 | 总数、成功数和失败数 |
| `Req Throughput (req/s)` | 请求/秒 | 成功请求数 / 测试总时长 |
| `Avg Latency (s)` | 秒 | 从发出请求到完整接收响应的平均时间 |
| `Avg TTFT (ms)` | 毫秒 | 从发出请求到收到首个有效流式内容块的平均时间 |
| `Avg TPOT (ms)` | 毫秒/Token | 每请求 `(Latency - TTFT) / (Output Tokens - 1)` 的平均值 |
| `Avg ITL (ms)` | 毫秒 | 相邻有效流式内容块之间间隔的平均值 |
| `Avg Input Tokens` / `Avg Output Tokens` | Token/请求 | 成功请求的平均输入、输出 Token 数 |
| `Output Throughput (tok/s)` | Token/秒 | 成功请求总输出 Token / 测试总时长 |
| `Total Throughput (tok/s)` | Token/秒 | 成功请求总输入和输出 Token / 测试总时长 |

TTFT、TPOT 和 ITL 应使用流式响应。非流式响应只能可靠提供端到端延迟；此时首个响应到达往往就是完整响应到达。

## 百分位指标

`benchmark_percentile.json` 按请求给出 `min`、P1、P5、P10、P25、P50、P75、P90、P95、P99 和 `max`。主要字段为：

- `Latency (s)`、`TTFT (ms)`、`ITL (ms)`、`TPOT (ms)`；
- `Input tokens`、`Output tokens`；
- `Output (tok/s)`、`Total (tok/s)`、`Decode (tok/s)`。

ITL 的百分位以流式内容块间隔为样本；其他时延百分位通常以成功请求为样本。`Decode (tok/s)` 为单请求 `1 / TPOT`，TPOT 为零或不可用时该值为空。

## 内置评测器输出

每个并发配置目录包含：

| 文件 | 内容 |
| --- | --- |
| `benchmark_args.json` | 已脱敏的实际参数、后端和 Token 计数说明 |
| `benchmark_summary.json` | EvalScope 风格汇总指标，另含成功率和 Token 来源 |
| `benchmark_percentile.json` | EvalScope 风格百分位行 |
| `benchmark_data.jsonl` | 每个请求的成功状态、时延、Token 和错误摘要，不保存密钥 |
| `benchmark.log` | 便于直接阅读的文本汇总 |

扫描多个并发配置时，运行根目录还包含 `performance_summary.json` 和 `performance_summary.txt`。

## Token 计数可信度

内置评测器优先读取 OpenAI 响应中的 `usage.prompt_tokens` 和 `usage.completion_tokens`。若服务没有返回 usage，它会用无依赖启发式方法估算，并将 `Token Count Source` 标记为 `estimated` 或 `mixed`。估算值只用于补齐 EvalScope 指标字段，不等价于模型 tokenizer 的精确计数。

需要精确的随机 Token 长度、Tokenizer 计数、Embedding/Rerank 指标、多轮指标、开放环路负载、SLA 自动搜索或 HTML 可视化报告时，应安装 `evalscope[perf]` 并使用 EvalScope 后端。
