---
name: xllm-performance-analysis
description: 独立完成 xLLM 模型的 CNPX 插桩、CNPerf 性能采集和结果导出。用户要求分析 xLLM 整体或指定模型模块，并输出 .cnperf-rep、CSV、JSON 时使用。
---

# xLLM CNPX/CNPerf 性能分析

本 Skill 自带 xLLM CNPX RAII Runtime、Runtime 安装器和 CNPerf 采集器，不依赖其他 Skill 或仓库。它支持全模型采集、通过 CNPX Range 精确采集指定模块，以及从已有 `.cnperf-rep` 导出 CNPerf 原生 CSV/JSON。

## 前置检查

1. 检查 `cnperf-cli --help`、版本、MLU 可见性、磁盘空间和输出目录。不要安装或升级 CNPerf/CNPX，也不要持久修改宿主环境。
2. 确认 xLLM 服务命令保持前台运行；本 Skill 只清理自己创建的进程组，不接管或终止预先存在的服务。
3. 阅读 [CNPX/CNPerf 要点](references/cnpx-cnperf-notes.md)。指定模块需要新增标记时读取 [独立插桩规则](references/instrumentation.md)；需要执行命令时读取 [工作流](references/workflow.md)；比较修改前后算子构成时读取 [对比协议](references/comparison-protocol.md)。

## 收集输入

尽量从上下文和启动脚本推导，只有关键输入缺失时才询问：

- xLLM 源码根目录、服务启动命令和构建方式；
- 模型、设备/TP/DP 配置及执行主机；远程机器应在目标环境内直接运行本 Skill 的脚本；
- 压测负载：输入长度、输出长度、batch size，以及可选的并发、请求数、地址、端口和超时；
- 分析目标：全模型，或准确的源码模块、层 ID/区间、Prefill/Decode 阶段；
- readiness URL、单次压测命令、输出目录和报告名称；
- 是否已有可用的 `.cnperf-rep`，目标启动脚本是否启用 MLU Graph。

不要因性能分析请求擅自修改模型业务参数。指定模块若位于 MLU Graph 内，普通 CNPX 层标记只覆盖 Graph capture，不代表 replay 的逐层耗时：可以标记整个 replay 作为模块，也可以征得用户同意后切换 eager 再做逐层采集；不得按时间邻近伪造图内层归属。

## 路由

### 已有 `.cnperf-rep`

执行只读离线分析，不重新启动服务、不修改 xLLM 源码：

调用 `scripts/profile_xllm.py export`。它校验报告非空，记录大小和 SHA256，并运行 `cnperf-cli report --csv` 与 `cnperf-cli timechart`。这是只读路径，不启动服务、不修改源码。

### 尚无 `.cnperf-rep`

全模型分析无需新增标记，直接调用 `scripts/profile_xllm.py run`。采集器在一个外层 `cnperf-cli record` 生命周期中启动服务、等待 readiness、执行一次压测、停止本次创建的进程组，然后导出 CSV/JSON。

指定模块分析先按 `references/instrumentation.md` 安装内置 Runtime 并在准确调用边界加入 RAII Range，重新构建 xLLM，再运行采集器并传入对应的 `--cnpx-include`。采集完成后恢复本次插桩改动；报告和日志不删除。

CNPerf 参数必须位于被追踪程序之前。普通端到端分析默认采集 kernel、memcpy、notifier 的 detail 数据，不默认启用 `--pmu`。每次运行使用尚不存在的新输出目录，不覆盖历史证据。

## 指定模块分析

使用内置 Domain `XLLM_PERF_ANALYSIS` 和线程内 RAII Range。一个分析目标使用一个稳定、无敏感信息的 Range 名，例如 `prefill.layers_3_7.moe`。采集规则为：

```text
XLLM_PERF_ANALYSIS@prefill.layers_3_7.moe/
```

需要多个模块时重复传入 `--cnpx-include`，采集器会用逗号组合规则。同一 Range 末尾的 `/` 是 CNPerf 对线程 Range 的类型标记，不是路径通配符。只有 CNPX Range 内下发的任务进入模块专属 `.cnperf-rep`；CPU 逻辑时间应从 timechart 的 Range 视图核对。

Range 必须包围真实模块调用，不能仅凭 Kernel 名、相邻时间窗或队列邻近推断所有权。选择若干层时，在业务代码中用稳定条件控制 `enabled`，让这些层共享本次分析的固定 Range 名。排除全 warmup/profile 批次，避免启动阶段污染结果。

## 产物契约

每次成功分析至少保留：

| 类型 | 产物 | 说明 |
|---|---|---|
| 原始证据 | `*.cnperf-rep` | CNPerf 原始报告，禁止用派生文件替代 |
| 原生汇总 | `csv/*.csv` | `cnperf-cli report --csv` 的函数、Kernel、内存等统计 |
| 原生时间线 | `json/*.json` | `cnperf-cli timechart` 输出 |
| 运行清单 | `manifest.json` | report 哈希、CNPX 规则、CNPerf 选项和导出文件列表 |
| 运行日志 | `server.log`、`client.log`、`cnperf_*.log` | 服务、压测、采集和导出证据 |

三个格式不是同一内容改扩展名：`.cnperf-rep` 是原始数据库，CSV 是 CNPerf 汇总统计，JSON 是 CNPerf timechart 数据。`manifest.json` 负责把它们绑定为一次运行。

## 验收与报告

完成前检查：

- `.cnperf-rep` 非空，CNPerf 退出成功，服务与压测生命周期证据完整；
- 压测日志能证明请求数、成功数以及固定输出场景的 token 数符合用户负载；
- 指定模块报告的 `manifest.json` 记录了正确的 CNPX include 规则；
- 原生 CSV 和 timechart JSON 均存在且可解析；
- 临时 Runtime 和调用点插桩已恢复，用户原有改动仍保留；
- 没有覆盖任何旧产物，也没有终止预先存在的服务。

最终用中文报告：执行环境和 CNPerf 版本、模型与负载、全模型或模块 Range、Graph/eager 模式、关键指标、异常/缺口、每类产物的绝对路径、源码恢复状态。若仅创建或验证工作流，明确说明没有执行真实 MLU 采集。

## 修改前后对比

用户需要解释候选版本的算子变化时，在冻结条件下分别采集基线与候选报告，生成 SQLite 数据库并调用 `scripts/compare_cnperf.py`。该工具只用于设备侧归因；候选接受或回退仍以同条件端到端评测、正确性和保护指标为准。
