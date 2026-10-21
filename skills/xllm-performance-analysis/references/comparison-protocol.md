# CNPerf 基线与候选对比协议

本协议用于解释 xLLM 修改前后的 Kernel、拷贝和设备侧构成变化。端到端性能评测是候选接受或回退的主要依据；CNPerf 对比用于归因。

## 冻结条件

基线与候选必须使用相同的：模型与权重、请求和执行阶段、Shape、batch/并发、设备与 Rank 映射、dtype/量化、Graph/Stream、预热、CNPerf 版本、采集范围和选项。

测量轮数服从调用方冻结的工作负载和性能评测 Skill 的要求，不在本协议中另设全局固定值。传给比较脚本的轮数必须等于各自 report 有效窗口中的真实轮数；两侧轮数可以不同，但每轮工作量必须相同。

## 获取 SQLite 数据库

优先使用 `profile_xllm.py` 生成的非空 `.cnperf-rep`。检查当前版本帮助后生成数据库：

```bash
cnperf-cli generate -o <output>/baseline.db -f <baseline.cnperf-rep>
cnperf-cli generate -o <output>/candidate.db -f <candidate.cnperf-rep>
```

不同 CNPerf 版本参数不一致时，以当前 `cnperf-cli --help` 为准。归档准确命令和日志，不使用 PMU Replay 数据推断端到端收益。

## 比较

```bash
python scripts/compare_cnperf.py \
  --baseline <output>/baseline.db \
  --candidate <output>/candidate.db \
  --baseline-rounds <真实轮数> \
  --candidate-rounds <真实轮数> \
  --significant-share 1.0 \
  --output <output>/operator-diff.md
```

脚本以原始 Kernel 名称聚合 `device_task_kernel_data` 和 `string_table`，输出每轮调用次数、每轮耗时、候选占比、新增/移除 Kernel 和最大变化。只有两个数据库使用完全相同过滤条件时才使用 `--include` 或 `--exclude`。

## 解释

对每项显著变化回答：

1. 哪个准确源码调用产生该 Kernel？
2. 调用次数、Shape、Layout、算法或执行阶段是否变化？
3. 它位于关键路径还是与其他 Stream 重叠？
4. 被移除的 Kernel 是否以重命名或融合形式重新出现？
5. 成本是否转移到 memcpy、cast、Layout、同步、通信或新 Kernel？
6. 同条件端到端指标是否同方向变化且超过噪声？

新增 Kernel 不自动表示回退。只有解释其来源、替代的旧工作和完整路径结果后才能作结论。并发时 Kernel 时间总和可能超过 Wall Time，不能把 `Duration` 总和直接当作端到端时延。

## 产物

至少保留基线和候选的 command、log、`.cnperf-rep`、`.db`、manifest 及 `operator-diff.md`。PREFILL 和 DECODE 使用独立目录和结果，不混合聚合。
