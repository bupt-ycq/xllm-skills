# 绘图组件与构建接口

`poster.py` 只提供样式原语，不包含任何模型事实。推荐在任务工作目录创建生成脚本：

```python
import sys
sys.path.insert(0, '<skill-dir>/scripts')
from poster import Poster
p = Poster(2600, 2300, '目标模型', '由官方配置核实的关键结构')
with p.panel('attention', 1600, 180, 960, 760,
             'Attention · 模块标题', '输入/输出概要', theme='attention'):
    # 模块内部默认与主干一样自下向上；真实分支由已核实的计算图决定。
    a = p.node(1680, 760, 350, 65, 'Input Projection', 'attention', sub='[T,D] → [T,H,d]')
    b = p.node(1680, 640, 350, 65, 'Normalization', 'attention')
    p.connect(a, b)  # 使用返回对象的真实边界端口
p.save('<work>/poster.svg')
```

API：

- `Poster(width,height,title,subtitle,direction='主干自下向上')`
- `panel(detail_id,x,y,w,h,title,subtitle='',theme='neutral')`：上下文管理器，虚线边框+导航属性；标题区预留约90px。
- `node(x,y,w,h,label,theme='neutral',sub='',pale=False) -> Box`：饱和色短操作节点；按估计宽度换行，并在需要时**增高**。不要假定实际h与传入h一致。通过缩短label或调整面板解决增高后的间距。
- `operator(cx,cy,symbol='+',theme='neutral',radius=18) -> Box`：加、乘、Σ等汇合。
- `state(x,y,w,h,title,lines) -> Box`：缓存/循环状态，lines可用字符串列表；高度由调用者为文字预留。
- `Box.port('top'|'bottom'|'left'|'right') -> (x,y)`。
- `connect(source,target,source_side='top',target_side='bottom',via=[])`：显式端口和正交转折点。
- `edge([(x1,y1),…],dashed=False,arrow=True,theme=None)`：绘制路径；模块展开用 `dashed=True, arrow=False`。计算边尽量水平/垂直走线。
- `text(x,y,value,size=20,color=...,weight=400,anchor='start',line_height=None,cls='')`：文字或多行列表，不自动换行；不要将长说明放进计算图中。
- `bracket(x,y,w,h,label)`：重复组外框。不能把特殊注入节点错误包进重复组。
- `layer_group(x,y,w,operations,label,direction='up',gap=16) -> list[Box]`：按执行顺序传入代表层的子层运算记录（`label/theme`，可选`sub/h`），只绘制一次并加重复/层范围标题。返回框仍按执行顺序排列，方便连接上下游和模块展开。`y`始终是组顶部；重复次数与具体层号由调用方核实后写入`label`。对外连线需绕开组顶部标题。此组件不推断周期，也不自动生成完整层清单。
- `save(path,footer=...)`：保存独立SVG。

可手写SVG补充复杂形状，沿用theme.json和输入约定。原语减少样式差异，不代替模型运算设计。

主干可用 `layer_group` 显示一个层的“读取 → 子层 → 写回 → 专家子层”等操作，连续同构层用重复标注；结构转折另建组。不要给每层只画一个相同的类型条。完整逐层配置作为详解的静态网格数据；不要把该清单的高度传给海报布局。

## meta.json

```json
{
  "model": "目标模型名称",
  "eyebrow": "FIXED REVISION · 架构类型",
  "summary": "一两句话说明架构主线，以及图中参数的口径。",
  "caption": "中央主干自下向上 · 双击模块查看详解",
  "metrics": [
    {"value": "经核实的数值", "label": "总参数 / 激活参数口径"},
    {"value": "经核实的层数", "label": "层类型构成"}
  ],
  "nav": [{"id":"overview","label":"总览"},{"id":"attention","label":"Attention"}]
}
```

复杂模型通常提供4–6个真正有用的指标：参数口径、层构成、D、专家路由、特殊记忆和上下文；不要填入未核实数字来凑卡片。nav使用短标签，id对应section。构建脚本会转义metadata文字；不要在metadata塞HTML。

`build_atlas.py --meta`可选，以兼容旧输入；新建应填写metadata才能获得完整概览。模板的控制器ID稳定；不要把固定模型名、尺寸、revision写入共享模板。

模板默认适配宽度；“查看全图”保留为独立检查模式。详解主题类同时提供 `--theme-pale/--theme-accent/--theme-ink/--theme-strong`，局部SVG可用 `class="theme-residual" style="fill:var(--theme-pale);stroke:var(--theme-accent)"` 沿用统一颜色。海报 SVG 自带作用域样式，导出不依赖网页CSS；不要把海报的全局 `text` 或 `.shape` 样式泄漏到阅读图。
