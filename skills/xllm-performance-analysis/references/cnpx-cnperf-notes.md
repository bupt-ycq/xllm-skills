# CNPX 与 CNPerf 使用要点

本页提炼自 `Cambricon-CNPX-Developer-Guide-CN-v1.6.0.pdf` 和 `Cambricon-CNPerf-User-Guide-CN-v6.5.0.pdf`，用于执行时快速核对；遇到版本差异，以当前机器的 `cnperf-cli --help` 和对应版本官方手册为准。

## CNPX 范围

- `cnpxRangeStart` / `cnpxRangeEnd` 表示进程范围，结束时必须使用 Start 返回的同一 handle。
- `cnpxRangePush` / `cnpxRangePop` 表示线程范围，Pop 与当前线程最近一次 Push 配对。
- 每个 Domain 拥有独立的 Push/Pop 栈；自定义 Domain 名不能以保留前缀 `CNPERF_` 开头。
- Python 支持 `Domain`、`rangePush/Pop`、`rangeStart/End` 和 `@cnpx.annotate`。
- 建议在正式测量前显式初始化 CNPX，避免首次隐式初始化落入目标区间。
- xLLM 指定模块插桩使用当前 Skill 的 `assets/xllm_cnpx_range.h`，其 Domain 固定为 `XLLM_PERF_ANALYSIS`；调用点只负责提供启用条件和稳定 Range 名。

## CNPerf 采集

基本形式：

```bash
cnperf-cli record [CNPerf 选项] <程序> [程序选项]
```

常用选项：

```text
-o <report-path>
-f / --force_overwrite
--trace_child=true
--process_traced=<regex>
--device_task=kernel,memcpy,notifier
--device_task_mode=detail
--capture_range=cnpx
--cnpx_include <rules>
--cnpx_exclude <rules>
```

- 所有 CNPerf 选项必须放在被追踪程序之前。
- `record` 的权威产物是 `.cnperf-rep`。
- xLLM 本地流程使用 `--trace_child=true --process_traced=xllm`，并让 server 和 client 处于同一个外层 record 生命周期。
- 多机采集需在每台机器分别保留不同 report，不能将不同节点报告覆盖为同一文件。
- `--pmu` 可能令设备任务下发变为同步，只适合明确的单 Kernel 调优，不能作为端到端默认值。
- `task_only` 开销较低，但缺少函数记录和 PMU 信息；选择它时要说明能力损失。
- 容器采集可能需要增大 `/dev/shm`，应在开始长任务前检查。

## CNPX 采集过滤

`--capture_range=cnpx` 需要与 include/exclude 规则配合才会按范围过滤。规则可表达 Domain、线程 Range 栈路径以及栈顶/栈底匹配，它不是通用的任意文本正则。

全模型测试默认保留完整 trace。指定模块测试先用小规模预采集验证目标 Range 的 Domain、名称和栈关系，再启用采集过滤生成模块专属 report；必须记录具体规则，并保留验证证据。

## 原生导出

汇总 CSV：

```bash
cnperf-cli report --csv -o /absolute/output/cnperf_csv \
  /absolute/output/trace.cnperf-rep
```

常见输出包括 `FunctionStatistics.csv`、`KernelStatistics.csv`、`MemoryOpTimeStatistics.csv`、`MemoryOpSizeStatistics.csv`、`AtomicOpStatistics.csv`、`NotifierStatistics.csv` 和 `JpuVppsStatistics.csv`；实际文件以当前 CNPerf 版本为准。

时间线 JSON：

```bash
cnperf-cli timechart --name xllm_trace \
  -o /absolute/output/cnperf_json \
  /absolute/output/trace.cnperf-rep
```

可根据报告规模和当前版本帮助信息选用 `--detail`、`--duration`、`--sampler false`、`-t <interval_ms>`。指定模块时，timechart JSON 来自已经过 CNPX filter 限定的 `.cnperf-rep`；它仍然是 CNPerf 时间线，而不是简单的 CSV 格式转换。

## 手册定位

- CNPX 编程示例：CNPX 手册 PDF 第 10-12 页。
- CNPX Range/Domain API：CNPX 手册 PDF 第 13-20 页。
- CNPX Python API：CNPX 手册 PDF 第 26-31 页。
- CNPerf `record`：CNPerf 手册 PDF 第 23-32 页。
- CNPerf `report --csv`：CNPerf 手册 PDF 第 33-35 页。
- CNPerf `timechart`：CNPerf 手册 PDF 第 49-52、65-66 页。
- CNPX filter：CNPerf 手册 PDF 第 72-76 页。
