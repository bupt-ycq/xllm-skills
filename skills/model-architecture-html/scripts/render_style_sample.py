#!/usr/bin/env python3
"""Render a symbolic style sample, not a real architecture or source of model facts."""
import argparse
from pathlib import Path
from poster import Poster
from build_atlas import build


def render(out):
    out.mkdir(parents=True,exist_ok=True)
    p=Poster(2600,2000,'Architecture Atlas · 视觉样张','虚构符号拓扑，仅展示样式与组件；真实模型结构必须独立核实')
    # Central spine: narrow, with operations rather than paragraph cards.
    a=p.node(1160,1790,280,70,'Token Embedding','residual',sub='[T,D]')
    b=p.node(1160,1630,280,70,'Residual Expand','residual',sub='[T,M,D]')
    p.connect(a,b)
    operations=[{'label':label,'theme':theme,'h':62} for label,theme in [
        ('Residual Read','residual'),('Recurrent Block','recurrent'),
        ('Residual Write','residual'),('Sparse Retrieval','attention'),
        ('Expert Mixture','moe'),('Residual Write','residual')]]
    layers=p.layer_group(1160,800,280,operations,'代表计算周期 × N',gap=34)
    p.connect(b,layers[0])
    prev=layers[-1]
    final=p.node(1160,590,280,70,'Final Mixer','residual');p.connect(prev,final,via=[(1300,790),(1510,790),(1510,700),(1300,700)])
    head=p.node(1160,430,280,70,'Output Head','residual');p.connect(final,head)
    p.text(1300,385,'Logits / Next Token',size=23,weight=700,anchor='middle');p.edge([head.port('top'),(1300,402)])
    p.text(1300,1920,'Text / Token IDs',size=23,weight=700,anchor='middle');p.edge([(1300,1892),a.port('bottom')])
    p.text(1300,230,['MODEL CONFIG','D · H · M · L','由固定版本证据填入'],size=20,color='#657287',anchor='middle',line_height=37)
    with p.panel('operator',40,180,970,760,'Recurrent Memory · 并行门控与状态','短操作节点、独立gate与显式状态读写',theme='recurrent'):
        x=p.node(125,805,360,62,'Content Projection','recurrent',sub='x → Q / K / V')
        gate=p.node(595,805,300,62,'Gate Projection','recurrent',sub='x → g')
        qkv=p.node(125,660,360,62,'Normalize / Reshape','recurrent');p.connect(x,qkv)
        g=p.node(595,660,300,62,'Sigmoid','recurrent');p.connect(gate,g)
        state=p.state(595,480,300,120,'跨步循环状态',['固定容量 · 明确dtype','prefill / decode 更新'])
        op=p.node(125,470,360,85,'State Update','recurrent',sub='Q / K / V + previous state');p.connect(qkv,op)
        p.connect(state,op,'left','right')
        mul=p.operator(305,365,'×','recurrent');p.connect(op,mul)
        p.edge([g.port('right'),(940,g.port('right')[1]),(940,365),mul.port('right')])
        outnode=p.node(125,275,360,55,'Output Projection','recurrent');p.connect(mul,outnode)
    with p.panel('operator',1590,180,970,760,'Expert Mixture · 分支、加权和共享路径','语义颜色贯穿海报和详解',theme='moe'):
        router=p.node(1660,790,380,64,'Router → Top-K','moe');shared=p.node(2180,670,290,65,'Shared Expert','moe')
        ex1=p.node(1640,645,200,65,'Expert i','moe');ex2=p.node(1880,645,200,65,'Expert j','moe')
        p.edge([router.port('top'),(1850,750),(1740,750),ex1.port('bottom')]);p.edge([(1850,750),(1980,750),ex2.port('bottom')])
        sigma=p.operator(1850,525,'Σ','moe');p.connect(ex1,sigma,'top','left',[(1740,525)]);p.connect(ex2,sigma,'top','right',[(1980,525)])
        plus=p.operator(2100,380,'+','moe');p.connect(sigma,plus,'top','left',[(1850,380)]);p.connect(shared,plus,'top','right',[(2325,380)])
        output=p.node(1940,275,320,60,'Expert Output','moe');p.connect(plus,output)
        p.edge([(1850,885),router.port('bottom')]);p.edge([(1850,885),(2325,885),shared.port('bottom')])
        p.text(1700,926,'Shared path从同一模块输入分叉，实际参数由模型决定。',size=19,color='#657287')
    with p.panel('operator',40,990,970,810,'Conditional Memory · 查表与融合','附加参数、读写状态和主干残差分别标注',theme='memory'):
        idx=p.node(110,1630,380,65,'Token Hash / Address','memory')
        lookup=p.node(110,1480,380,65,'Embedding Lookup','memory');p.connect(idx,lookup)
        value=p.node(110,1320,380,65,'Value Projection','memory');p.connect(lookup,value)
        gate=p.node(590,1320,350,65,'Context Gate','memory')
        mul=p.operator(525,1210,'×','memory');p.connect(value,mul,'top','left',[(300,1210)]);p.connect(gate,mul,'top','right',[(765,1210)])
        mix=p.node(335,1080,380,65,'Residual Injection','memory');p.connect(mul,mix)
        p.state(590,1470,350,130,'记忆表 / 历史',['独立参数口径','与计算激活区分'])
        p.text(110,1760,'图中为样式示意；不能据此认定目标模型存在该模块。',size=19,color='#657287')
    with p.panel('operator',1590,990,970,810,'Sparse Attention · 检索后精确计算','Q旁路、KV状态、选择索引与聚合分别表达',theme='attention'):
        q=p.node(1660,1610,350,65,'Q Projection','attention')
        index=p.node(2150,1610,330,65,'Indexer Projection','attention')
        topk=p.node(2150,1450,330,65,'Score → Top-K','attention');p.connect(index,topk)
        cache=p.state(1660,1400,350,120,'Original KV Cache',['长度随上下文增长','稀疏选择不等于删除历史'])
        gather=p.node(2150,1290,330,65,'Gather Selected KV','attention');p.connect(topk,gather)
        p.edge([cache.port('right'),(2070,1460),(2070,gather.port('left')[1]),gather.port('left')])
        core=p.node(1850,1100,450,85,'Attention → Output','attention',sub='Q · selected K / V')
        p.connect(gather,core,'top','right',[(2315,1142.5)])
        p.edge([q.port('left'),(1630,q.port('left')[1]),(1630,1142.5),core.port('left')])
    p.edge([(1160,1350),(1070,1350),(1070,530),(1010,530)],dashed=True,arrow=False,theme='recurrent')
    p.edge([(1440,960),(1510,960),(1510,530),(1590,530)],dashed=True,arrow=False,theme='moe')
    p.save(out/'poster.svg')
    example=Path(__file__).resolve().parents[1]/'assets/details-example.html'
    meta={'model':'Architecture Atlas · 视觉样张','summary':'用于检验排版与组件的虚构符号结构；不包含目标模型结论。','metrics':[{'value':'D','label':'隐藏维度符号'},{'value':'L','label':'层数符号'},{'value':'H','label':'头数符号'},{'value':'M','label':'分支数符号'}],'nav':[{'id':'overview','label':'总览'},{'id':'operator','label':'模块流程'}]}
    build(out/'poster.svg',example,'Architecture Atlas · 样式样张',out/'sample.html',meta)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);args=parser.parse_args();render(args.output)
