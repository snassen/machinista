"""Musical project and controller navigation, independent of USB/audio I/O."""
from pathlib import Path
import copy
import wave
import time
import random
import re
from app.storage import save_json, load_json
from app.devices import choose_audio

AUDIO_BUFFERS=(0,128,256,512,1024,2048,4096)
from app.browser import Browser, Source
from app.clip_arranger import ClipArranger,validate as validate_arrangement
from app.workspaces import Workspaces
from app.surface import OriginalSurface
from app.pattern_editor import PatternEditor
from app.project_manager import ProjectManager
from app.presets import Presets
from app.relink import Relink
from app.sampling import Sampling
from app.navigation import Navigation
from app.timing import Timing,validate_timing
from app.sampler import Sampler, validate_sampler, default_zone, zones
from app.slicing import Slicing
from app.plugins import Plugins, validate_plugins
from app.recording import Recording
from app.erasing import Erasing
from app.group_delete import GroupDelete
from app.polyphony import Polyphony,migrate_events,validate_poly
from app.recording_history import RecordingHistory
from app.modulation_history import ModulationHistory
from app.performance import Performance,validate_performance,PARAMETER_PLAY_PAGES
from app.banks import Banks
from app.routing import Routing, build_graph
from app.layout import MAX_GROUPS,bus_targets,GROUP_BASE,MASTER
from app.groove import Groove,validate_groove
from app.automation import Automation,validate_automation
from app.midi_remote import MidiRemote,validate_midi_mappings
from app.preferences import Preferences,PREFERENCES
from app.controller_settings import DISPLAY_PAGES,init_controller_settings,change_display,reset_display,display_value,is_mk2
from app.assets import resolve_assets, relative_assets
from app.event_shortcuts import EventShortcuts
from app.project_snapshot import project_snapshot
from app.export_audio import AudioExport
from app.mixer import Mixer
from app.multiselection import MultiSelection
from app.main_controls import MainControls
from app.settings_menu import SettingsMenu, SETTINGS_VIEWS, SETTINGS_LABELS, SETTING_PAGES
from app.live_fx import LiveEffects
from app.audio_loop import is_audio_sound

PAGES = {'SAMPLING': 'SAMPLING', 'BROWSE': 'BROWSE', 'PATTERN': 'PATTERN',
         'SCENE': 'SCENE', 'PAD MODE': 'PAD', 'VIEW': 'MIXER', 'MUTE': 'MUTE',
         'SOLO': 'SOLO', 'SELECT': 'SELECT', 'GROUP': 'GROUP'}


DISPLAY_DEFAULTS = {'display_brightness': 100, 'display_contrast': 42}

def new_project():
    return {'schema_version': 1, 'name': 'UNTITLED', 'tempo': 120,
            'groups': [{'pads': [{'sample': None, 'start': 0, 'end': 0, 'gain': 80,
                                 'mute': False, 'solo': False} for _ in range(16)],
                        'patterns': [[[False]*16 for _ in range(16)] for _ in range(16)]}
                       for _ in range(8)],
            'scenes':[[0]*8]+[[None]*8 for _ in range(15)]}


def validate_project(project):
    if project.get('schema_version') != 1 or not 40 <= project['tempo'] <= 240:
        raise ValueError('unsupported project/tempo')
    if not 8<=len(project['groups'])<=MAX_GROUPS or not 16<=len(project['scenes'])<=1024:
        raise ValueError('invalid project banks')
    if not re.fullmatch(r'[A-Za-z0-9 _-]{1,32}', project.get('name', '')):
        raise ValueError('invalid project name')
    if 'file_id' in project and (not isinstance(project['file_id'],str) or not re.fullmatch(r'PROJECT-[0-9]{4}',project['file_id'])):
        raise ValueError('invalid project file ID')
    song = project.get('song', [])
    if not isinstance(song, list) or len(song) > 1024 or any(type(i) is not int or not 0<=i<len(project['scenes']) for i in song):
        raise ValueError('invalid arrangement')
    for scene in project['scenes']:
        if len(scene) != len(project['groups']) or any(p is not None and (type(p) is not int or not 0<=p<len(project['groups'][g]['patterns'])) for g,p in enumerate(scene)):
            raise ValueError('invalid scene')
    for group in project['groups']:
        if len(group['pads']) != 16 or not 16<=len(group['patterns'])<=1024:
            raise ValueError('invalid group')
        for slot,pad in enumerate(group['pads']):
            # Portable/older Sounds can omit these optional saved fields. Every
            # validated runtime track must nevertheless support keyboard/MIDI
            # playback immediately, including preset replacement after startup.
            pad.setdefault('source','SAMPLE')
            pad.setdefault('note',36+slot)
            pad.setdefault('channel',1)
            validate_sampler(pad)
            if pad['sample'] is not None and not isinstance(pad['sample'], str):
                raise ValueError('invalid sample')
            if not 0 <= pad['start'] <= pad['end'] or not 0 <= pad['gain'] <= 100:
                raise ValueError('invalid trim/gain')
            if type(pad['mute']) is not bool or type(pad['solo']) is not bool:
                raise ValueError('invalid mute/solo')
        lengths=group.get('pattern_lengths',{})
        if not isinstance(lengths,dict) or any(not str(k).isdigit() or int(k)>=len(group['patterns']) or type(v) is not int or not 1<=v<=len(group['patterns'][int(k)][0]) for k,v in lengths.items()):raise ValueError('invalid pattern lengths')
        for pattern in group['patterns']:
            if len(pattern) != 16 or not 1<=len(pattern[0])<=4096 or any(len(lane) != len(pattern[0]) or any(type(s) is not bool for s in lane) for lane in pattern):
                raise ValueError('invalid pattern')
    options=project.get('sampling',{})
    if not isinstance(options,dict) or options.get('source','EXT STEREO') not in ('EXT STEREO','EXT MONO','INTERNAL','EXT LEFT','EXT RIGHT','GROUP','MASTER') or options.get('mode','MANUAL') not in ('MANUAL','DETECT','SYNC','LOOP') or options.get('bars',1) not in (1,2,4,8,16,32,64,'FREE') or type(options.get('threshold',-24)) is not int or not -60<=options.get('threshold',-24)<=0 or type(options.get('monitor',False)) is not bool:raise ValueError('invalid sampling setup')
    if options.get('source') in ('EXT STEREO','EXT MONO','INTERNAL'):
        value=options.get('input','IN 1')
        allowed=('IN 1',) if options.get('source')=='EXT STEREO' else ('IN 1 L','IN 1 R') if options.get('source')=='EXT MONO' else tuple(f'GROUP {i}' for i in range(len(project['groups'])))+('MASTER',)+tuple(f'SOUND {g} {p}' for g in range(len(project['groups'])) for p in range(16))
        if value not in allowed:raise ValueError('invalid recording input')
    if project.get('bus_layout',1)==1:
        old_base=len(project['groups'])*16
        for target in bus_targets(project).values():
            for macro in target.get('macros',{}).values():
                old=macro.get('bus',0)
                if old>=old_base:macro['bus']=MASTER if old==old_base+len(project['groups']) else GROUP_BASE+old-old_base
        project['bus_layout']=2
    build_graph(project)
    validate_plugins(project)
    for group in project['groups']:
        validate_plugins(group,group=True)
        for track in group['pads']:
            validate_plugins(track,instrument=True)
            if track.get('source', 'SAMPLE') not in ('SAMPLE', 'MIDI') or not 0 <= track.get('note', 36) <= 127 or not 1 <= track.get('channel', 1) <= 16:
                raise ValueError('invalid MIDI track')
        for key, event in group.get('events', {}).items():
            if not re.fullmatch(r'[0-9]+:(?:[0-9]|1[0-5]):[0-9]+',key) or not 1 <= event['velocity'] <= 127 or not 0 <= event['probability'] <= 100:
                raise ValueError('invalid event properties')
            pat,pad,step=map(int,key.split(':'))
            if pat>=len(group['patterns']) or step>=len(group['patterns'][pat][pad]):raise ValueError('event outside pattern')
            if 'length' in event and (type(event['length']) is not int or not 1<=event['length']<=98304):raise ValueError('invalid note length')
            if 'note' in event and (type(event['note']) is not int or not 0 <= event['note'] <= 127):
                raise ValueError('invalid event note')
    migrate_events(project)
    for group in project['groups']:
        for field in ('events','extra_events'):
            for event in group.get(field,{}).values():validate_poly(event)
    validate_groove(project)
    validate_automation(project)
    validate_midi_mappings(project)
    validate_performance(project)
    validate_arrangement(project)
    validate_timing(project)
    return project


class Application(ClipArranger,MultiSelection,MidiRemote,AudioExport,Mixer,Relink,Presets,ModulationHistory,Polyphony, GroupDelete, Erasing, RecordingHistory, Recording, MainControls, SettingsMenu, EventShortcuts, Groove, Automation, Preferences, Performance, Banks, Routing, Plugins, Sampler, Slicing, Navigation, Sampling, Timing, ProjectManager, PatternEditor, LiveEffects, OriginalSurface, Workspaces):
    def __init__(self, root):
        self.root = Path(root)
        from app.hardware_profiles import current
        self.hardware_profile=current()
        self.samples = self.root/'samples'
        self.samples.mkdir(parents=True, exist_ok=True)
        self.browser_preview_pending=None
        self.browser_preview_active=False
        self.mp3_serial=0;self.mp3_requests={};self.browser_decoded={}
        (self.root/'presets/Sounds').mkdir(parents=True,exist_ok=True)
        (self.root/'presets/Groups').mkdir(parents=True,exist_ok=True)
        kit_root=self.root/'presets/Groups'
        self.browser = Browser(self.samples, kit_root=kit_root)
        self.browser.internal_sources = (Source('SOUNDS',self.root/'presets/Sounds'),
                                         Source('SAMPLE KITS',self.browser.kit_menu),
                                         Source('PROJECT ASSETS',self.root/'projects'),
                                         Source('PRESET ASSETS',self.root/'presets'))
        self.project_path = self.root/'projects/current.json'
        self.settings_path = self.root/'config/settings.json'
        self.settings = load_json(self.settings_path, {'audio': 'AUTO', 'midi_in': 'OFF',
                                                       'midi_out': 'OFF', 'midi_channel': 1})
        if not isinstance(self.settings, dict):
            raise ValueError('invalid settings')
        for key in ('audio', 'midi_in', 'midi_out'):
            if not isinstance(self.settings.get(key), str):
                raise ValueError('invalid device preference')
        if type(self.settings.get('midi_channel')) is not int or not 1 <= self.settings['midi_channel'] <= 16:
            raise ValueError('invalid MIDI channel')
        self.settings.setdefault('sample_rate',48000)
        if type(self.settings['sample_rate']) is not int or self.settings['sample_rate'] not in (44100,48000):
            raise ValueError('invalid audio sample rate')
        from app.audio_ports import port
        for key,default in (('main_output','OUT 1/2'),('cue_output','OFF'),('cue_level',100)):
            self.settings.setdefault(key,default)
        if type(self.settings['cue_level']) is not int or not 0<=self.settings['cue_level']<=100:raise ValueError('invalid cue level')
        for key in ('main_output','cue_output'):
            if key=='cue_output' and self.settings[key]=='OFF':continue
            value=port(self.settings[key],'OUT')
            if not value:raise ValueError('invalid output channel')
        if set(port(self.settings['main_output'],'OUT') or ()) & set(port(self.settings['cue_output'],'OUT') or ()):raise ValueError('overlapping main/cue')
        self.settings.setdefault('plugin_delay',False)
        if type(self.settings['plugin_delay']) is not bool:raise ValueError('invalid plugin delay setting')
        self.settings.setdefault('audio_buffer', self.hardware_profile['audio_buffer'])
        if type(self.settings['audio_buffer']) is not int or self.settings['audio_buffer'] not in AUDIO_BUFFERS:raise ValueError('invalid audio buffer')
        from app.codec_levels import CONTROLS,MUTES
        for key,_ in MUTES.values():
            if type(self.settings.setdefault(key,False)) is not bool:raise ValueError('invalid hardware mute')
        for key,default,maximum,_ in CONTROLS.values():
            self.settings.setdefault(key,default)
            if type(self.settings[key]) is not int or not 0<=self.settings[key]<=maximum:
                raise ValueError('invalid hardware level')
        for key, default in DISPLAY_DEFAULTS.items():
            self.settings.setdefault(key, default)
            if type(self.settings[key]) is not int or not 0 <= self.settings[key] <= 100:
                raise ValueError('invalid display setting')
        self.init_preferences()
        init_controller_settings(self)
        self.project=validate_project(resolve_assets(load_json(self.project_path,new_project()),self.project_path.parent))
        from app.autosave import recover
        self.project,recovered=recover(self.root,self.project,self.project_path,validate_project) if self.settings['autosave']=='ON' else (self.project,False)
        self.page, self.menu = 'PAD', 0
        self.init_settings_menu()
        self.group = self.pad = self.pattern = self.scene = 0
        self.active_patterns = [0]*8
        self.playing = self.recording = self.shift = False
        self.step = -1
        self.dirty = recovered
        self.message = 'AUTOSAVE RECOVERED' if recovered else ''
        self.audio_devices, self.midi_devices, self.audio = [], [], None
        self.browser_dir = self.samples
        self.browser_index = 0
        self.sample_field = 0
        self.actions = []
        self.undo = []
        self.taps = []
        self.capture_started = None
        self.encoder_held = False
        self.init_workspaces()
        self.init_surface()
        self.init_live_fx()
        self.init_mixer()
        self.init_export()
        from app.controller_stems import initial
        self.stem_status=initial();self.stem_command_pending=False;self.stem_origin='BROWSE';self.stem_asset={};self.stem_name=''
        self.init_navigation()
        self.init_sampler()
        self.init_audio_loops()
        self.init_slicing()
        self.init_plugins()
        self.init_presets()
        self.init_routing()
        self.init_banks()
        self.init_performance()
        self.revision = 0
        self.project_generation=0
        self.sample_memory={}
        self.init_automation()
        self.init_multiselection()

    def remember(self):
        if getattr(self,"selection_batch",False):return
        if getattr(self,"modulation_rotating",False):self.remember_modulation();return
        if hasattr(self, "redo"):
            self.redo.clear()
        if hasattr(self,'recording_history'):
            keep={id(s) for s in self.undo}
            self.recording_history={k:v for k,v in self.recording_history.items() if k in keep}
        self.revision += 1
        self.undo.append(self.history_snapshot())
        self.undo = self.undo[-16:]
        self.dirty = True

    def save(self):
        targets=bus_targets(self.project)
        state_root=self.root/'projects'/((self.project.get('file_id') or 'CURRENT')+'.lv2')
        for bus,target in targets.items():
            for index,plugin in enumerate(target.get('plugins',[])):
                plugin['state']=str(state_root/f'{bus}-{index}'/'state.ttl')
        if any(t.get('plugins') for t in targets.values()):self.actions.append(('save_plugin_state',copy.deepcopy(self.project)))
        named=self.active_project_file()
        if named is not None:
            self.project['file_id']=named.stem
            save_json(named,relative_assets(self.project_for_save(),named.parent))
        save_json(self.project_path,relative_assets(self.project_for_save(),self.project_path.parent))
        self.dirty = False
        self.undo.clear()
        if hasattr(self, 'redo'): self.redo.clear()
        if hasattr(self,'recording_history'):self.recording_history.clear();self.reset_recording_take()
        self.message = 'PROJECT SAVED'

    def adjust_tempo(self, delta):
        increment=1 if self.shift or self.encoder_held else 100
        cents=max(4000,min(24000,round(self.project['tempo']*100)+delta*increment))
        value=cents/100
        if value!=self.project['tempo']:
            self.remember();self.project['tempo']=value;self.dirty=True

    def set_audio_rate(self, rate):
        if self.capture_started is not None or self.capture_armed:
            self.message='STOP RECORDING FIRST';return
        if rate==self.settings['sample_rate']:return
        self.settings['sample_rate']=rate
        save_json(self.settings_path,self.settings)
        self.actions.append(('audio_rate',rate))
        self.message=f'{rate} HZ'

    def refresh_devices(self, audio, midi):
        old = self.audio
        self.audio_devices, self.midi_devices = audio, midi
        self.audio = choose_audio(audio, self.settings['audio'], old.key if old else None)
        if self.audio != old:
            self.actions.append(('audio', self.audio))
            self.actions.append(('codec_levels',None))
            self.message = 'AUDIO CONNECTED' if self.audio else 'NO AUDIO DEVICE'

    def entries(self):
        return self.browser.entries()

    @property
    def browser_dir(self):
        return self.browser.directory

    @browser_dir.setter
    def browser_dir(self, value):
        self.browser.directory = value

    @property
    def browser_index(self):
        return self.browser.index

    @browser_index.setter
    def browser_index(self, value):
        self.browser.index = value

    def defer_browser_preview(self,now=None):
        if self.browser_preview_active:
            self.actions.append(('preview_stop',None))
            self.browser_preview_active=False
        self.browser_preview_pending=(
            (time.monotonic() if now is None else now)+0.5,
            self.browser.directory,self.browser.index)

    def browser_preview_tick(self,now):
        pending=self.browser_preview_pending
        if pending is None:return
        deadline,directory,index=pending
        if (self.page!='BROWSE' or not self.browser.prehear
                or (directory,index)!=(self.browser.directory,self.browser.index)):
            self.browser_preview_pending=None
        elif now>=deadline:
            self.browser_preview_pending=None
            self.preview_selected()

    def browser_preview_path(self):
        path = self.browser.selected()
        if path and not self.browser.expansion_samples and self.browser.kit_source(path):
            if path.name == 'Preset.json':
                candidate = path.parent.parent/'.preview.wav'
            else:
                candidate = path/'.preview.wav'
            if candidate.is_file() and not candidate.is_symlink():
                path = candidate
        return path

    def preview_selected(self):
        path=self.browser_preview_path()
        if path and (path.name=='Preset.json' or path.suffix.lower()=='.sound'):
            self.actions.append(('preview_stop',None));self.message='LOAD SOUND TO AUDITION';return
        if path and path.is_file():
            if self.audio:
                self.browser_preview_active=True
                self.actions.append(('preview', path))
            else:
                self.message = 'NO AUDIO DEVICE'
        else:self.actions.append(('preview_stop',None))

    def quick_browse_sample(self):
        track = self.track()
        items = zones(track)
        sample = items[min(self.zone_index, len(items)-1)].get('sample') if items else track.get('sample')
        from app.audio_import import browse_origin
        sample=browse_origin(sample,self.root/'cache')
        # Include newly created internal asset folders without disturbing USB roots.
        external = [source for source in self.browser.sources
                    if source.path != self.samples and source not in self.browser.internal_sources]
        self.browser.refresh(external)
        error = self.browser.locate(sample)
        self.message = error or 'SAMPLE FOUND'
        if not error:
            self.actions.append(('preview_stop', None))
            if self.browser.prehear:
                self.preview_selected()

    def track(self):
        return self.project['groups'][self.group]['pads'][self.pad]

    def lane(self):
        lane = self.project['groups'][self.group]['patterns'][self.pattern][self.pad]
        self.bank = min(self.bank, (self.step_cell_count()-1)//16)
        self.event_step = min(self.event_step, len(lane)-1)
        return lane

    def button(self, name, pressed):
        if pressed and time.monotonic()<getattr(self,'update_lock_until',0):return
        if name == 'SHIFT':
            self.shift = pressed
            if not pressed:self.finish_modulation_take()
        if pressed and name != 'SHIFT':
            self.message = ''
        # TAP is a transport gesture and must precede workspace handlers.
        if name=='TAP' or name=='ENTER' and self.shift:
            if pressed:self.tap_tempo()
            return
        if self.surface_button(name, pressed):
            return
        if name == 'ENCODER PUSH':
            self.encoder_held = pressed
            if self.page in ('SAMPLING', 'SAMPLE EDIT'):
                return
        if name == 'SHIFT':
            self.shift = pressed
            return
        if not pressed:
            return
        self.message = ''
        if not (self.shift and name in ('SAMPLING', 'ENTER', 'NOTE REPEAT')) and self.workspace_button(name):
            return
        if self.shift and name == 'NOTE REPEAT':
            self.page = 'STEP'
        elif name == 'MAIN':
            self.open_main_controls()
        elif name in PAGES:
            close_mode = ((name == 'BROWSE' and self.page == 'BROWSE') or
                          (name == 'SAMPLING' and self.page in ('SAMPLING', 'SAMPLE EDIT', 'CHOP', 'PROCESS', 'SAMPLING NAV', 'SAMPLE DELETE', 'ZONE', 'SLICE TARGET', 'AUTOSAMPLER')))
            self.page = self.control_home() if close_mode else PAGES[name]
            if name == 'BROWSE':
                if self.page=='BROWSE' and not self.browser.started:
                    self.browser_dir,self.browser_index=None,0;self.browser.started=True
                elif close_mode:self.actions.append(('preview_stop',None))
            if self.page == 'PATTERN' and self.shift:
                self.page = 'STEP'
        elif name == 'PLAY':
            self.playing = not self.playing
            if self.playing and self.clip_transport:
                from app.clip_arranger import length
                if self.clock_phase>=length(self.project):
                    self.clock_phase=-1;self.step=-1;self.native_arranger_seek=0
            if not self.playing:
                self.recording = False
                self.actions.append(('panic', None))
        elif name == 'REC':
            self.recording = not self.recording
        elif name == 'GRID':
            self.page = 'TEMPO'
        elif name == 'RESTART':
            self.step = -1
            self.clock_phase=-1
            self.actions.append(('restart', None))
        elif name in ('ENTER', 'ENCODER PUSH'):
            self.enter()
        elif name == 'F1':
            if self.page=='AUDIO RATE':self.set_audio_rate(44100)
            elif self.page in DISPLAY_PAGES:
                reset_display(self)
            elif self.page == 'SETTINGS':
                self.menu = 0
            elif self.page == 'BROWSE':
                self.browser.up();self.browser_preview_pending=None;self.browser_preview_active=False;self.actions.append(('preview_stop',None))
            elif self.page in ('SAMPLING', 'SAMPLE EDIT'):
                self.sample_field = (self.sample_field+1) % 2
            else:
                self.save()
        elif name == 'F2':
            if self.page=='AUDIO RATE':self.set_audio_rate(48000)
            elif self.page == 'SETTINGS':
                self.menu = 1
            elif self.page == 'PATTERN':
                self.page = 'STEP'
            elif self.page == 'PAD':
                self.page = 'STEP'
            elif self.page == 'BROWSE':
                self.enter()
            elif self.page in ('SAMPLING', 'SAMPLE EDIT'):
                if self.audio and self.audio.capture:
                    self.actions.append(('capture', self.audio.capture))
                else:
                    self.message = 'NO AUDIO INPUT'
            else:
                self.message = 'NO ACTION HERE'
        elif name == 'F3':
            if self.page in ('BRIGHTNESS', 'CONTRAST','AUDIO RATE'):
                self.page = 'SETTINGS'
            elif self.page == 'SETTINGS':
                self.menu = 2
            elif self.page in ('SAMPLING', 'SAMPLE EDIT'):
                self.actions.append(('capture_stop', None))
            elif self.page == 'BROWSE':
                self.browser.prehear = not self.browser.prehear
                if self.browser.prehear:
                    self.preview_selected()
                else:
                    self.browser_preview_pending=None;self.browser_preview_active=False
                    self.actions.append(('preview_stop', None))
            elif self.page == 'PAD':
                self.page = 'BROWSE'
            else:
                self.page = self.control_home()
        elif name in ('NAV LEFT', 'NAV RIGHT'):
            delta = -1 if 'LEFT' in name else 1
            if self.page in ('SAMPLING', 'SAMPLE EDIT') and name.startswith('NAV '):
                self.sample_field = max(0, min(1, self.sample_field+delta))
            else:
                self.rotate(delta)
        elif name == 'DUPLICATE':
            self.remember()
            destination = (self.pattern+1) % 16
            patterns = self.project['groups'][self.group]['patterns']
            patterns[destination] = copy.deepcopy(patterns[self.pattern])
            events = self.project['groups'][self.group]['events']
            copied = {f'{destination}:{key.split(":", 1)[1]}': copy.deepcopy(value)
                      for key, value in events.items() if key.startswith(f'{self.pattern}:')}
            for key in list(events):
                if key.startswith(f'{destination}:'):
                    del events[key]
            events.update(copied)
            self.pattern = destination
            self.active_patterns[self.group] = destination
            self.message = 'PATTERN COPIED'
        elif name == 'ERASE':
            self.message = 'SHIFT+ERASE THEN PAD: RESET' if self.shift else 'HOLD ERASE + PAD'

    def rotate_single(self,delta):
        descriptor=self.automation_descriptor();before=self.automation_value(descriptor) if descriptor else None
        old_capture=getattr(self,'automation_capture',None)
        if self.page=='LIVE FX' and self.playing and self.recording:self.automation_capture=True
        self.modulation_rotating=bool(descriptor and (descriptor[0]!=MASTER or self.song_playing) and self.playing and getattr(self,'automation_capture',self.shift) and not self.count_remaining)
        try:self._rotate(delta)
        finally:self.modulation_rotating=False
        if descriptor:
            after=self.automation_value(descriptor)
            if before!=after:self.midi_last_touched=(self.project_generation,descriptor)
            self.capture_automation(descriptor,before,after)
        if self.page=='LIVE FX' and self.playing and self.recording:
            if old_capture is None:
                try:del self.automation_capture
                except AttributeError:pass
            else:self.automation_capture=old_capture

    def _rotate(self, delta):
        if self.recording_rotate(delta):return
        self.message = ''
        if self.midi_remote_rotate(delta) or self.settings_rotate(delta):return
        if self.page=='CLIP ARRANGER':self.arranger_rotate(self.arranger_field,delta);return
        if self.page=='CLIP MENU':
            from app.clip_arranger import MENU
            self.arranger_menu=max(0,min(len(MENU)-1,self.arranger_menu+delta));return
        if self.surface_rotate(delta) or self.workspace_rotate(delta):
            return
        if self.page == 'SETTINGS':
            self.menu = (self.menu+delta) % len(SETTING_PAGES)
        elif self.page=='AUDIO BUFFER':
            if self.capture_started is not None or self.capture_armed:
                self.message='STOP RECORDING FIRST';return
            values=AUDIO_BUFFERS;current=self.settings['audio_buffer']
            value=values[max(0,min(len(values)-1,values.index(current)+delta))]
            if value!=current:
                self.settings['audio_buffer']=value;save_json(self.settings_path,self.settings)
                self.actions.append(('audio_buffer',value));self.audio_status={}
        elif self.page=='AUDIO RATE':
            if delta:self.set_audio_rate(44100 if delta<0 else 48000)
        elif self.page in ('AUDIO', 'MIDI IN', 'MIDI OUT'):
            key = {'AUDIO': 'audio', 'MIDI IN': 'midi_in', 'MIDI OUT': 'midi_out'}[self.page]
            options = ['AUTO']+[d.key for d in self.audio_devices] if key == 'audio' else ['OFF']+[d.key for d in self.midi_devices]
            current = self.settings[key]
            index = options.index(current) if current in options else 0
            self.settings[key] = options[(index+delta) % len(options)]
            save_json(self.settings_path, self.settings)
            self.refresh_devices(self.audio_devices, self.midi_devices)
        elif self.page in DISPLAY_PAGES:
            change_display(self,delta)
        elif self.page == 'MIDI CHANNEL':
            self.settings['midi_channel'] = max(1, min(16, self.settings['midi_channel']+delta))
            save_json(self.settings_path, self.settings)
        elif self.page == 'TEMPO':
            self.adjust_tempo(delta)
        elif self.page == 'BROWSE':
            previous=self.browser_index
            self.browser_index = max(0, min(max(0, len(self.entries())-1), self.browser_index+delta))
            if self.browser.prehear and self.browser_index!=previous:
                selected=self.browser.selected()
                if selected is not None and not self.browser.expansion_samples and self.browser.kit_source(selected):
                    self.defer_browser_preview()
                else:
                    self.browser_preview_pending=None
                    self.preview_selected()
        elif self.page in ('SAMPLE EDIT','SAMPLER'):
            track = self.track()
            if track['sample']:
                with wave.open(track['sample'], 'rb') as wav:
                    frames = wav.getnframes()
                self.remember()
                field = ('selection_start' if self.sample_field == 0 else 'selection_end') if self.range_page and self.page=='SAMPLE EDIT' else ('start' if self.sample_field == 0 else 'end')
                if self.range_page and self.page=='SAMPLE EDIT':
                    track.setdefault('selection_start', track['start'])
                    track.setdefault('selection_end', track['end'])
                view_start, view_end = self.wave_bounds(frames)
                visible_frames = view_end-view_start
                # One visible pixel for fine adjustment, four for normal turning.
                increment = max(1, visible_frames//(120 if self.encoder_held or self.shift else 30))
                track[field] = max(0, min(frames, track[field]+delta*increment))
                if self.range_page and self.page=='SAMPLE EDIT':
                    track['selection_start'] = min(track['selection_start'], track['selection_end'])
                else:
                    if field=='start':track['start']=min(track['start'],track['end']-1)
                    else:track['end']=max(track['start']+1,track['end'])
                    track['selection_start'], track['selection_end'] = track['start'], track['end']
                if track.get('zones') and not self.range_page:
                    z=track['zones'][min(self.zone_index,len(track['zones'])-1)];z.update(start=track['start'],end=track['end'],loop_start=track['start'],loop_end=track['end']);z['xfade']=min(z.get('xfade',0),track['end']-track['start'])
                self.actions.append(('load', (self.group, self.pad, copy.deepcopy(track))))
        elif self.page == 'MIXER':
            self.remember()
            self.track()['gain'] = max(0, min(100, self.track()['gain']+delta))
        elif self.page == 'GROUP':
            self.group = (self.group+delta) % len(self.project['groups']);self.group_bank=self.group//8;self.keyboard_root=0 if self.slice_keyboard() else self.performance()['root']
            self.pattern = self.active_patterns[self.group]
        else:
            self.pad = (self.pad+delta) % 16

    def enter(self):
        if self.page == 'SETTINGS':
            self.open_setting()
        elif self.page in SETTING_PAGES:
            self.page = 'SETTINGS'
        elif self.page == 'BROWSE':
            if self.browser.selected() is None:
                self.message = 'EMPTY FOLDER'
                return
            self.browser.started=True;self.browser_preview_pending=None;self.browser_preview_active=False;self.actions.append(('preview_stop',None))
            path = self.browser.open()
            if path is not None:
                if path.name=='Preset.json' or path.suffix.lower()=='.sound':
                    kind='GROUP' if self.browser.kit_source(path) else 'SOUND'
                    self.request_preset_load(path,kind,self.group,self.pad);return
                if path.suffix.lower()=='.mp3':
                    self.mp3_serial+=1;slot=(self.group,self.pad);self.mp3_requests[slot]=self.mp3_serial
                    context=dict(generation=self.project_generation,group=self.group,pad=self.pad,serial=self.mp3_serial,
                                 zone=self.zone_browse,expected=copy.deepcopy(self.track()))
                    self.actions.append(('import_mp3',(path,context)));self.message='DECODING MP3'
                else:
                    self.mp3_requests.pop((self.group,self.pad),None)
                    self.assign_browser_sample(path)

        else:
            self.page = self.control_home()

    def assign_browser_sample(self,path,group=None,pad=None,zone=None,prepared=None):
        group=self.group if group is None else group;pad=self.pad if pad is None else pad
        zone=self.zone_browse if zone is None else zone;track=self.project['groups'][group]['pads'][pad]
        with wave.open(str(path),'rb') as wav:
            if wav.getsampwidth() not in (1,2,3,4) or wav.getnchannels() not in (1,2):raise ValueError('WAV must be mono/stereo PCM')
            frames=wav.getnframes()
        self.remember()
        if track.get('routing',{}).get('midi_target','NONE')!='NONE':track['routing']['midi_target']='NONE'
        assigned=dict(track,sample=str(Path(path).resolve()),start=0,end=frames)
        if zone:
            track['zones']=list(zones(track))+[default_zone(assigned)]
            if (group,pad)==(self.group,self.pad):
                self.zone_index=len(track['zones'])-1;self.zone_browse=False;self.page='ZONE';self.sync_zone()
        else:
            track.update(sample=str(Path(path).resolve()),start=0,end=frames,zones=[default_zone(assigned)])
            for key in ('slices','slice_source','slice_mode','slice_committed','slice_manual'):track.pop(key,None)
        loaded=copy.deepcopy(track)
        if prepared:loaded['_ready_pcm']=prepared
        self.actions.append(('load',(group,pad,loaded)));self.message='SAMPLE ASSIGNED'

    def finish_mp3_import(self,context,result):
        slot=(context['group'],context['pad'])
        if context['generation']!=self.project_generation or self.mp3_requests.get(slot)!=context['serial']:return False
        self.mp3_requests.pop(slot,None)
        if self.project['groups'][slot[0]]['pads'][slot[1]]!=context['expected']:
            self.message='IMPORT CANCELLED: SOUND CHANGED';return False
        self.assign_browser_sample(result['sample'],*slot,zone=context['zone'],prepared=result['_ready_pcm'])
        return True

    def pad_on(self,slot,velocity=100,owner=None):
        if time.monotonic()<getattr(self,'update_lock_until',0):return
        start=len(self.actions);self.last_recorded=None;self.recorded_press=[]
        self._pad_on(slot,velocity,owner)
        bindings=[];step_inputs=set()
        for action,value in self.actions[start:]:
            if action in ('hit','event_hit'):
                group,pad=value[:2];note=value[3] if action=='event_hit' else self.project['groups'][group]['pads'][pad].get('note',36+pad);bindings.append((group,pad,note))
                if (group,pad) not in step_inputs:self.remember_step_input(group,pad,note if action=='event_hit' else None);step_inputs.add((group,pad))
            elif action in ('midi_note','chord_note'):
                bindings.append((self.group,self.pad,value[0]))
                # A chord chooses its played root, not its final harmony voice.
                if (self.group,self.pad) not in step_inputs:self.remember_step_input(self.group,self.pad,value[0]);step_inputs.add((self.group,self.pad))
        if bindings:self.live_notes[slot if owner is None else (owner,slot)]=(bindings,self.recorded_press,getattr(self,'input_timestamp',None) or time.monotonic())
        self.recorded_press=None

    def _pad_on(self, slot, velocity=100, owner=None):
        self.held_pads.add(slot)
        self.message = ''
        self.flash_until[slot] = time.monotonic()+0.12
        if self.fixed_velocity and self.page != 'LIVE FX':
            velocity = self.velocity_value
        if self.page in SETTINGS_VIEWS and not self.main_controls_active():
            # Hardware-level audition is live only, even with PLAY + REC armed.
            if 'SELECT' in self.held_buttons:
                self.select_sound(slot);return
            if self.velocities16:
                self.actions.append(('hit',(self.group,self.pad,round(127*(slot+1)/16))))
            elif self.keyboard_enabled:
                notes=self.performance_notes(slot)
                if self.keyboard_chord_mode()=='CUSTOM':
                    for delay,note,level in self.chord_plan(notes,velocity):self.actions.append(('chord_note',(note,level,self.track()['channel'],delay)))
                else:
                    for note in notes:self.actions.append(('midi_note',(note,velocity,self.track()['channel'])))
                self.performance_lights.update(notes)
            else:
                self.select_sound(slot)
                self.actions.append(('hit',(self.group,slot,velocity)))
            return
        if self.surface_pad(slot, velocity, owner):
            return
        if self.page=='PLUGIN' and not self.shift and not self.held_buttons and self.control_level==1 and self.plugin_slot==0:
            from app.virtualjv_multi import URI,internal_destination,rack
            group=self.project['groups'][self.group]
            selected=self.plugin_selected()
            multi=rack(group)
            track=group['pads'][slot]
            destination=internal_destination(track)
            if selected is multi and multi and selected.get('uri')==URI and destination and destination[0]==GROUP_BASE+self.group:
                channel=track.get('channel',1)
                part=next((index for index in range(8) if round(multi.get('controls',{}).get(f'p{index+1}_channel',10 if index==7 else index+1))==channel),None)
                if part is not None:
                    self.select_sound(slot)
                    if round(multi.get('controls',{}).get('editor_part',0))!=part:
                        multi.setdefault('controls',{})['editor_part']=part
                        self.plugin_param=0
                        self.actions.append(('plugin_controls',(GROUP_BASE+self.group,copy.deepcopy(group['plugins']))))
                    self.actions.append(('hit',(self.group,slot,velocity)))
                    return
        if self.page == 'STEP':
            cell=self.bank*16+slot
            if cell<self.step_cell_count():
                notes=self.notes_in_cell(self.pad,cell);self.remember_recording_note()
                meta=self.recording_history.setdefault(id(self.recording_undo),{'changes':[],'position':0});first=meta['position']
                if notes:
                    for (row,tick),event in notes.items():
                        self.remove_note(row,tick);self.recording_change((self.group,self.pattern,row,tick),event,None)
                else:
                    tick=cell*self.grid_ticks();event={'velocity':velocity,'probability':100,'length':self.grid_ticks()}
                    note=self.step_input_note()
                    if note is not None:event['note']=note
                    self.put_note(self.pad,tick,event);self.recording_change((self.group,self.pattern,self.pad,tick),None,event)
                added=meta['changes'][first:]
                if len(added)>1:meta['changes'][first:]=[{'bundle':added}];meta['position']=len(meta['changes'])
                self.event_step=min(len(self.lane())-1,cell*self.grid_ticks()//24)
        elif self.page == 'CHOP':
            if slot < self.slice_count:
                self.slice_index = slot
                self.actions.append(('slice_preview', (copy.deepcopy(self.track()), slot, self.slice_count)))
        elif self.page in ('KEYBOARD', 'CHORD'):
            note = min(127, self.keyboard_root+slot)
            intervals = (0,) if self.chord == 0 else (0, 4, 7) if self.chord == 1 else (0, 3, 7)
            self.record_pad_note(self.pad,velocity,note)
            for interval in intervals:
                self.actions.append(('midi_note', (min(127, note+interval), velocity, self.track()['channel'])))
        elif self.page == 'ARP':
            self.arp_notes.add(min(127, self.keyboard_root+slot))
        elif self.page == 'EVENT':
            self.event_step = min(len(self.lane())-1, self.bank*16+slot)
        elif self.page == 'GROUP':
            slots = [12, 13, 14, 15, 8, 9, 10, 11]
            if slot in slots:
                self.group = self.group_bank*8+slots.index(slot);self.keyboard_root=0 if self.slice_keyboard() else self.performance()['root']
                self.pattern = self.active_patterns[self.group]
        elif self.page == 'PATTERN':
            self.arranger_stop_mode()
            slot+=self.pattern_bank*16
            self.pattern = slot
            created=self.project['groups'][self.group]['pattern_created']
            if slot not in created:created.append(slot)
            self.active_patterns[self.group] = slot
            self.remember()
            self.project['scenes'][self.scene][self.group] = slot
            self.active_clips[self.group]=True
            self.message = 'SCENE PATTERN SET'
        elif self.page == 'SCENE':
            self.select_scene(slot)
        elif self.page in ('MUTE', 'SOLO'):
            self.remember()
            field = self.page.lower()
            track = self.project['groups'][self.group]['pads'][slot]
            track[field] = not track[field]
        else:
            self.select_sound(slot)
            if self.page in ('PAD', 'MIXER')+PARAMETER_PLAY_PAGES:
                self.record_pad_note(slot,velocity)
                self.actions.append(('hit', (self.group, slot, velocity)))

    def tick(self,emit=True):
        if not self.playing:
            return
        longest=self.scene_steps();song_advanced=False
        if self.step >= 0 and (self.step+1) % longest == 0:
            if self.loop_range is not None and not self.song_playing and self.pending_scene is None:
                first,last=self.loop_range
                self.pending_scene=self.scene+1 if first<=self.scene<last else first
            if self.song_playing:
                self.song_bar += 1;song_advanced=True
                if self.song_bar >= len(self.project['song']):
                    self.song_playing = self.playing = False
                    self.actions.append(('panic', None))
                    return
                self.pending_scene = self.project['song'][self.song_bar]
            if self.pending_scene is not None and self.settings['perform_grid']=='SCENE':
                self.activate_scene(self.pending_scene)
                self.pending_scene = None
                self.step = -1
                self.native_transport_revision=getattr(self,'native_transport_revision',0)+1
        self.step=self.step+1 if getattr(self,'native_sequence',False) else (self.step+1)%4096
        if song_advanced:self.song_phase_origin=self.step*24
        self.follow_step_view(self.step*24)
        if not emit:return
        group_solo = any(g.get('solo',False) for g in self.project['groups'])
        for group_index, group in enumerate(self.project['groups']):
            if not self.active_clips[group_index]:continue
            if group.get('mute',False) or (group_solo and not group.get('solo',False)):
                continue
            any_solo = any(p['solo'] for p in group['pads'])
            for slot, lane in enumerate(group['patterns'][self.active_patterns[group_index]]):
                track = group['pads'][slot]
                if is_audio_sound(track):continue
                index=self.step%self.pattern_steps(group_index,self.active_patterns[group_index])
                event = group['events'].get(f'{self.active_patterns[group_index]}:{slot}:{index}', {'velocity': 100, 'probability': 100})
                if lane[index] and not track['mute'] and (not any_solo or track['solo']):
                    for voice in [{k:v for k,v in event.items() if k!='poly'},*event.get('poly',{}).values()]:
                        if random.randrange(100)<voice['probability']:
                            action=('event_hit',(group_index,slot,voice['velocity'],voice['note'])) if 'note' in voice else ('hit',(group_index,slot,voice['velocity']))
                            self.actions.append(action)

    def display(self):
        if self.page=='UPDATE':
            from app.updater import display
            return display(self)
        if self.page in ('AUDIO LOOP','BOUNCE TO PAD'):
            from app.fokus_data import utility_data
            return utility_data(self)
        if self.page=='SCENE OPTIONS':
            from app.fokus_data import listing
            return listing('SCENE OPTIONS',self.scene_options(),self.scene_options_index,'ENCODER SELECT')
        if self.page=='BLUETOOTH MIDI':
            from app.bluetooth_midi import display
            return display(self)
        if self.page=='SAMPLE RAM':
            memory=self.sample_memory
            if not memory:return 'SAMPLE RAM',['READING MEMORY...','',''],'PURGE UNUSED ONLY'
            return 'SAMPLE RAM',[f"USED {memory.get('bytes',0)/1048576:.1f} MB",f"FREEABLE {memory.get('reclaimable_bytes',0)/1048576:.1f} MB",f"LIMIT {memory.get('limit',536870912)/1048576:.0f} MB"],'PURGE UNUSED ONLY'
        remote=self.midi_remote_display()
        if remote is not None:return remote
        workspace = self.workspace_display()
        if workspace is not None:
            return workspace
        header = f'{self.page}  {self.group_name()}:{self.pad+1:02}'
        if self.page == 'SETTINGS':
            header = self.settings_title()
            entries = self.setting_entries()
            first = max(0, min(self.menu-1, len(entries)-3))
            body = [('>' if i == self.menu else ' ')+SETTINGS_LABELS.get(entries[i], entries[i]) for i in range(first, min(first+3, len(entries)))]
            footer = 'ENC SELECT ENTER OPEN'
        elif self.page=='INTERFACE MIXER':
            from app.interface_mixer import value_text,db_text
            control=self.interface_control()
            if control:
                header=control['name']
                body=[control['direction'].upper()+(' SWITCH' if control['kind']=='switch' else ' LEVEL'),value_text(control),db_text(control)]
            else:body=[self.interface_mixer_error or ('READING MIXER...' if self.audio else 'NO AUDIO DEVICE'),'NO MIXER CONTROLS' if self.audio and not self.interface_mixer_error else '','']
            footer='ARROWS SELECT ENC LEVEL'
        elif self.page in ('MAIN OUTPUT','CUE OUTPUT','CUE LEVEL'):
            from app.audio_ports import port
            key={'MAIN OUTPUT':'main_output','CUE OUTPUT':'cue_output','CUE LEVEL':'cue_level'}[self.page]
            value=self.settings[key];physical=port(value,'OUT') if key!='cue_level' else None
            unavailable=physical and (not self.audio or max(physical)>=self.audio.output_channels)
            body=[str(value)+('%' if key=='cue_level' else ''),'UNAVAILABLE' if unavailable else 'ENC CHANGE','PREH / CLICK' if key=='cue_output' else '']
            footer='ENTER BACK'
        elif self.page in ('HEADPHONE MUTE','SPEAKER MUTE'):
            from app.codec_levels import MUTES,supported
            key,_=MUTES[self.page]
            body=['ON' if self.settings[key] else 'OFF','LEVEL RETAINED','ULTRA HAT' if supported(self.audio) else 'ULTRA HAT ONLY'];footer='ENC CHANGE / ENTER BACK'
        elif self.page in ('HEADPHONE LEVEL','SPEAKER LEVEL','INPUT GAIN'):
            from app.codec_levels import CONTROLS, caption, supported
            key,_,_,_=CONTROLS[self.page]
            body=[caption(self.page,self.settings[key])+(' MUTED' if self.settings.get(key+'_mute',False) else ''),'ULTRA HAT' if supported(self.audio) else 'ULTRA HAT ONLY','ENC HARDWARE LEVEL' if supported(self.audio) else 'NOT AVAILABLE']
            footer='ENTER BACK'
        elif self.page=='PLUGIN DELAY':
            frames=self.pdc_status.get('frames',0);rate=self.pdc_status.get('rate',self.settings['sample_rate'])
            status=self.pdc_status.get('status',0)
            body=['ON' if self.settings['plugin_delay'] else 'OFF',f'{frames} FR {frames/rate*1000:.1f} MS', {0:'FASTER PATHS DELAYED',1:'LIMIT: NO COMPENSATION',2:'UNSUPPORTED ROUTING',3:'LOW LATENCY'}.get(status,'')]
            footer='ENC CHANGE ENTER BACK'
        elif self.page=='AUDIO BUFFER':
            value=self.settings['audio_buffer'];actual=self.audio_status.get('buffer');rate=self.settings['sample_rate']
            body=['AUTO' if not value else f'{value} FRAMES', f'ACTIVE {actual}' if actual else 'NO ACTIVE BUFFER', f'{actual/rate*1000:.1f} MS QUEUE' if actual else 'ENC CHANGE']
            footer='ENTER BACK'
        elif self.page=='PLUGIN SC':
            body=['SIDECHAIN SOURCE',(self.plugin_selected() or {}).get('sidechain','NONE'),'ENC SELECT'];footer='F1 BACK'
        elif self.page=='AUDIO RATE':
            body=[f'{self.settings["sample_rate"]} HZ','MATCH DEVICE RATE','44100 / 48000 HZ']
            footer='ENC RATE ENTER BACK'
        elif self.page == 'AUDIO':
            preferred = self.settings['audio']
            name = next((d.name for d in self.audio_devices if d.key == preferred), 'AUTO USB/HAT' if preferred == 'AUTO' else 'DEVICE MISSING')
            body = [name, self.audio.name if self.audio else 'NO AUDIO DEVICE', f'{self.settings["sample_rate"]} HZ {self.audio.output_channels if self.audio else 0} OUT']
            footer = 'ENC DEVICE ENTER BACK'
        elif self.page in ('MIDI IN', 'MIDI OUT'):
            key = 'midi_in' if self.page == 'MIDI IN' else 'midi_out'
            name = next((d.name for d in self.midi_devices if d.key == self.settings[key]), 'OFF' if self.settings[key] == 'OFF' else 'DEVICE MISSING')
            body, footer = [name, f'CHANNEL {self.settings["midi_channel"]}'], 'ENC PORT ENTER BACK'
        elif self.page=='COLOR SCHEME':
            from app.mk3_theme import LABELS
            body=[LABELS.get(display_value(self),'Current'),'THIS CONTROLLER ONLY','SHIFT F1 RESET'];footer='ENTER BACK'
        elif self.page in DISPLAY_PAGES:
            value = display_value(self)
            body, footer = [('ON' if value else 'OFF') if self.page=='INVERT' else f'{value}%', (getattr(self,'controller_source','mk2').upper()+' '+('RIGHT' if self.page=='CONTRAST R' else 'BOTH' if self.page=='BRIGHTNESS' else 'BOTH' if self.page=='INVERT' else 'LEFT')) if is_mk2(self) else 'MIKRO ONLY', 'SHIFT F1 RESET'], 'ENTER BACK'
        elif self.page in ('MIDI CHANNEL', 'TEMPO'):
            body = [str(self.settings['midi_channel']) if self.page == 'MIDI CHANNEL' else f'{self.project["tempo"]:.2f} BPM']
            footer = 'ENC CHANGE ENTER BACK'
        elif self.page=='CLIP ARRANGER':
            rows=self.arranger_rows();label,value=rows[self.arranger_field];body=[label,value,'ARROWS: FIELD'];footer='ENC CHANGE / PUSH EDIT'
        elif self.page=='CLIP MENU':
            from app.clip_arranger import MENU
            body=[MENU[self.arranger_menu],'SELECT ACTION'];footer='ENTER SELECT'
        elif self.page == 'BROWSE':
            entries = self.entries()
            self.browser_index = min(self.browser_index, max(0, len(entries)-1))
            header = f'{self.browser.title()} {self.group_name()}:{self.pad+1:02}'
            first = max(0, self.browser_index-1)
            body = [('>' if i == self.browser_index else ' ')+self.browser.label(entries[i])
                    for i in range(first, min(first+3, len(entries)))] or ['EMPTY FOLDER']
            footer = self.browser.error or f'{self.browser_index+1 if entries else 0}/{len(entries)} ENTER OPEN LOAD'
        elif self.page == 'SAMPLE EDIT':
            track = self.track()
            if self.capture_started is not None:
                seconds = int(time.monotonic()-self.capture_started)
                body = ['RECORDING', f'{seconds//60:02}:{seconds%60:02}', 'F3 TO STOP AND ASSIGN']
            else:
                body = [Path(track['sample']).name if track['sample'] else 'NO SAMPLE',
                        f'{">" if self.sample_field == 0 else " "}START {track["start"]}',
                        f'{">" if self.sample_field == 1 else " "}END {track["end"]}']
            footer = 'F1 TRIM F2 REC F3 STOP'
        elif self.page == 'STEP':
            lane = self.lane()
            body = [''.join('X' if s else '-' for s in lane), f'STEP {self.step+1}', 'PADS TOGGLE STEPS']
            footer = 'F1 SAVE F3 PAD'
        elif self.page == 'PATTERN':
            body, footer = [f'PATTERN {self.pattern+1}', 'PADS SELECT', 'DUPLICATE TO COPY'], 'F2 STEP F1 SAVE'
        elif self.page == 'SCENE':
            body, footer = [f'SCENE {self.scene+1}', 'PADS SELECT SCENE'], 'F1 SAVE F3 PAD'
        elif self.page == 'GROUP':
            body, footer = [f'GROUP {self.group_name()}', 'PADS 13 TO 16 A TO D', 'PADS 9 TO 12 E TO H'], 'F1 SAVE F3 PAD'
        else:
            track = self.track()
            body = [Path(track['sample']).name if track['sample'] else 'NO SAMPLE',
                    f'GAIN {track["gain"]} M{int(track["mute"])} S{int(track["solo"])}',
                    f'{"PLAY" if self.playing else "STOP"} {self.project["tempo"]} BPM']
            footer = 'F1 SAVE MAIN SETTINGS'
        if self.message:
            footer = self.message
        return header, body, footer

    def softkeys(self):
        if self.page=='CLIP ARRANGER':return ('COPY','DELETE','SCENES') if self.shift else ('MENU','PLAY','BACK')
        if self.page=='CLIP MENU':return ('BACK','SELECT','BACK')
        if self.page=='SONG' and self.shift:return ('INSERT','CLIPS','AUTO')
        if self.page=='UPDATE':return ('BETA' if self.update_status.get('channel')=='beta' else 'REL','APPLY' if self.update_status.get('available') else 'CHECK','BACK')
        if self.page=='SCENE OPTIONS':return ('BACK','SELECT','')
        if self.page=='LIVE FX':return ('PUNCH','FLEX','KNOB')
        if self.page=='SAMPLE RAM':return ('BACK','REFRESH','PURGE')
        if self.page=='MIDI LEARN':return ('BACK','LEARN','REMOVE')
        if self.page=='SONG AUTO':return ('BACK','ON/OFF','REMOVE')
        if self.main_controls_active():return ('VOLUME','SWING','TEMPO')
        if self.page=='BLUETOOTH MIDI':return ('ON/OFF','PAIR' if self.shift else 'SCAN','BACK')
        from app.codec_levels import dac_context
        if dac_context(self):return ('HP MUTE','SP MUTE','BACK')
        if self.page in SETTINGS_VIEWS:
            return ('AUDIO', 'MIDI', 'SYSTEM')
        original = self.surface_softkeys()
        if original is not None:
            return original
        workspace = self.workspace_softkeys()
        if workspace is not None:
            return workspace
        if self.page in DISPLAY_PAGES:
            return ('RESET', '-', 'BACK')
        return {'SETTINGS': ('AUDIO', 'MIDI IN', 'MIDI OUT'),
                'BROWSE': ('UP', 'OPEN', 'PREH ON' if self.browser.prehear else 'PREH'),
                'SAMPLING': ('FIELD', 'REC', 'STOP'),
                'PAD': ('SAVE', 'STEP', 'BROWSE'),
                'PATTERN': ('SAVE', 'STEP', 'PAD')}.get(self.page, ('SAVE', '-', 'PAD'))
