"""Dependency-free SVG components for an architecture poster, with explicit graph ports.

Import this file from a task-local generator. It supplies style and drawing primitives,
not model topology. See references/components.md for the public API.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import unicodedata

THEMES = json.loads((Path(__file__).resolve().parents[1] / 'assets/theme.json').read_text())


def estimated_width(value, size):
    return sum(1 if unicodedata.east_asian_width(c) in 'WF' else .57 for c in value) * size


def wrap(value, width, size):
    lines = []
    for paragraph in str(value).split('\n'):
        line = ''
        for char in paragraph:
            if line and estimated_width(line + char, size) > width:
                lines.append(line.rstrip())
                line = ''
            line += char
        lines.append(line.strip())
    return lines


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    def port(self, side):
        return {'top': (self.x + self.w / 2, self.y),
                'bottom': (self.x + self.w / 2, self.y + self.h),
                'left': (self.x, self.y + self.h / 2),
                'right': (self.x + self.w, self.y + self.h / 2)}[side]


class Poster:
    def __init__(self, width, height, title, subtitle, direction='主干自下向上'):
        self.width, self.height = width, height
        self.items = [f'''<svg xmlns="http://www.w3.org/2000/svg" class="atlas-poster" viewBox="0 0 {width} {height}" role="img">
<title>{escape(title)}</title><desc>{escape(subtitle)}；{escape(direction)}。实线为计算依赖，虚线为模块展开关联。</desc>
<defs><marker id="poster-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#48556a"/></marker></defs>
<style>.atlas-poster text{{font-family:Arial,"Noto Sans CJK SC","Microsoft YaHei",sans-serif}}.atlas-poster .poster-module{{cursor:pointer;outline:none}}.atlas-poster .poster-module:hover>.module-boundary,.atlas-poster .poster-module:focus>.module-boundary{{stroke-width:3.2}}.atlas-poster .edge{{fill:none;stroke:#48556a;stroke-width:1.8;stroke-linejoin:round}}.atlas-poster .shape{{font-family:Consolas,"Noto Sans CJK SC",monospace}}</style>
<rect width="{width}" height="{height}" fill="white"/>''']
        self.text(width/2, 58, title, size=40, weight=700, anchor='middle')
        self.text(width/2, 98, subtitle, size=21, color='#657287', anchor='middle')
        self.text(width/2, 133, direction+' · 实线：计算依赖 · 虚线：模块展开 · 形状：逻辑全局尺寸', size=18, color='#657287', anchor='middle')

    def text(self, x, y, value, size=20, color='#182235', weight=400,
             anchor='start', line_height=None, cls=''):
        lines = value if isinstance(value, (list, tuple)) else str(value).split('\n')
        spacing = line_height or size * 1.5
        self.items.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}" class="{cls}">')
        for i, line in enumerate(lines):
            self.items.append(f'<tspan x="{x}" dy="{0 if i == 0 else spacing}">{escape(str(line))}</tspan>')
        self.items.append('</text>')

    @contextmanager
    def panel(self, detail_id, x, y, w, h, title, subtitle='', theme='neutral'):
        t = THEMES[theme]
        self.items.append(f'<g class="poster-module" data-theme="{escape(theme)}" data-detail="{escape(detail_id)}" role="button" tabindex="0" aria-label="{escape(title)} 详解"><title>{escape(title)}：双击或回车查看详解</title>')
        self.items.append(f'<rect class="module-boundary" x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="white" stroke="{t["accent"]}" stroke-width="1.8" stroke-dasharray="9 6"/>')
        self.text(x+20, y+35, title, size=27, color=t['strong'], weight=700)
        if subtitle:
            self.text(x+20, y+65, subtitle, size=17, color='#657287')
        try:
            yield Box(x,y,w,h)
        finally:
            self.items.append('</g>')

    def node(self, x, y, w, h, label, theme='neutral', sub='', pale=False):
        t = THEMES[theme]
        lines = wrap(label, w-24, 20)
        subs = wrap(sub, w-24, 16) if sub else []
        spacing = 29
        required = 24 + len(lines)*spacing + len(subs)*24
        h = max(h, required)
        fill, ink = (t['pale'], t['ink']) if pale else (t['strong'], '#ffffff')
        self.items.append(f'<g data-node="true"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{t["accent"]}" stroke-width="1.6"/>')
        block = (len(lines)-1)*spacing + (len(subs)*24 if subs else 0)
        baseline = y + (h-block)/2 + 7
        self.text(x+w/2, baseline, lines, size=20, color=ink, weight=600, anchor='middle', line_height=spacing)
        if subs:
            self.text(x+w/2, baseline+(len(lines)-1)*spacing+26, subs, size=16, color=ink, anchor='middle', line_height=24, cls='shape')
        self.items.append('</g>')
        return Box(x,y,w,h)

    def operator(self, x, y, symbol='+', theme='neutral', radius=18):
        t=THEMES[theme]
        self.items.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{t["pale"]}" stroke="{t["accent"]}" stroke-width="2"/>')
        self.text(x,y+7,symbol,size=24,color=t['strong'],weight=600,anchor='middle')
        return Box(x-radius,y-radius,2*radius,2*radius)

    def state(self, x, y, w, h, title, lines):
        t=THEMES['cache']
        self.items.append(f'<g data-state="true"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{t["pale"]}" stroke="{t["accent"]}" stroke-width="1.6" stroke-dasharray="7 5"/>')
        self.text(x+w/2,y+28,title,size=19,color=t['ink'],weight=600,anchor='middle')
        self.text(x+w/2,y+59,lines,size=17,color=t['ink'],anchor='middle',line_height=26,cls='cache-label')
        self.items.append('</g>')
        return Box(x,y,w,h)

    def edge(self, points, dashed=False, arrow=True, theme=None):
        if len(points)<2:
            raise ValueError('An edge needs at least two points')
        d='M'+' L'.join(f'{x},{y}' for x,y in points)
        extra=' stroke-dasharray="8 6"' if dashed else ''
        if theme:
            extra+=f' style="stroke:{THEMES[theme]["accent"]}"'
        if arrow:
            extra+=' marker-end="url(#poster-arrow)"'
        self.items.append(f'<path data-edge="{"association" if dashed else "compute"}" d="{d}" class="edge"{extra}/>')

    def connect(self, source, target, source_side='top', target_side='bottom', via=()):
        self.edge([source.port(source_side), *via, target.port(target_side)])

    def bracket(self,x,y,w,h,label):
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="none" stroke="#aebbd0" stroke-dasharray="7 5"/>')
        self.text(x+w/2,y-12,label,size=18,color='#657287',anchor='middle')

    def layer_group(self, x, y, w, operations, label, direction='up', gap=16):
        """Draw one representative computation, with an explicit repeat/range label.

        operations are in execution order; y is the top of the group, regardless
        of direction. Each record supplies label, theme and optionally sub/h.
        No layer count, cycle or model operation is inferred by this helper.
        Returns boxes in execution order so expansion edges can use real ports.
        """
        if direction not in ('up', 'down') or not operations:
            raise ValueError('Need nonempty operations and direction up/down')
        self.items.append('<g data-spine="computation" data-layer-group="true">')
        ordered = operations if direction == 'down' else list(reversed(operations))
        boxes = []
        cursor = y
        for operation in ordered:
            box = self.node(x, cursor, w, operation.get('h', 55),
                            operation['label'], operation.get('theme', 'neutral'),
                            sub=operation.get('sub', ''))
            boxes.append(box)
            cursor += box.h + gap
        self.bracket(x-14, y-14, w+28, cursor-y-gap+28, label)
        if direction == 'up':
            boxes.reverse()
        for source, target in zip(boxes, boxes[1:]):
            self.connect(source, target,
                         'top' if direction == 'up' else 'bottom',
                         'bottom' if direction == 'up' else 'top')
        self.items.append('</g>')
        return boxes

    def save(self,path,footer='双击模块查看详解 · 固定版本来源与未确认项见详解'):
        self.text(self.width/2,self.height-27,footer,size=17,color='#657287',anchor='middle')
        Path(path).write_text('\n'.join([*self.items,'</svg>']),encoding='utf-8')
