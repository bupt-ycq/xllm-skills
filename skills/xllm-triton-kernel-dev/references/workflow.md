# 端到端工作流

## 1. 发现目标与仓库约束

先确定 xLLM 仓库根目录，读取根目录及目标文件路径上所有适用的 `AGENTS.md`。若存在 xLLM 自带代码审查规范，也一并读取。随后用代码搜索还原：

```text
上层模型/层调用
  -> 公共 kernels API 或设备 dispatch
  -> MLU 实现
  -> 原始 Torch/ATen/C++ 计算
```

列出将修改的文件和不会修改的边界。不要顺手重构无关代码。

## 2. 建立算子契约

创建 `case_manifest.json`，至少包含：

- 算子名、Reference 入口和目标调用入口；
- 每个 Case 的稳定 `case_id`、shape、dtype、device、layout/stride；
- 标量、`optional` 参数、原地修改的 Tensor 和返回值；
- 动态维度范围、空 Tensor、非对齐维度、尾块和极值输入；
- 精度方法、`atol`、`rtol`、需要逐元素或统计检查的字段；
- 性能权重和真实业务来源。

Manifest 一经建立，在同一次优化比较中不得静默变化。确需修改时，重新采集基线并说明原因。

## 3. 基线与最小实现

1. 固化可独立执行的原实现 Reference。
2. 验证 Reference 的输入不会被前次测量污染；原地算子每次重新构造输入。
3. 记录逐 Case 正确性和基线延迟。
4. 设计 grid、tile、mask、布局和 `tl.constexpr`。
5. 先写语义直接、边界安全的 Triton 版本，不在首版叠加多个未经验证的优化。
6. 对全部 Case 编译并比较 Reference；失败 Case 不得从 Manifest 删除。

## 4. 优化循环

每轮使用固定模板记录：

```text
假设：从 benchmark、CNPerf 或 IR 得出的单一主要瓶颈判断
修改：代码/config 的具体变化
精度：全部 Case 的结果和日志
性能：相对当前最佳版本的逐 Case、聚合结果
结论：accept 或 rollback
后续：下一项最高价值假设
```

每轮从当前最佳版本出发。候选通过全 Case 精度后再测性能。若结果低于改善阈值或单 Case 回退超限，回退到当前最佳版本，但保留该轮记录。重复直到至少三轮被接受。

三轮必须是三个依次累积的有效变更，例如：

1. 访存连续化和边界处理简化；
2. 基于实测调整 tile/grid/warps/stages；
3. 融合中间结果并删除冗余 IO。

这只是示例，不能为了凑轮次拆分无意义修改。若一个候选同时包含多个不可分割变化，可算一轮，不可虚报多轮。

## 5. 接入与收尾

仅把通过三轮闸口的当前最佳版本接入生产调用路径。接入后重新执行：

- 裸 Kernel 与 Reference 对比；
- C++ Wrapper 测试；
- 实际模型/层调用链测试；
- 优化历史验证器；
- xLLM MLU 构建。

接入后性能如与独立 benchmark 显著不一致，检查额外 Tensor 转换、同步、编译、autotune 和 graph capture，不得只报告裸 Kernel 数据。

