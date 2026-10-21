# 跨 Skill 实验生命周期

本文件只约束多个 Skill 之间的证据交接。指标公式、采集参数、正确性标准、迭代轮数和专业产物格式由生成该产物的独立 Skill 决定。

## 目录建议

```text
<output>/
├── run-manifest.json
├── environment.md
├── plan/
│   ├── current.md
│   └── revisions/
├── model-analysis/
├── service-evaluation/
│   ├── baseline/
│   └── candidate-<id>/
├── device-profile/
│   ├── baseline/
│   └── candidate-<id>/
├── triton-kernels/
│   └── <kernel-name>/
├── iterations/
│   └── <id>-<hypothesis>/
└── final-report.md
```

只创建实际使用的目录。不要为了填满结构伪造空报告，也不要复制大型原始产物；使用绝对路径、哈希和生成者 Skill 记录引用它们。

## 运行清单

`run-manifest.json` 至少记录：

```json
{
  "schema_version": 1,
  "run_id": "稳定且不含敏感信息的标识",
  "source_revision": "源码版本",
  "workload_id": "冻结负载标识",
  "selected_skills": ["实际调用的 Skill"],
  "primary_metric": "由性能评测产物定义",
  "artifacts": [
    {
      "producer": "Skill 名称",
      "kind": "artifact kind",
      "path": "/absolute/path",
      "sha256": "文件产物可记录摘要"
    }
  ]
}
```

不要在清单中保存密钥、完整带凭据命令或用户敏感 Prompt。原始产物自己的 manifest 是权威信息，跨 Skill 清单只建立关联。

## 优化方案和修订

模型分析完成后、修改生产代码前生成 `plan/current.md`，并在 `plan/revisions/` 保存不可变版本。每个计划项记录：

- 目标阶段、源码路径和 Symbol；
- 结构或性能证据及其产物路径；
- 单一优化假设和收益上界；
- 依赖、支持范围、正确性和性能闸口；
- 回退方式和当前状态。

新的源码分析、服务指标、CNPerf 数据或候选结果改变方案时，先保存修订再继续实现。专业 Skill 的最新结论覆盖旧计划中的冲突假设。

## 候选迭代

每个候选目录记录：

```text
hypothesis.md
change.patch 或源码版本
correctness.md
service-evaluation.json 或产物引用
device-profile.md 或产物引用
decision.md
```

不要求每轮同时拥有服务评测和设备 profile：端到端指标用于接受或回退，设备 profile 仅在需要归因时采集。Triton 候选另外保留其 Skill 要求的 Case Manifest 和多轮优化历史。

每轮从当前已接受的最佳版本开始。`decision.md` 只能依据实际结果写为接受、拒绝或不确定；被拒绝修改不得泄漏到下一候选。

## 最终报告

按以下顺序汇总：

1. 结果及证据强度；
2. 冻结工作负载、环境和支持范围；
3. 实际调用的 Skill 和各自权威产物；
4. 方案演进；
5. 已接受、拒绝和不确定的改动；
6. 修改前后端到端指标；
7. 需要时的算子、拷贝、同步和通信归因；
8. 构建、正确性、Graph、分布式和内存验证；
9. 剩余风险、阻塞和后续步骤；
10. 回退方式。

没有同条件端到端数据时，只报告结构或算子层面的观察，不推断最终加速。
