"""Fokus layout for both MK2 LCDs, using actual Mk2Surface bindings.

Eight bottom parameter cells always correspond to encoders 1–8. Rendering
stays inside the existing detached MK2 output worker and waveform cache.
"""
import math
from pathlib import Path
from app.fokus import sample_wave
from app.fokus_mk2_style import Canvas,parameters,GRID_TOP,bold_font
from app.navigation import CONTROL_PAGES
from app.fokus_graphics import response,route,chain,bars,folder


def plugin_values(c,values):
    """Eight visual encoder levels; numeric values remain in the footer."""
    for number,label,_,fraction in values[:8]:
        column,row=divmod(number-1,4);x=4+column*126;y=23+row*6
        c.text(x,y,str(number),7)
        c.fitted(x+9,y,label,56)
        c.rect(x+69,y,53,5,c.ink,False)
        c.rect(x+70,y+1,round(51*max(0,min(1,fraction))),3)



def capture_meter(c,peaks,threshold=None):
    # Peak amplitude and the detection threshold share a -60..0 dBFS axis.
    def fraction(db):return max(0,min(1,(db+60)/60))
    for i,peak in enumerate(peaks[:2]):
        y=28+i*18;c.text(4,y+2,'LR'[i],10,font='bold7');c.rect(18,y,229,12,c.ink,False)
        level=fraction(20*math.log10(max(.001,peak)))
        c.rect(20,y+2,round(level*225),8)
        if threshold is not None:
            x=20+round(fraction(threshold)*224)
            c.rect(x-1,y-2,3,1)
            # Invert across the bar so the marker survives a filled meter.
            for yy in range(y-1,y+13):c.p[yy*c.w+x]^=1


def tiles(c,items,status=None,mode=''):
    for i,(label,present,selected) in enumerate(items):
        x=4+(i%4)*62;y=24+(3-i//4)*8
        if status is not None:
            selected,focused,audible,held=status[i]
            label=str(label)+(' +' if selected and mode=='SELECT' else ' M' if selected and mode=='MUTE' else ' S' if selected else '')
        if selected:c.rect(x,y,59,7)
        else:
            c.rect(x,y,59,7,c.ink,False)
            if not present:c.rect(x+52,y+3,3,1)
        c.text(x+2,y+1,label,55,ink=c.bg if selected else c.ink)
        if status is not None:
            if focused:c.rect(x-2,y,1,7)
            if held:c.rect(x+48,y+2,3,3,c.bg if selected else c.ink)
            if present and not audible and mode!='SELECT':c.rect(x+39,y+3,6,1,c.bg if selected else c.ink)


def keyboard(c,notes,active,root):
    notes=set(notes);active=set(active);first=max(0,min(96,((min(notes) if notes else root)//12)*12))
    last=min(128,max(first+24,((max(notes) if notes else first)//12+1)*12))
    whites=[n for n in range(first,last) if n%12 not in (1,3,6,8,10)]
    width=min(17,248//max(1,len(whites)));x0=(256-width*len(whites))//2
    c.rect(2,24,252,22,c.bg)
    for i,note in enumerate(whites):
        x=x0+i*width;c.rect(x,26,width-1,19)
        if note in notes:c.rect(x+max(1,width//5),38,max(1,width-width//5*2-1),5,c.bg)
        if note in active:c.rect(x+max(1,width//3),30,max(1,width-width//3*2-1),5,c.bg)
    for i,note in enumerate(whites):
        if note%12 in (0,2,5,7,9):
            bw=max(2,width//2);x=x0+(i+1)*width-bw//2;c.rect(x,26,bw,12,c.bg)
            if note+1 in notes:c.rect(x+1,31,max(1,bw-2),5)
            if note+1 in active:c.rect(x+1,27,max(1,bw-2),3)


def gauge(c,x,y,width,label,value,detail=''):
    c.text(x,y,label,width-35,font='bold5')
    c.text(x+width-32,y,'--%' if value is None else f'{value:.0f}%',32)
    c.rect(x,y+7,width,5,c.ink,False)
    if value is not None:c.rect(x+1,y+8,round((width-2)*max(0,min(100,value))/100),3)
    if detail:c.text(x,y+14,detail,width)



def settings_rows(c,rows,y=26):
    for i,row in enumerate(rows[:3]):
        selected=str(row).startswith('>');value=str(row).lstrip('> ');yy=y+i*11
        if selected:c.rect(3,yy-1,250,10)
        c.fitted(5,yy,value,246,font='bold7' if selected or i==0 and not any(str(v).startswith('>') for v in rows) else 'regular7',ink=c.bg if selected else c.ink)


def system_dashboard(p,q,state):
    stats=state['system']
    # Settings softkeys stay on the left. The unused right header becomes a
    # compact storage title; gauges get the full remaining screen height.
    for c in (p,q):c.rect(2,14,252,47,c.bg)
    q.rect(2,1,252,11,q.bg)
    q.fitted(4,3,'MACHINISTA / SYSTEM' if state['page_index']==0 else 'MACHINISTA / STORAGE',206,font='regular7')
    if state['page_total']>1:q.text(220,4,f"{state['page_index']+1}/{state['page_total']}",32)
    def meter(c,y,label,value,bar_y,bar_height,detail=''):
        c.fitted(5,y,label,184,font='regular7')
        c.fitted(199,y,'--%' if value is None else f'{value:.0f}%',50,font='bold7')
        c.rect(5,bar_y,244,bar_height,c.ink,False)
        if value is not None:c.rect(7,bar_y+2,round(240*max(0,min(100,value))/100),bar_height-4)
        if detail:c.fitted(5,bar_y+8,detail,244,font='regular5')
    if state['page_index']==0:
        from app.branding import paint_logo,VERSION
        paint_logo(p.p,256,10,17,236)
        p.text(4,54,VERSION,248,center=128)
        meter(q,17,'CPU / ALL CORES',stats['cpu'],28,8)
        meter(q,41,'RAM',(stats['ram'] or {}).get('percent'),52,8)
        return
    from app.system_info import core_page_count
    core_pages=core_page_count(stats,'mk2');index=state['page_index']-1
    if index<core_pages:
        q.rect(2,1,252,11,q.bg);q.text(4,3,'MACHINISTA / CPU CORES',212,font='regular7')
        q.text(220,4,f"{state['page_index']+1}/{state['page_total']}",32)
        rows=stats.get('cpu_cores',[])[index*8:index*8+8]
        for i,core in enumerate(rows):
            c=p if i<4 else q;y=16+(i%4)*11;value=core['percent']
            c.text(4,y,'CORE '+str(core['id']+1),62,font='bold7')
            c.rect(69,y+1,132,7,c.ink,False)
            if value is not None:c.rect(71,y+3,round(128*max(0,min(100,value))/100),3)
            c.text(206,y,'--%' if value is None else f'{value:.0f}%',46,font='bold7')
        if len(rows)<=4:
            q.rect(2,14,252,47,q.bg)
            meter(q,17,'CPU / ALL CORES',stats['cpu'],28,8)
            meter(q,41,'RAM',(stats['ram'] or {}).get('percent'),52,8)
        return
    meter(p,17,'CPU / ALL CORES',stats['cpu'],28,8)
    meter(p,41,'RAM',(stats['ram'] or {}).get('percent'),52,8)
    start=(state['page_index']-1-core_pages)*2
    disks=stats['storage'][start:start+2]
    for i,disk in enumerate(disks):
        meter(q,14+i*24,disk['name'],disk['percent'],23+i*24,6,f'{disk["used"]/1e9:.1f} / {disk["total"]/1e9:.1f} GB')
    if not disks:q.fitted(5,28,'NO STORAGE',244,font='bold7')


def hardware(p,q,values,device='mk2'):
    device=device.upper()
    p.title('DISPLAY / '+device);q.title('PADS / '+device)
    for i,(key,label) in enumerate((('brightness','LIGHT'),('contrast_left','LEFT'),('contrast_right','RIGHT'))):
        gauge(p,5+i*83,26,77,label,values[key])
    curve=values['pad_curve'];sensitivity=values['pad_sensitivity']
    q.text(5,27,curve,90,font='bold5');q.text(5,38,f'SENS {sensitivity}%',90)
    q.line(101,43,249,43);q.line(101,25,101,43)
    previous=None
    for i in range(148):
        level=min(1,i/147*sensitivity/100)
        level=level**.6 if curve=='SOFT' else level**1.6 if curve=='HARD' else 1 if curve=='FIXED' else level
        point=(102+i,43-round(level*18))
        if previous:q.line(*previous,*point)
        previous=point


def waveform(c,state,renderer):
    # The existing indexed/cache renderer owns all file reads and async work.
    # Reuse its genuine waveform pixels, not example data from the studies.
    _,source=renderer.legacy_frame(state)
    for yy in range(20):
        sy=27+yy*34//20
        c.p[(26+yy)*256+3:(26+yy)*256+253]=source[sy*256+3:sy*256+253]


def navigate_icon(c,x,y,kind,ink):
    """Native-pixel workspace symbols aligned with the eight display buttons."""
    def box(dx,dy,w,h,fill=False):c.rect(x+dx,y+dy,w,h,ink,fill)
    def line(a,b,d,e):c.line(x+a,y+b,x+d,y+e,ink)
    if kind==0:  # Pin
        box(5,0,10,3,True);line(7,3,6,9);line(13,3,14,9)
        line(4,10,16,10);line(10,11,10,18)
    elif kind==1:  # Scene clips
        for row in range(2):
            for col in range(3):box(col*7,row*9,5,7,row==0)
    elif kind==2:  # Song arrangement
        for row,(left,width) in enumerate(((0,12),(6,14),(2,16))):box(left,row*6,width,4,True)
    elif kind==3:  # Mixer faders
        for col,height in enumerate((4,11,7)):
            line(3+col*7,0,3+col*7,18);box(col*7,height,7,4,True)
    elif kind==4:  # Folder
        box(0,3,20,15);box(1,0,8,4);line(1,7,18,7)
    elif kind==5:  # Piano roll
        for row in range(4):line(0,row*5,20,row*5)
        for a,b,w in ((1,1,6),(9,6,9),(5,11,8)):box(a,b,w,3,True)
    elif kind==6:  # Performance pads
        for row in range(3):
            for col in range(3):box(col*7,row*6,5,4,row==col)
    else:  # Return arrow
        line(2,7,18,7);line(18,7,18,17);line(18,17,10,17)
        line(2,7,8,1);line(2,7,8,13)


def render(state,renderer):
    p,q=Canvas(256),Canvas(256);page=state['page']
    p.header(state['keys'][:4],state['active_left']);q.header(state['keys'][4:],state['active_right'])
    detail=state.get('focus_detail',state['position'])
    p.title(state['title'],detail)
    counter=f'{state["page_index"]+1}/{state["page_total"]}' if state['page_total']>1 else ''
    q.title(state.get('choice') or state['headings'][1] or page,counter)
    if page in CONTROL_PAGES and state.get('group_muted') and state['scope']:
        p.title('GROUP '+chr(65+state['group']%8)+' MUTED',detail)
    if page=='VIEW NAV':
        origin=state.get('view_origin','PAD')
        p.title('NAVIGATE','SELECT VIEW')
        q.title('DESTINATION',origin)
        for canvas,offset,active in ((p,0,state['active_left']),(q,4,state['active_right'])):
            for col in range(4):
                icon=offset+col;x=col*63+3
                canvas.rect(x,25,61,36,fill=False)
                if col in active:canvas.rect(x+1,26,59,34)
                ink=canvas.bg if col in active else canvas.ink
                navigate_icon(canvas,x+21,28,icon,ink)
                canvas.text(x+2,51,('PIN','IDEAS','SONG','MIXER','BROWSE','EVENTS','LIVE FX','BACK')[icon],57,ink=ink,center=x+30)
    if page=='OPTIONS':
        t=state['grid_options'];tab=t['tab'];p.title(('QUANTIZE','SWING','GRID')[tab],t['grid'])
        q.title(('NOTE POSITION','PLAYBACK TIMING','EDIT GRID')[tab])
        for n in range(9):
            x=8+n*29;p.line(x,27,x,42)
        p.line(8,41,240,41)
        for n in range(8):
            offset=round(14*t['swing']/100) if tab==1 and n%2 else 0
            x=8+n*29+offset;p.rect(x-2,32,5,5)
        if tab==0:
            q.fitted(5,27,'TARGET: '+t['target'],242,font='bold7')
            q.fitted(5,38,'APPLY ALIGNS EXISTING NOTES',242)
        elif tab==1:
            q.fitted(5,27,'SWING '+str(t['swing'])+'%',242,font='bold7')
            q.fitted(5,38,'SHIFTS OFFBEATS DURING PLAYBACK',242)
        else:
            q.fitted(5,27,'GRID '+('ON' if t['grid_on'] else 'OFF'),242,font='bold7')
            q.fitted(5,38,'NUDGE: '+t['nudge'],242)
    if page=='LIVE FX':
        mode,depth,current,effects=state['live_fx']
        p.title('LIVE FX / '+('PUNCH','FLEX','KNOB')[mode],'REC' if state.get('recording') else state['position'])
        p.fitted(5,27,effects[current-1] if current else 'DRY / OFF',242,font='bold7')
        p.rect(5,39,242,5,p.ink,False);p.rect(6,40,round(240*depth/100),3)
        q.title('PAD EFFECTS')
        labels=('LOW PASS','HIGH PASS','ECHO','ROLL 1/4','ROLL 1/8','STUTTER','REVERSE','TAPE STOP','BITCRUSH','RING MOD','PHASER','FLANGER','CHORUS','PITCH DN','PITCH UP','OFF')
        focused=state.get('live_fx_pad',15 if not current else current-1)
        for i,label in enumerate(labels):
            x=4+(i%4)*63;y=25+(3-i//4)*9;chosen=i==focused
            q.rect(x,y,59,8,q.ink,chosen)
            q.fitted(x+2,y+1,label,55,font='bold5',ink=q.bg if chosen else q.ink)
    if page=='AUTOSAMPLER':
        status,config=state['autosampler'];p.title('AUTOSAMPLER',config['source']);q.title('CAPTURE / '+status.get('state','IDLE'))
        p.fitted(4,27,config['name'] or 'SET SOUND NAME',248,font='bold7')
        p.fitted(4,39,'FOLDER: '+config['folder'],248)
        done,total=status.get('completed',0),status.get('total',0)
        q.text(4,27,f'{done}/{total} ZONES',245,font='bold7')
        if 'note' in status:q.text(4,37,f"NOTE {status['note']} / VEL {status['velocity']}",245)
        q.rect(4,44,248,2,q.ink,False);q.rect(5,44,round(246*done/max(1,total)),2)
    elif page in CONTROL_PAGES:
        if 'mono_channel_art' in state:
            p.rect(2,24,252,22,p.bg)
            if state['mono_channel_art']:
                from app.mono_instrument_icons import paint_channel
                paint_channel(p,state['mono_channel_art'])
            elif state.get('sound_wave',(None,))[0]:sample_wave(p,state['sound_wave'],renderer.waveforms,y=26,height=19,playhead=state.get('wave_cursor'))
        else:
            p.text(4,27,state['headings'][0],246)
            if state.get('sound_wave',(None,))[0]:sample_wave(p,state['sound_wave'],renderer.waveforms,playhead=state.get('wave_cursor'))
        if page=='SAMPLER':
            v=state.get('sampler_values',{});section=state.get('sampler_section',0)
            p.rect(2,24,252,22,p.bg)
            if state.get('sound_wave',(None,))[0]:sample_wave(p,state['sound_wave'],renderer.waveforms,y=26,height=19,playhead=state.get('wave_cursor'))
            else:response(p,section,v,y=25,h=16)
            response(q,section,v,y=26,h=14 if section==0 else 18)
        if state.get('signal_route'):route(q,state['signal_route'],y=33 if 'channel_modules' in state else 28)
        if state.get('latency'):q.text(4,37,state['latency'],246)
        if 'channel_modules' in state:
            modules=state['channel_modules'];cell=252//len(modules)
            q.rect(2,14,252,9,q.bg)
            for i,module in enumerate(modules):
                x=3+i*cell;selected=module==state['channel_module']
                if selected:q.rect(x,14,cell-3,9)
                q.fitted(x+2,15,module,cell-7,font='bold7' if selected else 'regular7',ink=q.bg if selected else q.ink,center=x+(cell-3)//2)
            q.text(4,25,state['headings'][0],200)
            if counter:q.text(220,25,counter,30)
    if 'wave' in state and page!='SLICE TARGET':
        waveform(p,state,renderer)
        path=state['wave'][0];q.title(Path(path).name if path else 'NO SAMPLE',' '.join(x for x in (state.get('sample_target',''),counter) if x))
        if state.get('capture_status'):q.title(state['capture_status'],state.get('sample_target',''))
        if page=='CHOP':
            ranges=state['markers'];base=state.get('slice_bank',0)*16
            tiles(q,tuple((str(base+i+1),base+i<len(ranges),base+i==state['slice_index']) for i in range(16)))
        elif page=='SAMPLING':
            capture_meter(q,state['capture_peaks'],state.get('capture_threshold'))
        elif page=='SAMPLE EDIT':
            q.rect(2,46,252,1)
            q.text(4,48,state['headings'][0],246,font='regular5')
            q.text(4,54,state['process'],246,font='bold7')
        else:
            q.text(4,28,state['headings'][0],246)
    if 'tiles' in state:
        if state.get('keyboard_slices'):
            q.title('SLICE PADS',counter);tiles(q,state['tiles'])
        elif 'keyboard_notes' in state:
            keyboard(q,state['keyboard_notes'],state['keyboard_active'],state['keyboard_root'])
            q.title('CHORD NOTES' if state.get('keyboard_custom') else 'KEYBOARD',counter)
            if state.get('keyboard_custom'):
                p.fitted(4,26,state['chord_name'],246,font='bold7')
                p.fitted(4,37,'LEARNING: PLAY MIDI / RELEASE' if state['chord_learning'] else 'PRESET E4 / NEXT PAGE: MORE',246)
        else:tiles(q,state['tiles'],state.get('pad_status'),page)
        if 'pad_status' in state:
            count=sum(item[0] for item in state['pad_status'])
            p.title(page+' / GROUP '+str(state['group']+1))
            if page in ('MUTE','SOLO'):
                p.text(5,27,f'{count} SOUND '+('MUTES' if page=='MUTE' else 'SOLOS'),242,font='bold7')
                p.text(5,37,'GROUPS / M: MUTED / S: SOLO',242)
                for i,(label,muted,solo,focused,audible) in enumerate(state['group_status']):
                    x=5+i*31;p.rect(x,46,28,13,p.ink,muted or solo)
                    p.text(x+2,50,label+(' M' if muted else ' S' if solo else ' -' if not audible else ''),24,ink=p.bg if muted or solo else p.ink)
                    if focused:p.rect(x,60,28,1)
            else:
                p.text(5,27,f'{count} SELECTED',242,font='bold7')
                p.text(5,39,'FILLED: ACTIVE / SIDE MARK: FOCUS',242)
                p.text(5,51,'+: SELECTED / DOT: HELD',242)
    if page=='SLICE TARGET':
        bank=state['target_bank'];p.title('APPLY TO / GROUP',counter)
        for i in range(min(8,state['groups']-bank*8)):
            x=5+i*31;selected=bank*8+i==state['target_group'];p.rect(x,28,27,15,p.ink,selected)
            p.text(x+3,33,chr(65+i)+(str(bank+1) if bank else ''),21,ink=p.bg if selected else p.ink)
        q.title('GROUP / MAX 16' if state['target_sound'] is None else 'SOUND '+str(state['target_sound']+1),f'{state["target_count"]} SLICES')
        tiles(q,tuple((str(i+1),True,i==state['target_sound']) for i in range(16)))
    if page=='STEP':
        for i,on in enumerate(state['steps']):
            x=5+i*15;q.rect(x,29,12,14,q.ink,on)
            if state['play_cell']==state['bank']*16+i:q.rect(x,25,12,2)
        p.text(4,37,f'STEPS {state["bank"]*16+1}-{min(state["cell_count"],state["bank"]*16+16)}',246)
    if 'grid' in state:
        grid=state['grid'];q.title('PATTERN EDITOR',counter,compact=True);p.text(4,29,grid['footer'],246)
        p.text(4,39,f'STEPS {grid["first"]}-{grid["last"]}'+(' / FOLLOW ON' if grid['follow'] else ' / FOLLOW OFF'),246)
        for row,(caption,focused,cells) in enumerate(grid['rows']):
            y=GRID_TOP+row*5
            if focused:q.rect(2,y,31,5)
            q.text(3,y,caption,29,ink=q.bg if focused else q.ink)
            for col,(valid,present,selected,cursor) in enumerate(cells):
                if not valid:continue
                x=36+col*212//grid['columns'];w=max(2,212//grid['columns']-2)
                if present:q.rect(x+1,y+1,max(1,w-2),3)
                if selected:
                    q.rect(x,y,w,5,q.bg);q.rect(x,y,w,5,q.ink,False)
                if cursor:q.rect(x,y,w,5,q.ink,False)
                if col%4==0:q.rect(x,y,1,5)
        if grid['playhead'] is not None:
            x=max(36,min(247,36+round((grid['playhead']-29)/96*212)))
            for y in range(GRID_TOP,GRID_TOP+25):q.p[y*256+x]^=1
    if 'browser' in state:
        from app.browser import browser_from_snapshot
        b,index,prehear=browser_from_snapshot(state['browser'])
        entries=b.entries();first=max(0,min(index-1,len(entries)-3))
        p.title('LIBRARY / '+b.title(),state.get('sample_target',''))
        for i,path in enumerate(entries[first:first+3]):
            yy=24+i*7;chosen=first+i==index
            if chosen:p.rect(3,yy,250,7)
            ink=p.bg if chosen else p.ink
            if b.is_folder(path):folder(p,5,yy,chosen)
            else:p.rect(6,yy+1,6,5,ink,False)
            p.fitted(20,yy+1,b.label(path),229,ink=ink,font='bold5')
        q.title('PREHEAR '+('ON' if prehear else 'OFF'))
        selected=entries[index] if entries and index<len(entries) else None
        decoded=state.get('browser_decoded',{}).get(str(selected)) if selected else None
        if selected and selected.is_file() and (selected.suffix.lower()=='.wav' or decoded):
            sample_wave(q,(decoded or str(selected),0,None),renderer.waveforms,y=25,height=20,playhead=state.get('wave_cursor'))
        else:
            if selected and b.is_folder(selected):folder(q,8,30)
            q.fitted(24,31,b.label(selected) if selected else 'EMPTY FOLDER',225,font='bold7')
    if 'settings_menu' in state:
        settings_folder,entries,index=state['settings_menu'];index=max(0,min(index,len(entries)-1))
        first=max(0,min(index-1,len(entries)-3))
        p.title('SETTINGS / '+settings_folder);q.title('OPTIONS',f'{index+1}/{len(entries)}')
        p.fitted(4,28,entries[index],246,font='bold7')
        p.fitted(4,39,'E1 SELECT / F8 OPEN / F4 BACK' if state.get('controller')=='mk1' else 'ENC SELECT / ENTER OPEN / LEFT BACK',246)
        settings_rows(q,[('>' if first+i==index else '')+v for i,v in enumerate(entries[first:first+3])],y=27)
    elif 'interface_mixer' in state:
        device,name,direction,value,db,amount,error=state['interface_mixer']
        p.title('INTERFACE MIXER',counter);q.title(direction.upper() if name else 'HARDWARE LEVELS')
        p.fitted(4,27,name or device,246,font='bold7')
        p.fitted(4,39,device if name else 'PADS: AUDITION / F4: BACK',246)
        if name:
            q.fitted(4,26,value,246,font='bold7')
            q.fitted(4,38,db,246)
            q.rect(4,49,248,9,q.ink,False);q.rect(6,51,round(amount*244),5)
        else:q.fitted(4,28,error or ('READING MIXER...' if device!='NO AUDIO DEVICE' else device),246,font='bold7')
    elif 'stem_separation' in state:
        s=state['stem_separation'];p.title('STEM SEPARATION');p.fitted(4,25,s.get('name',''),248,font='bold7')
        p.text(4,40,'VOCALS / DRUMS / BASS / OTHER',248)
        p.text(4,52,'WHOLE SAMPLE / MAX 60 SEC',248)
        q.title(s.get('state','IDLE'),str(s.get('progress',0))+'%')
        q.fitted(4,27,s.get('message',''),248)
        q.rect(4,42,248,9,q.ink,False);q.rect(6,44,round(244*max(0,min(100,s.get('progress',0)))/100),5)
    elif 'utility' in state and 'system' not in state and page!='AUTOSAMPLER':
        header,body,footer=state['utility'];p.title(header);q.title(page,counter)
        if state.get('settings_page') and not any(state['fields'][4:]):settings_rows(q,body)
        else:q.rows(body[:3] if any(state['fields'][4:]) else body[:4])
        if state.get('controller')=='mk1':
            footer=footer.replace('ENTER','F8' if state['keys'][7] else 'F2').replace('ENCODER:','E1:')
        p.fitted(4,29,footer,246)
        if len(body)>3 and any(state['fields'][4:]):p.fitted(4,38,body[3],246)
    if 'plugin_browser' in state:
        entries,index,kind=state['plugin_browser'];index=max(0,min(index,len(entries)-1))
        first=max(0,min(index-2,len(entries)-5))
        q.rect(2,24,252,37,q.bg)
        q.title('INSTRUMENTS' if kind=='INSTRUMENT' else 'EFFECTS',f'{index+1}/{len(entries)}')
        for row,value in enumerate(entries[first:first+5]):
            y=25+row*7;chosen=first+row==index
            if chosen:q.rect(3,y-1,244,7)
            q.fitted(5,y,value,239,font='bold5' if chosen else 'regular5',ink=q.bg if chosen else q.ink)
        if len(entries)>5:
            q.rect(250,24,1,36)
            height=max(3,36*5//len(entries));top=24+round((36-height)*first/(len(entries)-5))
            q.rect(249,top,3,height)
    if 'plugin_chain' in state:
        p.rect(2,24,252,22,p.bg);q.rect(2,24,252,22,q.bg)
        p.title('SIGNAL CHAIN',state['position'])
        items=state['plugin_chain'];selected=state['plugin_chain_selected']
        chain(p,items,selected)
        if not items:p.text(6,30,'EMPTY / ADD PLUGIN',240,font='bold7')
        if 'move_target' in state:
            target=state['move_target'];q.title('MOVE / TARGET')
            q.text(5,26,f'SLOT {selected+1} > SLOT {target+1}',242,font='bold7')
            q.fitted(5,37,items[target][0] if target<len(items) else 'EMPTY',242)
        elif state.get('ducktor'):
            d=state['ducktor'];q.title('MACHINISTA DUCKTOR',counter)
            q.fitted(4,25,'FROM '+d['source'],246,font='bold5')
            for y,label,fraction,value in ((33,'IN',(d['input_db']+60)/60,f"{d['input_db']:.1f} DB"),(40,'GR',d['reduction']/max(1,d['depth']),f"-{d['reduction']:.1f} DB")):
                q.text(4,y,label,16);q.rect(23,y,145,5,q.ink,False)
                q.rect(24,y+1,round(143*max(0,min(1,fraction))),3)
                q.text(174,y,value,76)
        elif state.get('plugin_names'):
            bank,preset=state['plugin_names'];q.title('BANK / PRESET')
            q.fitted(5,25,bank,244,font='regular7')
            q.fitted(5,36,preset,244,font='bold7')
        else:
            if state.get('plugin_section'):q.title(state['plugin_section'],counter)
            if 'plugin_values' in state:
                plugin_values(q,state['plugin_values'])
                if selected<len(items) and items[selected][1]:q.title((state.get('plugin_section') or 'PARAMETERS')+' / BYPASS',counter)
            else:
                bars(q,state.get('plugin_bars',()))
                if selected<len(items) and items[selected][1]:q.text(5,38,'BYPASSED',240,font='bold5')
    if state.get('synth_graph') and not state.get('mono_plugin'):
        from app.synth_display import draw
        graph=state['synth_graph'];p.rect(2,24,252,22,p.bg);p.title(graph['title'],counter);draw(p,graph,y=25,height=19)
    if state.get('mono_plugin'):
        from app.mono_instrument_icons import paint,arrows
        item=state['mono_plugin']
        if not item['source']:
            p.rect(2,24,252,22,p.bg)
            p.title('PLUG-IN',f"{item['selected']+1}/{item['count']}")
            if item.get('art'):
                from app.mono_effect_art import paint as machine
                machine(p,item['art'],17,25)
                p.fitted(129,26,item['name'],111,font='bold5')
                p.text(129,37,'BYPASSED' if item['bypass'] else item['role'],111)
            else:
                paint(p,item['icon'],17,25)
                p.fitted(59,26,item['name'],181,font='bold7')
                p.text(59,37,'BYPASSED' if item['bypass'] else item['role'],181)
        arrows(p,item['left'],item['right'])
    if 'group_cards' in state:
        q.rect(2,24,252,37,q.bg)
        for i,(label,present,selected) in enumerate(state['group_cards']):
            x=4+(i%4)*63;y=25+(i//4)*18
            q.rect(x,y,59,16,q.ink,selected)
            ink=q.bg if selected else q.ink
            q.text(x+3,y+2,label,53,ink=ink,font='bold5')
            status=state['group_status'][i]
            q.text(x+3,y+9,'MUTED' if status[1] else 'SOLO' if status[2] else 'LOADED' if present else 'EMPTY',53,ink=ink)
    if 'arrangement' in state:
        song,index,play=state['arrangement'];p.rect(2,24,252,22,p.bg);q.rect(2,24,252,22,q.bg)
        first=max(0,index-3)
        for col,scene in enumerate(song[first:first+8]):
            c=p if col<4 else q;x=4+(col%4)*63;chosen=first+col==index
            c.rect(x,26,58,17,c.ink,chosen);c.text(x+4,31,'S'+str(scene+1).zfill(2),50,ink=c.bg if chosen else c.ink,font='bold7',center=x+29)
            if first+col==play:c.rect(x,44,58,1)
        if not song:p.text(5,30,'EMPTY ARRANGEMENT',240,font='bold7')
    if 'repeat_graph' in state:
        rate,division=state['repeat_graph'];p.rect(2,24,252,22,p.bg)
        p.text(5,29,'1/'+str(rate)+(' T' if division=='TRIPLET' else ' D' if division=='DOTTED' else ''),92,font='bold7')
        steps=max(1,min(32,round(rate*1.5 if division=='TRIPLET' else rate/1.5 if division=='DOTTED' else rate)))
        for i in range(steps):
            x=102+i*146//steps;p.rect(x,27,max(1,146//steps-2),16,p.ink,False)
    if 'macro_values' in state:
        for c in (p,q):c.rect(2,24,252,22,c.bg)
        for i,(label,value) in enumerate(state['macro_values']):
            c=p if i<4 else q;x=5+(i%4)*63
            c.rect(x,27,53,6,c.ink,False);c.rect(x+2,29,round(max(0,min(100,value))/100*49),2)
            c.text(x,37,label,55,font='bold5')
    if 'zone_map' in state and state['headings'][0]=='MAP':
        z=state['zone_map'];q.rect(2,24,252,22,q.bg)
        for note in range(32):
            x=5+note*246//32;pitch=note*4;active=z['key_lo']<=pitch<=z['key_hi']
            q.rect(x,26,6,17,q.ink,active)
    if 'name_edit' in state:
        value,cursor=state['name_edit'];q.rect(2,24,252,22,q.bg)
        for i,char in enumerate(value.upper().ljust(32)):
            x=5+i*7;selected=i==cursor
            if selected:q.rect(x-1,28,7,8)
            q.text(x,30,char,7,ink=q.bg if selected else q.ink)
        q.text(4,40,f'CHAR {cursor+1}/32',246)
    if 'nav_choices' in state:
        choices=state['nav_choices'];index=state['nav_index'];first=max(0,min(index-1,len(choices)-3))
        p.rows([('>' if first+i==index else '')+choice for i,choice in enumerate(choices[first:first+3])])
        preview=state['nav_preview']
        q.title(preview['module'],f'{preview["index"]+1}/{preview["total"]}')
        q.fitted(4,29,preview['section'],246,font='regular7')
        q.text(4,40,'RELEASE NAV: OPEN',246)
    if state.get('hardware'):
        for c in (p,q):c.rect(2,24,252,39,c.bg)
        hardware(p,q,state['hardware'],state.get('controller','mk2'))
    if 'system' in state:system_dashboard(p,q,state)
    if 'mixer' in state:
        mix=state['mixer']
        for c in (p,q):c.rect(2,24,252,39,c.bg)
        for i,levels in enumerate(mix['levels']):
            c=p if i<4 else q;x=4+(i%4)*63;f=state['fields'][i]
            c.text(x,25,mix['names'][i]+(' '+f[0] if f else ''),57,center=x+28)
            if mix['first']+i==mix['selected']:c.rect(x+4,31,49,1)
            for channel,level in enumerate(levels):
                xx=x+18+channel*11
                c.rect(xx-1,33,10,20,c.ink,False)
                def height(value):return 0 if value<=0 else max(0,min(18,round((20*math.log10(max(1e-4,value))+60)/60*18)))
                h=height(level)
                if h:c.rect(xx,52-h,8,h)
                peak=mix['peaks'][i][channel]
                if peak>0:c.rect(xx,52-max(1,height(peak)),8,1)
            if f:
                value=f[1];font=bold_font(c,value,57)
                c.fitted(x,54,value,57,font=font,center=x+28)
        p.title(mix['title'],state['position']);q.title('MIXER / '+('LEVEL','PAN','ROUTE')[state['active_right'][0]] if state['active_right'] else 'MIXER')
    elif 'system' not in state and page=='LIVE FX':
        parameters(p,state['fields'][:4])
    elif 'system' not in state:
        parameters(p,state['fields'][:4],grid='grid' in state);parameters(q,state['fields'][4:],grid='grid' in state)
        # Keep the control-page footer aligned across both LCDs, even when
        # a parameter page only assigns encoders on the left display.
        if page in CONTROL_PAGES:
            for c in (p,q):c.rect(2,46,252,1)
    if state.get('auto_write'):
        title,detail,compact=q.last_title;q.title(title,'AUTO'+(' '+detail if detail else ''),compact)
    if state['message'] and page in CONTROL_PAGES:
        q.message(state['message'])
    elif page=='LIVE FX' and state['message'].startswith('TAP '):
        p.rect(2,24,252,12,p.bg)
        p.fitted(5,27,state['message'],242,font='bold7')
    elif state['message'] and page=='PLUGIN BROWSE':p.message(state['message'])
    elif state['message'] and page not in ('SAMPLE EDIT','CHOP','ZONE','MIXER','LIVE FX'):q.message(state['message'])
    if state.get('master_feedback'):
        label,value=state['master_feedback'];p.rect(2,15,252,31,p.bg);p.title(label);p.fitted(4,32,value,246,font='bold7',center=128)
    renderer.needs_refresh=renderer.waveforms.future is not None
    return p.finish(),q.finish()
