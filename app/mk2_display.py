"""Native 2x256x64 MK2 layouts and detached rendering snapshots."""
from pathlib import Path
from app.controller_settings import on_controller,DEVICE_PAGES
import math
import time
from app.mk2_font import FONTS
from app.lcd_text import display_text
from app.navigation import CONTROL_PAGES
from app.sampler import ZONE_PAGES
from app.surface import PROCESSING
from app.mk2_protocol import led_reports,LED_BUTTONS,TRANSPORT
from app.leds import led_report
from app.ni_display import name

PALETTE=((100,25,0),(95,0,0),(95,55,0),(20,90,0),(0,80,45),(0,40,100),(60,0,100),(95,0,50))


def rect(p,x,y,w,h,color=1,fill=True):
    for yy in range(max(1,y),min(63,y+h)):
        for xx in range(max(1,x),min(255,x+w)):
            if fill or yy in (y,y+h-1) or xx in (x,x+w-1):p[yy*256+xx]=color


def text(p,x,y,value,color=1,font='bold5',limit=250,center=None,preserve_case=False):
    glyphs=FONTS[font];value=display_text(str(value));value=value if preserve_case else value.upper()
    def width(v):return sum(len(glyphs.get(c,glyphs[' '])[0])+1 for c in v)-1
    while value and width(value)>limit:value=value[:-1]
    if center is not None:x=max(x,center-width(value)//2)
    for c in value:
        rows=glyphs.get(c,glyphs[' '])
        for dy,row in enumerate(rows):
            for dx,bit in enumerate(row):
                if bit=='1' and 0<x+dx<255 and 0<y+dy<63:p[(y+dy)*256+x+dx]=color
        x+=len(rows[0])+1


def dotted(p,y,x=12,end=244):
    for xx in range(x,end,2):rect(p,xx,y,1,1)


def parameter(p,column,label,value):
    x=4+column*63;center=x+29
    text(p,x,46,label,limit=58,center=center)
    text(p,x,54,value,font='bold7',limit=58,center=center)


def mixer_strip(p,column,caption,value,levels,peaks,selected=False):
    """Stereo dB meters grow upward; held peaks remain separate from signal."""
    x=4+column*63;center=x+29
    text(p,x,18,caption,limit=58,center=center)
    if selected:rect(p,x+4,24,50,1)
    rect(p,center-11,26,22,25,1,False)
    def height(peak):
        return 0 if peak<=0 else max(0,min(22,round((20*math.log10(max(1e-4,peak))+60)/60*22)))
    for channel in range(2):
        xx=center-9+channel*10
        h=height(levels[channel] if channel<len(levels) else 0)
        if h:rect(p,xx,49-h,8,h)
        held=peaks[channel] if channel<len(peaks) else 0
        if held>0:rect(p,xx,49-max(1,height(held)),8,1)
    text(p,x,54,value,font='bold7',limit=58,center=center)


def tabs(p,labels,active=()):
    for i,label in enumerate(labels):
        if not label:continue
        x=2+i*63;selected=i in active
        rect(p,x,2,61,11,1,selected)
        text(p,x+2,4,label,0 if selected else 1,font='bold7',limit=57,center=x+30)
    rect(p,2,14,252,1)


def navigate_active(app):
    active={0} if 'VIEW' in app.pinned_modes else set()
    destination={'SCENE':1,'SONG':2,'CLIP ARRANGER':2,'CLIP MENU':2,'MIXER':3,'BROWSE':4,'PATTERN GRID':5,'GRID EDIT':5,'LIVE FX':6}.get(app.view_origin)
    if destination is not None:active.add(destination)
    return active


@on_controller('mk2')
def snapshot(surface):
    from app.ui_context import nav_preview,visible_message,pinned
    a=surface.app;p=a.page
    fields=surface.fields();index,total=surface.page_state()
    state=dict(controller=surface.source,display_invert=a.settings['controllers'][surface.source].get('invert',False),page=p,keys=surface.softkeys(),fields=tuple((f.label,f.value) if f else None for f in fields),
        group=a.group,pad=a.pad,scope=a.control_level,title=name(a),project=a.project['name'],
        position=a.pattern_position(),transport=a.transport_title(),tempo=a.project['tempo'],
        playing=a.playing,recording=a.recording,message=visible_message(a),page_index=index,page_total=total,
        master_mode=surface.master_mode,master_feedback=surface.master_feedback(),auto_write=surface.auto_locked or 'AUTO' in surface.held,active_left=(),active_right=(),headings=(p,p))
    if p=='STEM SEPARATION':state['stem_separation']=dict(a.stem_status,name=(a.stem_status.get('name') if a.stem_status.get('busy') else '') or a.stem_name)
    if p=='OPTIONS':
        state['grid_options']=dict(a.timing(),tab=a.grid_tab)
        state['active_left']=({0:3,1:1,2:2}[a.grid_tab],)
    from app.wave_playback import position,visible_path
    state['wave_cursor']=position(a,visible_path(a))
    from app.codec_levels import dac_context
    from app.fokus_data import group_status
    state['group_status']=group_status(a)
    state['group_muted']=bool(a.project['groups'][a.group].get('mute',False))
    if p in CONTROL_PAGES:
        state['active_left']=(a.control_level,);state['active_right']=(1 if p in ('SAMPLER','PLUGIN') else 0,)
        state['title']=a.project['name'] if a.control_level==0 else a.project['groups'][a.group].get('name',a.group_name()) if a.control_level==1 else name(a)
        state['choice']='1. SAMPLER' if p=='SAMPLER' else (a.plugin_metadata(a.plugin_selected()['uri']) or {}).get('name','NO PLUGIN') if p=='PLUGIN' and a.plugin_selected() else {'PAD':'OUTPUT','CHANNEL':'OUTPUT','INPUT':'INPUT','GROOVE':'GROOVE','MACRO':'MACRO'}.get(p,'ADD PLUGIN')
        if p=='SAMPLER':state['headings']=(('VOICE','PITCH / GATE','FX','MODULATION ENVELOPE','LFO','VELOCITY')[a.sampler_page],('ENGINE','AMPLITUDE ENVELOPE','FILTER','DESTINATION','DESTINATION','MODWHEEL')[a.sampler_page])
        else:state['headings']=(('AUDIO','AUX 1','AUX 2','MIDI')[a.channel_page] if p in ('PAD','CHANNEL') else state['choice'],'')
        if p in ('PAD','CHANNEL','INPUT','GROOVE','MACRO'):
            state['channel_modules']=('OUTPUT','GROOVE','MACRO') if a.control_level==0 else ('INPUT','OUTPUT','GROOVE','MACRO')
            state['channel_module']={'PAD':'OUTPUT','CHANNEL':'OUTPUT'}.get(p,p)
    if p in ('SAMPLING','BROWSE','SAMPLE EDIT','CHOP','ZONE','STRETCH'):state['sample_target']=f'{a.group_name()}:{a.pad+1:02}'
    if p=='AUTOSAMPLER':
        a.auto_setup();state['autosampler']=(dict(a.auto_status),dict(a.auto_config))
        state['active_left']=(1+a.auto_field//8,);state['active_right']=()
    if p=='SAMPLING':state['capture_status']='RECORDING' if a.capture_started is not None else 'WAITING / '+a.capture_options()['mode'] if a.capture_armed else ''
    if p in ('SAMPLING','SAMPLE EDIT','CHOP','ZONE','STRETCH','SLICE TARGET'):
        state['active_left']=(('SAMPLING','SAMPLE EDIT','CHOP','ZONE').index(p),) if p in ('SAMPLING','SAMPLE EDIT','CHOP','ZONE') else (1 if p=='STRETCH' else 2,)
        t=a.track();source=surface.waveform_source() if p in ('SAMPLE EDIT','CHOP','ZONE') else t
        state['direct_wave']=p in ('SAMPLE EDIT','CHOP','ZONE') and not a.wave_view()
        state['wave']=surface.waveform_window() if p in ('SAMPLE EDIT','CHOP','ZONE') else (source.get('sample'),source.get('start',0),source.get('end',0))
        state['sample_polarity']=p in ('SAMPLE EDIT','STRETCH')
        state['markers']=tuple(tuple(x) for x in a.slice_ranges()) if p=='CHOP' else ((source.get('selection_start',source['start']) if p=='SAMPLE EDIT' and a.range_page else source['start'],source.get('selection_end',source['end']) if p=='SAMPLE EDIT' and a.range_page else source['end']),)
        state['slice_index']=a.slice_index;state['slice_edit']=a.slice_edit;state['slice_bank']=a.slice_bank
        if p=='CHOP' and a.slice_edit:state['active_right']=(0,)
        state['headings']=('TIME' if p=='CHOP' and not a.slice_edit else 'SLICE' if p=='CHOP' else 'PLAY RANGE' if p=='SAMPLE EDIT' and not a.range_page else 'SELECTION' if p=='SAMPLE EDIT' else ZONE_PAGES[a.zone_page][0] if p=='ZONE' else ('RECORDING' if a.capture_section==0 else 'MONITOR') if p=='SAMPLING' else p,'WAVEFORM')
        if p=='CHOP' and a.slice_edit:state['headings']=(f'SLICE {a.slice_index+1:02} - MASTER','WAVEFORM')
        state['process']=PROCESSING[a.process_index]
        state['capture_peaks']=tuple(a.capture_stereo_peak)
        options=a.capture_options()
        state['capture_threshold']=options['threshold'] if options['mode']=='DETECT' else None
        if p=='SLICE TARGET':state.update(target_group=a.slice_target_group,target_sound=a.slice_target_sound,groups=len(a.project['groups']),target_bank=a.slice_target_group//8,target_count=len(a.slice_ranges()))
    if p=='PLUGIN BROWSE':
        entries=('REMOVE PLUG-IN' if a.plugin_selected() else '*EMPTY SLOT*',)+tuple(v['name'] for v in a.plugin_items())
        state['plugin_browser']=(entries,a.plugin_browser_index+1,a.plugin_filter)
    if p=='BROWSE':
        state['browser_decoded']=dict(a.browser_decoded)
        from app.browser import browser_snapshot
        b=a.browser;state['browser']=browser_snapshot(b)
        state['headings']=('FOLDERS','FILES')
        if b.prehear:state['active_left']=(3,)
    if p=='VIEW NAV':
        state['headings']=('ARRANGEMENT','PATTERN EDITOR')
        state['view_origin']=a.view_origin
        active=navigate_active(a)
        state['active_left']=tuple(sorted(i for i in active if i<4))
        state['active_right']=tuple(sorted(i-4 for i in active if i>=4))
    if p=='LIVE FX':
        from app.live_fx import LIVE_FX
        state['active_left']=(a.live_fx_mode,)
        state['live_fx']=(a.live_fx_mode,a.live_fx_depth,a.live_fx_current,LIVE_FX[1:]+('OFF',))
        state['live_fx_pad']=a.live_fx_pad
    if p=='MIXER':
        from app.live_display import live_state
        state['mixer']=live_state(a);state['active_left']=(a.mixer_level,);state['active_right']=(a.mixer_field,)
    if p=='STEP':
        state['steps']=tuple(any(row==a.pad and tick//a.grid_ticks()==a.bank*16+i for row,tick in a.notes()) for i in range(16))
        state['bank']=a.bank;state['cell_count']=a.step_cell_count();state['play_cell']=a.phase_cell() if a.playing else -1
        state['active_left']=(3,) if a.fixed_velocity else ();state['active_right']=(0,) if a.follow else ()
        state['headings']=('PATTERN                        EVENTS','')
    if p in ('PATTERN','SCENE','SELECT','MUTE','SOLO','PAD CONFIG'):
        state['tiles']=tuple((str(i+1),a.sound_present(i),i==a.pad) for i in range(16))
        if p in ('SELECT','MUTE','SOLO'):
            pads=a.project['groups'][a.group]['pads'];solo=any(t['solo'] for t in pads)
            state['pad_status']=tuple((i in a.selected_pads if p=='SELECT' else t[p.lower()],
                i==a.pad,not t['mute'] and (not solo or t['solo']) and not state['group_muted'] and
                (not any(g.get('solo',False) for g in a.project['groups']) or a.project['groups'][a.group].get('solo',False)),i in a.held_pads) for i,t in enumerate(pads))
        if p=='PATTERN':state['tiles']=tuple((str(a.pattern_bank*16+i+1),a.pattern_bank*16+i in a.project['groups'][a.group]['pattern_created'],a.pattern_bank*16+i==a.pattern) for i in range(16))
        if p=='SCENE':state['tiles']=tuple((str(a.scene_bank*16+i+1),a.scene_bank*16+i in a.project['scene_created'],a.scene_bank*16+i==a.scene) for i in range(16))
        if p=='PAD CONFIG':
            state['active_left']=tuple(i for i,enabled in enumerate((True,a.keyboard_enabled,a.velocities16,a.fixed_velocity)) if enabled)
            if a.keyboard_enabled:
                from app.ni_display import note_name
                state['tiles']=tuple((note_name(a.performance_notes(i)[0]) if a.performance_notes(i) else '-',bool(a.performance_notes(i)),i in a.held_pads) for i in range(16))
                state['keyboard_notes']=tuple(a.performance_notes(getattr(a,'chord_focus',0)));state['keyboard_active']=tuple(a.performance_lights);state['keyboard_root']=a.keyboard_root
                state['keyboard_custom']=a.keyboard_chord_mode()=='CUSTOM'
                state['keyboard_slices']=a.slice_keyboard()
                if state['keyboard_slices']:
                    focus=a.step_input_note();focus=0 if focus is None else focus
                    state['tiles']=tuple((str(a.keyboard_root+i+1),bool(a.performance_notes(i)),a.keyboard_root+i==focus) for i in range(16))
                row=a.chord_row();state['chord_name']=row.get('name') or 'CHORD '+str(a.performance().get('custom_bank',0)*16+a.chord_focus+1) if row else 'UNASSIGNED PAD'
                state['chord_learning']=a.chord_learning is not None
                if surface.pad_page==2 and state['chord_learning']:state['active_right']=(0,)
    if p in ('PATTERN GRID','GRID EDIT'):
        from app.pattern_display import pattern_state
        state['grid']=pattern_state(a)
        state['active_left']=tuple(getattr(surface,'event_select_index',0) if i==0 else i for i,on in enumerate((bool(a.grid_cursor_targets() & a.grid_selected),p=='GRID EDIT',a.grid_follow)) if on)
        state['headings']=('','')
    if p in ('NOTE REPEAT','ARP'):
        active=surface.repeat_active_keys();state['active_left']=tuple(i for i in active if i<4);state['active_right']=tuple(i-4 for i in active if i>=4)
    if p in DEVICE_PAGES:
        values=a.settings['controllers'][surface.source]
        state['hardware']=dict(values)
        for key,default in (('brightness',100),('contrast_left',42),('contrast_right',42)):
            if state['hardware'][key] is None:state['hardware'][key]=default
    from app.settings_menu import SETTINGS_VIEWS,SETTINGS_LABELS
    if p in ('CLIP ARRANGER','CLIP MENU'):
        from app.arranger_display import state as clip_state
        state['clip_arranger']=clip_state(a)
        from app.clip_arranger import position
        state['position']=position(max(0,a.clock_phase))
        if p=='CLIP ARRANGER' and a.arranger_follow:state['active_right']=(1,)
    state['settings_page']=p in SETTINGS_VIEWS and p!='BLUETOOTH MIDI'
    if p=='SETTINGS':
        state['active_left']=(('AUDIO','MIDI','SYSTEM').index(a.settings_folder),)
        state['settings_menu']=(a.settings_title(),tuple(SETTINGS_LABELS.get(v,v) for v in a.setting_entries()),a.menu)
    if p=='INTERFACE MIXER':
        from app.interface_mixer import value_text,db_text
        control=a.interface_control()
        state['interface_mixer']=(a.audio.name if a.audio else 'NO AUDIO DEVICE',control['name'] if control else '',control['direction']+(' SWITCH' if control['kind']=='switch' else ' LEVEL') if control else '',value_text(control) if control else '',db_text(control) if control else '',control['value']/(100 if control['kind']=='level' else 1) if control else 0,a.interface_mixer_error)
    if p=='UPDATE':
        state['updater']=dict(a.update_status)
        state['active_right']=(0 if a.update_status.get('channel')=='beta' else 1,)
    if p=='SYSTEM':
        import copy
        state['system']=copy.deepcopy(a.system_stats)
    if p=='SAMPLER':
        state['sampler_values']=dict(a.track().get('sampler',{}))
        state['sampler_section']=a.sampler_page
    if p in ('PAD','CHANNEL','SAMPLER') and a.control_level==2:
        t=a.track();state['sound_wave']=(t.get('sample'),t.get('start',0),t.get('end',0))
    if p=='PLUGIN':
        from app.ducktor import view
        ducktor=view(a)
        if ducktor:state['ducktor']=ducktor
        from app.synth_display import view as synth_view
        synth=synth_view(a)
        if synth:state['synth_graph']=synth
    if p in ('PLUGIN','PLUGIN SLOTS','PLUGIN MOVE'):
        items=a.plugin_target().get('plugins',[])
        state['plugin_chain']=tuple(((a.plugin_metadata(v['uri']) or {}).get('name',v['uri']),v.get('bypass',False)) for v in items)
        state['plugin_chain_selected']=a.plugin_slot
        if p=='PLUGIN MOVE':state['move_target']=a.plugin_move_to
        selected=a.plugin_selected();controls=a.plugin_controls() if selected else ()
        from app.plugin_profiles import names
        if selected:
            named=names(a.root,selected)
            if named and a.plugin_param//8==0:state['plugin_names']=named
            if controls:
                port=controls[min(a.plugin_param,len(controls)-1)]
                if port.get('section'):
                    state['plugin_section']=port['section'];state['plugin_preset']=named[1] if named else ''
                    from app.virtualjv_controls import effective
                    state['plugin_bars']=tuple((v['name'],max(0,min(1,(effective(v,selected['controls'].get(v['symbol'],v['default']))-v['min'])/max(1e-9,v['max']-v['min'])))) for v in controls[a.plugin_param:a.plugin_param+3])
        if 'plugin_bars' not in state:state['plugin_bars']=tuple((port['name'],max(0,min(1,(selected['controls'].get(port['symbol'],port['default'])-port['min'])/max(1e-9,port['max']-port['min'])))) for port in controls[a.plugin_param:a.plugin_param+3])
        if p=='PLUGIN' and selected:
            from app.virtualjv_controls import effective
            first=a.plugin_param//8*8
            state['plugin_values']=tuple((i+1,fields[i].label,fields[i].value,
                max(0,min(1,(effective(port,selected['controls'].get(port['symbol'],port['default']))-port['min'])/max(1e-9,port['max']-port['min']))))
                for i,port in enumerate(controls[first:first+8]) if fields[i] is not None)
    if surface.source in ('mk1','mk2') and p in ('PLUGIN','SAMPLER','AUDIO LOOP') and index==0:
        from app.mono_instrument_icons import overview
        detail=overview(a)
        if detail:state['mono_plugin']=detail
    if surface.source in ('mk1','mk2') and p in ('PAD','CHANNEL') and a.channel_page==0:
        from app.mono_instrument_icons import channel_art
        state['mono_channel_art']=channel_art(a)
    if p in ('PAD','CHANNEL','INPUT'):
        from app.routing import route_defaults
        r=route_defaults(a.plugin_target());scope=('MASTER','GROUP '+a.group_name(),'SOUND '+str(a.pad+1))[a.control_level]
        state['signal_route']=(r['input'],scope) if p=='INPUT' else (scope,r['dest'] if a.channel_page==0 else r['aux1_dest'] if a.channel_page==1 else r['aux2_dest'] if a.channel_page==2 else 'MIDI')
    if p=='GROUP':state['group_cards']=tuple((chr(65+i),any(a.sound_present(j,a.group_bank*8+i) for j in range(16)),a.group_bank*8+i==a.group) for i in range(min(8,len(a.project['groups'])-a.group_bank*8)))
    if p=='SONG':state['arrangement']=(tuple(a.project['song']),a.song_index,a.song_bar if a.song_playing else -1)
    if p in ('NOTE REPEAT','ARP'):state['repeat_graph']=(a.project['repeat_presets'][a.repeat_bank*2+a.repeat_preset],a.project['arp']['division'])
    if p=='MACRO':state['macro_values']=tuple((a.plugin_target().get('macros',{}).get(str(i),{}).get('name','UNASSIGNED'),a.plugin_target().get('macros',{}).get(str(i),{}).get('value',0)) for i in range(8))
    if p=='ZONE' and a.zone():state['zone_map']={key:a.zone()[key] for key in ('key_lo','key_hi','vel_lo','vel_hi','root')}
    state['focus_detail']=('REC ' if a.recording else 'PLAY ' if a.playing else '')+a.pattern_position()
    if p=='CHOP' and a.slice_edit:state['focus_detail']='END' if a.slice_focus_end else 'START'
    if p in ('PARAM NAV','SAMPLING NAV'):
        state['nav_choices']=tuple(a.parameter_choices()) if p=='PARAM NAV' else ('RECORD','EDIT','SLICE','ZONE','AUTO')
        state['nav_index']=a.parameter_choice if p=='PARAM NAV' else a.sampling_nav
        state['nav_preview']=nav_preview(a)
    if p not in CONTROL_PAGES+('SAMPLING','SAMPLE EDIT','CHOP','ZONE','STRETCH','SLICE TARGET','BROWSE','MIXER','STEP','PATTERN','SCENE','PAD CONFIG','SELECT','MUTE','SOLO','PATTERN GRID','GRID EDIT','VIEW NAV','PARAM NAV','SAMPLING NAV','NOTE REPEAT','ARP','LIVE FX','OPTIONS'):
        from app.fokus_data import utility_data
        from app.fokus import enabled
        header,body,footer=utility_data(a) if enabled() else a.display();state['utility']=(header,tuple(body),footer)
        if p=='PROJECT NAME':state['name_edit']=(a.name_value,a.name_cursor)
    for i,key in enumerate(state['keys']):
        if key=='PIN':
            side='active_left' if i<4 else 'active_right'
            active=set(state[side]);active.discard(i%4)
            if pinned(a):active.add(i%4)
            state[side]=tuple(sorted(active))
    if dac_context(a):state['active_left']=tuple(i for i,k in enumerate(('hat_headphone_mute','hat_speaker_mute')) if a.settings[k])
    return state


def leds(surface,channels,now=None):
    surface.sync()
    a=surface.app;now=time.monotonic() if now is None else now
    legacy=led_report(a,channels,now)
    buttons={name:3 for name in LED_BUTTONS+TRANSPORT}
    for key,index in a.button_led_map.items():
        if key in buttons:buttons[key]=min(100,legacy[index+1]*3)
    buttons['CONTROL']=85 if a.page in CONTROL_PAGES else 8
    buttons['STEP']=85 if a.page=='STEP' else 8
    buttons['NAVIGATE']=85 if a.page in ('VIEW NAV','MIXER') or a.wave_view() else 8
    if a.page=='LIVE FX':buttons['SOLO']=85
    for name in ('VOLUME','SWING','TEMPO'):buttons[name]=85 if surface.master_mode==name else 8
    events=set(a.event_notes()) if a.page in ('PATTERN GRID','GRID EDIT') else None
    all_selected=bool(events) and events.issubset(a.grid_selected) if events is not None else len(a.selected_pads)==16
    buttons['ALL']=85 if all_selected else 8
    buttons['AUTO']=85 if surface.auto_locked or 'AUTO' in surface.held else 8
    left,right=surface.page_directions();buttons['PAGE LEFT']=35 if left else 0;buttons['PAGE RIGHT']=35 if right else 0
    keys=surface.softkeys()
    active=set()
    if a.page in CONTROL_PAGES:active={a.control_level,5 if a.page in ('SAMPLER','PLUGIN') else 4}
    elif a.page in ('SAMPLING','SAMPLE EDIT','CHOP','ZONE'):active={('SAMPLING','SAMPLE EDIT','CHOP','ZONE').index(a.page)}
    elif a.page=='AUTOSAMPLER':active={1+a.auto_field//8}
    elif a.page=='PAD CONFIG':active={0}|({1} if a.keyboard_enabled else set())|({2} if a.velocities16 else set())|({3} if a.fixed_velocity else set())
    elif a.page=='OPTIONS':active={{0:3,1:1,2:2}[a.grid_tab]}
    elif a.page=='VIEW NAV':active=navigate_active(a)
    elif a.page=='LIVE FX':active={a.live_fx_mode}
    elif a.page in ('PATTERN GRID','GRID EDIT'):active={getattr(surface,'event_select_index',0) if i==0 else i for i,on in enumerate((bool(a.grid_cursor_targets() & a.grid_selected),a.page=='GRID EDIT',a.grid_follow)) if on}
    elif a.page=='STEP':active=({3} if a.fixed_velocity else set())|({4} if a.follow else set())
    elif a.page=='MIXER':active={a.mixer_level,4+a.mixer_field}
    elif a.page in ('NOTE REPEAT','ARP'):active=surface.repeat_active_keys()
    if a.page=='CHOP' and a.slice_edit:active.add(4)
    from app.ui_context import pinned
    for i,key in enumerate(keys):
        if key=='PIN':
            active.discard(i)
            if pinned(a):active.add(i)
    for i,key in enumerate(keys):buttons[f'DISPLAY {i+1}']=85 if i in active else 25 if key and key!='-' else 0
    pads={}
    for slot in range(16):
        index=channels.get((slot,'orange'));value=legacy[index+1]/31 if index is not None else 0
        if a.page=='LIVE FX':value=.85 if slot==a.live_fx_pad else .25
        pads[slot]=tuple(round(c*value) for c in PALETTE[a.group%8])
    groups={}
    group_solo=any(g.get('solo',False) for g in a.project['groups'])
    for i,letter in enumerate('ABCDEFGH'):
        group=a.group_bank*8+i;value=1 if (a.slice_target_group if a.page=='SLICE TARGET' else a.group)==group else .12
        if group<len(a.project['groups']) and a.page!='SLICE TARGET':
            target=a.project['groups'][group]
            if target.get('mute',False):value=0
            elif group_solo and not target.get('solo',False):value=.04
            elif a.page in ('MUTE','SOLO'):value=1 if group==a.group else .55
        groups[letter]=tuple(round(c*value) for c in PALETTE[i]) if group<len(a.project['groups']) else (0,0,0)
    return led_reports(buttons,pads,groups)


def tiles(p,items):
    for i,(label,present,selected) in enumerate(items):
        x=4+(i%4)*62;y=23+(3-i//4)*9
        if selected:rect(p,x,y,59,8)
        else:rect(p,x,y,59,8,1,False)
        text(p,x+2,y+1,label,0 if selected else 1,limit=55)
        if not present:rect(p,x+48,y+3,5,1,0 if selected else 1)


class Mk2Renderer:
    def __init__(self,startup=False):
        from app.waveform_index import IndexedWaveforms
        self.waveforms=IndexedWaveforms(max_assets=16);self.needs_refresh=False;self.sample_headers={}
        from app.branding import BootSplash
        self.boot=BootSplash()
        self.boot_requested=startup
        from app.text_marquee import Marquee
        self.marquee=Marquee()
    def dismiss_boot(self):
        self.boot_requested=False;self.boot.dismiss()
    def close(self):self.waveforms.close()
    def __call__(self,state):
        from app.display_polarity import pixels
        from app.text_marquee import bitmap_names
        frames=self.draw(state)
        if not self.boot.active():
            frames=bitmap_names(self.marquee,state,frames)
            self.needs_refresh=self.needs_refresh or self.marquee.active
        return tuple(pixels(frame,state.get('display_invert',False)) for frame in frames)

    def draw(self,state):
        if state['page'] in ('CLIP ARRANGER','CLIP MENU'):
            from app.arranger_display import mono,menu_mono
            a=state['clip_arranger']
            if state['page']=='CLIP MENU':return menu_mono(a['menu'])
            active=tuple(state.get('active_left',()))+tuple(i+4 for i in state.get('active_right',()))
            return mono(a,state['keys'],active)
        if self.boot_requested:
            self.boot.start();self.boot_requested=False
        if self.boot.active():
            from app.branding import boot_frame
            self.needs_refresh=True
            return boot_frame(256),boot_frame(256)
        from app.fokus import enabled
        if enabled():
            from app.fokus_mk2 import render
            return render(state,self)
        return self.legacy_frame(state)

    def legacy_frame(self,state):
        p=bytearray(16384);q=bytearray(16384);page=state['page']
        tabs(p,state['keys'][:4],state['active_left']);tabs(q,state['keys'][4:],state['active_right'])
        if page in CONTROL_PAGES:
            # Control property selector spans the two rightmost buttons.
            rect(q,128,1,126,13,0);rect(q,129,2,124,11,1,False)
            text(q,139,4,state['choice'],font='bold7',limit=104,center=191)
            rect(q,129,2,8,11,1,False);rect(q,245,2,8,11,1,False)
            text(q,131,5,'<',limit=5);text(q,247,5,'>',limit=5)
        for target in (p,q):dotted(target,17);dotted(target,29)
        text(p,12,20,state['title'],font='regular7',limit=120)
        text(p,139,20,f'{state["tempo"]:.2f}',font='regular7',limit=52,center=165)
        text(p,203,20,state['position'],font='regular7',limit=43,center=225)
        for target,heading in ((p,state['headings'][0]),(q,state['headings'][1])):
            if heading:text(target,4,38,heading,limit=211)
            rect(target,2,44,252,1)
        text(p if 'wave' in state else q,225,38,f'{state["page_index"]+1}/{state["page_total"]}',limit=28)
        for i,field in enumerate(state['fields']):
            if field is not None:parameter(p if i<4 else q,i%4,*field)
        if 'wave' in state and page!='SLICE TARGET':
            path,first,last=state['wave'];rect(q,2,16,252,46,0)
            duration=None
            if path:
                import wave
                try:
                    metadata=Path(path).stat();key=(path,metadata.st_mtime_ns,metadata.st_size)
                    if key not in self.sample_headers:
                        with wave.open(path,'rb') as wav:self.sample_headers[key]=wav.getnframes()/wav.getframerate()
                        while len(self.sample_headers)>16:self.sample_headers.pop(next(iter(self.sample_headers)))
                    duration=self.sample_headers[key]
                except (OSError,EOFError,wave.Error):pass
            text(q,4,17,Path(path).name if path else 'NO SAMPLE',font='regular7',limit=151 if duration is not None else 244)
            if duration is not None:text(q,160,17,f'LENGTH:{duration:.2f}S',font='regular7',limit=92)
            envelope=self.waveforms.envelope(path,first,last) if path else None
            light=bool(path and state['sample_polarity'])
            bottom=61
            mid=(27+bottom)//2;amplitude=max(1,(bottom-28)//2)
            rect(q,3,26,250,bottom-25,1,False)
            if light:rect(q,4,27,248,bottom-27)
            ink=0 if light else 1
            if path:rect(q,5,mid,246,1,ink)
            if envelope:
                for i,(lo,hi) in enumerate(envelope.peaks):
                    x=5+i*246//max(1,len(envelope.peaks));y=mid-round(hi*amplitude)
                    rect(q,x,y,max(1,246//max(1,len(envelope.peaks))),max(1,round((hi-lo)*amplitude)),ink)
            if last>first:
                if page in ('SAMPLE EDIT','ZONE','STRETCH') and path and state['markers']:
                    start,end=state['markers'][0]
                    left=4 if start<=first else min(252,5+round((start-first)/(last-first)*246))
                    right=252 if end>=last else max(4,5+round((end-first)/(last-first)*246))
                    # Keep the playable range unchanged; reverse both the
                    # waveform and its background outside the trim markers.
                    for yy in range(27,bottom):
                        for xx in range(4,252):
                            if xx<left or xx>=right:q[yy*256+xx]^=1
                for index,(start,end) in enumerate(state['markers']):
                    if first<end<=last:
                        x=min(250,5+round((end-first)/(last-first)*246));rect(q,x,28,1,bottom-29,ink)
                    if first<=start<last:
                        x=5+round((start-first)/(last-first)*246);rect(q,x,28,1,bottom-29,ink)
                    if page=='CHOP' and index==state['slice_index']:
                        # Clip the selected area independently of the start
                        # marker so END focus also retains slice highlighting.
                        left=max(5,5+round((start-first)/(last-first)*246))
                        right=min(251,5+round((end-first)/(last-first)*246))
                        for yy in range(28,bottom-1):
                            for xx in range(left,right):q[yy*256+xx]^=1
            point=state.get('wave_cursor')
            if point is not None and first<=point<last:
                x=max(5,min(250,5+round((point-first)/max(1,last-first)*246)))
                for yy in range(27,bottom):q[yy*256+x]^=1
            if page=='SAMPLE EDIT':
                rect(q,2,1,126,13,0);rect(q,3,2,124,11,1,False)
                text(q,11,4,state['process'],font='bold7',limit=108,center=65)
                text(q,5,5,'<',limit=5);text(q,120,5,'>',limit=5)
            if page=='SAMPLING':
                rect(p,2,16,252,21,0)
                for i,peak in enumerate(state['capture_peaks']):
                    rect(p,12,19+i*7,229,5,1,False);rect(p,13,20+i*7,round(max(0,min(1,peak))*227),3)
        if page=='SLICE TARGET':
            rect(p,2,29,252,33,0);rect(q,2,16,252,46,0)
            bank=state['target_bank']
            tiles(p,tuple((chr(65+i)+(str(bank+1) if bank else ''),True,bank*8+i==state['target_group']) for i in range(min(8,state['groups']-bank*8))))
            tiles(q,tuple((str(i+1),True,i==state['target_sound']) for i in range(16)))
        if 'tiles' in state:
            rect(q,2,16,252,46,0);tiles(q,state['tiles'])
        if page=='STEP':
            rect(q,2,17,252,45,0)
            for i,on in enumerate(state['steps']):
                x=5+i*15;rect(q,x,26,12,24,1,on)
                if state['play_cell']==state['bank']*16+i:rect(q,x,20,12,3)
            text(q,5,55,f'{state["bank"]*16+1}-{min(state["cell_count"],state["bank"]*16+16)}',limit=245)
        if 'mixer' in state:
            mix=state['mixer']
            for target in (p,q):rect(target,2,16,252,46,0)
            for i,levels in enumerate(mix['levels']):
                field=state['fields'][i]
                caption=mix['names'][i]+(' '+field[0] if field else '')
                mixer_strip(p if i<4 else q,i%4,caption,field[1] if field else '',
                            levels,mix['peaks'][i],mix['first']+i==mix['selected'])
        if 'grid' in state:
            grid=state['grid'];rect(q,2,16,252,46,0)
            text(p,4,35,grid['footer'],limit=245)
            for row,(caption,focused,cells) in enumerate(grid['rows'][1:4]):
                y=19+row*8;text(q,3,y,caption,limit=30)
                for col,(valid,present,selected,cursor) in enumerate(cells):
                    if not valid:continue
                    x=36+col*212//grid['columns'];w=max(2,212//grid['columns']-2)
                    rect(q,x,y,w,6,1,present)
                    if selected:rect(q,x+1,y+1,max(1,w-2),4,0)
                    if cursor:rect(q,x,y+6,w,1)
            head=grid['playhead']
            if head is not None:rect(q,36+round((head-29)/96*212),17,1,26)
            for i,field in enumerate(state['fields'][4:]):
                if field:
                    parameter(q,i,*field)
        if 'browser' in state:
            from app.browser import browser_from_snapshot
            browser,index,prehear=browser_from_snapshot(state['browser'])
            rect(p,2,29,252,33,0);rect(q,2,16,252,46,0)
            text(p,4,32,browser.title(),limit=245)
            text(p,4,46,'PREHEAR '+('ON' if prehear else 'OFF'),limit=245)
            rows=browser.entries();first=max(0,min(index-2,len(rows)-5))
            for i,path in enumerate(rows[first:first+5]):
                selected=first+i==index;y=18+i*9
                if selected:rect(q,3,y-1,249,8)
                text(q,5,y,browser.label(path),0 if selected else 1,limit=243)
        if 'utility' in state:
            header,body,footer=state['utility'];rect(p,2,16,252,46,0);rect(q,2,16,252,46,0)
            text(p,4,20,header,limit=245,font='regular7')
            for i,line in enumerate(body[:4]):
                line=str(line);selected=line.startswith('>')
                if selected:rect(q,3,18+i*10,249,9)
                text(q,5,20+i*10,line,0 if selected else 1,limit=243)
            text(p,4,49,footer,limit=245)
        if 'live_fx' in state:
            mode,depth,current,effects=state['live_fx'];active=15 if current==0 else current-1
            tabs(p,('PUNCH','FLEX','KNOB'),(mode,));tabs(q,('PAD FX','', ''),())
            for i,label in enumerate(effects):
                x=4+(i%8)*31;y=20+(i//8)*17;chosen=i==active
                rect(q,x,y,29,14,1,chosen)
                text(q,x+1,y+4,label[:4],0 if chosen else 1,font='bold5',limit=27,center=x+14)
            text(p,4,33,'DEPTH',font='regular7',limit=245)
            rect(p,4,43,246,6,1,False);rect(p,5,44,round(244*depth/100),4)
            text(p,4,52,f'{depth}% / {state["live_fx"][3][active]}',font='bold7',limit=245)
        if 'interface_mixer' in state:
            device,name,direction,value,db,amount,error=state['interface_mixer']
            for target in (p,q):rect(target,2,16,252,46,0)
            text(p,5,19,name or 'INTERFACE MIXER',font='bold7',limit=244)
            text(p,5,32,device,font='regular7',limit=244)
            for i,field in enumerate(state['fields']):
                if field is not None:parameter(p,i,*field)
            text(q,5,19,direction.upper() if name else (error or 'READING MIXER...'),font='regular7',limit=244)
            text(q,5,31,value,font='bold7',limit=244)
            if name:
                rect(q,5,44,244,5,1,False);rect(q,6,45,round(amount*242),3)
                text(q,5,53,db,font='regular7',limit=244)
        if 'hardware' in state:
            for target in (p,q):
                rect(target,2,16,252,46,0);rect(target,2,44,252,1)
            text(p,12,20,'MASCHINE MK2',font='regular7',limit=231)
            text(p,4,38,'HARDWARE SETTINGS',limit=245)
            text(q,12,20,'MK2 ONLY',font='regular7',limit=231)
            text(q,4,38,'PAD RESPONSE',limit=245)
            for i,field in enumerate(state['fields']):
                if field is not None:parameter(p if i<4 else q,i%4,*field)
        if 'system' in state:
            stats=state['system']
            for target in (p,q):rect(target,2,16,252,46,0)
            text(p,4,18,'Machinista',font='regular7',preserve_case=True)
            def gauge(target,y,label,value,detail=''):
                text(target,4,y,label,limit=168)
                text(target,199,y,'--%' if value is None else f'{value:.0f}%',limit=50)
                rect(target,4,y+7,246,5,1,False)
                if value is not None:rect(target,5,y+8,round(244*max(0,min(100,value))/100),3)
                if detail:text(target,4,y+14,detail,limit=245)
            if state['page_index']==0:
                from app.branding import paint_logo,VERSION
                rect(p,2,16,252,46,0);paint_logo(p,256,10,17,236)
                text(p,4,54,VERSION,limit=247,center=128)
                gauge(q,25,'CPU',stats['cpu']);gauge(q,45,'RAM',(stats['ram'] or {}).get('percent'))
            else:
                gauge(p,31,'CPU',stats['cpu']);gauge(p,48,'RAM',(stats['ram'] or {}).get('percent'))
                start=(state['page_index']-1)*2
                for i,disk in enumerate(stats['storage'][start:start+2]):
                    gauge(q,19+i*22,disk['name'],disk['percent'],f'{disk["used"]/1e9:.1f}/{disk["total"]/1e9:.1f} GB')
        if state['message'] and 'wave' not in state and page in CONTROL_PAGES:
            text(q,12,20,state['message'],font='regular7',limit=231)
        if state.get('auto_write') and page in CONTROL_PAGES:
            rect(q,2,18,252,10,0)
            text(q,12,20,'AUTO WRITE' if state['playing'] else 'AUTO WRITE - START PLAY',font='regular7',limit=231)
        if state.get('master_feedback'):
            label,value=state['master_feedback']
            rect(p,2,16,252,46,0)
            text(p,8,23,label,font='bold7',limit=240,center=128)
            dotted(p,35)
            text(p,8,45,value,font='bold7',limit=240,center=128)
        self.needs_refresh=self.waveforms.future is not None
        return bytes(p),bytes(q)
