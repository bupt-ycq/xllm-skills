#!/usr/bin/env python3
"""Assemble model-authored SVG/details and optional metadata into the styled offline atlas."""
import argparse
import html
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def theme_css():
    themes=json.loads((ROOT/'assets/theme.json').read_text())
    return '\n'.join(
        f'.{name},.theme-{name}{{'
        f'--theme-pale:{t["pale"]};--theme-accent:{t["accent"]};'
        f'--theme-ink:{t["ink"]};--theme-strong:{t["strong"]};'
        f'background:{t["pale"]};border-color:{t["accent"]};color:{t["ink"]}}}'
        for name,t in themes.items())


def build(poster, details, title, output, metadata=None):
    raw=poster.read_text(encoding='utf-8')
    svg=ET.fromstring(raw)
    if svg.tag!='{http://www.w3.org/2000/svg}svg':
        raise ValueError('Poster must be an SVG with the SVG namespace')
    viewbox=[float(v) for v in re.split(r'[\s,]+',svg.get('viewBox','').strip())]
    if len(viewbox)!=4 or viewbox[:2]!=[0,0] or not all(0<n<=16000 for n in viewbox[2:]):
        raise ValueError('Expected viewBox="0 0 W H", with 0 < W,H <= 16000')
    if re.search(r'<(?:\w+:)?(?:foreignObject|script)\b',raw,re.I):
        raise ValueError('SVG must not contain foreignObject or scripts')
    if svg.find('{http://www.w3.org/2000/svg}title') is None or svg.find('{http://www.w3.org/2000/svg}desc') is None:
        raise ValueError('SVG requires title and desc')
    raw=re.sub(r'^\s*<\?xml.*?\?>\s*','',raw,flags=re.S)
    raw=re.sub(r'(<svg\b)([^>]*)(>)',lambda m:m[1]+re.sub(r'\s+id\s*=\s*([\'"]).*?\1','',m[2])+' id="architecture-poster"'+m[3],raw,count=1)
    fragment=details.read_text(encoding='utf-8')
    if re.search(r'<(?:html|head|body|script)\b',fragment,re.I):
        raise ValueError('Details must be a body fragment without scripts')
    meta=metadata or {}
    metrics=meta.get('metrics',[])
    nav=meta.get('nav',[])
    if not nav:
        for ident,heading in re.findall(r'<section\b[^>]*id="([^"]+)"[^>]*>.*?<h2[^>]*>(.*?)</h2>',fragment,re.S):
            nav.append({'id':ident,'label':re.sub('<[^>]+>','',heading)})
    esc=lambda value:html.escape(str(value),quote=True)
    values={
        'TITLE':esc(title),'MODEL':esc(meta.get('model',title)),
        'EYEBROW':esc(meta.get('eyebrow','MODEL STRUCTURE & EVIDENCE')),
        'SUMMARY':esc(meta.get('summary','整体计算图、逐模块结构、张量形状与状态说明。')),
        'CAPTION':esc(meta.get('caption','主干方向与图例见海报 · 双击模块查看详解')),
        'METRICS':''.join(f'<div class="metric"><strong>{esc(m["value"])}</strong><span>{esc(m["label"])}</span></div>' for m in metrics),
        'NAV':''.join(f'<a href="#{esc(n["id"])}">{esc(n["label"])}</a>' for n in nav),
        'THEME_CSS':theme_css(),'POSTER':raw,'DETAILS':fragment,
        'FILE_STEM':re.sub(r'[^a-zA-Z0-9_-]','-',output.stem) or 'model-architecture',
    }
    shell=(ROOT/'assets/atlas-shell.html').read_text(encoding='utf-8')
    result=re.sub(r'@@([A-Z_]+)@@',lambda m:values[m[1]],shell)
    from validate_atlas import inspect
    inspect(result)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(result,encoding='utf-8')
    print(f'Saved: {output.resolve()} ({len(result.encode("utf-8"))} bytes)')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('poster','details','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--title',required=True)
    parser.add_argument('--meta',type=Path,help='JSON with model, summary, metrics, nav and caption')
    args=parser.parse_args()
    try:
        build(args.poster,args.details,args.title,args.output,json.loads(args.meta.read_text()) if args.meta else None)
    except (ValueError,ET.ParseError,KeyError) as error:
        parser.exit(1,f'Invalid architecture input: {error}\n')
