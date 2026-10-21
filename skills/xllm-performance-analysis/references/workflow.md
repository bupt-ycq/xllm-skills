# 独立执行工作流

所有路径在执行前解析为绝对路径。每次采集或导出都使用尚不存在的新输出目录；采集器会拒绝覆盖。

## 1. 环境预检

```bash
command -v cnperf-cli
cnperf-cli --help
cnmon info
```

确认 MLU 可见、Neuware/CNPerf 与当前环境匹配、磁盘空间足够，容器场景还要检查 `/dev/shm`。不要在采集过程中安装软件或切换运行环境。

服务启动命令必须保持前台运行。采集器以独立进程组启动它，并且只停止该进程组；会自行 daemonize、调用 `setsid` 或复用已有服务的脚本不适用，应先准备一个保持前台的运行命令。

## 2. 全模型采集

```bash
python /absolute/path/to/xllm-performance-analysis/scripts/profile_xllm.py run \
  --server-cmd '/absolute/path/to/start_xllm.sh' \
  --client-cmd '/absolute/path/to/run_benchmark.sh' \
  --ready-url 'http://127.0.0.1:8000/v1/models' \
  --output-dir /absolute/results/run-001 \
  --name xllm_full
```

采集器实际执行：

```text
cnperf-cli record -o <name>.cnperf-rep
  --trace_child=true
  --device_task=kernel,memcpy,notifier
  --device_task_mode=detail
  --process_traced=xllm
  <内置生命周期程序>
```

CNPerf 选项全部位于生命周期程序之前。生命周期按顺序启动服务、轮询 readiness、执行一次 client、停止本次服务、等待 record 退出。

如果当前 CNPerf 版本对进程过滤存在问题，可在证据支持时使用 `--no-process-filter`。额外 record 参数使用 `--record-option=--option=value`；端到端测试不要默认添加 `--pmu`。

## 3. 指定模块采集

先完整阅读 `references/instrumentation.md`，安装内置 Runtime、插入 RAII Range、重新构建并确认服务使用新产物。假设 Range 为 `prefill.layers_3_7.moe`：

```bash
python /absolute/path/to/xllm-performance-analysis/scripts/profile_xllm.py run \
  --server-cmd '/absolute/path/to/start_instrumented_xllm.sh' \
  --client-cmd '/absolute/path/to/run_benchmark.sh' \
  --ready-url 'http://127.0.0.1:8000/v1/models' \
  --output-dir /absolute/results/run-002 \
  --name prefill_layers_3_7_moe \
  --cnpx-include 'XLLM_PERF_ANALYSIS@prefill.layers_3_7.moe/'
```

采集器会自动增加 `--capture_range=cnpx`。多个模块重复传入 `--cnpx-include`。如需排除已证实的嵌套 Range，可重复传入 `--cnpx-exclude`；不能只传 exclude。

先执行小负载验证 report 非空和 timechart Range，再执行正式负载。指定模块的 `.cnperf-rep` 本身已由 CNPX filter 限定，因此它导出的 Kernel、内存和时间线数据都是该范围的派生数据，不需要其他分析包。

## 4. 从已有 report 导出

```bash
python /absolute/path/to/xllm-performance-analysis/scripts/profile_xllm.py export \
  --report /absolute/results/run-001/xllm_full.cnperf-rep \
  --output-dir /absolute/results/export-001 \
  --name xllm_full
```

内部执行：

```bash
cnperf-cli report --csv -o <output>/csv <report>
cnperf-cli timechart --name <name> -o <output>/json <report>
```

## 5. 产物布局

```text
run-001/
├── xllm_full.cnperf-rep
├── csv/
│   └── *.csv
├── json/
│   └── *.json
├── manifest.json
├── server.log
├── client.log
├── cnperf_help.log
├── cnperf_record.log
├── cnperf_report.log
└── cnperf_timechart.log
```

`manifest.json` 记录 report 的绝对路径、大小、SHA256、CNPX include/exclude、CNPerf 选项及 CSV/JSON 文件列表。它只记录 server/client 命令的 SHA256，不回显可能包含凭据的完整命令。

## 6. 验证与恢复

检查 report 非空、`manifest.json` 状态为 `complete`、CSV/JSON 文件列表非空、client 日志中的请求完成数符合负载。指定模块还要在 timechart 中核对 Domain/Range，并确认 include 后的任务属于预期调用。

最后恢复调用点和内置 Runtime，核对源码基线。采集器失败时保留输出目录、失败 manifest 和日志供诊断；不要用失败报告生成结论。
