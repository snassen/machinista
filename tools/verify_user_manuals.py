"""Check release manuals, build manifests and render printable review sheets.

Offline only. No controller, audio engine or project files are opened.
"""
import hashlib,json,re,zipfile
from pathlib import Path
from pypdf import PdfReader
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/pdf';REVIEW=ROOT/'tmp/pdfs/manual-review'


def verify():
    REVIEW.mkdir(parents=True,exist_ok=True);results=[]
    catalog=json.loads((ROOT/'tmp/pdfs/manual-assets/catalog.json').read_text())
    for item in catalog:
        for device in ('mikro','mk1','mk2','mk3'):
            assert Path(item['paths'][device]).is_file(),(item['label'],device)
    for lang in ('EN','DE'):
        outputs=[]
        for device in ('Mikro_MK1','MK1','MK2','MK3'):
            path=OUT/f'Machinista_{device}_User_Manual_{lang}.pdf';reader=PdfReader(path)
            texts=[p.extract_text() for p in reader.pages];text='\n'.join(texts)
            assert len(reader.pages)>80
            assert all('0.1.0-beta.18' in t for t in texts[1:]), (path.name, 'outdated footer version')
            for forbidden in ('Native Instruments','Editor notes','Banken'):
                assert forbidden not in text,(path.name,forbidden)
            for other in ('MK1','MK2','MK3','Mikro'):
                if other not in device:assert not re.search(r'\b'+other+r'\b',text),(path.name,other)
            assert ('7 November 2026' if lang=='EN' else '7. November 2026') in texts[0]
            assert ('selected Sound/pad only' if lang=='EN' else 'ausgewählten Sounds/Pads') in text,path.name
            assert ('Your first sound - no samples needed' if lang=='EN' else 'Dein erster Sound - ohne eigene Samples') in text
            assert ('Words you will see on screen' if lang=='EN' else 'Begriffe auf dem Display') in text
            assert all(value in text for value in ('Ducktor','SoundFont','FOLLOW','SELECT','Sample Kits','Import folder'))
            if device!='Mikro_MK1':
                assert not any('\n'+page+'\n' in text for page in ('PARAM NAV','SAMPLING NAV')),(path.name,'Mikro-only intermediate view')
            if device=='MK3':assert all(v in text for v in ('480 x 272','4D','Smart Strip'))
            # Chapter links must resolve to the page bearing the same chapter number.
            for dest in reader.outline:
                if isinstance(dest,list):continue
                page=reader.get_destination_page_number(dest)
                assert page is not None and 0<=page<len(texts),(path.name,dest.title)
                number=re.match(r'^(\d{2})\s',dest.title)
                if number:assert re.search(r'\b'+number[1]+r'\s',texts[page]),(path.name,dest.title,page)
            errors=[]
            with pdfplumber.open(path) as pdf:
                for i,page in enumerate(pdf.pages):
                    for word in page.extract_words():
                        if word['x0']<39 or word['x1']>page.width-39 or word['top']<18 or word['bottom']>page.height-16:
                            errors.append((i+1,word['text'],round(word['x0'],1),round(word['top'],1)))
            assert not errors,(path.name,errors[:12])
            # All MK3 pages, plus overview and changed chapters in existing guides.
            pdf=pdfium.PdfDocument(path)
            selected=range(len(pdf)) if device=='MK3' else [i for i,t in enumerate(texts) if i==0 or any(x in t for x in ('Events: select a time range','Events: einen Zeitbereich','Ducktor:','SoundFonts as native','SoundFonts als native','Die Anzeigen verstehen','Reading the displays'))]
            # Render every revised guide page; unchanged reference atlases stay covered
            # by layout checks, with the full color atlas retained for visual review.
            atlas_begin=next((i for i,t in enumerate(texts) if ('Screen atlas / workspace index' in t or 'Displayübersicht / Arbeitsbereichsindex' in t) and i>5),len(texts))
            indices=sorted(set(selected)|set(range(atlas_begin)))
            for bank in range((len(indices)+29)//30):
                sheet=Image.new('RGB',(1000,1500),'#d9d9d9');draw=ImageDraw.Draw(sheet)
                for j,idx in enumerate(indices[bank*30:(bank+1)*30]):
                    image=pdf[idx].render(scale=.34).to_pil();image.thumbnail((188,230));x=(j%5)*200;y=(j//5)*250
                    sheet.paste(image,(x+6,y+16));draw.text((x+7,y+2),str(idx+1),fill='black')
                sheet.save(REVIEW/f'{device}-{lang}-contact-{bank+1}.png')
            for i,t in enumerate(texts):
                if (device=='MK3' and (i in (0,5,15,16) or any(x in t for x in ('Ducktor:','SoundFonts as native','SoundFonts als native')))) or ('Events: einen Zeitbereich' in t):
                    pdf[i].render(scale=1.25).to_pil().save(REVIEW/f'{device}-{lang}-p{i+1}.png')
            row=dict(file=path.name,pages=len(reader.pages),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),annotations=sum(len(p.get('/Annots',[])) for p in reader.pages),layout_errors=errors)
            outputs.append(row);results.append(row)
        sources={}
        for pattern in ('tools/*manual*.py','app/mk3*.py','app/pattern_editor.py','app/mk2_surface.py'):
            for source in ROOT.glob(pattern):sources[str(source.relative_to(ROOT))]=hashlib.sha256(source.read_bytes()).hexdigest()
        manifest=dict(edition='2026-11-07',software='Machinista 0.1.0-beta.18 / Fokus V2',accent='orange',outputs=outputs,sources=sources)
        (OUT/('manuals-manifest.json' if lang=='EN' else 'manuals-manifest-de.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(OUT/'Machinista-Manuals-EN-DE.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for row in results:archive.write(OUT/row['file'],row['file'])
        for name in ('manuals-manifest.json','manuals-manifest-de.json'):archive.write(OUT/name,name)
    (REVIEW/'verification.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__':verify()
