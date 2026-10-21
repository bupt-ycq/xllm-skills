---
name: xllm-performance-evaluate
description: 对运行中的 xLLM 或其他 OpenAI Chat Completions 兼容推理服务进行并发性能评测，输出 TTFT、TPOT、ITL、端到端延迟、请求吞吐和 Token 吞吐等 EvalScope 指标。适用于压测、吞吐/时延测量、并发扫描和性能回归验证；不用于模型准确率评测、服务部署或单个算子的设备侧分析。
---

# xLLM 性能评测

使用 `scripts/run_performance.py` 作为统一入口。它先严格检测当前 Python 环境是否安装了 `evalscope` 发行包：已安装时调用 `evalscope perf`，未安装时调用无第三方依赖的内置评测器。不要仅凭工作区里存在同名源码目录或 `import evalscope` 成功就认定已经安装。

## 运行前确认

1. 确认目标是已运行的 OpenAI Chat Completions 兼容服务，并获取完整端点（例如 `http://127.0.0.1:7442/v1/chat/completions`）。
2. 确认模型名、并发数、请求数、最大输出 Token、是否流式，以及用户希望固定还是变化的 Prompt。模型名缺省时，脚本会尝试从同一服务的 `/v1/models` 读取第一个模型。
3. 先检查后端，不发起压测请求：

```bash
python xllm-performance-evaluate/scripts/run_performance.py --check
```

4. 密钥优先放入环境变量，然后传变量名；不要把真实密钥写入 Skill、日志或结果文件：

```bash
export OPENAI_API_KEY='...'
```

## 执行评测

先用小规模负载验证服务和参数，再运行正式负载。默认启用流式响应，因为非流式请求不能真实测量 TTFT、TPOT 和 ITL。

```bash
python xllm-performance-evaluate/scripts/run_performance.py \
  --url http://127.0.0.1:7442/v1/chat/completions \
  --model MODEL_NAME \
  --parallel 1 \
  --number 10 \
  --max-tokens 128 \
  --outputs-dir outputs/performance-smoke
```

正式的并发扫描将 `--parallel` 和 `--number` 按位置配对：

```bash
python xllm-performance-evaluate/scripts/run_performance.py \
  --url http://127.0.0.1:7442/v1/chat/completions \
  --model MODEL_NAME \
  --parallel 1 8 32 \
  --number 20 160 640 \
  --max-tokens 512 \
  --warmup-num 5 \
  --api-key-env OPENAI_API_KEY \
  --outputs-dir outputs/performance
```

需要冻结输入时使用 `--prompt`；需要多条输入时使用 `--dataset-path`，文件每行一个 Prompt。不要在性能对比中途改变 Prompt、输入/输出长度、并发、请求数、流式设置、服务配置或预热条件。

## 后端规则

- `evalscope` 已安装：入口脚本必须执行官方 `evalscope perf` 路径，并保留其控制台表格、JSON、SQLite 和 HTML 报告。若 perf 额外依赖缺失或命令失败，直接报告原始错误并建议检查 `evalscope[perf]`；不要把失败伪装成“未安装”并自动降级。
- `evalscope` 未安装：入口脚本自动执行内置评测器，生成兼容 EvalScope 命名的 `benchmark_args.json`、`benchmark_summary.json`、`benchmark_percentile.json`、`benchmark_data.jsonl` 和汇总报告。不主动安装 EvalScope，除非用户明确要求。
- `--force-fallback` 只用于验证内置路径或用户明确要求对比评测器，不能用于绕过一个已安装但运行失败的 EvalScope。
- 内置评测器仅覆盖 OpenAI Chat Completions 的单轮文本请求；Embedding、Rerank、Responses API、多轮数据集、随机 Token 数据集和 SLA 自动调优必须使用 EvalScope。

## 验收与报告

读取结果前先确认进程退出码为 `0`、`Success Requests` 大于 `0`，并同时报告失败请求数和成功率。至少汇报：

- 测试条件：后端、模型、端点、并发、请求数、流式设置、Prompt/数据集、最大输出 Token 和预热数；
- 汇总指标：`Req Throughput (req/s)`、`Avg Latency (s)`、`Avg TTFT (ms)`、`Avg TPOT (ms)`、`Avg ITL (ms)`、`Output Throughput (tok/s)`、`Total Throughput (tok/s)`；
- 尾延迟：Latency、TTFT 和 TPOT 的 P50、P90、P95、P99；
- 数据质量：失败数、错误类型，以及 Token 计数是服务端 usage 的精确值还是内置估算值。

内置路径在服务未返回 usage 时会估算 Token 数，并在结果中写入 `Token Count Source`。此时延迟和请求吞吐仍可使用，但 Token 吞吐及 TPOT 只能标为近似值，不能与精确 Token 计数结果直接比较。指标定义、公式和结果文件说明见 [metrics.md](references/metrics.md)。

只有在测试条件一致、成功率可接受且结果差异超过正常抖动时，才声称存在性能改善或回退。正式回归比较至少重复 3 轮并报告中位数；不要只比较最好的一次。
