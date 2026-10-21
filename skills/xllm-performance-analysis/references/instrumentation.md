# xLLM 指定模块独立插桩

仅在用户要求指定源码模块、层或阶段，而且现有代码没有可直接用于 CNPerf filter 的 CNPX Range 时使用本页。本流程只依赖当前 Skill 的 `assets/` 和 `scripts/`。

## 1. 确定执行边界

先从真实服务启动命令解析模型路径、设备、TP/DP、Graph 开关和模型参数，再在该模型实际执行路径中定位目标调用。使用 `rg` 搜索模型类、layer loop 和 `forward`，确认：

- Range 包围的是目标调用本身，而不是配置解析、张量准备或异步等待；
- 目标调用确实由本次服务命令执行；
- Prefill/Decode 是否共用调用点；
- layer ID/区间条件在当前作用域可用；
- 是否能识别全 warmup/profile 批次。

若启用了 MLU Graph，普通层调用只在 capture 时执行，replay 时不会再次执行。此时只能选择：

1. 在真实 Graph replay 调用外标记整个图的聚合耗时；
2. 征得用户同意后关闭 Graph，以 eager 模式测指定层；
3. 停止并说明逐节点 Graph ownership 不在本 Skill 当前能力内。

不得把 Graph capture 的单次层标记报告成稳定 replay 层耗时。

## 2. 保护源码状态

优先在专用于性能采集的 disposable Git worktree 中构建，避免污染用户工作树。若必须使用当前工作树：

- 在编辑前记录 `git status --short`、HEAD 和所有将修改文件的 SHA256；
- 保留用户已有改动，不覆盖、不格式化无关代码；
- 只恢复本次插入的 include、Range 和 Runtime 文件；
- 恢复后再次核对基线 status 和原有 dirty 文件内容。

存在无法与用户改动安全分离的重叠编辑时停止，请用户选择 disposable worktree 或明确处理方式。

## 3. 安装内置 Runtime

```bash
python /absolute/path/to/xllm-performance-analysis/scripts/instrumentation_runtime.py \
  manifest

python /absolute/path/to/xllm-performance-analysis/scripts/instrumentation_runtime.py \
  install --source-root /absolute/path/to/xllm

python /absolute/path/to/xllm-performance-analysis/scripts/instrumentation_runtime.py \
  check --source-root /absolute/path/to/xllm
```

安装目标固定为：

```text
xllm/core/common/xllm_cnpx_range.h
```

安装器遇到同名但哈希不同的文件会拒绝覆盖。头文件只在 `USE_MLU` 下包含 `cnpx.h`；CNPX 手册说明无需额外链接库。

## 4. 放置 RAII Range

在目标源码加入：

```cpp
#include "xllm/core/common/xllm_cnpx_range.h"
```

在准确调用边界构造 Range：

```cpp
const bool profile_selected_layers =
    !all_requests_are_warmup && layer_id >= 3 && layer_id <= 7;
xllm::performance_analysis::ScopedModuleRange module_range(
    profile_selected_layers, "prefill.layers_3_7.moe");
layer->forward(...);
```

示例中的谓词和调用名必须根据当前 revision 的真实变量改写，不能照抄不存在的标识符。遵守以下约束：

- 使用固定 Range 字符串，不在热路径拼接 layer 名；
- 同一次目标分析的所有选中层可共享一个名称；
- Prefill/Decode 需要分开报告时使用两个固定名称和互斥条件；
- 仅将 CNPX 逻辑放进谓词，不改变模型执行、流、队列、同步或张量；
- warmup/profile 判断应基于当前 revision 的真实请求标识；无法可靠判断时在报告中明确启动阶段污染风险；
- 不使用手工 Push/Pop，确保异常和提前返回时仍由 RAII 配对。

Domain 固定为 `XLLM_PERF_ANALYSIS`。对应 include 规则为：

```text
XLLM_PERF_ANALYSIS@prefill.layers_3_7.moe/
```

末尾 `/` 告诉 CNPerf 这是同线程 Range。若只想保留 Range 栈顶的数据，可按手册使用 `]`，但必须先通过小规模采集确认嵌套关系。

## 5. 构建和验证

使用 xLLM 当前 MLU 构建方式重新编译，并证明服务命令加载的是这次构建产物。至少检查：

- `git diff --check`；
- 目标文件能找到内置头文件；
- MLU 构建成功，非 MLU 编译分支没有未使用变量错误；
- 服务 readiness 正常；
- 小规模采集的 timechart 中出现 Domain 和 Range；
- 使用 include 规则后 report 非空，且 Kernel/内存任务数量与目标范围合理。

若 include 后 report 为空，不要移除过滤并把全模型数据冒充模块数据。先检查调用点、谓词、Range 名、Graph 模式和 CNPerf filter 语法。

## 6. 恢复

采集完成后先恢复调用点 include 和 RAII 代码，再安全移除 Runtime：

```bash
python /absolute/path/to/xllm-performance-analysis/scripts/instrumentation_runtime.py \
  remove --source-root /absolute/path/to/xllm --confirm
```

移除器仅删除与 Skill 资产 SHA256 完全一致的目标文件。若哈希不同，它会拒绝删除；此时保留现场并人工确认，不要强制移除。最后核对用户原有改动仍在、没有新增插桩残留，报告和日志仍保留在源码树之外。
