# 精度与性能验证规范

## 精度

Reference 必须是替换前的真实语义，不得为了匹配 Triton 结果修改它。对每个 Case：

1. 从同一逻辑输入分别克隆 Reference 与候选输入；
2. 执行 Reference 和候选；
3. 同步设备后比较返回值；
4. 比较所有原地修改的 Tensor、cache 和状态；
5. 检查 NaN/Inf 规则、dtype、shape、stride（若契约要求）和设备；
6. 使用算子数值特性决定 `atol`/`rtol`，记录理由。

随机测试不能替代边界 Case。至少包含最小维度、非对齐尾块、临界 tile、真实常见 Shape 和最大可接受 Shape。对写操作使用 canary、guard 区或 sanitizer 等可用手段检查 OOB。

## Benchmark

比较必须满足：

- 同一物理设备、频率策略、软件栈和环境；
- 同一 `case_manifest.json`、输入分布和权重；
- 同一进程内交替或按稳定顺序测量当前最佳与候选；
- 编译和 autotune 不进入稳态延迟，除非目标就是首请求性能；
- 足够 warmup，测量前后执行设备同步；
- 每个 Case 重复足够次数，默认使用 median；
- 原地算子每次恢复输入，防止状态累积改变工作量；
- 同时报告逐 Case 和加权聚合结果。

默认加权聚合延迟：

```text
aggregate_latency = sum(case_latency * case_weight) / sum(case_weight)
improvement_pct = (best_aggregate - candidate_aggregate) / best_aggregate * 100
case_regression_pct = (candidate_latency - best_latency) / best_latency * 100
```

默认接受条件：`improvement_pct >= 1.0` 且每个 Case 的 `case_regression_pct <= 2.0`。阈值用于过滤噪声，不代表所有业务都应使用固定值；用户或项目有明确 SLA 时按其要求设置并记录。

## 证据完整性

每个版本保存不可歧义的候选文件及 SHA256。每轮至少保存：

- 精度日志，含 Case 总数和逐 Case 结果；
- benchmark 原始或汇总日志，含逐 Case 延迟；
- 单一主要假设和代码/config 差异说明；
- 可用时的 CNPerf 报告、关键 IR 或分析摘要；
- `accept` 或 `rollback` 结论。

优化历史校验器检查文件、哈希、Case、版本链和阈值，但它不能证明日志内容真实。执行者仍需提供可复现命令并诚实记录环境。

