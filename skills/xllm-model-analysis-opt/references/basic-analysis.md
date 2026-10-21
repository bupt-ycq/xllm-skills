# 基础模型分析方法

## 分析产物

先建立一张热点与数据流台账。每个条目记录源码路径和 Symbol、调用者/消费者、执行阶段、Shape/dtype/Layout、执行次数、Tensor 生命周期、设备、Stream、Rank、计算量、读写字节、同步和初步风险。结论必须能回到具体代码，不把命名相似当作语义相同。

## 1. 重复计算与结果复用

从相同表达式、重复函数调用和同源 Tensor 变换开始，向上追踪输入和向下追踪消费者。常见候选包括重复 Mask/Position/Index、RoPE 参数、Shape 推导、类型/Layout 转换、归一化统计量、路由信息和每 Token 不变值。

只有同时证明以下条件才能复用：

- 输入值、Shape、dtype、device、Layout 和数值模式一致；
- 结果在所选生命周期内不会被原地修改或别名写入；
- 缓存键覆盖 batch、sequence、device、stream、rank、配置和所有影响结果的状态；
- 失效时机明确，不会把请求、Layer、Step 或模型版本之间的数据错误共享；
- 缓存内存、维护和同步成本小于节省的计算与搬运。

优先做“直接消除重复工作”和“在最窄安全生命周期内提取不变量”，不要先引入全局缓存。

## 2. 无用返回与数据处理

对 tuple、结构体和临时 Tensor 的每个字段建立消费者列表。检查：

- 生成后无人读取的返回值、统计量、调试输出和状态副本；
- 仅为包装接口而进行的 reshape、cast、clone、contiguous、split/concat；
- 先物化完整结果、下游却只取切片或单字段的路径；
- 同一数据在 Python/C++/设备接口间反复打包和解包；
- 能延迟计算、按需返回或直接写入最终目标的中间结果。

删除返回值前搜索所有静态与动态调用者，并覆盖 optional 分支、插件/模型变体、Graph Capture 和调试模式。接口兼容需要保留时，可先消除内部物化而保持外部签名。

## 3. 循环批量化

识别按 Token、Head、Expert、Layer、Request、Beam 或 Rank 展开的循环。为每个循环确认迭代是否独立、Shape 是否一致、是否有原地写、提前退出、随机状态或跨迭代依赖。

候选重写包括 batched Tensor 操作、stack 后一次执行、segment/padded batch、向量化索引、grouped GEMM、批量通信和单 Kernel 内部循环。比较时同时考虑：

- padding 与 mask 增加的无效 FLOPs；
- ragged Shape 的索引和临时内存；
- batch 后峰值内存、首 Token 延迟和调度公平性；
- 原有执行顺序、累加顺序和数值误差变化；
- Kernel 发射减少是否被更差的并行度或 Layout 抵消。

## 4. 拷贝、转换与同步

搜索并追踪 `to`、`copy`、`clone`、`contiguous`、dtype cast、Host 标量读取、显式 synchronize、Event wait、阻塞 Collective、临时 buffer 和隐式设备转换。区分：

- 语义必需的数据迁移；
- 为不兼容 Layout/dtype 产生的适配搬运；
- 可通过保持上游 Layout、复用 buffer 或直接写目标位置消除的搬运；
- 只为 Host 控制流读取设备值而产生的全局同步；
- 本可使用 Stream/Event 局部依赖却采用全设备同步的路径。

消除同步前必须建立生产者—消费者关系；异步并不自动正确，也不自动缩短关键路径。

## 5. 通信方案与通信计算组合

先确定语义：每个 Rank 需要完整结果、分片结果还是仅目标分片；随后计算 payload、参与 Rank、调用频次和关键路径暴露时间。比较 AllReduce、ReduceScatter+AllGather、AllGather+本地计算、Scatter/Reduce、AllToAll、P2P、分层 Collective，以及张量并行和专家并行中的融合计算通信方案。

优先顺序不是固定 API，而是：满足语义 -> 通信字节更少 -> 中间结果更少 -> 可与足够计算窗口重叠 -> 拓扑利用合理。详细方法见 [communication-overlap.md](communication-overlap.md)。

## 6. 通信计算重叠

把 Collective 分为 launch、传输和 wait，寻找 launch 后、wait 前与通信结果无依赖的计算。检查分块、Microbatch、异步 Collective、多 Stream、双缓冲和分阶段 GEMM/Collective 的可能性。只优化暴露在关键路径上的通信；已经被完全掩盖的通信即使自身耗时较长，也不是首要目标。

## 补充分析角度

- **算法与数据结构**：是否存在复杂度更低或避免全量物化的等价算法。
- **执行阶段**：PREFILL 和 DECODE 的 Shape、带宽、发射和缓存瓶颈应分别判断。
- **算子碎片**：大量小算子、Python/C++ 循环和调度开销是否主导端到端时间。
- **内存生命周期**：临时分配、峰值内存、碎片、buffer 复用和 in-place 的收益与别名风险。
- **Layout 与 dtype**：连续化、转置和升降精度是否在相邻算子间往返发生。
- **Shape 与 Graph**：动态 Shape、分支和 Specialization 是否导致重复编译或 Graph Replay Miss。
- **负载均衡**：Token、Expert、Rank、Pipeline Stage 或设备间是否存在长尾和空泡。
- **Host 路径**：锁、队列、序列化、日志和 Python 控制流是否让设备饥饿。
- **重计算与物化**：比较保存中间结果的内存/通信成本和按需重计算成本。

## 候选排序

为每个候选记录收益上界和置信度。通常优先：消除无用工作 -> 安全复用 -> 批量化和减少发射 -> 消除转换/拷贝/同步 -> 减少通信量 -> 掩盖暴露通信 -> 融合或专用 Kernel -> 调度和 Graph 重构。实际顺序必须服从证据，而不是固定模板。

