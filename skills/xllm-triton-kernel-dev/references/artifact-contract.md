# 产物契约

## 推荐目录

```text
<artifact-dir>/
├── case_manifest.json
├── optimization_history.json
├── candidates/
│   ├── baseline.py
│   ├── round_01.py
│   ├── round_02.py
│   └── round_03.py
└── evidence/
    ├── baseline_accuracy.log
    ├── baseline_benchmark.json
    ├── round_01_accuracy.log
    ├── round_01_benchmark.json
    └── ...
```

路径相对 `optimization_history.json` 所在目录解析。候选文件可以是 Python Kernel，也可以是能唯一描述 Kernel 与配置的非空 bundle/manifest；其 SHA256 必须随有效实现或配置变化。

## optimization_history.json

```json
{
  "schema_version": 1,
  "benchmark_protocol": {
    "device": "MLU-...",
    "environment_sha256": "64位十六进制摘要",
    "warmup": 20,
    "repeat": 100,
    "synchronize": true,
    "statistic": "median"
  },
  "acceptance": {
    "min_effective_rounds": 3,
    "min_aggregate_improvement_pct": 1.0,
    "max_case_regression_pct": 2.0
  },
  "cases": [
    {"case_id": "case_001", "weight": 1.0}
  ],
  "baseline": {
    "candidate_file": "candidates/baseline.py",
    "candidate_sha256": "...",
    "accuracy_pass": true,
    "latency_ms": {"case_001": 0.100},
    "accuracy_log": "evidence/baseline_accuracy.log",
    "benchmark_log": "evidence/baseline_benchmark.json"
  },
  "rounds": [
    {
      "round": 1,
      "hypothesis": "使最低维访存连续",
      "input_candidate_sha256": "基线摘要",
      "candidate_file": "candidates/round_01.py",
      "candidate_sha256": "候选摘要",
      "accuracy_pass": true,
      "latency_ms": {"case_001": 0.090},
      "decision": "accept",
      "analysis_file": "evidence/round_01_analysis.md",
      "accuracy_log": "evidence/round_01_accuracy.log",
      "benchmark_log": "evidence/round_01_benchmark.json"
    }
  ]
}
```

字段约束：

- `environment_sha256` 是记录驱动、固件、编译器、xLLM/Triton 提交和关键环境的文件摘要；
- `cases` 中 `case_id` 唯一，`weight` 必须为正；每个 latency map 必须与其完全一致；
- `candidate_file`、精度/性能/分析证据必须存在且非空；摘要使用文件内容的 SHA256；
- `round` 从 1 连续递增；`decision` 只能是 `accept` 或 `rollback`；
- 每轮输入摘要必须指向当时当前最佳候选；接受轮候选成为新的当前最佳，回退轮不改变当前最佳；
- 接受轮必须精度通过、候选摘要发生变化，并满足聚合提升和逐 Case 回退阈值；
- `min_effective_rounds` 不得低于 3；只有接受轮计入有效轮次。

运行校验：

```bash
python <skill-dir>/scripts/validate_optimization_history.py \
  <artifact-dir>/optimization_history.json
```

成功返回码为 0；失败返回码为 1 并逐条输出错误。`--json` 可输出机器可读结果。

