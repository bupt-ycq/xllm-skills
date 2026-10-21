---
name: model-architecture-html
description: 为大模型生成或更新独立 HTML 架构图，提供论文式 SVG 计算海报、彩色模块流程详解、张量与缓存说明，以及缩放和 SVG/PNG 导出。适用于模型结构调研与可视化；不用于模型移植或性能压测。
---

# 模型架构图谱

交付离线可打开的单文件 HTML。默认按宽度展示可缩放的论文式架构海报，允许纵向滚动；“查看全图”用于检查整体布局。点击“阅读详解”进入有概览指标、模块导航、计算流程和来源的阅读视图。**海报展示紧凑拓扑，详解按分支重新组织计算与说明；两者不是同一幅 SVG 的不同缩放。**

## 工作流程

1. **确定任务输入。** 新建时以模型标识、官方资料及用户提供的参考为输入。更新时先读原文件并保留有价值的结构。模型版本歧义会改变结构时才询问。若用户要求独立/无历史验证，只使用本 skill、该次请求和新获取的官方资料，不读先前产物或调研结论。
2. **核对事实。** 读 [evidence.md](references/evidence.md)。固定模型配置与 forward 的 revision，整理来源、形状、层调度、状态和未确认项。联网核实新模型。模型显示名、架构类名、model_type 分别记录。
3. **建立计算图。** 先列主干、逐层类型、特殊注入点和各模块运算 DAG，再决定空间布局。海报主干画代表层的子层运算与最小重复周期；完整层号和来源关系放详解层网格，不能用数十个层类型条替代计算主干。注意残差、共享专家、门控/value支路和缓存读写，不能为了套版改动计算语义。
4. **落实视觉风格。** 读 [design.md](references/design.md)、[components.md](references/components.md)，查看 [样式样张](assets/style-reference.png)。样张仅演示视觉语法；模型事实须重新查证。使用 `poster.py` 绘图组件和 `theme.json` 的统一语义色，或实现相同视觉语法的原生 SVG。默认窄中央主干、宽双侧展开、彩色实心运算块、虚线模块边界、显式分叉与汇合。
5. **编写可视化详解。** 读 [details.md](references/details.md)，查看 [详解概览](assets/details-style-reference.png)、[模块排版](assets/details-module-reference.png) 并使用 [组件样例](assets/details-example.html)。优先用 HTML 并列分支，把形状、局部公式和说明放进对应分支；交叉连线复杂的局部可用独立设计的内联 SVG。不要复制整个海报面板为全宽大图后再堆正文。准备 `meta.json` 的概览指标及短导航标签。
6. **组装并验收。** 使用下面的构建脚本。静态检查后运行浏览器检查并保存截图；按 design.md 检查默认宽度视图、全图、密集局部及详解。用户给出参考作品时，在相同视口与显示模式下对比，记录比例、主干粒度、分支组织的差异。检查脚本的视觉提示并逐项解释或修正；脚本通过不代表视觉达标。
7. **交付。** 保存到指定路径，给出文件链接、可用交互、实际验证范围和影响理解的未确认项。无需部署模型服务或执行 xLLM 编译。

## 文件和命令

模型专属内容放在任务工作目录，**不要写入 skill 内**。skill 本身不含任何目标模型的固定尺寸、论文结论或完成版架构图。

```bash
python <skill-dir>/scripts/build_atlas.py \
  --poster <work>/poster.svg --details <work>/details.html \
  --meta <work>/meta.json --title '模型名称 · 模型结构' \
  --output <目标路径>/model-architecture.html
python <skill-dir>/scripts/validate_atlas.py <目标路径>/model-architecture.html
python <skill-dir>/scripts/validate_atlas.py <目标路径>/model-architecture.html \
  --browser --artifacts <work>/validation
```

- `scripts/poster.py`：可导入的原生 SVG 组件；语义配色、虚线面板、实心节点、端口连线、运算汇合、缓存框。详见 components.md。节点会因内容增高，连线应使用返回的 Box 端口，排版预留余量。
- `assets/theme.json`：海报与详解共用的语义色。`assets/atlas-shell.html`：深色概览、指标卡、粘性导航、流程组件、形状/缓存开关、缩放/拖拽/导出/打印。复用模板，模型内容通过输入文件填入。
- `scripts/build_atlas.py`：组装并校验输入；`meta.json` 内容转义，详解为可信的自写 HTML 片段，允许原生内联 SVG，不含 html/head/body/script。
- `scripts/validate_atlas.py`：ID、映射、外链资源、交互、窄屏、导出、图内文字边界、截图与打印。浏览器模式需要 Playwright 与 Chromium；优先使用已有环境，可通过 `--browser-executable` 指定现有浏览器。
- `scripts/render_style_sample.py`：可重建的虚构符号样张，用于验证组件与模板，不是生成目标模型的起点数据。

## 输出约定

`poster.svg` 使用正的 `viewBox="0 0 W H"`、title/desc、白底和内嵌样式。用原生 text/tspan、rect、path、circle 绘制，避免 foreignObject、外链素材和文本栅格化。

可导航模块：`<g data-detail="attention" role="button" tabindex="0" aria-label="Attention 详解">…</g>`，对应详解 `<section id="attention">…</section>`。ID唯一。details组件可以显示逻辑张量、原生表格和公式；正文必须在无JS时可读，交互仅做增强。

## 完成标准

- 固定版本证据与完整计算图一致，已确认/推导/部署策略/待确认可区分。
- 主干是层堆叠，模块是节点和边；彩色节点内是短操作名，长解释在图外。
- 残差、并行gate/value、缓存读写、可选路径清楚；连线落在端口，汇合不悬空。
- 详解包含实际流程组件、模块配色、公式/状态块，不只是普通文章。
- 全图比例协调；局部标签不溢出、文字不重叠、箭头不穿文字；移动端和打印可用。
- 记录真实检查结果；没有进行模型推理时，不声称精度、吞吐或显存实测通过。
