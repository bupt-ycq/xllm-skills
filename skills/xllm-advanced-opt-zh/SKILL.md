---
name: xllm-advanced-opt-zh
description: 编排 xLLM 模型分析、服务性能评测、CNPerf/CNPX 设备侧分析和 Triton Kernel 开发优化。适用于用户要求完成跨多个阶段的 xLLM 端到端性能优化、回归定位或综合优化报告；单项模型分析、性能采集、服务压测或 Triton 算子任务应直接使用对应的独立 Skill。
---

# xLLM 高级性能优化编排

本 Skill 只负责任务分解、阶段顺序、产物交接和最终结论，不重复定义各专业能力的实现规则。开始前读取 [能力注册表](references/skill-registry.json)；只加载本次任务需要的 Skill。

## 权威性和冲突规则

- 每项专业工作的规则、参数、验收标准和脚本以对应独立 Skill 为准。
- 本编排与独立 Skill 冲突时，采用独立 Skill 的要求；若多个已选 Skill 的要求不同，采用不改变用户目标且更严格的正确性和证据闸口。
- 不把“编排完整流程”解释为自动授权修改代码、启动服务、安装依赖或执行高成本采集。分析请求保持只读；用户明确要求优化或实现后才修改。
- 未使用的 Skill 不必读取或调用。缺少某阶段所需环境时记录阻塞和降级路径，不伪造产物。

## 路由

优先让用户直接调用最小能力：

| 任务 | 选择 |
|---|---|
| 分析模型结构、冗余计算、循环、拷贝、同步和通信 | `xllm-model-analysis-opt` |
| 采集或导出 CNPX/CNPerf，定位模型或模块设备热点 | `xllm-performance-analysis` |
| 对运行中的 OpenAI 兼容服务测 TTFT、TPOT、ITL 和吞吐 | `xllm-performance-evaluate` |
| 创建、三轮有效优化并接入 xLLM MLU Triton Kernel | `xllm-triton-kernel-dev` |

用户要求综合优化、修改前后闭环比较或无法判断瓶颈所属层次时，使用本编排流程。新增能力按注册表中的 `invoke_when` 路由；不得仅因它已安装就无条件调用。

## 综合流程

1. **建立契约**：确认 xLLM 版本、模型、PREFILL/DECODE 阶段、负载、dtype/量化、设备和并行拓扑、主要指标、保护指标、支持矩阵及用户授权。
2. **结构分析**：调用 `xllm-model-analysis-opt` 建立调用链、数据流、通信依赖和优化候选。用户未要求深度分析时，尊重其基础阶段停止条件。
3. **冻结服务基线**：需要端到端性能结论且服务可运行时，调用 `xllm-performance-evaluate` 采集基线。轮数、EvalScope/fallback 和指标定义由该 Skill 决定。
4. **设备侧归因**：只有需要定位算子、拷贝、同步或模块热点时调用 `xllm-performance-analysis`。已有报告优先离线导出；不要为了形式完整重复采集。
5. **制定候选**：把结构证据、服务指标和设备侧证据合并为一个可证伪假设。优先消除工作量、复用结果、批量化、减少转换/同步/通信，再考虑专用 Kernel。
6. **实现候选**：普通模型路径改动遵循模型分析 Skill 的支持矩阵和验证规则。只有证据满足融合条件时调用 `xllm-triton-kernel-dev`，并完整执行其三轮有效优化和接入闸口。
7. **验证和接受**：先构建和验证正确性，再用相同条件调用性能评测 Skill 比较当前最佳版本；需要解释算子变化时调用性能分析 Skill 做相同协议的 profile 对比。失败或收益不确定时只回退当前候选。
8. **报告**：按 [跨 Skill 实验生命周期](references/experiment-lifecycle.md) 汇总各 Skill 的原始产物、已接受/拒绝假设、支持范围和后续步骤。没有同条件端到端数据时不宣称性能提升。

每次只推进一个主要假设。候选被接受后才成为下一轮基线，避免多个变更混合后无法归因。

## 产物交接

- 模型分析输出源码证据、支持矩阵、优化计划和变更验证要求。
- 性能评测输出端到端原始样本、汇总指标和成功率，作为接受或回退的主要证据。
- 性能分析输出 `.cnperf-rep`、CSV、JSON、manifest 和可选的基线/候选算子差异，作为归因证据。
- Triton 开发输出 Reference、Case Manifest、优化历史、Kernel、xLLM 接入代码和测试。
- 编排报告只引用上述产物，不复制或改写其机器可读内容。

## 扩展

项目会自动发现 `skills/` 下已注册的 Skill。新增 Skill 使用项目根目录的管理脚本：

```bash
python scripts/manage_skills.py add \
  --source /absolute/path/to/new-skill \
  --role <capability-role> \
  --order 50 \
  --when "描述何时调用"
python scripts/manage_skills.py validate
```

新增项必须保持独立 `SKILL.md` 和资源，不得通过相对路径依赖其他 Skill 的内部文件。注册后根据其描述和 `invoke_when` 按需路由，不需要修改已有专业 Skill。
