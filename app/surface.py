import time
"""Mikro manual workflows adapted to MK1 controls and our sample/MIDI backend."""
import copy
from pathlib import Path
from app.storage import save_json

TEMPORARY = {'SCENE': 'SCENE', 'PATTERN': 'PATTERN', 'PAD MODE': 'PAD CONFIG',
             'VIEW': 'MIXER', 'SELECT': 'SELECT', 'MUTE': 'MUTE', 'SOLO': 'SOLO',
             'GRID': 'OPTIONS', 'NOTE REPEAT': 'NOTE REPEAT', 'DUPLICATE': 'DUPLICATE', 'EVENTS': 'PATTERN GRID'}
PROCESSING = ('TRUNCATE', 'NORMALIZE', 'REVERSE', 'FADE IN', 'FADE OUT', 'FIX DC', 'SILENCE', 'CUT','COPY','PASTE','DUPLICATE','STRETCH','STEM SEPARATION')


class OriginalSurface:
    def init_surface(self):
        self.held_buttons = set()
        self.held_pads = set()
        self.mode_origins = {}
        self.pinned_modes = set(self.settings.get('pinned_modes', []))
        self.follow = True
        self.fixed_velocity = True
        self.velocity_value = 100
        self.velocities16 = False
        self.keyboard_enabled = False
        self.process_index = 0
        self.pad_field = 0
        self.slice_field = 0
        self.control_level = 2
        self.range_page = 0
        self.sampling_nav = 0
        self.wave_view_active = self.wave_view_pinned = self.wave_selected = False
        self.wave_zoom = self.wave_offset = 0
        self.wave_sample = None
        self.select_multi = False
        self.selected_pads = {self.pad}
        self.redo = []
        self.init_event_shortcuts()
        self.repeat_locked = False
        self.repeat_preset = 0
        self.repeat_rates = [8, 16]
        self.repeat_pads = set()
        self.arp_position = 0
        self.flash_until = {}
        self.calibration = None
        self.loop_range = None
        self.scene_pads = set()
        self.duplicate_source = None
        self.duplicate_origin = "PAD"
        self.duplicate_events = True
        self.slice_edit = False
        self.transport_repeat = {}
        self.button_led_map = {}
        path = self.root/'captures/mikro-mk1-button-led-map.json'
        if path.exists():
            import json
            self.button_led_map = json.loads(path.read_text())['buttons']

    def sound_present(self, slot, group=None):
        track = self.project['groups'][self.group if group is None else group]['pads'][slot]
        return bool(track.get('routing',{}).get('midi_target','NONE')!='NONE') or bool(track['sample']) or track.get('source')=='MIDI' or bool(track.get('plugins'))

    def pattern_present(self, index):
        return bool(self.notes(self.group,index))

    def double_pattern(self):
        from app.polyphony import clone_cell
        pattern = self.project['groups'][self.group]['patterns'][self.pattern]
        length=self.pattern_steps()
        if length*2>4096:
            self.message = 'MAX LENGTH 256 BARS'
            return
        self.remember()
        for lane in pattern:
            lane[:length*2]=lane[:length]+lane[:length]
        self.project['groups'][self.group]['pattern_lengths'][str(self.pattern)]=length*2
        extra=self.project['groups'][self.group]['extra_events']
        for key,value in list(extra.items()):
            pat,pad,tick=map(int,key.split(':'))
            if pat==self.pattern:extra[f'{pat}:{pad}:{tick+length*24}']=clone_cell(value)
        for key,lane in self.project['groups'][self.group].get('automation',{}).items():
            if key.startswith(str(self.pattern)+':'):
                lane['points'].update({str(int(tick)+length*24):value for tick,value in list(lane['points'].items()) if int(tick)<length*24})
        events = self.project['groups'][self.group]['events']
        for key, value in list(events.items()):
            pat, pad, step = map(int, key.split(':'))
            if pat == self.pattern and step < length and step+length < 4096:
                events[f'{pat}:{pad}:{step+length}'] = clone_cell(value)

    def duplicate_pattern(self):
        group=self.project['groups'][self.group];patterns=group['patterns']
        if len(patterns)>=1024:self.message='PATTERN LIMIT';return
        self.remember();source=self.pattern;patterns.insert(source+1,copy.deepcopy(patterns[source]))
        for name in ('events','extra_events'):
            moved={}
            for key,value in group[name].items():
                pat,pad,tick=map(int,key.split(':'));moved[f'{pat+1 if pat>source else pat}:{pad}:{tick}']=value
                if pat==source:moved[f'{pat+1}:{pad}:{tick}']=copy.deepcopy(value)
            group[name]=moved
        lengths={str(int(k)+1 if int(k)>source else int(k)):v for k,v in group['pattern_lengths'].items()}
        lengths[str(source+1)]=self.pattern_steps();group['pattern_lengths']=lengths
        lanes={}
        for key,value in group.get('automation',{}).items():
            pat=int(key.split(':',1)[0]);tail=key.split(':',1)[1];lanes[f'{pat+1 if pat>source else pat}:{tail}']=value
            if pat==source:lanes[f'{pat+1}:{tail}']=copy.deepcopy(value)
        group['automation']=lanes
        group['pattern_created']=[i+1 if i>source else i for i in group['pattern_created']]+[source+1]
        for scene in self.project['scenes']:
            if scene[self.group] is not None and scene[self.group]>source:scene[self.group]+=1
        for clip in self.project.get('arrangement',{}).get('clips',[]):
            if clip['group']==self.group and clip['pattern']>source:clip['pattern']+=1
        while len(patterns)%16:patterns.append([[False]*16 for _ in range(16)])
        self.pattern+=1;self.pattern_bank=self.pattern//16;self.active_patterns[self.group]=self.pattern;self.project['scenes'][self.scene][self.group]=self.pattern;self.message='PATTERN DUPLICATED'

    def clear_pattern(self):
        self.remember()
        group = self.project['groups'][self.group]
        for lane in group['patterns'][self.pattern]:
            lane[:] = [False]*len(lane)
        group['events'] = {k:v for k,v in group['events'].items() if not k.startswith(f'{self.pattern}:')}
        group['extra_events']={k:v for k,v in group['extra_events'].items() if not k.startswith(f'{self.pattern}:')}
        group['automation']={k:v for k,v in group.get('automation',{}).items() if not k.startswith(f'{self.pattern}:')}
        group['pattern_created']=[index for index in group['pattern_created'] if index!=self.pattern]

    def seek_transport(self, name):
        direction = -1 if name == 'TRANSPORT LEFT' else 1
        distance=self.grid_ticks() if self.shift else {'1 BAR':384,'1/2':192,'1/4':96,'1/8':48,'1/16':24}[self.settings['arrange_grid']]
        # Manual Scene length controls scene changes, not the editable Pattern range.
        # A short Scene must not fold every bar-sized locate back to bar one.
        length=max(self.pattern_ticks(),self.scene_steps()*24)
        if self.clip_transport:
            from app.clip_arranger import length as clip_length
            length=max(1,clip_length(self.project))
        phase=max(0,self.clock_phase) if self.clock_phase>=0 else max(0,self.step)*24
        self.clock_phase=(phase+direction*distance)%length;self.step=self.clock_phase//24
        self.follow_step_view(self.clock_phase)
        self.actions.append(('panic', None))

    def transport_repeat_tick(self, now):
        for name, deadline in list(self.transport_repeat.items()):
            if now >= deadline:
                # Opposite directions held together pause movement; no catch-up burst.
                if len(self.transport_repeat) == 1:
                    if not self.playing and not self.shift and 'ERASE' in self.held_buttons:self.erase_locate(name)
                    else:self.seek_transport(name)
                self.transport_repeat[name] = now+0.25

    def surface_button(self, name, pressed):
        if pressed:
            self.held_buttons.add(name)
        else:
            self.held_buttons.discard(name)
        # Global emergency choke must precede every workspace-specific handler.
        if pressed and self.shift and name=='MUTE':
            self.stop_live_chop()
            self.repeat_pads.clear();self.arp_notes.clear();self.arp_played.clear()
            self.actions.append(('panic',None))
            self.message='CHOKE ALL NOTES'
            return True
        if self.live_fx_button(name, pressed):return True
        if self.midi_remote_button(name,pressed):return True
        from app.controller_stems import button as stem_button
        if stem_button(self,name,pressed):return True
        if self.export_button(name,pressed):return True
        if self.arranger_button(name,pressed):return True
        if self.mixer_button(name,pressed):return True
        if self.recording_button(name,pressed):return True
        if self.erasing_button(name,pressed):return True
        if self.page == 'BROWSE' and self.shift and name == 'F2':
            if pressed:self.quick_browse_sample()
            return True
        if pressed and name=='MAIN' and self.shift and not any(key in self.held_buttons for key in tuple(TEMPORARY)+('VIEW','NAV')):
            from app.settings_menu import SETTINGS_VIEWS
            if self.page in SETTINGS_VIEWS and not self.main_controls_active():
                self.page=getattr(self,'settings_origin',self.control_home())
                self.main_controls=getattr(self,'settings_main_controls',False)
            else:
                self.settings_origin=self.page
                self.settings_main_controls=self.main_controls_active()
                self.open_settings()
            return True
        if pressed and ((name in ('PLAY','REC') and not self.shift) or name=='RESTART'):
            self.reset_recording_take()
        if self.main_controls_button(name,pressed):return True
        if self.settings_button(name, pressed):return True
        if pressed and self.shift and name=='PAD MODE':
            self.keyboard_enabled=not self.keyboard_enabled;self.velocities16=False
            return True
        if pressed and self.shift and name in ('SAMPLING','SELECT'):
            # Direct destinations survive release of a temporary mode button.
            self.mode_origins.pop(name,None)
            self.wave_view_active=self.wave_view_pinned=False
            if name=='SAMPLING':self.open_sampling_page('SAMPLE EDIT')
            else:self.open_pattern_grid()
            return True
        if pressed and self.shift and name=='GROUP' and 'ERASE' in self.held_buttons:
            self.mode_origins['GROUP']=self.page;self.page='GROUP';return True
        if pressed and self.page=='SELECT' and name in ('NAV LEFT','NAV RIGHT'):
            self.group_bank=max(0,min((len(self.project['groups'])-1)//8,self.group_bank+(-1 if name=='NAV LEFT' else 1)))
            return True
        if self.control_button(name,pressed):return True
        if self.groove_button(name,pressed):return True
        if self.preferences_button(name,pressed):return True
        if self.performance_button(name,pressed):return True
        if self.bank_button(name,pressed):return True
        if self.routing_button(name,pressed):return True
        if self.plugins_button(name,pressed):return True
        if self.sampler_button(name,pressed):return True
        if self.slicing_button(name,pressed):return True
        if self.navigation_button(name,pressed):return True
        if self.sampling_button(name,pressed):return True
        if self.timing_button(name,pressed):return True
        if self.relink_button(name,pressed):return True
        if self.presets_button(name,pressed):return True
        if self.project_manager_button(name, pressed):return True
        if self.pattern_editor_button(name, pressed):
            return True
        if self.calibration is not None:
            if pressed and name != 'SHIFT':
                self.calibrate_button(name)
            return True
        if not pressed:
            if name in ('TRANSPORT LEFT', 'TRANSPORT RIGHT'):
                self.transport_repeat.pop(name, None)
                return True
            if name == 'GROUP' and 'GROUP' in self.mode_origins:
                self.page = self.mode_origins.pop('GROUP')
            elif name in TEMPORARY and name not in self.pinned_modes and name in self.mode_origins:
                origin = self.mode_origins.pop(name)
                if self.page == TEMPORARY[name] or (name == 'NOTE REPEAT' and self.page == 'ARP') or (name == 'EVENTS' and self.page == 'GRID EDIT'):
                    self.page = origin
            if name == 'NOTE REPEAT' and not self.repeat_locked:
                self.repeat_pads.clear()
            return name in TEMPORARY or name == 'GROUP'
        if name in ('TRANSPORT LEFT', 'TRANSPORT RIGHT'):
            self.seek_transport(name)
            self.transport_repeat[name] = time.monotonic()+0.25
            return True
        if name == 'MAIN':
            held = next((key for key in TEMPORARY if key in self.held_buttons), None)
            if held:
                if held in self.pinned_modes:
                    self.pinned_modes.remove(held)
                else:
                    self.pinned_modes.add(held)
                self.settings['pinned_modes'] = sorted(self.pinned_modes)
                save_json(self.settings_path, self.settings)
                self.message = 'PIN ON' if held in self.pinned_modes else 'PIN OFF'
                return True
        if self.shift and name == 'RESTART':
            self.loop_range = None if self.loop_range else (0,15)
            self.message = 'LOOP ALL' if self.loop_range else 'LOOP SCENE'
            return True
        if self.shift and name in ('NOTE REPEAT', 'GROUP'):
            self.page = self.control_home() if self.page == 'STEP' else 'STEP'
            return True
        if name == 'GROUP':
            self.mode_origins['GROUP'] = self.page
            self.page = 'GROUP'
            return True
        if name in TEMPORARY and not (self.shift and name == 'VIEW'):
            if name=='SELECT':self.sync_selection()
            target = TEMPORARY[name]
            if name == 'DUPLICATE':
                self.duplicate_source = None
                self.duplicate_origin = self.page
            if name == 'NOTE REPEAT' and self.keyboard_enabled:
                target = 'ARP'
                self.arp_on = True
            if self.page == target:
                # Editor/direct navigation can leave an unpinned mode visible
                # without an origin. Never make that workspace its own origin.
                origin = self.mode_origins.pop(name, self.control_home())
                self.page = self.control_home() if origin == target else origin
            else:
                self.mode_origins[name] = self.page
                self.page = target
            return True
        if self.page in ('NOTE REPEAT','ARP') and name in ('F1','F2','F3'):
            if name == 'F3': self.repeat_locked = not self.repeat_locked
            else: self.repeat_preset = int(name[1])-1
            return True
        if self.page == 'SCENE' and name in ('F1','F2','F3'):
            if self.shift and name=='F1':self.scene_options_index=0;self.page='SCENE OPTIONS';return True
            if self.shift and name in ('F2','F3'):
                self.page='SONG' if name=='F2' else 'PROJECT'
                return True
            if name == 'F1':
                self.loop_range=(0,max(self.project['scene_created'],default=0))
                self.message = 'LOOP ALL SCENES'
            elif name == 'F2':
                self.confirm('DUPLICATE SCENE?', self.duplicate_scene)
            else:
                self.confirm('CLEAR SCENE CLIPS?', self.clear_scene)
            return True
        if self.page == 'DUPLICATE' and name == 'F1':
            self.duplicate_events = not self.duplicate_events
            return True
        if self.page == 'CHOP' and name in ('F1','F2','F3'):
            if name == 'F1':
                self.slice_edit = not self.slice_edit
            else:
                self.confirm(f'REPLACE {self.slice_count} PADS?', self.apply_chop)
            return True
        if self.page == 'PAD' and name in ('F1', 'F2', 'F3'):
            self.control_level = int(name[1])-1
            return True
        if self.page == 'SELECT' and name in ('F1','F2','F3'):
            if name == 'F3':
                self.select_multi = not self.select_multi
            elif name == 'F1':
                pass  # QUIET changes the selection tool, never the MULTI option.
            else:
                self.open_pattern_grid()
            return True
        if name in ('NAV LEFT', 'NAV RIGHT'):
            delta = -1 if name == 'NAV LEFT' else 1
            fields = {'PAD CONFIG': ('pad_field', 2), 'SAMPLE EDIT': ('sample_field', 2), 'SAMPLER': ('sample_field',2),
                      'CHOP': ('slice_field', 2), 'EVENT': ('event_field', 3),
                      'OPTIONS': ('option_field', 2), 'MIDI TRACK': ('track_field', 3)}
            if self.page in fields:
                attr, count = fields[self.page]
                setattr(self, attr, max(0, min(count-1, getattr(self, attr)+delta)))
                return True
            if self.page in ('PAD', 'SAMPLING', 'PATTERN', 'SCENE', 'MUTE', 'SOLO',
                             'NOTE REPEAT', 'ARP', 'SELECT', 'MIXER', 'KEYBOARD', 'CHORD', 'LENGTH'):
                return True
        if self.page == 'PAD CONFIG':
            if name in ('ENTER','ENCODER PUSH') and self.keyboard_enabled:
                self.page='KEYBOARD'
            elif name == 'F1':
                self.keyboard_enabled = not self.keyboard_enabled
                if self.keyboard_enabled:
                    self.velocities16 = False
            elif name == 'F2':
                if self.keyboard_enabled:
                    self.keyboard_root = max(0, self.keyboard_root-(16 if self.slice_keyboard() else 12))
                else:
                    self.velocities16 = not self.velocities16
                    if self.velocities16:
                        self.fixed_velocity = False
            elif name == 'F3':
                if self.keyboard_enabled:
                    self.keyboard_root = min(112 if self.slice_keyboard() else 111, self.keyboard_root+(16 if self.slice_keyboard() else 12))
                else:
                    self.fixed_velocity = not self.fixed_velocity
                    self.velocities16 = False
            elif name in ('NAV LEFT','NAV RIGHT'):
                self.pad_field = (self.pad_field+(1 if name == 'NAV RIGHT' else -1)) % 2
            else:return False
            return True
        if self.page == 'STEP':
            if name == 'F1':
                self.follow = not self.follow;self.follow_step_view()
            elif name == 'F2': self.double_pattern()
            elif name == 'F3': self.fixed_velocity = not self.fixed_velocity
            elif name in ('NAV LEFT','NAV RIGHT'):
                self.follow = False
                self.bank = max(0,min((self.step_cell_count()-1)//16,self.bank+(-1 if 'LEFT' in name else 1)))
            else: return False
            return True
        if self.page == 'PATTERN' and name in ('F1','F2','F3'):
            if name == 'F1':
                self.double_pattern()
            elif name == 'F2': self.duplicate_pattern()
            else: self.confirm('DELETE PATTERN?', self.clear_pattern)
            return True
        if self.page in ('MUTE','SOLO') and name in ('F1','F2','F3'):
            if name == 'F3':
                self.message = 'MUTE CUTS AUDIO'
            else:
                self.remember()
                for track in self.project['groups'][self.group]['pads']:
                    track['mute'] = name == 'F2'
                    track['solo'] = False
            return True
        if self.page == 'SAMPLING' and name in ('F1','F2','F3'):
            if name == 'F1':
                if self.capture_started is not None:
                    self.actions.append(('capture_stop', None))
                elif self.audio and (self.audio.capture or self.capture_options()['source']=='INTERNAL'):
                    self.capture_armed=True;self.actions.append(('capture',self.audio.capture))
                else: self.message = 'NO AUDIO INPUT'
            elif name == 'F2' and self.capture_started is not None:
                self.actions.append(('capture_cancel', None))
            return True
        if self.page in ('SAMPLE EDIT','PROCESS') and name in ('F1','F2','F3'):
            if name == 'F2':
                operation = PROCESSING[self.process_index]
                if operation=='STEM SEPARATION':
                    from app.controller_stems import open_page
                    open_page(self)
                elif operation=='STRETCH':self.page='STRETCH';self.sample_field=0
                else:self.confirm('NORM WHOLE SAMPLE?' if operation=='NORMALIZE' else operation+' SAMPLE?',lambda:self.actions.append(('process',operation)))
            else:
                self.process_index = (self.process_index+(-1 if name == 'F1' else 1)) % len(PROCESSING)
            return True
        if self.page == 'NAVIGATE' and self.nav_origin in ('SAMPLING','SAMPLE EDIT','CHOP') and name in ('NAV LEFT','NAV RIGHT'):
            self.range_page = 0 if name == 'NAV LEFT' else 1
            self.page = 'SAMPLE EDIT'
            return True
        return False

    def surface_rotate(self, delta):
        if self.page=='SCENE OPTIONS':self.scene_options_index=max(0,min(len(self.scene_options())-1,self.scene_options_index+delta));return True
        if self.live_fx_rotate(delta):return True
        if self.export_rotate(delta):return True
        if self.mixer_rotate(delta):return True
        if self.groove_rotate(delta):return True
        if self.preferences_rotate(delta):return True
        if self.performance_rotate(delta):return True
        if self.routing_rotate(delta):return True
        if self.plugins_rotate(delta):return True
        if self.sampler_rotate(delta) or self.slicing_rotate(delta):return True
        if self.navigation_rotate(delta):return True
        if self.sampling_rotate(delta):return True
        if self.timing_rotate(delta):return True
        if self.relink_rotate(delta):return True
        if self.presets_rotate(delta):return True
        if self.project_manager_rotate(delta):return True
        if self.pattern_editor_rotate(delta):return True
        if self.page == 'PAD':
            self.remember()
            target = self.project if self.control_level == 0 else self.project['groups'][self.group] if self.control_level == 1 else self.track()
            target['gain'] = max(0,min(100,target.get('gain',100)+delta))
            if self.control_level == 2:
                for slot in self.selected_pads-{self.pad}:
                    t=self.project['groups'][self.group]['pads'][slot]
                    t['gain']=max(0,min(100,t['gain']+delta))
            return True
        if self.page == 'CHOP' and not self.slice_edit and self.slice_field == 0:
            return True  # SPLIT is currently the only implemented slicing mode.
        if self.page == 'CHOP' and self.slice_edit:
            self.slice_index=max(0,min(self.slice_count-1,self.slice_index+delta))
            return True
        if self.page=='PATTERN':self.adjust_pattern_length(delta);return True
        if self.page=='SCENE':
            self.remember();self.project['scene_lengths'][str(self.scene)]=max(1,min(4096,self.scene_steps()+delta*(1 if self.encoder_held else 16)));return True
        if self.page == 'PAD CONFIG':
            if self.pad_field == 0:
                self.keyboard_root = max(0,min(111,self.keyboard_root+delta))
            else:
                self.velocity_value = max(1,min(127,self.velocity_value+delta))
            return True
        if self.page == 'STEP':
            self.velocity_value = max(1,min(127,self.velocity_value+delta))
            return True
        return False

    def surface_pad(self, slot, velocity, owner=None):
        if self.page=='LIVE FX':return self.live_fx_pad_on(slot,velocity,owner)
        if self.group_delete_pad(slot):return True
        if self.page=='PARAM NAV' and self.navigation_pad(slot):return True
        if (self.page=='SAMPLING NAV' or self.wave_view()) and self.sampling_pad(slot,velocity):return True
        if self.event_shortcut_pad(slot):return True
        if self.erase_pad(slot):return True
        if self.selection_pad(slot):return True
        if self.page=='STRETCH':
            if self.track().get('sample'):
                self.actions.append(('stretch_preview',(copy.deepcopy(self.track()),(self.project_generation,self.group,self.pad,self.zone_index),velocity)))
            else:self.message='NO SAMPLE'
            return True
        if self.mixer_pad(slot):return True
        if self.performance_pad(slot,velocity):return True
        if self.slicing_pad(slot,velocity):return True
        if self.navigation_pad(slot):return True
        if self.sampling_pad(slot,velocity):return True
        if self.pattern_editor_pad(slot):return True
        if self.page == 'NAVIGATE' and self.nav_origin in ('SAMPLING','SAMPLE EDIT','CHOP'):
            page = {12:'SAMPLING',13:'SAMPLE EDIT',14:'CHOP'}.get(slot)
            if page:
                self.page = page
            return True
        if 'DUPLICATE' in self.held_buttons or self.page == 'DUPLICATE':
            kind='GROUP' if self.page=='GROUP' else 'PATTERN' if self.page=='PATTERN' or self.duplicate_origin=='PATTERN' else 'SOUND'
            if kind=='GROUP':
                slots=(12,13,14,15,8,9,10,11)
                if slot not in slots:return True
                slot=self.group_bank*8+slots.index(slot)
            if self.duplicate_source is None:
                self.duplicate_source=(kind,self.group,slot)
                self.message='SELECT TARGET'
            else:
                source=self.duplicate_source
                target=(kind,self.group,slot)
                self.confirm('REPLACE '+kind+'?',lambda:self.copy_object(source,target))
                self.duplicate_source=None
            return True
        if self.page == 'SCENE':
            if self.scene_pads:
                first=next(iter(self.scene_pads));slot+=self.scene_bank*16
                self.loop_range=(min(first,slot),max(first,slot))
                self.message='SCENE LOOP RANGE'
            else:
                self.loop_range=None
                self.select_scene(self.scene_bank*16+slot)
            self.scene_pads.add(slot)
            return True
        if self.page == 'GROUP':
            slots=(12,13,14,15,8,9,10,11)
            if slot not in slots: return True
            index=self.group_bank*8+slots.index(slot)
            origin=self.mode_origins.get('GROUP')
            if origin in ('MUTE','SOLO'):
                self.remember()
                group=self.project['groups'][index]
                field=origin.lower()
                group[field]=not group.get(field,False)
            else:
                self.select_group(index)
            return True
        if 'SELECT' in self.held_buttons or self.page == 'SELECT':
            self.select_sound(slot,self.select_multi)
            return True
        if self.page == 'NOTE REPEAT':
            self.repeat_pads.add(slot)
            return True
        if self.page == 'PAD' and self.keyboard_enabled:
            if self.repeat_locked:
                self.arp_notes.add(min(127,self.keyboard_root+slot))
            else:
                intervals=(0,) if self.chord==0 else (0,4,7) if self.chord==1 else (0,3,7)
                self.record_pad_note(self.pad,velocity,min(127,self.keyboard_root+slot))
                for interval in intervals:
                    self.actions.append(('midi_note',(min(127,self.keyboard_root+slot+interval),velocity,self.track()['channel'])))
            return True
        if self.page == 'PAD' and self.repeat_locked:
            self.repeat_pads.add(slot)
            return True
        if self.page == 'BROWSE':
            self.select_sound(slot)
            if self.browser.prehear:self.preview_selected()
            else:self.actions.append(('hit',(self.group,slot,velocity)))
            return True
        if self.page == 'SAMPLING':
            # Capture owns its start target; changing focus never stops it.
            self.select_sound(slot)
            self.actions.append(('hit',(self.group,slot,velocity)))
            return True
        if self.page == 'SAMPLE EDIT':
            self.actions.append(('hit',(self.group,self.pad,velocity)))
            return True
        if self.page == 'PAD CONFIG':
            if self.keyboard_enabled:
                self.record_pad_note(self.pad,velocity,self.keyboard_root+slot)
                self.actions.append(('midi_note',(self.keyboard_root+slot,velocity,self.track()['channel'])))
            else:
                self.select_sound(slot)
                self.record_pad_note(slot,velocity)
                self.actions.append(('hit',(self.group,slot,velocity)))
            return True
        return False

    def surface_softkeys(self):
        from app.controller_stems import PAGE,keys,browser_sample
        if self.page==PAGE:return keys(self)
        if self.page=='BROWSE' and self.shift:return ('BACK','FIND','STEMS' if browser_sample(self) else '')
        if self.page=='RECORD PREPARE':return ('2','4','8') if self.prepare_field==0 else ('-','-','-')
        from app.preferences import PREFERENCES
        from app.navigation import CONTROL_PAGES
        if self.page in CONTROL_PAGES and not self.shift:return ('MASTER','GROUP','SOUND')
        if self.page in PREFERENCES:return ("RESET","-","BACK")
        if self.page=="GROOVE":return ("-","-","-")
        if self.page=="STRETCH":return ("-","APPLY","BACK")
        if self.page=="MACRO":return ("-","ASSIGN","CLEAR")
        if self.page=="MACRO ASSIGN":return ("-","APPLY","-")
        if self.page=='PLUGIN SC':return ('BACK','-','-')
        if self.page=="PLUGIN BROWSE":return (self.plugin_filter,"REMOVE" if self.plugin_browser_index==-1 and self.plugin_selected() else "LOAD","BACK")
        if self.page=="PLUGIN MOVE":return ("","CANCEL","MOVE")
        if self.page in ("PLUGIN","PLUGIN SLOTS"):return ("COPY","PASTE","MOVE") if self.shift else ("BYPASS","ADD","REMOVE")
        if self.page=="VIEW NAV":
            if self.view_selector:
                from app.mikro_navigate import keys
                return keys(self)
            return ("SCENE","PAT","-")
        if self.page=="PARAM NAV":return ("-","CHNL.","PLUG-IN")
        if self.page=='ZONE':return ('PREV','NEXT','REMOVE' if self.shift else 'ADD')
        if self.page=='SLICE TARGET':return ('EDIT','APPL.TO','APPLY')
        if self.page=="SAMPLER":return ("-","-","-")
        if self.wave_view():return ("-","WAVE","-")
        if self.page=='AUTOSAMPLER':return ('BACK','START','CANCEL')
        if self.page=="SAMPLING NAV":return ("RECORD","EDIT","SLICE")
        if self.page=="SAMPLE DELETE":return ("CANCEL","SELECT","-")
        if self.page=='SAMPLING' and self.shift:return ('BOUNCE','AUDIO','DELETE')
        if self.page=='AUDIO LOOP':return ('BACK','','')
        if self.page=='BOUNCE TO PAD':return ('BACK','CANCEL' if self.capture_armed or self.capture_started is not None else '', 'STOP' if self.capture_started is not None else 'WAIT' if self.capture_armed else 'START')
        if self.page=="SAMPLE EDIT" and self.shift:return ("-","-","DELETE")
        if self.page=='OPTIONS':return ('QUANT','SWING','GRID')
        if self.page=='RECORD SETTINGS':return ('METRO','COUNT','BACK')
        if self.page=='MISSING SAMPLES':return ('BACK','SEARCH' if self.missing_rows else 'SCAN','BROWSE')
        if self.page=='RELINK RESULTS':return ('BACK','SELECT','BROWSE')
        if self.page=='RELINK BROWSE':return ('UP','OPEN','BACK')
        if self.page=='PRESET LOAD':return ('BACK','LOAD','BACK')
        project_keys=self.project_manager_softkeys()
        if project_keys:return project_keys
        grid_keys=self.pattern_editor_softkeys()
        if grid_keys:return grid_keys
        if self.page == 'PAD': return ('MASTER','GROUP','SOUND')
        if self.page == 'PAD CONFIG':
            if self.keyboard_enabled and self.keyboard_chord_mode()=='CUSTOM' and self.shift:return ('LEARN','INV-','INV+')
            if self.keyboard_enabled and self.slice_keyboard():return ('KEYBD','BANK-','BANK+')
            return ('KEYBD','OCT-' if self.keyboard_enabled else '16 VEL','OCT+' if self.keyboard_enabled else 'FIX VEL')
        if self.page == 'STEP': return ('FOLLOW','DOUBLE','FIX VEL')
        if self.page=='EXPORT DONE':return ('BACK','-','NEW')
        if self.page=='EXPORT':return ('CANCEL','-','-') if self.export_busy else ('BACK','-','EXPORT')
        if self.page=='MIXER':return ('-','OUTPUT','RESET') if self.shift else ('MASTER','GROUP','SOUND')
        if self.page == 'PATTERN': return ('DBL','DUPL','DELETE')
        if self.page == 'SCENE': return ('OPTIONS','SONG','PROJECT') if self.shift else ('ALL','DUPL','DELETE')
        if self.page in ('MUTE','SOLO'): return ('ALL ON','NONE','-')
        if self.page == 'SELECT': return ('QUIET','EVENTS','MULTI')
        if self.page == 'SAMPLING':
            start,action,previous,next_take=self.capture_actions()
            return (start,'CANCEL' if action=='CANCEL' else previous or '-',next_take or '-')
        if self.page in ('SAMPLE EDIT','PROCESS'):
            return ('<', {'TRUNCATE':'TRUNC','NORMALIZE':'NORM','REVERSE':'REV','STEM SEPARATION':'STEMS'}.get(PROCESSING[self.process_index],PROCESSING[self.process_index]),'>')
        if self.page in ('NOTE REPEAT','ARP'):return tuple(f'1/{rate}' for rate in self.project['repeat_presets'][self.repeat_bank*2:self.repeat_bank*2+2])+('LOCK',)
        if self.page == 'BROWSE':
            entry=self.browser.selected()
            return ('BACK','FIND' if self.shift else 'OPEN' if entry and self.browser.is_folder(entry) else 'LOAD' if entry else '-','PREH')
        if self.page == 'CHOP': return ('EDIT','ADD' if self.slice_edit and not self.slice_single_apply else 'APPL.TO',('APPLY' if self.slice_single_apply else 'DEL ALL' if self.shift else 'REMOVE') if self.slice_edit else 'APPLY')
        if self.page == 'DUPLICATE': return ('+ EVNT','-','-')
        return None

    def active_softkeys(self):
        if self.page=='UPDATE':return {0}
        if self.page=='LIVE FX':return {self.live_fx_mode}
        from app.codec_levels import dac_context
        if dac_context(self):return {i for i,k in enumerate(('hat_headphone_mute','hat_speaker_mute')) if self.settings[k]}
        if self.page=='MIXER':return set() if self.shift else {self.mixer_level}
        if self.main_controls_active():return {self.main_tab}
        from app.settings_menu import SETTINGS_VIEWS, SETTINGS_FOLDERS
        if self.page in SETTINGS_VIEWS:return {tuple(SETTINGS_FOLDERS).index(self.settings_folder)}
        from app.navigation import CONTROL_PAGES
        if self.page in CONTROL_PAGES and not self.shift:return {self.control_level}
        if self.page=="PLUGIN":return {0} if self.plugin_selected() and self.plugin_selected().get("bypass") else set()
        if self.page=="VIEW NAV" and self.view_selector and self.view_tool=='GRID':return {2} if self.grid_follow else set()
        if self.page=="VIEW NAV":return set() if self.view_selector else {0 if self.view_target=="SCENE" else 1}
        if self.page=="PARAM NAV":return {1 if self.parameter_kind=="CHNL" else 2}
        if self.wave_view():return {1} if self.wave_selected else set()
        if self.page=="AUDIO RATE":return {0 if self.settings["sample_rate"]==44100 else 1}
        if self.page=="SAMPLING NAV":return {self.sampling_nav}
        if self.page=='OPTIONS':return {self.grid_tab}
        if self.page=='RECORD SETTINGS':return {0} if self.timing()['metro'] else set()
        if self.page in ('PATTERN GRID','GRID EDIT') and self.shift:return {0} if self.grid_follow else set()
        if self.page=='PATTERN GRID':return {0} | ({1} if self.grid_cursor_targets() & self.grid_selected else set())
        if self.page == 'PAD': return {self.control_level}
        if self.page == 'STEP': return ({0} if self.follow else set()) | ({2} if self.fixed_velocity else set())
        if self.page=='PAD CONFIG' and self.keyboard_enabled and self.keyboard_chord_mode()=='CUSTOM' and self.shift:return {0} if self.chord_learning is not None else set()
        if self.page == 'PAD CONFIG': return ({0} if self.keyboard_enabled else set()) | ({1} if self.velocities16 else set()) | ({2} if self.fixed_velocity and not self.keyboard_enabled else set())
        if self.page == 'BROWSE': return {2} if self.browser.prehear else set()
        if self.page == 'SLICE TARGET':return {1}
        if self.page == 'CHOP': return ({0} if self.slice_edit else set()) | ({1} if self.slice_single_apply else set())
        if self.page == 'DUPLICATE': return {0} if self.duplicate_events else set()
        if self.page == 'SELECT': return {0} | ({2} if self.select_multi else set())
        if self.page in ('NOTE REPEAT','ARP'): return {self.repeat_preset} | ({2} if self.repeat_locked else set())
        return set()

    def release_pad(self, slot, owner=None,still_held=False):
        if self.live_fx_pad_off(slot,owner):
            if not still_held:self.held_pads.discard(slot)
            if still_held:return
        if not still_held:
            self.held_pads.discard(slot)
            self.erase_targets.pop(slot,None)
        binding=self.live_notes.pop(slot if owner is None else (owner,slot),None)
        if binding:
            voices,recorded,started=binding
            for group,pad,note in voices:self.actions.append(('note_off',(group,pad,note)))
            for reference in recorded or []:
                if reference in self.chord_offsets:
                    delay=self.chord_offsets.pop(reference);elapsed=(getattr(self,'input_timestamp',None) or time.monotonic())-started
                    self.finish_chord_recording(reference,elapsed,delay);continue
                group,pattern=reference[:2];key=reference[2:];event=self.event_notes(group,pattern).get(key)
                if event:
                    before=copy.deepcopy(event)
                    self.remember_recording_note();event=copy.deepcopy(event);event['length']=max(1,min(self.pattern_ticks(group,pattern),round(((getattr(self,'input_timestamp',None) or time.monotonic())-started-self.chord_offsets.pop(reference,0))/self.clock_interval())));self.put_event(key,event,group,pattern)
                    self.recording_change(reference,before,event,merge=True)

        if still_held:return
        if self.keyboard_enabled or self.page in ('KEYBOARD','CHORD','ARP'):
            self.flash_until.pop(slot,None)
        self.scene_pads.discard(slot)
        self.repeat_pads.discard(slot)
        if not self.arp_hold:
            for note in self.performance_notes(slot):self.arp_notes.discard(note)
            self.arp_played=[note for note in self.arp_played if note in self.arp_notes]
        self.performance_lights=set(note for held in self.held_pads for note in self.performance_notes(held))

    def repeat_tick(self,now):self.performance_repeat(now)

    def duplicate_scene(self):
        scenes=self.project['scenes']
        if len(scenes)>=1024:self.message='SCENE LIMIT';return
        self.remember();scenes.insert(self.scene+1,copy.deepcopy(scenes[self.scene]))
        while len(scenes)%16:scenes.append([None]*len(self.project['groups']))
        self.project['scene_created']=[i+1 if i>self.scene else i for i in self.project['scene_created']]+[self.scene+1]
        self.project['scene_lengths']={str(int(k)+1 if int(k)>self.scene else int(k)):v for k,v in self.project['scene_lengths'].items()}
        if str(self.scene) in self.project['scene_lengths']:self.project['scene_lengths'][str(self.scene+1)]=self.project['scene_lengths'][str(self.scene)]
        self.project['song']=[i+1 if i>self.scene else i for i in self.project['song']]
        self.select_scene(self.scene+1)

    def clear_scene(self):
        self.remember();self.project['scenes'][self.scene]=[None]*len(self.project['groups']);self.activate_scene(self.scene);self.message='SCENE CLIPS CLEARED'

    def copy_object(self, source, target):
        kind,sg,ss=source
        _,tg,ts=target
        if source==target:return
        if kind=='SOUND' and self.project['groups'][sg]['pads'][ss].get('routing',{}).get('midi_target','NONE')!='NONE':self.message='SHARED PART: COPY GROUP';return
        self.remember()
        src=self.project['groups'][sg];dst=self.project['groups'][tg]
        if kind=='SOUND':
            dst['pads'][ts]=copy.deepcopy(src['pads'][ss])
            if self.duplicate_events:
                lanes=[copy.deepcopy(p[ss]) for p in src['patterns']]
                properties={k:copy.deepcopy(v) for k,v in src['events'].items() if int(k.split(':')[1])==ss}
                fine={k:copy.deepcopy(v) for k,v in src['extra_events'].items() if int(k.split(':')[1])==ss}
                for pat,lane in enumerate(lanes):
                    length=len(dst['patterns'][pat][0])
                    dst['patterns'][pat][ts]=(lane+[False]*64)[:length]
                dst['events']={k:v for k,v in dst['events'].items() if int(k.split(':')[1])!=ts}
                for key,value in properties.items():
                    pat,_,step=map(int,key.split(':'))
                    if step<len(dst['patterns'][pat][0]):dst['events'][f'{pat}:{ts}:{step}']=value
                dst['extra_events']={k:v for k,v in dst['extra_events'].items() if int(k.split(':')[1])!=ts}
                for key,value in fine.items():
                    pat,_,tick=map(int,key.split(':'))
                    if tick<len(dst['patterns'][pat][0])*24:dst['extra_events'][f'{pat}:{ts}:{tick}']=value
        elif kind=='PATTERN':
            pattern=copy.deepcopy(src['patterns'][ss])
            props={f'{ts}:{k.split(":",1)[1]}':copy.deepcopy(v) for k,v in src['events'].items() if k.startswith(f'{ss}:')}
            dst['patterns'][ts]=pattern
            dst['events']={k:v for k,v in dst['events'].items() if not k.startswith(f'{ts}:')}
            dst['events'].update(props)
            fine={f'{ts}:{k.split(":",1)[1]}':copy.deepcopy(v) for k,v in src['extra_events'].items() if k.startswith(f'{ss}:')}
            dst['extra_events']={k:v for k,v in dst['extra_events'].items() if not k.startswith(f'{ts}:')}
            dst['extra_events'].update(fine)
        else:
            copied=copy.deepcopy(self.project['groups'][ss])
            from app.layout import GROUP_BASE
            mapping={ss*16+i:ts*16+i for i in range(16)};mapping[GROUP_BASE+ss]=GROUP_BASE+ts
            for target in [copied]+copied['pads']:
                for macro in target.get('macros',{}).values():macro['bus']=mapping.get(macro['bus'],macro['bus'])
                for key in ('dest','aux1_dest','aux2_dest','midi_target'):
                    value=target.get('routing',{}).get(key,'')
                    if value==f'GROUP {ss}':target['routing'][key]=f'GROUP {ts}'
                    elif value.startswith('SOUND ') and ss*16<=int(value.split()[1])<ss*16+16:target['routing'][key]=f'SOUND {ts*16+int(value.split()[1])%16}'
            remapped={}
            for name,lane in copied.get('automation',{}).items():
                pat,bus,kind,slot,key=name.split(':',4)
                remapped[':'.join((pat,str(mapping.get(int(bus),int(bus))),kind,slot,key))]=lane
            copied['automation']=remapped
            if not self.duplicate_events:
                for key in ('automation','pattern_lengths','pattern_created'):
                    copied[key]=copy.deepcopy(self.project['groups'][ts].get(key,{} if key!='pattern_created' else []))
                copied['patterns']=copy.deepcopy(self.project['groups'][ts]['patterns'])
                copied['events']=copy.deepcopy(self.project['groups'][ts]['events'])
                copied['extra_events']=copy.deepcopy(self.project['groups'][ts]['extra_events'])
            self.project['groups'][ts]=copied
        if kind=='PATTERN':self.copy_automation(sg,ss,tg,ts);dst['pattern_lengths'][str(ts)]=self.pattern_steps(sg,ss)
        elif kind=='SOUND' and self.duplicate_events:
            for pattern in range(min(len(src['patterns']),len(dst['patterns']))):self.copy_automation(sg,pattern,tg,pattern,ss,ts)
        self.actions.append(('reload',None))
        self.page=self.duplicate_origin
        self.message=kind+' COPIED'
