"""Native color MK3 views. Immutable snapshots, real meters/waveforms only."""
import math
import time
from app.mk3_theme import themed,resolve,foreground,GroupColor
from pathlib import Path
from app.mk3_graphics import Canvas,BG,PANEL,LINE,INK,MUTED,ACCENT,GROUPS,font,content_y
from app.mk3_style import CYAN,PURPLE,YELLOW,GREEN,RED,tint,parameter_color

class Mk3Renderer:
    def __init__(self,startup=False):
        from app.mk3_waveforms import Mk3Waveforms
        self.waveforms=Mk3Waveforms();self.cached_wave_revision=-1;self.needs_refresh=False;self.cached_state=None;self.cached_images=None;self.scene_renders=0;self.encoder=None;self.encoder_tried=False;self.wire_images={}
        from app.text_marquee import Marquee
        self.marquee=Marquee();self.chain_key=None;self.chain_previous=None;self.chain_transition=None
    def dismiss_boot(self):pass
    def close(self):
        self.waveforms.close()
        if self.encoder:self.encoder.close()
    def list(self,c,items,index,y=88,first=None):
        index=max(0,min(index,len(items)-1))
        first=max(0,min(index-2,len(items)-6)) if first is None else max(0,first)
        for row,item in enumerate(items[first:first+6]):
            selected=first+row==index;yy=y+row*21
            if selected:c.rect(8,yy,464,21,ACCENT,radius=3)
            c.text(17,yy+1,item,15,selected,BG if selected else INK,width=444)
    def plugin_values(self,c,state):
        for number,label,value,fraction in state.get('plugin_values',())[:8]:
            column,row=divmod(number-1,4);x=15+column*234;y=88+row*31
            color=parameter_color(label,state.get('group',0))
            c.text(x,y,str(number),10,True,color,width=13)
            c.text(x+17,y,label,11,color=INK,width=137)
            # Numeric values are deliberately smaller than the encoder footer.
            c.text(x+157,y,value,11,color=MUTED,width=63)
            c.rect(x,y+20,216,3,PANEL)
            c.rect(x,y+20,round(216*max(0,min(1,fraction))),3,color)
    def kit_cover(self,canvas,browser,selected):
        if selected is None or not browser.kit_source(selected):
            return False
        from app.kit_artwork import KIT_ARTWORK,expansion_artwork,thumbnail
        base=selected.parent.parent if selected.name=='Preset.json' else selected
        expansion=not (base/'Set.json').is_file()
        folder=base if expansion else base.parent
        try:
            shared=expansion_artwork(folder,folder.stat().st_mtime_ns) if (folder/'.expansion').is_file() else None
        except OSError:
            shared=None
        if expansion and shared is None:return False
        base=shared or base
        art=thumbnail(base/KIT_ARTWORK['artwork'],(230,116))
        logo=thumbnail(base/KIT_ARTWORK['logo'],(205,76))
        if art is None and logo is None:
            return False
        right=460
        if art is not None:
            left=135-art.width//2 if logo else right-art.width
            canvas.image.paste(art,(left,content_y(142-art.height//2,canvas.compact_header)),art)
        image=logo or art
        top=142-image.height//2
        if logo is not None:
            canvas.image.paste(logo,(right-logo.width,content_y(top,canvas.compact_header)),logo)
        if expansion:return True
        label=browser.label(selected)
        face=font(15,True)
        width=220 if logo and art else 440
        while face.getlength(label)>width:
            label=label[:-2]+'…' if label.endswith('…') else label[:-1]+'…'
        canvas.text(right-face.getlength(label),top+image.height+5,label,15,True,width=width)
        return True

    def capture_meter(self,c,peaks,threshold=None):
        # Match the monochrome recording meters: amplitude and trigger marker
        # both use a -60..0 dBFS axis, rather than linear signal amplitude.
        def fraction(db):return max(0,min(1,(db+60)/60))
        for i,value in enumerate(peaks[:2]):
            y=100+i*43
            c.text(3,y+5,'LR'[i],11,True,color=MUTED)
            c.rect(18,y,440,25,PANEL)
            level=fraction(20*math.log10(max(.001,value)))
            c.rect(18,y,round(440*level),25,GREEN)
            if threshold is not None:
                x=18+round(439*fraction(threshold))
                c.line((x,y-3,x,y+28),ACCENT,2)
        for db in (-60,-48,-36,-24,-12,0):
            x=18+round(439*fraction(db))
            c.line((x,172,x,175),MUTED)
            c.text(x,178,str(db),10,color=MUTED,center=db!=-60)
    def wave(self,c,ref,state):
        path,first,last=ref
        if not path:
            c.rect(8,82,464,120,PANEL,radius=4);c.text(240,128,'No sample',16,color=MUTED,center=True);return
        env=self.waveforms.envelope(path,first,last if last and last>first else None,columns=460)
        c.rect(8,82,464,120,PANEL,radius=4);c.line((10,142,469,142),LINE)
        if env is None:return
        if not env.peaks:c.text(240,128,'No sample',16,color=MUTED,center=True);return
        start,end=env.start,env.end;span=max(1,end-start)
        marks=state.get('markers',());selected=state.get('slice_index',0)
        for i,(lo,hi) in enumerate(marks):
            if hi<=start or lo>=end:continue
            x=10+round(458*max(0,lo-start)/span);right=10+round(458*min(span,hi-start)/span)
            if i==selected:c.rect(x,84,max(1,right-x),116,tint(getattr(self,'accent',ACCENT),.48))
            if start<=lo<=end:c.line((x,84,x,199),CYAN,2)
            if start<=hi<=end:c.line((right,84,right,199),PURPLE,2)
        for i,(lo,hi) in enumerate(env.peaks):
            x=10+round(i*458/max(1,len(env.peaks)-1));c.line((x,142-round(hi*53),x,142-round(lo*53)),INK,2)
        cursor=state.get('wave_cursor')
        if cursor is not None and start<=cursor<=end:
            x=10+round((cursor-start)*458/span);c.line((x,84,x,200),YELLOW,2)
    def grid(self,c,g):
        rows=g['rows'];cols=g['columns'];h=120/max(1,len(rows));w=420/max(1,cols)
        for r,(caption,focus,cells) in enumerate(rows):
            y=82+r*h;c.text(8,y,caption,13,focus,ACCENT if focus else MUTED,width=45)
            for col,(valid,present,selected,cursor) in enumerate(cells):
                x=52+col*w;c.rect(x,y,w-1,h-1,PANEL if valid else BG,LINE if col%4==0 else None)
                if present:c.rect(x+2,y+3,max(2,w-4),h-6,ACCENT if selected else '#7cae8b')
                if cursor:c.rect(x,y,w-1,h-1,fill=None,outline=INK)
        if g['playhead'] is not None:
            x=52+max(0,min(1,(g['playhead']-29)/96))*420;c.line((x,82,x,202),YELLOW,2)
        c.text(8,202,g['footer'],12,color=MUTED,width=464)
    def events(self,p,q,g):
        start,end=g['start'],g['end'];span=max(1,end-start);x0=48;w=416;y0=106;rh=12
        for row,(caption,focus) in enumerate(g['rows']):
            y=y0+row*rh;p.rect(11,y,32,rh-1,tint(ACCENT,.45) if focus else PANEL,radius=1)
            p.text(15,y-1,caption,10,focus,ACCENT if focus else MUTED,width=29)
            p.rect(x0,y,w,rh-1,tint(self.accent,.25) if focus else PANEL)
        selection=g.get('selection_range')
        if selection and selection[0]<end and selection[1]>start:
            left=x0+max(0,selection[0]-start)*w/span;right=x0+min(span,selection[1]-start)*w/span
            top,bottom=y0-2,202
            if not g['notes_mode']:
                row=next((i for i,v in enumerate(g['rows']) if v[1]),0)
                top=y0+row*rh;bottom=top+rh-1
            p.rect(left,top,max(1,right-left),bottom-top,tint(ACCENT,.20))
            p.line((left,top,left,bottom),ACCENT);p.line((right,top,right,bottom),ACCENT)
        step=max(g['unit'],math.ceil(span/64/max(1,g['unit']))*max(1,g['unit']))
        for tick in range((start//step)*step,end+step,step):
            if tick<start or tick>end:continue
            x=x0+(tick-start)*w/span;p.line((x,y0,x,y0+96),LINE if tick%96==0 else '#293440')
        beat=max(96,math.ceil(span/768)*96)
        for tick in range(math.ceil(start/beat)*beat,end,beat):
            x=x0+(tick-start)*w/span
            p.text(x,89,f'{tick//384+1}.{tick%384//96+1}',10,tick%384==0,MUTED,width=min(45,464-x))
        for row,tick,duration,marked,cursor in reversed(g['notes']):
            left=x0+max(0,tick-start)*w/span;right=x0+min(span,tick+duration-start)*w/span
            y=y0+row*rh+2;color=ACCENT if marked or cursor else self.accent
            p.rect(left+1,y,max(2,right-left-2),rh-4,color,radius=2)
            if marked or cursor:p.rect(left,y-1,max(3,right-left),rh-2,None,INK,2)
        cursor=g['cursor']
        if start<=cursor<end:
            row=next((i for i,v in enumerate(g['rows']) if v[1]),0);x=x0+(cursor-start)*w/span
            p.rect(x,y0+row*rh,max(2,min(w*g['unit']/span,464-x)),rh-1,None,INK,1)
        phase=g['playhead']
        if phase is not None:
            x=x0+(phase-start)*w/span;p.line((x,y0-2,x,202),YELLOW,2)
            p.polygon(((x-4,102),(x+4,102),(x,107)),YELLOW)
        p.text(12,203,f'{start//384+1}-{max(start,end-1)//384+1} BAR / {g["grid"]} GRID',10,color=MUTED,width=245)
        p.text(300,203,f'{g["selected_count"]} SELECTED',10,color=ACCENT,width=168)
        detail=g['detail']
        if detail:
            q.rect(12,96,116,73,tint(ACCENT,.40),radius=4)
            q.text(70,99,'SELECTED' if g['selected_count'] else 'CURSOR',10,True,ACCENT,width=100,center=True)
            q.text(70,119,detail['pitch'],30,True,width=100,center=True)
            for x,label,value in ((145,'POSITION',detail['position']),(315,'LENGTH',detail['length'])):
                q.text(x,100,label,10,color=MUTED,width=140);q.text(x,119,value,19,True,width=140)
            q.text(145,148,'VELOCITY '+str(detail['velocity']),12,True,CYAN,width=165)
            q.text(315,148,'PROB. '+str(detail['probability'])+'%',12,color=MUTED,width=145)
        else:
            q.text(20,107,'EMPTY CELL',23,True,width=440)
            q.text(20,148,'Press encoder to insert a note',15,color=MUTED,width=440)
        q.rect(12,178,456,25,PANEL,radius=2)
        for tick,velocity,marked,cursor in reversed(g['velocities']):
            x=18+(tick-start)*444/span;h=round(max(0,min(127,velocity))*21/127)
            q.rect(x,200-h,4,h,ACCENT if marked or cursor else self.accent)
        if phase is not None:
            x=18+(phase-start)*444/span;q.line((x,176,x,203),YELLOW,2)
        q.text(12,204,'EVENT VELOCITIES',9,color=MUTED,width=450)

    def tiles(self,c,items,offset=0,empty_selection_outline=False):
        for slot,(label,present,selected) in enumerate(items[:16]):
            x=12+slot%4*116;y=89+(3-slot//4)*30
            empty_selected=empty_selection_outline and selected and not present
            c.rect(x,y,108,27,PANEL if empty_selected else ACCENT if selected else getattr(self,'accent',ACCENT) if present else PANEL,ACCENT if empty_selected else INK if selected else None,3)
            c.text(x+54,y+4,label,12,selected,ACCENT if empty_selected else BG if selected or present else MUTED,width=100,center=True)

    def synth_plot(self,c,graph):
        color=PURPLE if 'ENV' in graph.get('title','') else parameter_color(graph.get('title','SYNTH'))
        c.rect(8,86,464,126,BG)
        c.rect(12,88,456,120,PANEL,radius=4)
        c.text(20,90,graph.get('title','SYNTH'),12,True,color,width=440)
        points=graph.get('points',())
        if points:
            for y in (112,158,204):c.line((16,y,463,y),LINE)
            c.line(tuple((16+i*447/max(1,len(points)-1),158-max(-1,min(1,v))*46) for i,v in enumerate(points)),color,3)
        elif 'levels' in graph:
            for i,value in enumerate(graph['levels']):
                x=24+i*112
                c.text(x+40,108,'OSC '+str(i+1),10,True,color,width=80,center=True)
                c.rect(x,122,80,82,BG,radius=3)
                h=round(max(0,min(1,value))*82)
                if h:c.rect(x,204-h,80,h,color,radius=2)
        elif 'route' in graph:
            c.text(24,144,' → '.join(graph['route']),20,True,width=432)
        elif graph.get('missing'):
            c.text(24,144,'MISSING WAVE',20,True,RED,width=432)

    def pad_grid(self,c,state,x,y,cell=22):
        color=GROUPS[state.get('group',0)%8];selected=state.get('pad',0)
        for pad in range(16):
            xx=x+(pad%4)*(cell+4);yy=y+(3-pad//4)*(cell+4);active=pad==selected
            c.rect(xx,yy,cell,cell,color if active else tint(color,.28),INK if active else color,3)
            c.text(xx+cell/2,yy+(cell-14)/2,str(pad+1),10,active,BG if active else color,width=cell-2,center=True)

    def navigate(self,p,q,s):
        from app.navigation_art import image
        for side,c in enumerate((p,q)):
            for i in range(4):
                index=side*4+i;x=3+i*120
                selected=i in s.get('active_left' if side==0 else 'active_right',())
                c.rect(x,91,114,115,PANEL,ACCENT if selected else LINE,8)
                if selected:
                    c.rect(x+1,92,112,113,None,ACCENT,7)
                    c.rect(x+13,201,88,3,ACCENT,radius=1)
                icon=image(index,selected)
                if icon is not None:c.image.paste(icon,(x+19,102),icon)
                c.text(x+57,182,s['keys'][index],12,True,INK,width=106,center=True)

    def clip_arranger(self,p,q,a):
        from app.clip_arranger import position,duration
        x0=42;width=422;span=a['last']-a['first'];rowheight=13
        for g,label in a['groups']:
            row=g-a['groups'][0][0];y=99+row*rowheight;color=GROUPS[g%8]
            p.rect(10,y,27,rowheight-1,color if g==a['group'] else PANEL,radius=2)
            p.text(23,y-1,label,10,True,foreground(color) if g==a['group'] else MUTED,center=True,width=25)
            p.rect(x0,y,width,rowheight-1,PANEL)
        step=max(384,math.ceil(span/3072)*384)
        for tick in range(a['first']//step*step,a['last']+1,step):
            x=x0+(tick-a['first'])*width/span
            if not x0<=x<=464:continue
            p.line((x,97,x,202),LINE)
            p.text(x,84,str(tick//384+1),10,color=MUTED,width=min(40,480-x))
        for clip in a['clips']:
            y=100+(clip['group']-a['groups'][0][0])*rowheight
            x=x0+max(0,clip['start']-a['first'])*width/span
            end=x0+min(span,clip['start']+clip['length']-a['first'])*width/span
            color=GROUPS[clip['group']%8];selected=a['selected'] and clip['id']==a['selected']['id']
            p.rect(x+1,y,max(1,end-x-2),10,color,radius=2)
            if end-x>30:p.text(x+4,y-1,'P'+str(clip['pattern']+1),9,True,foreground(color),width=end-x-7)
            if selected:p.rect(x,y-1,max(2,end-x),12,None,INK,2)
        phase=a['phase'] if a['phase'] is not None else a['cursor']
        if a['first']<=phase<=a['last']:
            x=x0+(phase-a['first'])*width/span;p.line((x,97,x,204),YELLOW,2)
        c=a['selected']
        if c:
            q.text(18,92,'GROUP '+str(a['rows'][0][1])+' / PATTERN '+str(c['pattern']+1),20,True,width=444)
            q.text(18,122,'LINKED PATTERN · '+str(a['links'])+' CLIPS',12,color=MUTED,width=444)
            q.rect(18,148,444,45,PANEL,radius=3)
            for pad,tick,gate in a['preview']:
                x=23+tick*432/a['pattern_ticks'];right=min(455,x+gate*432/a['pattern_ticks'])
                q.rect(x,152+pad%8*5,max(2,right-x),3,GROUPS[c['group']%8])
            q.text(18,199,'SHIFT + COPY: MAKE UNIQUE',11,color=MUTED,width=440)
        else:
            q.text(18,94,'NO CLIP SELECTED',22,True,width=440)
            q.text(18,132,'ADD at '+position(a['cursor']),16,color=MUTED,width=440)
            q.text(18,168,'FROM SONG copies your Scene sequence',13,color=MUTED,width=440)

    def mixer(self,p,q,s):
        """Eight physical encoder strips, continuous group-colored stereo meters."""
        m=s['mixer'];master=m.get('master_mixer');field=m.get('mixer_field',0)
        for side,c in enumerate((p,q)):
            for i in range(4):
                index=side*4+i
                if master:
                    if side or i>1:continue
                    slot=0;pair=(m['levels'][0][i],);caption=('L','R')[i];color=self.accent
                elif index<len(m['levels']):
                    slot=index;pair=m['levels'][slot][:2];caption=m['names'][slot]
                    color=GROUPS[m.get('colors',(s.get('group',0)%8,)*len(m['levels']))[slot]]
                else:continue
                x=11+i*118;selected=master or m['first']+index==m['selected']
                mute,solo=m.get('status',((False,False),)*len(m['levels']))[slot]
                c.rect(x,94,104,107,PANEL,radius=3)
                header=color if selected else tint(color,.35)
                c.rect(x,94,104,23,header,radius=2)
                c.text(x+7,98,caption,11,True,foreground(header),width=88)
                for channel,value in enumerate(pair):
                    xx=x+12+channel*18;c.rect(xx,124,12,67,LINE)
                    db=20*math.log10(max(value,1e-9));h=round(max(0,min(1,(db+60)/60))*67)
                    if h:c.rect(xx,191-h,12,h,color)
                    peak=m['peaks'][slot][i if master else channel]
                    if peak>0:
                        held=round(max(0,min(1,(60+20*math.log10(peak))/60))*67)
                        c.rect(xx,191-held,12,2,RED if peak>=1 else INK)
                    if value>=1:c.rect(xx,123,12,3,RED)
                gain=m.get('gains',(1,)*len(m['levels']))[slot]
                c.line((x+77,127,x+77,189),LINE,3)
                fy=186-round(gain*56);c.rect(x+66,fy,23,7,INK,radius=1)
                if mute or solo:
                    c.rect(x+48,177,15,19,RED if mute else YELLOW,radius=2)
                    c.text(x+55,179,'M' if mute else 'S',10,True,BG,center=True,width=14)
                # The physical encoder footer keeps LEVEL/PAN/ROUTE bindings.
                f=s.get('fields',())[index] if index<len(s.get('fields',())) else None
                if f:
                    fx=i*120+5;c.rect(fx,222,110,44,PANEL,radius=3)
                    c.text(fx+7,225,f[0],10,color=MUTED,width=98)
                    c.text(fx+7,241,f[1],16,True,width=98)
                    c.rect(fx+7,261,96,3,LINE)
                    if field==0:c.rect(fx+7,261,round(96*gain),3,color)
                    else:c.rect(fx+7,261,96,3,color)
        if master:
            q.text(20,106,'MASTER OUTPUT',22,True,width=440)
            q.text(20,143,'L / R  ·  −60 TO 0 dBFS',13,color=MUTED,width=440)
            q.text(20,174,'PEAK HOLD / RESET',12,color=MUTED,width=440)

    @themed
    def draw(self,s):
        # Mixer strips span both displays and share one vertical baseline.
        p,q=Canvas(),Canvas(compact_header='mixer' not in s and 'view_origin' not in s);accent=GROUPS[s.get('group',0)%8]
        self.accent=accent
        keys=s.get('keys',('',)*8)
        for side,c in enumerate((p,q)):
            active=s.get('active_left' if side==0 else 'active_right',())
            for i,key in enumerate(keys[side*4:side*4+4]):
                chosen=i in active
                c.rect(i*120+3,3,114,24,ACCENT if chosen else PANEL,radius=3)
                if chosen:c.rect(i*120+7,26,106,2,ACCENT)
                c.text(i*120+60,6,key,12,True,BG if chosen else RED if key in ('DELETE','DEL ALL','REMOVE') else INK,width=106,center=True)
            if side==0:
                statuses=s.get('group_status',())
                for i,color in enumerate(GROUPS):
                    x=10+i*28;status=statuses[i] if i<len(statuses) else None
                    selected=i==s.get('group',0)%8
                    c.rect(x,35,22,17,color,INK if selected else None,radius=3)
                    c.text(x+11,35,chr(65+i),11,selected,foreground(color) if s.get('color_scheme')=='daylight' else BG,width=20,center=True)
                    if status and status[1]:c.line((x+3,49,x+18,38),RED,1)
                    elif status and status[2]:c.rect(x+16,36,3,3,YELLOW)
                running=s.get('recording') or s.get('capture_status')=='RECORDING'
                status='REC' if running else 'PLAY' if s.get('playing') else 'STOP'
                color=RED if running else GREEN if s.get('playing') else MUTED
                c.rect(252,35,48,17,color if running or s.get('playing') else PANEL,radius=3);c.text(276,35,status,11,True,BG if running or s.get('playing') else MUTED,width=44,center=True)
                c.text(316,34,f'{s.get("tempo",0):.2f}',13,True,width=67)
                c.text(438,34,s.get('position',''),13,True,width=73,center=True)
            title=(s.get('group_label',chr(65+s.get('group',0)%8))+' / '+s.get('title','Machinista')) if side==0 else s.get('choice',s.get('page',''))
            if s['page'] in ('CLIP ARRANGER','CLIP MENU'):title='CLIP ARRANGER' if side==0 else 'CLIP ACTIONS' if s['page']=='CLIP MENU' else 'SELECTED CLIP'
            if 'mixer' in s:
                m=s['mixer'];title=('MASTER MIXER' if m.get('master_mixer') else 'GROUP MIXER' if s.get('scope')==1 else 'SOUND MIXER')
            if side==0 and 'project_list' in s:title='MANAGE PROJECTS' if s['page']=='PROJECT MANAGE' else 'PROJECTS'
            if side==0 and 'updater' in s:title='SOFTWARE UPDATE'
            if side==0 and 'settings_menu' in s:title='SETTINGS / '+s['settings_menu'][0]
            if 'events_native' in s:
                if side==1:title='PATTERN EDITOR'
                else:
                    detail=s['events_native']['detail'];title='EVENT / '+detail['pitch'] if detail else 'EMPTY CELL'
            c.rect(10,59,4,25,accent)
            c.text(21,61,title,17,True,width=367)
            if s.get('page_total',1)>1:c.text(444,64,f'{s.get("page_index",0)+1}/{s["page_total"]}',11,color=MUTED,width=48,center=True)
            c.line((10,216,470,216),LINE)
            for i,f in enumerate(s.get('fields',())[side*4:side*4+4]):
                if f:
                    label,value=f;color=parameter_color(label,s.get('group',0))
                    if 'mixer' in s and side*4+i<len(s['mixer'].get('colors',())):color=GROUPS[s['mixer']['colors'][side*4+i]]
                    if 'mixer' in s:continue
                    c.rect(i*120+5,222,110,44,color,radius=4)
                    c.text(i*120+10,224,label.replace('_',' ').upper(),11,color=foreground(color) if isinstance(color,GroupColor) and s.get('color_scheme')=='daylight' else BG,width=102)
                    size=17
                    while size>12 and c.draw.textlength(str(value),font=font(size,True))>104:size-=1
                    c.text(i*120+10,242,value,size,True,color=foreground(color) if isinstance(color,GroupColor) and s.get('color_scheme')=='daylight' else BG,width=104)
                    if f'KNOB {side*4+i+1} TOUCH' in s.get('touches',()):c.rect(i*120+7,219,105,2,ACCENT)
        if s['page']=='CLIP ARRANGER':self.clip_arranger(p,q,s['clip_arranger'])
        elif s['page']=='CLIP MENU':
            from app.clip_arranger import MENU
            self.list(p,MENU,s['clip_arranger']['menu']);q.text(20,105,MENU[s['clip_arranger']['menu']],24,True,width=440)
        elif s['page']=='COLOR SCHEME':
            from app.mk3_theme import SCHEMES,LABELS,PALETTES
            scheme=s.get('color_scheme','current');index=SCHEMES.index(scheme) if scheme in SCHEMES else 0
            self.list(p,[LABELS[v] for v in SCHEMES],index,y=86,first=0)
            q.rect(18,92,444,48,ACCENT,radius=3)
            q.text(31,101,LABELS[SCHEMES[index]],25,True,BG,width=414)
            q.text(20,152,'THIS CONTROLLER ONLY',12,color=MUTED,width=440)
            for i,(label,color) in enumerate((('ACCENT',ACCENT),('SIGNAL',CYAN),('FILTER',YELLOW),('LEVEL',GREEN))):
                q.rect(20+i*113,180,100,12,color,radius=2)
                q.text(20+i*113,196,label,10,color=MUTED,width=102)
        elif s['page']=='SLICE TARGET':
            target=s['target_group'];bank=s['target_bank']
            for i in range(min(8,s['groups']-bank*8)):
                x=12+(i%4)*116;y=94+(i//4)*50;chosen=bank*8+i==target
                p.rect(x,y,108,42,ACCENT if chosen else PANEL,radius=4);p.text(x+54,y+10,chr(65+i),18,True,BG if chosen else GROUPS[i],center=True)
            self.tiles(q,tuple((str(i+1),True,i==s['target_sound']) for i in range(16)))
            p.text(15,199,f'{s["target_count"]} SLICES / GROUP '+chr(65+target%8),11,color=MUTED,width=450)
        elif 'group_cards' in s:
            cards=s['group_cards'];self.tiles(q,tuple((name,present,selected) for name,present,selected in cards))
            p.text(20,105,'GROUPS',24,True,width=440)
        elif 'arrangement' in s:
            song,selected,play=s['arrangement'];first=max(0,selected-3)
            for i,scene in enumerate(song[first:first+8]):
                c=p if i<4 else q;x=12+(i%4)*116;chosen=first+i==selected
                c.rect(x,112,108,60,ACCENT if chosen else PANEL,radius=4);c.text(x+54,128,'S'+str(scene+1).zfill(2),21,True,BG if chosen else INK,width=102,center=True)
                if first+i==play:c.rect(x,181,108,3,YELLOW)
            if not song:p.text(20,110,'EMPTY ARRANGEMENT',22,True,width=440)
        elif 'wave' in s and s['page']!='SLICE TARGET':
            self.wave(p,s['wave'],s)
            if s['page']=='SAMPLING':
                self.capture_meter(q,s.get('capture_peaks',(0,0)),s.get('capture_threshold'))
                q.text(18,198,s.get('capture_status') or 'Ready to record',16,True,width=440)
            elif s['page']=='CHOP':
                markers=s.get('markers',());base=s.get('slice_bank',0)*16
                self.tiles(q,tuple((str(base+i+1),base+i<len(markers),base+i==s.get('slice_index',0)) for i in range(16)))
            else:
                q.text(20,100,s.get('process','') if s['page']=='SAMPLE EDIT' else s.get('headings',('',''))[0],24,True,width=440)
                q.text(20,145,Path(s['wave'][0]).name if s['wave'][0] else 'No sample',15,color=MUTED,width=440)
                q.text(20,178,'Target '+s.get('sample_target',''),14,color=accent)
        elif 'browser' in s:
            from app.browser import browser_from_snapshot
            b,index,_=browser_from_snapshot(s['browser'])
            entries=b.entries()
            self.list(p,[('' if b.is_folder(v) else '♪ ')+b.label(v) for v in entries],index)
            selected=entries[index] if 0<=index<len(entries) else None
            if self.kit_cover(q,b,selected):
                self.browser_wave=None
            elif selected and selected.is_file():
                ref=s.get('browser_decoded',{}).get(str(selected),str(selected));self.browser_wave=(ref,0,None);self.wave(q,self.browser_wave,s)
            else:self.browser_wave=None;q.text(20,110,b.label(selected) if selected else 'Empty folder',20,True,width=440)
        elif 'plugin_browser' in s:
            entries,index,kind=s['plugin_browser'];self.list(q,entries,index);p.text(20,100,kind,24,True,width=440);p.text(20,147,'Select a plug-in · press to load',16,color=MUTED,width=440)
        elif 'events_native' in s:
            self.events(q,p,s['events_native'])
        elif 'grid' in s:
            self.grid(p,s['grid'])
            q.text(20,87,'EVENT EDITOR',14,color=MUTED)
            q.text(20,116,s['grid']['footer'],20,True,width=440)
            q.text(20,160,'FOLLOW '+('ON' if s['grid']['follow'] else 'OFF'),16,True,color=accent)
            q.text(20,188,'Select / insert / erase with the softkeys',13,color=MUTED,width=440)
        elif 'mixer' in s:self.mixer(p,q,s)
        elif 'keyboard_root' in s and not s.get('keyboard_slices'):
            p.text(20,105,s.get('chord_name','KEYBOARD') if s.get('keyboard_custom') else 'KEYBOARD',22,True,width=440)
            p.text(20,150,'Play the selected Sound',15,color=MUTED,width=440)
            active=set(s.get('keyboard_notes',()))|set(s.get('keyboard_active',()))
            # Match MK2: follow the last played pad/chord, not the mapping root.
            # keyboard_notes retains that focus after physical release.
            focus=set(s.get('keyboard_notes',())) or set(s.get('keyboard_active',()))
            root=s['keyboard_root'];first=max(0,min(96,((min(focus) if focus else root)//12)*12))
            last=min(128,max(first+24,((max(focus) if focus else first)//12+1)*12))
            whites=[n for n in range(first,last) if n%12 not in (1,3,6,8,10)]
            width=450/max(1,len(whites))
            for i,n in enumerate(whites):q.rect(15+i*width,93,width-1,99,accent if n in active else INK,radius=2)
            for n in range(first,last):
                if n%12 in (1,3,6,8,10):
                    preceding=sum(1 for v in whites if v<n);q.rect(15+preceding*width-width*.32,93,width*.64,61,accent if n in active else BG,LINE,2)
            from app.ni_display import note_name
            for i,n in enumerate(whites):
                if n%12==0:q.text(15+(i+.5)*width,174,note_name(n),11,True,BG,width=max(8,width-2),center=True)
            caption=s.get('chord_name','KEYBOARD') if s.get('keyboard_custom') else f'{note_name(first)} – {note_name(last-1)}'
            q.text(15,194,caption,12,color=MUTED,width=450)
        elif 'tiles' in s:
            self.tiles(q,s['tiles'],empty_selection_outline=s['page']=='PATTERN');p.text(20,105,s['page'],24,True,width=440)
            for i,status in enumerate(s.get('pad_status',())):
                if status[0]:q.text(12+i%4*116+90,93+(3-i//4)*30,'M' if s['page']=='MUTE' else 'S' if s['page']=='SOLO' else '+',11,True,RED if s['page']=='MUTE' else YELLOW,width=16)
            p.text(20,150,s.get('focus_detail',''),16,color=MUTED,width=440)
        elif 'steps' in s:
            for i,on in enumerate(s['steps']):
                x=12+i*28;q.rect(x,124,23,48,self.accent if on else PANEL,LINE,3);q.text(x+11,180,str(s.get('bank',0)*16+i+1),10,color=INK,width=26,center=True)
                if s.get('play_cell',-1)==s.get('bank',0)*16+i:q.rect(x,111,23,5,YELLOW)
            p.text(20,105,'STEP SEQUENCER',23,True,width=440)
            p.text(20,150,'Steps '+str(s.get('bank',0)*16+1)+'–'+str(min(s.get('cell_count',16),s.get('bank',0)*16+16)),17,color=MUTED,width=440)
        elif 'settings_menu' in s:
            title,entries,index=s['settings_menu'];self.list(p,entries,index);q.text(20,100,title,24,True,width=440);q.text(20,150,'4D encoder: select / press: open',16,color=MUTED,width=440)
        elif 'view_origin' in s:self.navigate(p,q,s)
        elif 'plugin_chain' in s:
            chain=s['plugin_chain'];selected=s.get('plugin_chain_selected',0)
            self.list(p,[str(i+1)+'. '+name+(' / BYPASS' if bypass else '') for i,(name,bypass) in enumerate(chain)],selected)
            if 'plugin_names' in s:
                bank,patch=s['plugin_names'];q.text(20,96,'BANK',12,color=CYAN);q.text(20,115,bank,21,True,width=440)
                q.text(20,151,'PATCH',12,color=PURPLE);q.text(20,170,patch,21,True,width=440)
            elif 'plugin_values' in s:self.plugin_values(q,s)
            else:
                for i,(label,value) in enumerate(s.get('plugin_bars',())[:3]):
                    y=94+i*38;color=parameter_color(label,s.get('group',0));q.text(15,y,label,12,color=color,width=450)
                    q.rect(15,y+21,446,9,PANEL);q.rect(15,y+21,round(446*max(0,min(1,value))),9,color)
            if s.get('synth_graph') and 'levels' not in s['synth_graph']:
                self.synth_plot(q if s.get('chain_cards') else p,s['synth_graph'])
        elif 'live_fx' in s:
            mode,depth,current,names=s['live_fx'];items=tuple((n,True,i==s.get('live_fx_pad')) for i,n in enumerate(names))
            self.tiles(q,items)
            p.text(20,101,('PUNCH','FLEX','KNOB')[mode],22,True,width=440)
            p.text(20,139,names[current-1] if current else 'DRY / OFF',18,True,width=440)
            p.rect(20,183,440,12,PANEL);p.rect(20,183,round(440*depth/100),12,ACCENT)
        elif 'system' in s:
            stats=s['system']
            rows=[('CPU / ALL CORES',stats.get('cpu')),('RAM',(stats.get('ram') or {}).get('percent'))]
            for i,(caption,value) in enumerate(rows):
                y=84+i*60;p.text(15,y,caption,14,color=MUTED);p.text(365,y,'—' if value is None else f'{value:.0f}%',18,True)
                p.rect(15,y+28,446,17,PANEL);p.rect(15,y+28,round(446*max(0,min(100,value or 0))/100),17,ACCENT)
            for i,core in enumerate(stats.get('cpu_cores',[])[:8]):
                y=94+i*16;q.text(12,y,'CPU '+str(core['id']+1),11,color=MUTED)
                v=core.get('percent') or 0;q.rect(80,y+3,310,9,PANEL);q.rect(80,y+3,round(310*v/100),9,ACCENT);q.text(407,y,f'{v:.0f}%',11)
        elif 'synth_graph' in s:
            self.synth_plot(p,s['synth_graph'])
            for i,f in enumerate(s.get('fields',())[4:]):
                if f:q.text(15,84+i*30,f[0]+'   '+str(f[1]),17,i==0,width=450)
        elif 'sampler_values' in s:
            v=s['sampler_values'];voices=v.get('polyphony',8);voices=1 if voices=='LEGATO' else voices
            if s.get('sound_wave',(None,))[0]:self.wave(p,s['sound_wave'],s)
            elif s.get('sampler_section',0)==0:
                p.text(20,88,str(voices)+' voices',22,True)
                for i in range(32):p.rect(20+(i%16)*27,126+(i//16)*28,19,17,accent if i<voices else PANEL,radius=3)
            else:
                p.text(20,104,s.get('headings',('SAMPLER',''))[0],22,True,width=440)
            # Use native right-screen coordinates to fill the space recovered
            # by the compact header; footer geometry stays fixed.
            from app.fokus_graphics import response
            plot=Canvas();plot.image=q.image;plot.draw=q.draw
            section=s.get('sampler_section',0)
            if section==0:
                plot.text(240,72,str(voices)+' VOICES',24,True,color=accent,width=448,center=True)
                for i in range(32):
                    plot.rect(20+(i%16)*27,120+(i//16)*37,23,28,accent if i<voices else PANEL,radius=3)
            else:
                plot.rect(12,68,456,140,PANEL,radius=4)
                for yy in (74,136,199):plot.line((16,yy,463,yy),LINE)
                class Plot:
                    w=480;ink=PURPLE;bg=PANEL
                    def line(self,x1,y1,x2,y2):plot.line((x1,y1,x2,y2),YELLOW if section==2 else CYAN if section==4 else PURPLE,3)
                    def rect(self,x,y,w,h,color=accent,fill=True):plot.rect(x,y,w,h,color if fill else None,None if fill else color)
                    def text(self,x,y,value,width,**kwargs):plot.text(x,y,value,22,True,width=width)
                response(Plot(),section,v,x=16,y=74,w=448,h=126)
        elif 'signal_route' in s:
            source,dest=s['signal_route'];p,q=q,p
            if s['page'] in ('PAD','CHANNEL') and s.get('scope')==2:
                self.pad_grid(p,s,61,111)
                arrow_start,arrow_end,target_x,center_y=180,223,240,161
            else:
                p.rect(15,132,190,58,PANEL,LINE,5);p.text(110,150,source,17,True,width=180,center=True)
                arrow_start,arrow_end,target_x,center_y=212,257,270,161
            p.line((arrow_start,center_y,arrow_end,center_y),accent,3)
            p.line((arrow_end-11,center_y-9,arrow_end,center_y,arrow_end-11,center_y+9),accent,3)
            p.rect(target_x,center_y-29,195,58,PANEL,LINE,5)
            p.text(target_x+97,center_y-11,dest,17,True,width=183,center=True)
            p,q=q,p
            if s.get('sound_wave',(None,))[0]:self.wave(p,s['sound_wave'],s)
            elif s['page'] in ('PAD','CHANNEL'):
                from app.instrument_art import image
                artwork=image(s.get('output_art'))
                if artwork is not None:p.image.paste(artwork,(16,90),artwork)
                elif s.get('scope')!=2:p.text(20,108,source,22,True,width=440)
            else:p.text(20,108,source,22,True,width=440)
        elif 'sound_wave' in s and s['sound_wave'][0]:self.wave(p,s['sound_wave'],s)
        elif 'stem_separation' in s:
            u=s['stem_separation'];p.text(18,88,'STEM SEPARATION',23,True,width=440)
            p.text(18,126,u.get('name',''),19,True,width=440)
            for i,label in enumerate(('VOCALS','DRUMS','BASS','OTHER')):
                x=18+i*112;p.rect(x,174,106,43,PANEL,LINE,4);p.text(x+53,187,label,13,True,center=True,width=100)
            q.text(18,91,u.get('state','IDLE'),22,True,width=442)
            q.text(18,126,u.get('message',''),13,color=MUTED,width=442)
            q.rect(18,161,444,12,PANEL,LINE,3);q.rect(20,163,max(1,round(440*max(0,min(100,u.get('progress',0)))/100)),8,ACCENT,radius=2)
            q.text(18,185,str(u.get('progress',0))+'% / WHOLE SAMPLE / MAX 60 SEC',14,True,width=442)
        elif 'updater' in s:
            u=s['updater'];p.text(18,91,'INSTALLED',13,color=MUTED);p.text(18,110,u.get('current','--'),27,True,width=442)
            p.text(18,151,'LATEST / '+u.get('channel','release').upper(),13,color=MUTED);p.text(18,170,u.get('latest') or '--',25,True,width=442)
            q.text(18,91,u.get('state','OFFLINE'),22,True,width=442)
            q.text(18,126,u.get('error') or u.get('message',''),13,color=MUTED,width=442)
            q.rect(18,161,444,12,PANEL,LINE,3);q.rect(20,163,max(1,round(440*u.get('progress',0)/100)),8,ACCENT,radius=2)
            q.text(18,183,'Machinista + Raspberry Pi OS',14,True,width=442)
        elif 'project_list' in s:
            entries,index=s['project_list']
            manage=s['page']=='PROJECT MANAGE'
            if entries:
                # Keep each page stationary while the colored cursor visits all
                # six rows. Never feed the monochrome, pre-scrolled arrow list.
                self.list(p,entries,index,first=index//6*6)
                q.text(20,96,'SELECTED ACTION' if manage else 'SELECTED PROJECT',12,True,color=MUTED,width=440)
                size=23
                while size>14 and q.draw.textlength(entries[index],font=font(size,True))>440:size-=1
                q.text(20,121,entries[index],size,True,width=440)
                q.text(20,166,f'{index+1} / {len(entries)}',15,color=ACCENT,width=440)
                q.text(20,194,'Press encoder to open' if manage else 'Press encoder to load',13,color=MUTED,width=440)
            else:
                p.text(20,100,'No saved projects',19,color=MUTED,width=440)
                q.text(20,100,'Create or import a project',17,color=MUTED,width=440)
        elif 'utility' in s:
            header,body,footer=s['utility'];self.list(p,body,0);q.text(20,96,header,23,True,width=440);q.text(20,150,footer,15,color=MUTED,width=440)
        else:
            for c,side in ((p,0),(q,1)):
                for i,f in enumerate(s.get('fields',())[side*4:side*4+4]):
                    if not f:continue
                    x=18+(i%2)*234;y=86+(i//2)*61
                    c.text(x,y,f[0],13,color=MUTED,width=215);c.text(x,y+20,f[1],23,True,width=215)
        if s.get('chain_cards',{}).get('items'):self.chain_card(p,s)
        if s.get('message'):
            q.rect(8,179,464,33,PANEL,LINE,3);q.text(18,184,s['message'],15,True,width=444)
        self.needs_refresh=self.waveforms.future is not None
        return p.image,q.image
    def chain_card(self,c,state):
        from app.instrument_art import image
        from PIL import Image
        chain=state['chain_cards'];items=chain['items'];selected=chain['selected'];item=items[selected]
        c.rect(8,86,464,129,BG)
        first=max(0,min(selected-1,len(items)-3))
        width=456/min(3,len(items))
        for i,slot in enumerate(items[first:first+3]):
            x=12+round(i*width);active=first+i==selected
            c.rect(x,87,round(width)-4,23,self.accent if active else PANEL,radius=3)
            c.text(x+6,90,str(first+i+1)+'. '+slot['name'],13,active,BG if active else MUTED,width=round(width)-16)
        if item['art']:
            asset=image(item['art'])
            if asset is not None:
                asset=asset.resize((360,96),Image.Resampling.LANCZOS);c.image.paste(asset,(60,111),asset)
        elif state.get('sound_wave',(None,))[0]:
            wave=Canvas();self.wave(wave,state['sound_wave'],state)
            c.image.paste(wave.image.crop((8,82,472,202)).resize((408,87)),(36,112))
        else:c.text(240,145,item['name'],23,True,center=True,width=390)
        # Real arrowheads, with no next-slot indication on a single-item chain.
        if selected:c.polygon(((24,145),(13,154),(24,163)),self.accent)
        if selected+1<len(items):c.polygon(((456,145),(467,154),(456,163)),self.accent)
        c.text(240,201,f'{selected+1} / {len(items)}'+('  BYPASS' if item['bypass'] else ''),11,True,color=MUTED,width=240,center=True)

    def chain_animation(self,images,state):
        chain=state.get('chain_cards');now=time.monotonic()
        if not chain or not chain['items']:
            self.chain_key=None;self.chain_transition=None;self.chain_previous=None;return images
        key=(chain['context'],chain['selected'],tuple((v['name'],v['art']) for v in chain['items']))
        region=(36,111,444,199);target=images[0].crop(region)
        if key!=self.chain_key:
            if self.chain_key and key[0]==self.chain_key[0] and key[2]==self.chain_key[2] and self.chain_previous is not None:
                direction=chain.get('motion',(0,'MASTER RIGHT'))[1]
                self.chain_transition=(now,self.chain_previous,direction)
            else:self.chain_transition=None
            self.chain_key=key
        if self.chain_transition:
            start,old,direction=self.chain_transition;progress=min(1,(now-start)/.18)
            if progress<1:
                from PIL import Image
                frame=Image.new('RGB',target.size,resolve(BG));vertical=direction in ('MASTER UP','MASTER DOWN')
                extent=target.height if vertical else target.width;shift=round(extent*progress)
                sign=-1 if direction in ('MASTER RIGHT','MASTER DOWN') else 1
                frame.paste(old,(0,sign*shift) if vertical else (sign*shift,0))
                frame.paste(target,(0,sign*(shift-extent)) if vertical else (sign*(shift-extent),0))
                left=images[0].copy();left.paste(frame,region[:2]);images=(left,images[1]);self.needs_refresh=True
            else:self.chain_transition=None
        self.chain_previous=images[0].crop(region)
        return images

    def playback_overlay(self,images,state):
        from PIL import ImageDraw
        canvases=[]
        for side,image in enumerate(images):
            c=Canvas(compact_header=side==1 and 'mixer' not in state);c.image=image.copy();c.draw=ImageDraw.Draw(c.image)
            if side==0:c.text(438,34,state.get('position',''),13,True,width=73,center=True)
            canvases.append(c)
        p,q=canvases
        g=state.get('events_native')
        if g and g['playhead'] is not None:
            start,end=g['start'],g['end'];span=max(1,end-start);phase=g['playhead']
            # Match MK2: piano roll right, selected-event detail/velocity left.
            x=48+(phase-start)*416/span;q.line((x,104,x,202),YELLOW,2)
            q.polygon(((x-4,102),(x+4,102),(x,107)),YELLOW)
            x=18+(phase-start)*444/span;p.line((x,176,x,203),YELLOW,2)
        elif state.get('grid',{}).get('playhead') is not None:
            x=52+max(0,min(1,(state['grid']['playhead']-29)/96))*420;p.line((x,82,x,202),YELLOW,2)
        ref=state.get('wave') if state.get('page')!='SLICE TARGET' else None
        if not ref and state.get('page') in ('SAMPLER','PAD','CHANNEL'):ref=state.get('sound_wave')
        if not ref and state.get('browser'):
            # Browser selected-file waveform lives on the right.
            ref=getattr(self,'browser_wave',None);target=q
        else:target=p
        cursor=state.get('wave_cursor')
        if ref and ref[0] and cursor is not None:
            path,first,last=ref
            envelope=self.waveforms.envelope(path,first,last if last and last>first else None,columns=460)
            if envelope and envelope.peaks and envelope.start<=cursor<=envelope.end:
                ratio=(cursor-envelope.start)/max(1,envelope.end-envelope.start)
                if state.get('chain_cards'):
                    x=36+round(ratio*406);target.line((x,113,x,198),YELLOW,2)
                else:
                    x=10+round(ratio*458);target.line((x,84,x,200),YELLOW,2)
        if state.get('message'):
            q.rect(8,179,464,33,PANEL,LINE,3);q.text(18,184,state['message'],15,True,width=444)
        return p.image,q.image

    @themed
    def images(self,state):
        if state.get('norns_mode'):  # norns-mode fork hook
            from app.norns_display import images as norns_images
            return norns_images(state)
        self.waveforms.collect()
        if not any(state.get(k) for k in ('wave','browser','sound_wave')):
            self.waveforms.prefetch(state.get('wave_preload'))
        base=dict(state);base['position']='';base['wave_cursor']=None
        if 'grid' in base:base['grid']=dict(base['grid'],playhead=None)
        if 'events_native' in base:base['events_native']=dict(base['events_native'],playhead=None)
        if base.get('focus_detail','').startswith(('PLAY ','REC ')):base['focus_detail']=base['focus_detail'].split(' ')[0]
        if self.cached_images is None or self.cached_state!=base or self.cached_wave_revision!=self.waveforms.revision or self.waveforms.future is not None:
            self.cached_images=self.draw(base);self.cached_state=base;self.cached_wave_revision=self.waveforms.revision;self.scene_renders+=1
        from app.text_marquee import color_names
        images=color_names(self.marquee,state,self.playback_overlay(self.cached_images,state))
        self.needs_refresh=self.waveforms.future is not None or self.cached_wave_revision!=self.waveforms.revision or self.marquee.active
        return self.chain_animation(images,state)

    def __call__(self,state):
        from app.mk3_graphics import rgb565
        return tuple(rgb565(image,state.get('display_invert',False)) for image in self.images(state))

    def wire_frames(self,state):
        from app.mk3_frame_encoder import FrameEncoder,DisplayFrame
        from app.mk3_graphics import rgb565
        from app.mk3_protocol import display_packet
        if not self.encoder_tried:
            self.encoder_tried=True
            try:self.encoder=FrameEncoder()
            except OSError:self.encoder=None
        frames=[];invert=state.get('display_invert',False)
        for display,image in enumerate(self.images(state)):
            rgb=image.tobytes();identity=(rgb,invert)
            if self.wire_images.get(display)==identity:frames.append(None);continue
            frame=None
            if self.encoder:
                try:frame=self.encoder.encode(rgb,display,invert)
                except (OSError,ValueError):self.encoder.close();self.encoder=None
            if frame is None:frame=DisplayFrame(display_packet(rgb565(image,invert),display))
            frames.append(frame);self.wire_images[display]=identity
        return tuple(frames)
