# xLLM MLU 运行时与 Graph 补充分析

仅在基础分析发现 Graph、调度、Host 空泡、Shape Specialization 或 MLU 资源利用问题时读取。本文件补充模型分析方法，不替代主 Skill 的支持矩阵和正确性要求。

## Graph 和 Shape

检查 Decode Graph、Prefill Piecewise Graph、无 Padding Graph、Bucket 覆盖和 Replay Miss。一个 Bucket 必须覆盖所有会改变以下内容的维度：

- Kernel 选择、Grid 或 Workspace；
- Token/Task 数、Block Table 和序列元数据解释；
- 通信规模、通信组或参与 Rank；
- Host 侧 Tiling、Planning 和分支；
- JIT Signature 或需要重新 Autotune 的参数。

安全的动态数据可以写入地址稳定的 Device Buffer；执行路径本身变化时应增加 Bucket 维度或保留明确 Graph Break。不要只因 Graph 功能存在就启用，必须比较 Capture 成本、命中率、Replay 收益和内存代价。

## Host 和调度

Timeline 出现短 Kernel 之间的空泡时，检查 Python/C++ Dispatch、Shape 查询、设备标量读取、分配器、锁、队列、日志和重复发射参数计算。把首次 JIT、Module Load、Autotune、Graph Capture 和分配器预热与稳态路径分开分析。

调度重叠、预测执行或多 Stream 只有在目标请求长度和负载能够摊销额外 Step，并且依赖 DAG 证明关键路径缩短时才成立。不同 Stream 同时出现非零耗时不等于成功 overlap。

## MLU 证据

结合当前设备和工具实际提供的指标区分：

- IO/DRAM 事务和连续性；
- 片上搬运和 Layout 转换；
- SIMD/VFU/LT 等计算利用；
- Mask、Index、Branch 和指针计算带来的 Scalar 工作；
- 软件流水、同步、Grid/Core 利用和尾部不均衡。

将理论最小读写量和 FLOPs 与实测数据比较。低带宽可能来自小事务、Stride 或 Latency，高计算利用也可能包含超出算法下界的冗余工作。不要套用 CUDA Warp、Shared Memory 或 Occupancy 公式替代 MLU 实测。

## 不安全捷径

拒绝以下候选：

- 仅因当前负载未命中就删除公共正确性路径；
- 为单个 Shape 硬编码但没有显式 Guard 和等价路径；
- 未经授权降低精度、量化标准或容差；
- 用移动同步制造潜在数据竞争；
- 把请求可变数据缓存到其安全生命周期之外；
- Microbenchmark 变快但端到端或保护指标回退；
- 只报告旧热点消失，隐藏新增转换、同步或高耗时算子。
