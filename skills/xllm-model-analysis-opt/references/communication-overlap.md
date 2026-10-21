# 通信方案与计算重叠分析

## 建立通信台账

对每个 Collective 记录：源码位置、PREFILL/DECODE 阶段、通信组、Rank 数 `p`、Tensor 元素数和字节数 `n`、调用次数、同步/异步模式、Stream、输入生产者、结果消费者以及在关键路径上暴露的时间。

区分算法字节量、链路实际流量和端到端暴露时间。不同实现和拓扑的系数不同，不能只用理论公式代替实测；理论值用于筛掉明显不合理的候选。

## 比较候选语义

先回答每个 Rank 最终需要什么：

- 全量规约结果：常见候选是 AllReduce，或可与后续分片计算组合的 ReduceScatter + 按需 AllGather。
- 分片规约结果：优先评估 ReduceScatter，避免先 AllReduce 再切片。
- 收集参数/激活后做矩阵计算：比较 AllGather + GEMM 与分块 AllGather/GEMM 流水，或支持时的计算通信融合。
- Expert/Token 重分布：比较 AllToAll、分层 AllToAll、按目标 Rank 压缩/排序以及本地路由计算。
- Pipeline 传递：比较整块 P2P 与 Microbatch/Chunk 流水，注意 Bubble 和小消息开销。

比较维度包括总字节、小消息数量、中间 Tensor、拓扑匹配、额外计算、峰值内存、可分块性、可重叠窗口和数值语义。不能为了降低理论字节而引入更长串行依赖。

## 依赖 DAG

把目标区间表示为：

```text
输入计算 -> Collective Launch -> 通信进行中 -> Wait/首次消费 -> 后续计算
```

列出 launch 后可以执行的所有节点。一个计算只有在不读取 Collective 输出、不覆盖通信输入/输出 buffer、不依赖同一互斥资源，并且所有 Rank 保持一致调用顺序时，才是合法 overlap 候选。

可尝试：

- 把与通信结果无关的后续计算移动到 wait 前；
- 将 Tensor 分块，使第 i 块通信与第 i+1 块计算流水；
- Microbatch 之间交错计算与 Collective；
- 独立 Stream + Event 建立局部依赖，替代全设备同步；
- 双缓冲避免下一块写入仍在通信的 buffer；
- 将规约结果直接交给消费算子，减少中间物化和同步。

## 实施检查

改动前再次确认：

- 通信库和 API 确实支持异步，返回句柄的生命周期正确；
- 输入 buffer 在通信完成前保持有效且不被写入；
- 消费 Stream 等待正确 Event/Work，而不是依赖偶然的默认 Stream 顺序；
- 所有 Rank 的 Collective 次序、Shape 和通信组一致，无条件分支导致死锁；
- Graph Capture/Replay 支持相关通信、Stream 和 Event；
- overlap 不会因争用计算核心、内存带宽或链路而使计算和通信都变慢；
- 错误传播、超时和退出路径不遗留未完成 Work。

## 验证指标

同时报告：Collective 自身时间、暴露通信时间、相邻计算时间、端到端时延/吞吐、峰值内存和各 Rank 长尾。判断 overlap 是否成功应看关键路径缩短，而不是仅看异步 API 已调用。

