#!/usr/bin/env python3
"""Check an atlas statically, optionally exercise it with Playwright Chromium."""
import argparse
import math
import json
import shutil
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
import tempfile
import xml.etree.ElementTree as ET


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.targets, self.resources = [], [], [], []
        self.detail_ids = []
        self.in_details = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id') == 'details-content':
            self.in_details = True
        if self.in_details and 'id' in a:
            self.detail_ids.append(a['id'])
        if 'id' in a:
            self.ids.append(a['id'])
        if 'data-detail' in a:
            self.targets.append(a['data-detail'])
            if a.get('role') != 'button' or a.get('tabindex') != '0':
                raise ValueError('Interactive module needs role="button" and tabindex="0"')
        if a.get('href', '').startswith('#'):
            self.links.append(a['href'][1:])
        if tag in ('img', 'script', 'iframe', 'source', 'video', 'audio') and a.get('src'):
            self.resources.append(a['src'])
        if tag in ('image', 'use', 'link'):
            resource = a.get('href', a.get('xlink:href', ''))
            if resource and not resource.startswith(('#', 'data:')):
                self.resources.append(resource)

    def handle_endtag(self, tag):
        if tag == 'main':
            self.in_details = False


def inspect(source):
    doc = Document()
    doc.feed(source)
    duplicates = [key for key, count in Counter(doc.ids).items() if count > 1]
    if duplicates:
        raise ValueError('Duplicate IDs: '+', '.join(duplicates))
    missing = sorted((set(doc.links) - set(doc.ids)) | (set(doc.targets) - set(doc.detail_ids)))
    if missing:
        raise ValueError('Missing anchors/detail targets: '+', '.join(missing))
    if doc.resources or re.search(r'@import\s|url\(\s*[\'"]?(?:https?:|//|file:)', source, re.I):
        raise ValueError('External display resources must be embedded')
    if re.search(r'@@[A-Z_]+@@', source):
        raise ValueError('Unresolved template placeholders')
    for required in ('architecture-poster', 'poster-view', 'details-view', 'details-content'):
        if required not in doc.ids:
            raise ValueError('Missing required element: '+required)
    svg_source = re.search(r'<svg\b[^>]*id="architecture-poster".*?</svg>', source, re.S)
    if not svg_source:
        raise ValueError('Missing serializable architecture SVG')
    svg = ET.fromstring(svg_source[0])
    dims = [float(v) for v in re.split(r'[\s,]+', svg.get('viewBox', '').strip())]
    if len(dims) != 4 or not all(math.isfinite(n) for n in dims) or dims[:2] != [0, 0] or min(dims[2:]) <= 0:
        raise ValueError('Invalid SVG viewBox')
    return dims[2:], doc.targets


def layout_report(page):
    """Geometry diagnostics; crossing warnings still require human visual assessment."""
    return page.locator('#architecture-poster').evaluate(r"""svg=>{
      const issues=[],outside=[],cross=[];
      const bounds=svg.viewBox.baseVal;
      const texts=[...svg.querySelectorAll('text')].map(t=>({el:t,b:t.getBBox(),text:t.textContent.trim()}));
      for(const t of texts){
        if(t.b.x<0||t.b.y<0||t.b.x+t.b.width>bounds.width||t.b.y+t.b.height>bounds.height)outside.push(t.text);
      }
      for(const n of svg.querySelectorAll('[data-node], [data-state]')){
        const r=n.querySelector('rect')?.getBBox();if(!r)continue;
        for(const t of n.querySelectorAll('text')){const b=t.getBBox();if(b.x<r.x-1||b.y<r.y-1||b.x+b.width>r.x+r.width+1||b.y+b.height>r.y+r.height+1)issues.push(t.textContent.trim());}
      }
      for(const edge of svg.querySelectorAll('path[data-edge="compute"]')){
        const length=edge.getTotalLength();let found=false;
        for(let d=4;d<length-4&&!found;d+=5){const p=edge.getPointAtLength(d);for(const t of texts){const b=t.b;if(p.x>b.x+2&&p.x<b.x+b.width-2&&p.y>b.y+3&&p.y<b.y+b.height-3){cross.push(t.text);found=true;break;}}}
      }
      const compactSpineBars=[...svg.querySelectorAll('rect')].filter(r=>{const b=r.getBBox();return b.width<bounds.width*.18&&b.width>bounds.width*.05&&b.height<=40&&b.x<bounds.width*.5&&b.x+b.width>bounds.width*.5;}).length;
      const grouped=svg.querySelectorAll('[data-layer-group]').length;
      const warnings=[];
      if(compactSpineBars>24&&!grouped)warnings.push('Main spine may be a layer inventory: '+compactSpineBars+' compact central bars; inspect representative sublayer computation and repeats.');
      return {node_text_overflow:issues,canvas_text_overflow:outside,edge_text_warnings:[...new Set(cross)],quality_warnings:warnings,composition:{canvas_aspect_ratio:bounds.width/bounds.height,compact_spine_bars:compactSpineBars,representative_layer_groups:grouped},visual_signals:{solid_nodes:svg.querySelectorAll('[data-node]').length,operators:svg.querySelectorAll('circle').length,panels:svg.querySelectorAll('[data-detail]').length,detail_cards:document.querySelectorAll('#details-content .card').length,detail_flows:document.querySelectorAll('#details-content .node').length,metrics:document.querySelectorAll('.metric').length}};
    }""")


def details_report(page):
    """Report reading composition; these signals require visual interpretation."""
    return page.locator('#details-content').evaluate(r"""main=>{
      const warnings=[],sections=[];
      for(const section of main.querySelectorAll(':scope > section')){
        const diagrams=[...section.querySelectorAll('svg')].map(svg=>{
          const r=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal;
          const sizes=[...svg.querySelectorAll('text')].map(t=>parseFloat(getComputedStyle(t).fontSize)*(vb.width?r.width/vb.width:1)).sort((a,b)=>a-b);
          return {height:Math.round(r.height),median_text_px:sizes.length?sizes[Math.floor(sizes.length/2)]:null};
        });
        const row={id:section.id,height:Math.round(section.getBoundingClientRect().height),cards:section.querySelectorAll('.card').length,html_nodes:section.querySelectorAll('.node').length,paragraphs:section.querySelectorAll('p').length,diagrams};
        sections.push(row);
        if(diagrams.some(d=>d.height>900)&&row.html_nodes===0)warnings.push(section.id+': full-width SVG dominates reading; inspect branch cards and local explanations.');
        if(diagrams.some(d=>d.median_text_px>24))warnings.push(section.id+': diagram labels exceed normal reading size; consider a local diagram beside explanations.');
      }
      return {sections,quality_warnings:warnings};
    }""")


def browser_check(path, executable, dimensions, targets, artifacts=None):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p, tempfile.TemporaryDirectory() as temp:
        options = {'headless': True}
        if executable:
            options['executable_path'] = executable
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        errors = []
        if artifacts:
            artifacts.mkdir(parents=True, exist_ok=True)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(path.resolve().as_uri())
        page.evaluate('document.fonts.ready')
        page.wait_for_function("document.querySelector('#architecture-poster').getBoundingClientRect().width > 0")
        initial = page.locator('#architecture-poster').evaluate("s=>({scale:s.getBoundingClientRect().width/s.viewBox.baseVal.width,display_width:s.getBoundingClientRect().width,viewport_width:document.querySelector('#viewport').clientWidth})")
        if artifacts:
            page.screenshot(path=str(artifacts/'poster-default.png'))
        page.locator('#fit-width').click()
        if artifacts:
            page.screenshot(path=str(artifacts/'poster-width.png'))
        page.locator('#fit-all').click()
        page.evaluate('document.fonts.ready')
        if artifacts:
            page.screenshot(path=str(artifacts/'poster-preview.png'))
        layout = layout_report(page)
        page.locator('#show-details').click()
        assert page.locator('#details-view').is_visible()
        reading = details_report(page)
        if artifacts:
            page.screenshot(path=str(artifacts/'details-overview.png'))
            flow = page.locator('#details-content .grid3, #details-content .grid4').first
            if flow.count():
                flow.scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts/'details-module.png'))
            # Element crops must not contain the sticky navigation or return button.
            capture_style = page.add_style_tag(content='.details-nav,#back-poster{visibility:hidden!important}')
            seen = set()
            for detail_id in targets:
                if detail_id in seen:
                    continue
                seen.add(detail_id)
                section = page.locator('#details-content section[id="'+detail_id+'"]')
                safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', detail_id)
                section.screenshot(path=str(artifacts/('section-'+safe_name+'.png')))
            capture_style.evaluate('e=>e.remove()')
        if page.locator('#toggle-shapes').count():
            page.locator('#toggle-shapes').uncheck()
            assert page.locator('#details-view').evaluate("e=>e.classList.contains('hide-shapes')")
            assert page.locator('#details-view .shape').evaluate_all("elements=>elements.every(e=>getComputedStyle(e).display==='none')")
            page.locator('#toggle-shapes').check()
            page.locator('#toggle-caches').uncheck()
            assert page.locator('#details-view').evaluate("e=>e.classList.contains('hide-caches')")
            page.locator('#toggle-caches').check()
        for grid in page.locator('[data-layer-grid]').all():
            button = grid.locator('[data-layer-info]').last
            if button.count():
                button.click()
                inspector = page.locator('#'+grid.get_attribute('data-inspector'))
                assert inspector.inner_text() == button.get_attribute('data-layer-info')
        disclosures = page.locator('.disclosure')
        before_print = disclosures.evaluate_all('elements=>elements.map(e=>e.open)')
        page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
        assert disclosures.evaluate_all('elements=>elements.every(e=>e.open)')
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        assert before_print == disclosures.evaluate_all('elements=>elements.map(e=>e.open)')
        page.locator('#back-poster').click()
        if targets:
            module = page.locator('svg [data-detail]').first
            module.dblclick()
            assert page.locator('#details-view').is_visible()
            page.locator('#back-poster').click()
            for i in range(page.locator('svg [data-detail]').count()):
                target = page.locator('svg [data-detail]').nth(i)
                detail_id = target.get_attribute('data-detail')
                target.focus()
                target.press('Enter')
                assert page.locator('#details-view').is_visible()
                assert page.locator('#'+detail_id).is_visible()
                page.locator('#back-poster').click()
        page.locator('#actual-size').click()
        assert page.locator('#zoom-value').inner_text() == '100%'
        page.locator('#zoom').fill('150')
        assert page.locator('#zoom-value').inner_text() == '150%'
        bounds = page.locator('#viewport').bounding_box()
        page.mouse.move(bounds['x']+bounds['width']*.8, bounds['y']+bounds['height']*.8)
        page.mouse.down()
        page.mouse.move(bounds['x']+bounds['width']*.5, bounds['y']+bounds['height']*.5, steps=8)
        page.mouse.up()
        assert not page.locator('#viewport').evaluate("e=>e.classList.contains('dragging')")
        before_zoom = page.locator('#zoom-value').inner_text()
        page.keyboard.down('Control')
        page.mouse.wheel(0, -100)
        page.keyboard.up('Control')
        page.wait_for_function("document.querySelector('#zoom-value').textContent !== " + json.dumps(before_zoom))
        for kind in ('svg', 'png'):
            with page.expect_download(timeout=60000) as download:
                page.locator('#export-'+kind).click()
            exported = Path(temp)/('poster.'+kind)
            download.value.save_as(exported)
            if artifacts:
                shutil.copyfile(exported, artifacts/exported.name)
            if kind == 'svg':
                ET.parse(exported)
            else:
                data = exported.read_bytes()
                assert data[:8] == b'\x89PNG\r\n\x1a\n'
                width, height = struct.unpack('>II', data[16:24])
                assert [width, height] == [int(n*2+.5) for n in dimensions]
        if artifacts:
            page.locator('#fit-all').click()
            page.emulate_media(media='print')
            page.pdf(path=str(artifacts/'poster-print.pdf'), width='350mm', height=str(350*dimensions[1]/dimensions[0]+10)+'mm', print_background=True)
            page.emulate_media(media='screen')
            page.locator('#show-details').click()
            page.emulate_media(media='print')
            page.pdf(path=str(artifacts/'details-print.pdf'), format='A4', print_background=True, margin={'top':'12mm','bottom':'12mm','left':'12mm','right':'12mm'})
            page.emulate_media(media='screen')
            page.locator('#back-poster').click()
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('#fit-width').click()
        assert page.locator('#viewport').bounding_box()['height'] > 150
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        if artifacts:
            page.screenshot(path=str(artifacts/'mobile-poster.png'))
        page.locator('#show-details').click()
        assert page.locator('#details-view').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        if artifacts:
            page.screenshot(path=str(artifacts/'mobile-details.png'))
        mobile_reading = details_report(page)
        # Check actual SVG readability, not only document-level horizontal overflow.
        for section in mobile_reading['sections']:
            for diagram in section['diagrams']:
                if diagram['median_text_px'] is not None and diagram['median_text_px'] < 10:
                    reading['quality_warnings'].append(section['id']+': SVG text below 10px on mobile; reflow HTML branches or use a scrollable local diagram.')
        assert not errors, errors
        no_js = browser.new_page(java_script_enabled=False)
        no_js.goto(path.resolve().as_uri())
        assert no_js.locator('#details-view').is_visible()
        assert no_js.locator('#details-content section').count() > 0
        no_js.close()
        if initial['display_width'] / initial['viewport_width'] < .9:
            layout['quality_warnings'].append('Default poster uses less than 90% of viewport width; compare fit-width readability.')
        quality = layout['quality_warnings'] + reading['quality_warnings']
        if artifacts:
            (artifacts/'validation.json').write_text(json.dumps({'browser':'PASS','visual_review':'PENDING_MANUAL_REVIEW','default_view':initial,'layout':layout,'reading':reading,'quality_warnings':quality,'console_errors':errors,'modules':len(targets)},ensure_ascii=False,indent=2))
        if layout['node_text_overflow']:
            raise ValueError('Node labels overflow their boxes: '+str(layout['node_text_overflow']))
        browser.close()
    print('Browser PASS: views, all module navigation, zoom, drag, toggles, mobile, SVG/PNG exports, console')
    print('Layout diagnostics: '+json.dumps(layout, ensure_ascii=False))
    print('Reading diagnostics: '+json.dumps(reading, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', type=Path)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--browser-executable')
    parser.add_argument('--artifacts', type=Path, help='Save screenshots, exports, print PDFs and layout report')
    args = parser.parse_args()
    dimensions, targets = inspect(args.html.read_text(encoding='utf-8'))
    print(f'Static PASS: SVG {dimensions}, {len(targets)} interactive modules; IDs, anchors, embedded resources')
    if args.browser:
        browser_check(args.html, args.browser_executable, dimensions, targets, args.artifacts)
