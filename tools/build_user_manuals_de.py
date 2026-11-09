"""Build German manuals from the same unchanged English display assets."""
from pathlib import Path
import json,re,hashlib
import tools.build_user_manuals as base
from tools.manuals_de import localize_chapters,SCREEN_HELP

WORDS={
'USER MANUAL':'BEDIENUNGSANLEITUNG',
'User Manual':'Bedienungsanleitung',
'English':'Deutsch',
'English edition':'Deutsche Ausgabe',
'Play. Record. Slice. Sequence. Arrange.':'Spielen. Aufnehmen. Slicen. Sequenzieren. Arrangieren.',
'18 October 2026':'18. Oktober 2026',
'22 October 2026':'22. Oktober 2026',
'24 October 2026':'24. Oktober 2026',
'27 October 2026':'27. Oktober 2026',
'8 November 2026':'8. November 2026',
' / continued':' / Fortsetzung',
'Workflows, controls and illustrated screen reference':'Arbeitsabläufe, Bedienung und bebilderte Displayübersicht',
'Contents':'Inhalt',
'Contents / continued':'Inhalt / Fortsetzung',
'Guide':'Anleitung',
'Workflow / reference':'Arbeitsablauf / Referenz',
'Display reference':'Displayübersicht',
'Screen atlas / workspace index':'Displayübersicht / Arbeitsbereichsindex',
'Screen atlas / index continued':'Displayübersicht / Index-Fortsetzung',
'Select a chapter title to jump to it. The screen atlas follows the workflow chapters.':'Wähle einen Kapiteltitel, um dorthin zu springen. Die Displayübersicht folgt auf die Bedienkapitel.',
'Notation: CAPITALS identify hardware buttons or displayed labels. A + means hold the first control while operating the next. Numbered steps describe the order of an operation.':'Schreibweise: GROSSBUCHSTABEN bezeichnen Tasten oder angezeigte Beschriftungen. Ein + bedeutet: das erste Bedienelement halten und das nächste betätigen. Nummerierte Schritte geben die Reihenfolge an.',
'Find the workspace name in this index. Atlas figures preserve the actual display pixels. Not every illustrated state is reached by a separate button: many are parameter banks, temporary overlays or confirmation steps.':'Suche den englischen Namen des Arbeitsbereichs im Index. Die Abbildungen erhalten die Displaypixel. Nicht jede Anzeige hat eine eigene Taste: Viele sind Parameterbänke, vorübergehende Einblendungen oder Bestätigungen.',
'A settings subpage; return to its parent folder when finished.':'Eine Unterseite der Einstellungen. Kehre nach dem Einstellen in den übergeordneten Ordner zurück.',
'Use the displayed action labels. In settings, choose the value with the encoder and return to the parent folder with ENTER.':'Nutze die angezeigten Aktionen. Wähle in den Einstellungen den Wert mit dem Encoder und kehre mit ENTER zum übergeordneten Ordner zurück.',
}

def tr(text):
    if text.endswith(' / continued') and not text.startswith('Contents'):
        return tr(text[:-12])+' / Fortsetzung'
    if text in WORDS:return WORDS[text]
    captions={
        'Startup / controller connected':'Start / Controller verbunden',
        'Record / running':'RECORD / Aufnahme läuft',
        'Edit / play range':'EDIT / Wiedergabebereich',
        'Edit / selection':'EDIT / Auswahl',
        'Apply / first None':'APPL.TO / alle Sounds',
        'Apply / first 0':'APPL.TO / erster Sound 1',
        'Apply / first 15':'APPL.TO / erster Sound 16',
        'Editor / pitches False':'Editor / Sound-Zeilen',
        'Editor / pitches True':'Editor / Tonhöhen',
        'Tutorial / Slice zoom':'Beispiel / Slice-Zoom',
        'Tutorial / Keyboard':'Beispiel / Keyboard',
        'Tutorial / Wave zoom':'Beispiel / Wellenform-Zoom',
    }
    if text in captions:return captions[text]
    if ' / ' in text and not text.startswith('<'):
        text=text.replace(' / page ',' / Seite ').replace(' / bank ',' / Bank ').replace(' / row ',' / Zeile ')
        text=text.replace('Settings / ','Einstellungen / ').replace('Projects / ','Projects / ')
        text=text.replace('Storage / ','Datenträger / ').replace('System / Storage ','System / Datenträger ')
        text=text.replace('Pad config / keyboard False / ','PAD CONFIG / PAD / Seite ')
        text=text.replace('Pad config / keyboard True / ','PAD CONFIG / KEYBOARD / Seite ')

    # Case-converted headers/footers are drawn directly onto the canvas.
    if text=='User Manual  |  0.1.0-beta.19  |  English':return 'Bedienungsanleitung  |  0.1.0-beta.19  |  Deutsch'
    for english,german in WORDS.items():
        if text==english.upper():return german.upper()
    if text.startswith('Screen atlas / '):return text.replace('Screen atlas / ','Displayübersicht / ',1)
    if text.startswith('<b>Screen atlas</b> begins on page '):
        page=re.search(r'page (\d+)',text).group(1)
        return f'<b>Displayübersicht</b> ab Seite {page}. Sie enthält einen Arbeitsbereichsindex, die aktuellen Displayabbildungen und Hinweise zur Bedienung des jeweiligen Controllers.'
    return text

class LocalizedCanvas:
    def __init__(self,original):self.original=original
    def __getattr__(self,name):return getattr(self.original,name)
    def drawString(self,x,y,text,*args,**kwargs):return self.original.drawString(x,y,tr(text),*args,**kwargs)
    def drawRightString(self,x,y,text,*args,**kwargs):return self.original.drawRightString(x,y,tr(text),*args,**kwargs)
    def drawCentredString(self,x,y,text,*args,**kwargs):return self.original.drawCentredString(x,y,tr(text),*args,**kwargs)
    def addOutlineEntry(self,title,*args,**kwargs):return self.original.addOutlineEntry(tr(title),*args,**kwargs)

class GermanManual(base.Manual):
    def __init__(self,device,catalog):
        # Reuse renderer assets and geometry, never localize application state.
        super().__init__(device,catalog)
        self.path=base.OUT/f'Machinista_{"Mikro_MK1" if device=="mikro" else device.upper()}_User_Manual_DE.pdf'
        self.c=base.canvas.Canvas(str(self.path),pagesize=(base.W,base.H),pageCompression=1)
        self.c.setTitle('Machinista - '+self.name+' Bedienungsanleitung')
        self.c.setAuthor('Machinista');self.c.setSubject('Deutsche Bedienungsanleitung und Displayübersicht | 0.1.0-beta.19')
        from reportlab.pdfbase.pdfdoc import PDFString
        self.c._doc.Catalog.Lang=PDFString('de-DE')
        self.c=LocalizedCanvas(self.c)
    def text(self,text,*args,**kwargs):return super().text(tr(text),*args,**kwargs)
    def atlas_hint(self,page):
        if page in SCREEN_HELP:return base.choose(SCREEN_HELP[page],self.device)
        return tr('A settings subpage; return to its parent folder when finished.')
    def shot(self,item,y,caption=None):
        if caption and caption.startswith('Workspace: '):caption=caption.replace('Workspace: ','Arbeitsbereich: ',1)
        return super().shot(item,y,caption)

if __name__=='__main__':
    original=base.CH;base.CH=localize_chapters(original)
    from tools.manual_web_chords import enrich
    enrich(base.CH,'de')
    from tools.manual_controller_scope import scope_chapters,system_hint
    scope_chapters(base.CH,'de');SCREEN_HELP['SYSTEM']=system_hint('de')
    from tools.manual_audio_loops import enrich as enrich_audio
    enrich_audio(base.CH,'de')
    from tools.manual_native_synth import enrich as enrich_synth
    enrich_synth(base.CH,'de')
    from tools.manual_current import enrich as enrich_current
    enrich_current(base.CH,'de')
    from tools.manual_plain_language import enrich as enrich_plain
    enrich_plain(base.CH,'de')
    from tools.manual_native_effects import enrich as enrich_effects
    enrich_effects(base.CH,'de')
    from tools.manual_clip_arranger import enrich as enrich_clips
    enrich_clips(base.CH,'de')
    from tools.manual_controller_stems import enrich as enrich_stems
    enrich_stems(base.CH,'de')
    from tools.manual_sample_sets import enrich as enrich_sets
    enrich_sets(base.CH,'de')
    base.MANUAL_LANGUAGE='de'
    # The same source labels choose the same chapter-specific screenshots.
    catalog=json.loads((base.ASSETS/'catalog.json').read_text()) if (base.ASSETS/'catalog.json').exists() else base.render_assets()
    required={label for ch in base.CH for supplement in ch.get('supplements',[]) for label in supplement.get('figures',[])}
    if not required.issubset({item['label'] for item in catalog}):catalog=base.render_assets()
    report=[base.build(GermanManual,device,catalog) for device in ('mikro','mk1','mk2','mk3')]
    (base.ASSETS/'build-report-de.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    if any(item['overflow'] for item in report):raise SystemExit(2)
