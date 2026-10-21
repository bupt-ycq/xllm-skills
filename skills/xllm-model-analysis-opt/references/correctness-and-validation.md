# 正确性、支持范围与性能验证

## 支持矩阵

分析开始时记录修改前支持范围，至少包含：

| 维度 | 需要记录的内容 |
|---|---|
| 模型阶段 | PREFILL、DECODE、MIXED、CHUNKED_PREFILL 等实际路径 |
| 输入 | batch、sequence、hidden、head、expert、非对齐和边界 Shape |
| 数值 | dtype、量化模式、累加精度、NaN/Inf 语义、容差 |
| 存储 | Layout、stride、contiguous/非连续、别名、in-place |
| 状态 | KV cache、position、router state、随机状态和失效条件 |
| 分布式 | 单卡、TP/PP/EP/DP 拓扑、通信组和 Rank 行为 |
| 运行时 | eager、Graph Capture/Replay、Stream、JIT/autotune 缓存 |
| 平台 | MLU 型号、受支持后端，以及原有非目标 dispatch |

修改后的支持矩阵必须至少覆盖修改前集合。局部优化可以只命中特定组合，但未命中组合必须保留正确的等价路径。

## Reference 与测试

- 保留修改前语义作为 Reference，不为候选修改 Reference、输入或容差。
- 对返回值、所有原地 Tensor、cache 和隐藏状态分别比较。
- 覆盖真实常见 Case、最小/最大边界、非对齐尾块、空值、optional 分支和非连续输入。
- 测试首次调用与缓存后调用，覆盖 JIT/Graph Specialization。
- 通信改动至少验证所有 Rank 完成、Collective 顺序一致、无死锁、数值一致和超时/错误路径。
- 循环批量化要验证原执行顺序、mask/padding、ragged 输入、随机状态和累加误差。
- 复用或缓存要测试缓存命中、每一种失效键变化和跨请求/Step 不泄漏。

现有测试缺少目标行为时，获准修改的任务应先补最小回归测试，再改变实现。

## 公平性能比较

固定模型源码、权重、请求、随机性、Shape、并发、输入输出长度、并行拓扑、设备状态、预热、重复次数、同步边界和统计量。除非目标是冷启动，否则把编译、加载、autotune 和 Graph Capture 排除在稳态区间。

同时记录逐样本和中位数/分位数，不比较最好的一次。主要指标根据目标选择 TTFT、TPOT/ITL、端到端时延或吞吐，并保护：

- 输出正确性和稳定性；
- P50/P95/P99 或相关尾延迟；
- 峰值内存和 OOM 边界；
- 非目标阶段、Shape 和并行配置；
- Kernel/Collective 次数、Host 空泡和暴露通信时间。

性能收益必须超过实验噪声。只有 profile 变化而端到端指标没有可信改善时，记录为结构变化或不确定，不宣称性能提升。

## 实施循环

1. 陈述单一假设和收益上界。
2. 从当前最佳版本实现最小改动。
3. 运行格式化/静态检查和相关构建。
4. 运行支持矩阵中的最小正确性测试，再运行模型调用链测试。
5. 执行冻结 benchmark；涉及通信时增加多 Rank 和压力验证。
6. 检查保护指标和非目标场景。
7. 只有全部通过且收益可信才接受，否则回退本轮候选并记录原因。

修改 xLLM MLU 代码时遵循目标仓库的构建闸口；通常需要运行 `python setup.py build --device mlu`。如果环境缺少设备、编译器、权重或多卡资源，明确标记未执行项，输出候选和可复现命令，但不得写成通过。

