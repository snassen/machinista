"""Build accessible static HTML manuals from the same chapters as the PDF guides.

Run from the development tree after rendering the PDF manual assets. The output
is self-contained, works offline and is published unchanged by GitHub Pages.
"""
from pathlib import Path
from html import escape
import copy
import hashlib
import json
import tools.build_user_manuals as base

DEST = base.ROOT / 'docs/manuals'
NAMES = {'mikro': 'Mikro MK1 / MK2', 'mk1': 'MK1', 'mk2': 'MK2', 'mk3': 'MK3 / Maschine+'}
CSS = '''
:root{color-scheme:light;--accent:#b84b00;--ink:#29231e;--paper:#fffaf5}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:2rem}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 system-ui,sans-serif}
a{color:var(--accent);text-underline-offset:3px}a:hover{text-decoration-thickness:2px}
header,main,footer{max-width:1120px;margin:auto;padding:2rem}header{border-bottom:3px solid #ff993d}
h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.15;margin:.5em 0}h2{line-height:1.3;margin-top:0}
h3{line-height:1.4}.eyebrow{font-weight:700;letter-spacing:.12em;color:var(--accent)}
.layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:3rem}
nav{font-size:.9rem}nav ol{padding-left:1.5rem}nav li{margin-bottom:.6rem}
section{margin-bottom:4rem;border-bottom:1px solid #e4cdb9;padding-bottom:2rem;overflow-wrap:anywhere}
li{margin-bottom:.65rem}figure{margin:1.5rem 0;padding:1rem;background:#f0e7dd;border-radius:10px}
img{display:block;max-width:100%;height:auto;margin:auto}img.display{image-rendering:pixelated;width:100%}
figure.micro img{max-width:384px}figcaption{font-size:.85rem;margin-top:.6rem;color:#625044}
table{border-collapse:collapse;width:100%;font-size:.95rem}th,td{border:1px solid #dfcbbb;text-align:left;padding:.65rem;vertical-align:top}
th:first-child,td:first-child{min-width:6em}
.note{border-left:3px solid #ff993d;padding-left:1rem}.top{font-size:.85rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1.2rem}.card{padding:1.3rem;border:1px solid #dfcbbb;border-radius:10px;background:white}
.skip{position:absolute;left:-9999px}.skip:focus{position:static}footer{font-size:.9rem}
@media(max-width:850px){.layout{display:block}header,main,footer{padding:1.2rem}nav{margin-bottom:3rem}}
@media print{nav,.top,.skip{display:none}.layout{display:block}body{background:white;font-size:11pt}section{break-before:auto}figure{break-inside:avoid}a{color:inherit}}
'''


def prepare(language, original):
    base.CH = copy.deepcopy(original)
    if language == 'de':
        from tools.manuals_de import localize_chapters
        base.CH = localize_chapters(base.CH)
    from tools.manual_web_chords import enrich
    from tools.manual_controller_scope import scope_chapters
    from tools import manual_audio_loops, manual_native_synth, manual_current, manual_plain_language, manual_native_effects, manual_clip_arranger, manual_controller_stems, manual_sample_sets
    enrich(base.CH, language)
    scope_chapters(base.CH, language)
    for module in (manual_audio_loops, manual_native_synth, manual_current, manual_plain_language, manual_native_effects, manual_clip_arranger, manual_controller_stems, manual_sample_sets):
        module.enrich(base.CH, language)
    base.MANUAL_LANGUAGE = language
    return base.CH


def asset(path):
    path = Path(path)
    body = path.read_bytes()
    name = hashlib.sha256(body).hexdigest()[:24] + path.suffix.lower()
    target = DEST / 'images' / name
    target.write_bytes(body)
    return 'images/' + name


def document(title, language, body):
    return f'''<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Machinista</title><meta name="description" content="Machinista illustrated controller manual — workflows, WebUI and display reference.">
<link rel="stylesheet" href="manuals.css"></head><body>{body}</body></html>'''


def build(device, language, chapters, catalog):
    de = language == 'de'
    title = NAMES[device] + (' — Bedienungsanleitung' if de else ' — User manual')
    choose = lambda value: escape(base.choose(value, device))
    resolver = object.__new__(base.Manual)
    resolver.catalog = catalog
    def figure(item):
        return f'<figure class="{"micro" if device == "mikro" else "wide"}"><img class="display" src="{asset(item["paths"][device])}" alt="{escape(item["label"], quote=True)}" loading="lazy"><figcaption>{escape(item["label"])}</figcaption></figure>'
    def prose(ch):
        out = '<p>' + choose(ch['intro']) + '</p>'
        if ch.get('table'):
            out += '<table>'
            for i, row in enumerate(ch['table']):
                tag = 'th' if i == 0 else 'td'
                out += '<tr>' + ''.join(f'<{tag}>{choose(v)}</{tag}>' for v in row) + '</tr>'
            out += '</table>'
        if ch.get('steps'):
            out += '<ol>' + ''.join('<li>' + choose(v) + '</li>' for v in ch['steps']) + '</ol>'
        for heading, body in ch.get('notes', []):
            if base.choose(body, device):
                out += f'<p class="note"><strong>{choose(heading)}.</strong> {choose(body)}</p>'
        return out
    toc = ''.join(f'<li><a href="#chapter-{i+1}">{escape(ch["title"])}</a></li>' for i,ch in enumerate(chapters))
    contents = 'Inhalt' if de else 'Contents'
    atlas_title = 'Displayübersicht' if de else 'Screen reference'
    nav = f'<nav aria-label="{contents}"><h2>{contents}</h2><ol>{toc}</ol><a href="#screens">{atlas_title}</a></nav>'
    text = ''
    for i,ch in enumerate(chapters):
        text += f'<section id="chapter-{i+1}"><h2>{i+1:02} · {escape(ch["title"])}</h2>'
        text += prose(ch)
        for name in ch.get('screens', []):
            if device != 'mikro' and name in ('PARAM NAV','SAMPLING NAV'):continue
            text += figure(resolver.workflow_figure(ch.get('source_title',ch['title']), name))
        for sup in ch.get('supplements', []):
            text += f'<h3>{escape(sup["title"])}</h3>' + prose(sup)
            for label in sup.get('figures', []):
                text += figure(next(x for x in catalog if x['label'] == label))
            for image in sup.get('images', []):
                text += f'<figure><img src="{asset(base.ROOT / "assets/manual-web" / (image + ".png"))}" alt="WebUI: {escape(image)}" loading="lazy"><figcaption>WebUI · {escape(image)}</figcaption></figure>'
        text += f'<a class="top" href="#top">{"Zum Anfang" if de else "Back to top"}</a></section>'
    text += f'<section id="screens"><h2>{atlas_title}</h2>'
    seen = set(); count = 0
    for item in catalog:
        if device == 'mikro' and item['page'] in ('CONTRAST L','CONTRAST R'):continue
        if device != 'mikro' and item['page'] in ('CONTRAST','PARAM NAV','SAMPLING NAV'):continue
        digest = item['hashes'][device]
        if digest in seen:continue
        seen.add(digest); count += 1
        text += '<h3>' + escape(item['page']) + '</h3>' + figure(item)
        fields = item.get('fields_by_device', {}).get(device, item.get('fields', []))
        if fields:text += '<p>' + escape(' · '.join(f'{k}: {v}' for k,v in fields)) + '</p>'
    text += '</section>'
    alternate = 'en' if de else 'de'
    filename = 'Mikro_MK1' if device == 'mikro' else device.upper()
    pdf = f'https://github.com/photogeen/machinista/releases/download/v0.1.0-beta.18/Machinista_{filename}_User_Manual_{language.upper()}.pdf'
    body = f'<a class="skip" href="#content">{"Zum Inhalt" if de else "Skip to content"}</a><header id="top"><a href="index.html">Machinista · {"Alle Handbücher" if de else "All manuals"}</a><h1>{escape(title)}</h1><p><a href="{device}-{alternate}.html" lang="{alternate}">{"English" if de else "Deutsch"}</a> · <a href="{pdf}">PDF</a> · <a href="https://github.com/photogeen/machinista">GitHub</a></p><p>{"Englische Menü- und Tastennamen bleiben unverändert." if de else "Illustrated workflows, WebUI instructions and complete display reference."}</p></header><main class="layout">{nav}<article id="content">{text}</article></main><footer>Machinista · 7 November 2026 · <a href="index.html">{contents}</a></footer>'
    (DEST / f'{device}-{language}.html').write_text(document(title,language,body))
    return {'controller':device,'language':language,'chapters':len(chapters),'screens':count}


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    (DEST / 'images').mkdir(exist_ok=True)
    (DEST / 'manuals.css').write_text(CSS)
    catalog = json.loads((base.ASSETS/'catalog.json').read_text())
    original = copy.deepcopy(base.CH)
    report = []
    for language in ('en','de'):
        chapters = prepare(language, original)
        for device in NAMES:report.append(build(device,language,chapters,catalog))
    cards = ''.join(f'<div class="card"><h2>{escape(name)}</h2><p><a href="{device}-en.html">English</a> · <a href="{device}-de.html">Deutsch</a></p></div>' for device,name in NAMES.items())
    (DEST/'index.html').write_text(document('User manuals / Bedienungsanleitungen','en',f'<header><div class="eyebrow">MACHINISTA</div><h1>User manuals<br>Bedienungsanleitungen</h1><p>Choose your controller and language. / Wähle deinen Controller und deine Sprache.</p><p>MK3 / Maschine+: Controller mode with a connected Pi.</p><a href="https://github.com/photogeen/machinista">GitHub</a></header><main class="cards">{cards}</main>'))
    (DEST/'.nojekyll').write_text('')
    (DEST/'build-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    # Remove stale generated images without touching unrelated development files.
    used = ''.join(p.read_text() for p in DEST.glob('*.html'))
    for image in (DEST/'images').glob('*.png'):
        if image.name not in used:image.unlink()
    print(json.dumps(report,indent=2))

if __name__ == '__main__':main()
