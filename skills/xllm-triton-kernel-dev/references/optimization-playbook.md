# MLU Triton 优化手册

## 使用原则

优化必须由测量证据驱动。benchmark 决定接受或回退；CNPerf、编译 IR 和生成代码用于解释瓶颈，不能替代端到端测量。每轮只选择一个主要假设，避免无法归因的大包修改。

MLU 的 NRAM、WRAM、SRAM 以及 IO/Move/Compute/Scalar 流不能机械类比 CUDA register/shared memory。`num_warps` 在 MLU 上关联 Core/XPE 映射，也不能套用 CUDA occupancy 结论。所有建议最终以目标 MLU 和当前编译器实测为准。

## 优先级一：访存与布局

- 保持最低维连续，合并连续访问，避免无规律 gather/scatter 和碎片 DMA；
- 让 load/compute/store 向量化，关注 64/128/512 字节访问粒度与对齐；
- 使用规则 shape/stride/boundary 的 block pointer（当前 Triton 版本支持时）；
- 删除重复 load/store、中间 Tensor 和多余 layout conversion；
- 评估 tile 的 NRAM 占用，防止过大 tile 产生溢出、额外搬运或并行度下降；
- 尾块用 mask/boundary_check 保证 OOB 安全，同时避免主路径承担不必要的分支。

## 优先级二：并行与配置

- 联合调优 BLOCK/tile、grid、`num_warps` 和 `num_stages`，不单独迷信某一个参数；
- 对长任务尝试 persistent grid，并验证任务分配是否均衡；
- 显式把业务数据映射到 program id，多 Core 启动不会自动正确切分数据；
- 区分小 Shape 的启动开销和大 Shape 的带宽/计算瓶颈；
- 只搜索当前 xLLM JIT 和 MLU Triton 后端真实支持的配置。

## 优先级三：融合与数据复用

- 融合 producer/consumer，消除写回再读入的中间结果；
- 把轻量后处理融合到 reduction、matmul 或主循环中；
- 在 tile 内复用公共输入和计算结果，避免跨 program 重复读取或计算；
- 融合后重新核算 NRAM、寄存/标量压力和并行度，融合并非总是更快。

## 优先级四：计算与索引

- 把循环不变量和标量计算外提，做安全的代数强度削减；
- 在索引范围可证明安全时，将 int64 地址/循环计算降为 int32；
- 对允许近似的算子，在精度契约内评估 libdevice `fast_exp`、`fast_log`、`fast_sqrt`、`fast_rcp` 或 `fast_sigmoid` 的完整模式替换；
- 重排 reduction 轴与 layout，观察是否生成高效 `sumpool`/`maxpool`；
- matmul 类算子比较 `tl.dot`、FMA 或显式 sum，联合调整 M/N/K tile，并融合后处理。

## CNPerf 与 IR 检查

可用时记录每个最佳版本的 profile，并对照理论 FLOPs、最小 IO 和实际 PMU：

- IO/Move 时间高：检查连续性、对齐、重复搬运、gather/scatter；
- Compute 时间高：检查指令选择、向量化、冗余数学和 reduction/dot 映射；
- Scalar 时间高：检查地址计算、循环控制、int64 和分支；
- Core 利用不均：检查 grid、任务粒度和 persistent 分派；
- Kernel 数量多：检查融合机会和 host launch 开销。

IR/生成代码重点查找冗余 copy、未融合后处理、低效 reduce/dot、标量化访问、流水空洞和意外的 layout conversion。若 profile 与 benchmark 结论冲突，先检查采集范围和同步，再以可复现 benchmark 为接受依据。

## 三轮示例与反例

可接受：三次累积版本分别实现连续 load、合理 tile/grid、融合冗余中间结果，且每次都独立满足精度和性能阈值。

不可接受：

- 同一代码重复测三次；
- 只改注释、变量名或格式；
- 一次完整优化拆成三个提交但中间版本无独立收益；
- 只挑变快 Case，删除变慢或失败 Case；
- 第三轮相对原始基线变快，但相对第二轮当前最佳变慢；
- 使用不同输入、warmup、统计量或环境比较两轮。
