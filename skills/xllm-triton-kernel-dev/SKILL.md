---
name: xllm-triton-kernel-dev
description: 为 xLLM 的寒武纪 MLU 执行路径创建、优化、验证并接入 Triton 算子。适用于把 xLLM 中指定的 Python/C++/Torch 计算片段改写为 MLU Triton Kernel，补齐 C++ JIT Wrapper、公共 API 与调用替换，或继续优化已有 xLLM Triton 算子；接入前强制完成替换前后精度验证和至少三轮可复核的有效性能优化。不用于 CUDA Triton、孤立于 xLLM 的通用算子实验或仅做性能采集的任务。
---

# xLLM Triton 算子开发

## 不可违背的约束

- 本 Skill 的专用运行资源必须全部位于当前目录。不得从当前目录外导入专用脚本、模块、编排文件或运行时；除目标 xLLM 仓库和任务所需的编译、测试及性能工具外，不得增加外部前置条件。
- 只面向 xLLM 的 MLU Triton JIT 路径。开始修改前，读取目标仓库的 `AGENTS.md` 及其引用的代码规范；仓库规则优先。
- 先固定原实现、输入域、精度标准和性能协议，再写 Kernel。不得修改 Reference、容差、输入分布或计时边界来制造通过或提速。
- 新算子接入 xLLM 前必须累计至少三轮**有效且已接受**的优化。尝试次数不等于有效轮次；无提升、精度失败或回退超限的轮次必须回退且不计数。
- 若目标硬件、编译器或可运行测试环境缺失，允许生成未接入候选和操作说明，但不得声称完成真实优化，也不得替换生产调用路径。
- 不得通过固定 seed、Case ID、指针地址、缓存旧输出、跳过计算或把工作移出计时区间进行投机特化。

## 工作流

1. **确认范围**：定位目标调用链、原实现、输入/输出、原地状态、dtype、shape、stride、布局、可选参数和动态边界。创建 `case_manifest.json`，它是 Case 范围的唯一事实来源。详细步骤见 [workflow.md](references/workflow.md)。
2. **建立基线**：保留可直接调用的 Reference；在同一设备进程中完成预热、同步和重复测量，记录逐 Case 精度与延迟。基准规范见 [correctness-and-benchmark.md](references/correctness-and-benchmark.md)。
3. **实现算子**：在 `xllm/core/kernels/mlu/triton_kernel/` 创建 Python Kernel，并按需实现 C++ `JITKernel` Wrapper、MLU API、跨平台 dispatch 和真实调用替换。参数顺序、`tl.constexpr`、grid 和 autotune 约束见 [xllm-integration.md](references/xllm-integration.md)。
4. **验证候选**：对 Manifest 中全部 Case 做 Reference 对比、原地状态检查、尾块/OOB、非连续布局、缓存复用和调用链测试。任何 Case 失败都先修复，禁止静默移除。
5. **逐轮优化**：每轮只验证一个主要假设，产生实际代码或配置变更，并以当前最佳版本为对照执行全量精度和同协议 benchmark。根据 [optimization-playbook.md](references/optimization-playbook.md) 依次检查访存、并行、融合、计算和 IR/CNPerf 证据。
6. **执行三轮闸口**：把基线、每次尝试、哈希、日志和结论写入 `optimization_history.json`。默认要求每轮加权聚合延迟改善至少 `1%`，任一 Case 回退不超过 `2%`；用户给出阈值时采用用户阈值。用以下命令验证：

   ```bash
   python <skill-dir>/scripts/validate_optimization_history.py \
     <artifact-dir>/optimization_history.json
   ```

   只有校验通过才能执行第 7 步。数据格式见 [artifact-contract.md](references/artifact-contract.md)。无法获得三轮有效优化时，停止接入并报告已接受轮次、失败假设和阻塞原因。
7. **接入 xLLM**：从当前最佳候选接入，保留清晰的 API 边界；不得增加静默 fallback 或吞异常。完成直接 Kernel 测试和实际 xLLM 调用链回归。
8. **交付验证**：运行目标测试、优化历史校验、静态检查以及 `python setup.py build --device mlu`。仅文档变更可跳过 MLU 构建。记录无法运行的项目和原因，不得把未运行写成通过。

## 有效优化轮次判定

一次尝试仅在同时满足以下条件时记为有效：

- 输入哈希等于当时当前最佳版本哈希，候选哈希与输入哈希不同；
- 使用同一设备、软件环境、Manifest、warmup、repeat、同步方式和统计量；
- Manifest 中所有 Case 均存在且精度通过，证据文件非空；
- 相对当前最佳版本的加权聚合延迟改善达到阈值；
- 任一 Case 的性能回退不超过阈值；
- `decision` 为 `accept`，接受后该候选成为下一轮基线。

`rollback` 轮次应保留，便于复核优化过程，但不进入已接受版本链，也不计入三轮。

## 交付内容

- 目标范围和 `case_manifest.json`；
- Reference、Triton Kernel、xLLM Wrapper/API/调用替换及测试；
- 基线和所有优化轮次的精度、性能、CNPerf/IR（若可用）证据；
- `optimization_history.json` 及校验器通过结果；
- 三轮有效优化的逐轮假设、变化、结果和累计收益；
- 构建与回归结果，以及剩余风险。
