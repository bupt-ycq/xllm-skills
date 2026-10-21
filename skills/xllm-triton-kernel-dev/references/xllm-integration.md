# xLLM MLU Triton 接入规范

## 文件与打包

典型 Python Kernel 位置：

```text
xllm/core/kernels/mlu/triton_kernel/<kernel_name>.py
```

xLLM 的 `setup.py` 会将该目录中的 Kernel 暂存并打包。C++ 中应使用安装后可导入的 dotted module path，例如：

```text
xllm.core.kernels.mlu.triton_kernel.<kernel_name>
```

禁止使用构建机绝对路径。新增 Python/C++ 文件时遵循仓库版权头、命名、格式化和类型注解要求。

## Python Kernel 与 C++ JIT Wrapper

典型 C++ 调用：

```cpp
JITKernel& kernel = JITKernel::get(
    "xllm.core.kernels.mlu.triton_kernel.<kernel_name>",
    "<kernel_function>");

kernel.launch(
    static_cast<void*>(queue),
    {grid_x, grid_y, grid_z},
    {/*num_warps=*/1, /*num_stages=*/1},
    tensor_arg,
    scalar_arg,
    constexpr_arg);
```

接入时检查：

- Python 函数参数与 C++ `launch()` 参数数量、顺序和类型严格一致；
- `tl.constexpr` 参数由参数位置识别并在编译期特化；
- Tensor、`optional<Tensor>`、`nullptr` 和算术标量使用 JIT 参数打包器支持的形式；
- 对不应生成大量变体的 runtime scalar 使用运行时已有的 `do_not_specialize` 机制；
- grid 维度与 Kernel 内 program id 解释一致；MLU 后端启动前会按 `num_warps` 调整 `Grid.x`，不要重复放大；
- 配置必须来自当前 xLLM Runtime 支持的搜索空间或真实验证，不照搬 CUDA 参数经验。

查阅当前仓库实现，而不是假定接口不变：

```text
xllm/core/triton_jit/include/jit_kernel.h
xllm/core/triton_jit/include/types.h
xllm/core/triton_jit/include/spec.h
xllm/core/triton_jit/include/arg_pack.h
xllm/core/triton_jit/scripts/triton_compile.py
xllm/core/triton_jit/src/jit_kernel.cpp
xllm/core/triton_jit/src/mlu_backend.cpp
```

## API 与调用替换

C++ Wrapper 通常放在 `xllm/core/kernels/mlu/<op>.cpp`。按目标调用链决定是否修改：

```text
xllm/core/kernels/mlu/mlu_ops_api.h
xllm/core/kernels/ops_api.h
xllm/core/kernels/ops_api.cpp
```

保持已有设备 dispatch 风格，不给非 MLU 路径引入 MLU 头文件或链接依赖。用固定宽度整数、显式 `static_cast` 和仓库现有 `CHECK` 风格验证输入。不要用 catch-all 异常或静默退回原实现掩盖失败。

## Autotune 与 Graph Capture

- 可使用 `JITKernel::set_autotune()` / `autotune()` 搜索受支持的 `num_warps`、`num_stages` 或 constexpr 配置。
- autotune 前要定义可重复输入；原地 Kernel 必须恢复输入，避免不同配置读取不同状态。
- graph capture 中可能跳过 autotune，因此在 capture 前完成 warmup/tune，确认目标配置已缓存。
- 报告最终选定配置和覆盖的 Shape；若不同 Shape 分派不同配置，测试全部分支。

## 测试位置与覆盖

测试通常位于 `tests/core/kernels/mlu/`，并登记到对应 `CMakeLists.txt`。至少覆盖：

- Reference 与 Triton 输出 `allclose`；
- 所有原地 Tensor 和隐藏状态；
- dtype、shape、stride、optional 参数；
- 非对齐 Shape、尾块、最小/最大合法维度；
- JIT 缓存后的第二次调用；
- 相邻内存 canary 或等效 OOB 检查；
- 实际 xLLM 调用链，而不只直接调用裸 Kernel。

